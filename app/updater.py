"""Self-updater for HollerBox.app.

Polls the GitHub Releases API for the project, compares the latest
release's tag to the bundled version, and (if newer) downloads the
release's `HollerBox.zip` asset and swaps the running app on disk via
a tiny helper shell script that survives the parent process quitting.

Update flow:
1. `check_for_update()` → returns an `UpdateAvailable` or `None`.
2. `apply_update(...)` downloads the zip, unpacks it, drops a helper
   shell script, spawns it detached, and tells the caller to quit.
3. The helper waits for the running PID to disappear, replaces the
   installed `HollerBox.app`, then re-opens it.

GitHub API call is anonymous (no token) → 60 req/hr/IP limit, which
is plenty for "once per launch + occasional manual checks".
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

__version__ = "0.0.1"
GITHUB_REPO = "Parth-Kadakia/hollerbox"
RELEASE_ASSET_NAME = "HollerBox.zip"
USER_AGENT = f"HollerBox/{__version__} (+https://github.com/{GITHUB_REPO})"

log = logging.getLogger("hollerbox.updater")


@dataclass(frozen=True)
class UpdateAvailable:
    """A release newer than the running build was found on GitHub."""

    current: str
    latest: str
    asset_url: str
    release_url: str
    notes: str


# --------------------------- version parsing ---------------------------


def parse_version(v: str) -> tuple[int, ...]:
    """Best-effort semver-style tuple. Tolerates leading 'v', drops
    pre-release / build suffixes ("1.0.0a1" → (1, 0, 0))."""
    cleaned = v.lstrip("vV").split("+", 1)[0].split("-", 1)[0]
    out: list[int] = []
    for part in cleaned.split("."):
        if part.isdigit():
            out.append(int(part))
            continue
        # Take leading digits only — "0a1" → 0, not 01.
        leading = ""
        for c in part:
            if c.isdigit():
                leading += c
            else:
                break
        out.append(int(leading) if leading else 0)
    return tuple(out)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


# --------------------------- GitHub poll ---------------------------


def check_for_update(
    *,
    current_version: str = __version__,
    repo: str = GITHUB_REPO,
    timeout: float = 5.0,
) -> UpdateAvailable | None:
    """Hit GitHub's `releases/latest` and return an UpdateAvailable if a
    newer build exists. Returns `None` for "you're on the latest" or
    "couldn't reach GitHub" — never raises, so a startup check can't
    take down the launcher.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(  # noqa: S310 — pinned to api.github.com
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.info("update check skipped: %s", exc)
        return None

    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return None
    if not is_newer(tag, current_version):
        return None

    asset_url = _find_zip_asset(data.get("assets") or [])
    if asset_url is None:
        log.info("release %s has no %s asset; skipping", tag, RELEASE_ASSET_NAME)
        return None

    return UpdateAvailable(
        current=current_version,
        latest=tag.lstrip("vV"),
        asset_url=asset_url,
        release_url=data.get("html_url") or f"https://github.com/{repo}/releases/latest",
        notes=(data.get("body") or "")[:1000],
    )


def _find_zip_asset(assets: list[dict]) -> str | None:
    for a in assets:
        if a.get("name") == RELEASE_ASSET_NAME:
            url = a.get("browser_download_url")
            if isinstance(url, str):
                return url
    # Fall back to anything ending in .zip — looser but useful while we
    # haven't settled the canonical asset name across releases.
    for a in assets:
        name = a.get("name", "")
        if isinstance(name, str) and name.endswith(".zip"):
            url = a.get("browser_download_url")
            if isinstance(url, str):
                return url
    return None


# --------------------------- apply update ---------------------------


def installed_app_path() -> Path | None:
    """Best-effort path to the running `HollerBox.app` bundle.

    Inside a PyInstaller-built `.app`, `sys.executable` is
    `.../HollerBox.app/Contents/MacOS/HollerBox`. Walk up to the .app.
    Outside a bundle (dev `python launcher.py`) we return None — there
    is no installed bundle to swap.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def _cache_dir() -> Path:
    base = Path.home() / "Library" / "Caches" / "HollerBox"
    base.mkdir(parents=True, exist_ok=True)
    return base


def download_and_extract(update: UpdateAvailable) -> Path:
    """Download the release asset and extract it to a cache dir.
    Returns the path to the new `HollerBox.app` inside the extraction."""
    cache = _cache_dir()
    target_dir = cache / f"unpack-{update.latest}"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    req = urllib.request.Request(  # noqa: S310 — GitHub-hosted CDN URL
        update.asset_url, headers={"User-Agent": USER_AGENT}
    )
    log.info("downloading %s", update.asset_url)
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(target_dir)

    # Find the .app inside the extraction. Most zips contain a top-level
    # `HollerBox.app/...` but we don't depend on that name.
    for entry in target_dir.rglob("*.app"):
        return entry.resolve()
    raise RuntimeError(
        f"download from {update.asset_url} contained no .app bundle"
    )


_HELPER_SCRIPT = """#!/bin/bash
# HollerBox auto-update helper. Waits for the running parent to exit,
# then atomically replaces the installed .app and relaunches.
set -e
parent_pid="$1"
installed_app="$2"
new_app="$3"
log="$HOME/.hollerbox/launcher.log"

echo "--- update helper $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$log"
echo "parent_pid=$parent_pid" >> "$log"
echo "installed=$installed_app" >> "$log"
echo "new=$new_app" >> "$log"

# Wait up to 30 seconds for the parent to quit cleanly.
for i in $(seq 1 60); do
  if ! kill -0 "$parent_pid" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

# Atomic swap. Move old aside first so a rollback is possible.
backup="$installed_app.old.$$"
if [ -d "$installed_app" ]; then
  mv "$installed_app" "$backup" >> "$log" 2>&1 || true
fi
mv "$new_app" "$installed_app" >> "$log" 2>&1

# Strip quarantine so macOS launches the freshly-moved bundle.
xattr -cr "$installed_app" >> "$log" 2>&1 || true
codesign --force --deep --sign - "$installed_app" >> "$log" 2>&1 || true

# Relaunch.
open "$installed_app" >> "$log" 2>&1

# Best-effort cleanup of the previous version.
rm -rf "$backup" >> "$log" 2>&1 || true
"""


def apply_update(update: UpdateAvailable) -> None:
    """Download the new bundle and spawn the swap helper.

    Caller is expected to call `rumps.quit_application()` immediately
    after this returns — the helper script waits for our PID to exit
    before doing anything destructive.
    """
    installed = installed_app_path()
    if installed is None:
        raise RuntimeError(
            "auto-update requires the installed HollerBox.app — running from "
            "source instead. Use `git pull && make app-build`."
        )
    new_app = download_and_extract(update)

    helper = Path(tempfile.mkdtemp(prefix="hb-update-")) / "swap.sh"
    helper.write_text(_HELPER_SCRIPT, encoding="utf-8")
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    log.info("spawning update helper: %s", helper)
    subprocess.Popen(  # noqa: S603
        ["bash", str(helper), str(os.getpid()), str(installed), str(new_app)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
