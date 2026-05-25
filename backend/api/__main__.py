"""Run `python -m api` or the `hollerbox-api` console script to start the server."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("HOLLERBOX_API_HOST", "127.0.0.1")
    port = int(os.environ.get("HOLLERBOX_API_PORT", "8787"))
    uvicorn.run("api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
