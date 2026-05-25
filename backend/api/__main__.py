"""Run `python -m api` or the `hollerbox-api` console script to start the server."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("HOLLERBOX_API_HOST", "127.0.0.1")
    port = int(os.environ.get("HOLLERBOX_API_PORT", "8787"))
    # Dev-friendly default: reload on backend file save so users don't end
    # up staring at "extra_forbidden" errors when they pull new code and
    # forget to restart. Flip with `HOLLERBOX_API_RELOAD=0` for prod.
    reload = os.environ.get("HOLLERBOX_API_RELOAD", "1") != "0"
    uvicorn.run("api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
