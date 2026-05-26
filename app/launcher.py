"""HollerBox menu-bar launcher (macOS).

A small `rumps` app that lives in the macOS menu bar. On launch it:

1. Generates an API token if the user hasn't pinned one (so the install
   is auth-protected by default).
2. Boots `api.main:app` in a subprocess on 127.0.0.1:8787.
3. Opens the browser to the local URL with the token already in
   place — the user never sees a "paste this token" prompt.

Menu items:
- Open HollerBox       (re-opens the browser)
- Copy server token
- Reveal data folder   (the SQLite DB / Fernet key / uploads)
- Show logs            (opens the live server log file)
- Quit

For packaging into a `HollerBox.app` see `app/pyinstaller.spec`.
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# rumps is macOS-only and pulls in PyObjC — import is gated so the file
# can still be analyzed in CI on Linux. Real execution requires macOS.
try:
    import rumps  # type: ignore
except ImportError:  # pragma: no cover
    rumps = None  # type: ignore[assignment]


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DATA_DIR = Path("~/.hollerbox").expanduser()
TOKEN_FILE = DATA_DIR / "launcher_token"
LOG_FILE = DATA_DIR / "launcher.log"


# --------------------------- helpers ---------------------------


def _ensure_token() -> str:
    """Stable token across launcher runs. Stored at 0600 alongside the Fernet key."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    new_token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(new_token, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return new_token


def _project_root() -> Path:
    """Find the repo root so we can resolve `web/dist` from a dev checkout.

    When PyInstaller has bundled us, `_MEIPASS` is set and `api.main`
    finds `web/dist` next to itself.
    """
    here = Path(__file__).resolve().parent
    if (here.parent / "backend").is_dir():
        return here.parent
    return here


def _server_command() -> tuple[list[str], dict[str, str]]:
    """Build the subprocess command + env for the API server.

    Dev: `uv run hollerbox-api` inside the backend dir.
    Bundled: the bundled `hollerbox-api` binary is on PATH.
    """
    env = os.environ.copy()
    env["HOLLERBOX_API_HOST"] = DEFAULT_HOST
    env["HOLLERBOX_API_PORT"] = str(DEFAULT_PORT)
    env["HOLLERBOX_API_RELOAD"] = "0"
    env["HOLLERBOX_API_KEY"] = _ensure_token()

    if getattr(sys, "frozen", False):  # PyInstaller-built binary
        return [sys.executable, "--run-api"], env

    backend_dir = _project_root() / "backend"
    return ["uv", "run", "--directory", str(backend_dir), "hollerbox-api"], env


# --------------------------- the app ---------------------------


class HollerBoxApp:
    def __init__(self) -> None:
        assert rumps is not None, "rumps is required on macOS"
        self.token = _ensure_token()
        self.app = rumps.App(  # type: ignore[attr-defined]
            "HollerBox",
            title="HB",  # placeholder until you ship an icon
            icon=self._icon_path(),
            quit_button=None,
        )
        self.app.menu = [
            rumps.MenuItem("Open HollerBox", callback=self.open_browser),  # type: ignore[attr-defined]
            None,
            rumps.MenuItem("Copy server token", callback=self.copy_token),  # type: ignore[attr-defined]
            rumps.MenuItem("Reveal data folder", callback=self.reveal_data),  # type: ignore[attr-defined]
            rumps.MenuItem("Show logs", callback=self.show_logs),  # type: ignore[attr-defined]
            None,
            rumps.MenuItem("Quit HollerBox", callback=self.quit),  # type: ignore[attr-defined]
        ]
        self.server: subprocess.Popen | None = None

    def _icon_path(self) -> str | None:
        # Use the brand logo as a menu bar icon if available.
        # macOS will auto-mask to template style if the asset has alpha.
        candidates = [
            _project_root() / "assets" / "logo.png",
            Path(__file__).resolve().parent / "logo.png",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)
        return None

    # --------------------------- lifecycle ---------------------------

    def start_server(self) -> None:
        cmd, env = _server_command()
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_handle = LOG_FILE.open("a", encoding="utf-8")
        log_handle.write(f"\n--- launcher start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_handle.flush()
        self.server = subprocess.Popen(  # noqa: S603
            cmd,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        # Race the open-browser call so the page renders shortly after the
        # API is reachable. If we miss the window the user will just see
        # the connecting spinner — TokenGate retries on its own.
        threading.Thread(target=self._open_when_ready, daemon=True).start()

    def _open_when_ready(self) -> None:
        url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/?_token={self.token}"
        # Give uvicorn ~3 seconds to bind. If we open earlier the browser
        # gets a connection-refused.
        import urllib.error
        import urllib.request

        for _ in range(40):  # ~6 seconds total
            try:
                urllib.request.urlopen(  # noqa: S310 — local-only
                    f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health", timeout=0.2
                )
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.15)
        webbrowser.open(url)

    def stop_server(self) -> None:
        if self.server is None:
            return
        try:
            self.server.send_signal(signal.SIGTERM)
            self.server.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                self.server.kill()
            except ProcessLookupError:
                pass
        self.server = None

    def run(self) -> None:
        self.start_server()
        try:
            self.app.run()
        finally:
            self.stop_server()

    # --------------------------- menu callbacks ---------------------------

    def open_browser(self, _sender) -> None:  # noqa: ANN001 — rumps signature
        webbrowser.open(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/?_token={self.token}")

    def copy_token(self, _sender) -> None:  # noqa: ANN001
        try:
            subprocess.run(  # noqa: S603, S607
                ["pbcopy"], input=self.token, text=True, check=True
            )
            rumps.notification("HollerBox", "Token copied", "Paste it into the web UI.")  # type: ignore[attr-defined]
        except Exception:
            # If pbcopy isn't available, just open an alert with the value.
            rumps.alert("HollerBox token", self.token)  # type: ignore[attr-defined]

    def reveal_data(self, _sender) -> None:  # noqa: ANN001
        subprocess.run(  # noqa: S603, S607
            ["open", str(DATA_DIR)], check=False
        )

    def show_logs(self, _sender) -> None:  # noqa: ANN001
        if LOG_FILE.exists():
            subprocess.run(["open", str(LOG_FILE)], check=False)  # noqa: S603, S607
        else:
            rumps.alert("No logs yet", "The server hasn't written anything to log.")  # type: ignore[attr-defined]

    def quit(self, _sender) -> None:  # noqa: ANN001
        self.stop_server()
        rumps.quit_application()  # type: ignore[attr-defined]


def main() -> None:
    """Module entry point.

    Two modes:
    - default: run the menu bar UI (boots the server as a subprocess)
    - `--run-api`: act as the API server (used by the bundled binary's
      subprocess to re-invoke itself).
    """
    if len(sys.argv) > 1 and sys.argv[1] == "--run-api":
        from api import __main__ as api_main

        api_main.main()
        return

    if rumps is None:
        print(
            "The HollerBox launcher requires `rumps` (macOS only). "
            "Install with: `uv pip install rumps` (or use `make api` instead).",
            file=sys.stderr,
        )
        sys.exit(1)

    HollerBoxApp().run()


if __name__ == "__main__":
    main()
