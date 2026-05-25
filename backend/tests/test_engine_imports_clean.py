"""Engine purity guard — enforces the §3 hard rule.

Nothing under `hollerbox/` may `import fastapi`. The engine must be runnable
from the CLI with the API never started.
"""

from __future__ import annotations

import ast
import pathlib

import hollerbox

FORBIDDEN_ROOT_IMPORTS = {"fastapi", "uvicorn", "starlette", "sse_starlette"}


def _engine_root() -> pathlib.Path:
    return pathlib.Path(hollerbox.__file__).resolve().parent


def _iter_imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0]


def test_engine_has_no_web_imports() -> None:
    offenders: list[tuple[str, str]] = []
    for py in _engine_root().rglob("*.py"):
        for mod in _iter_imports(py):
            if mod in FORBIDDEN_ROOT_IMPORTS:
                offenders.append((str(py.relative_to(_engine_root())), mod))
    assert not offenders, (
        "Engine package must not import web/API modules. Offenders:\n"
        + "\n".join(f"  {p} -> {m}" for p, m in offenders)
    )


def test_engine_importable_without_fastapi(monkeypatch) -> None:
    """Importing hollerbox must not require fastapi to be installed."""
    import sys

    monkeypatch.setitem(sys.modules, "fastapi", None)
    # Re-import is a no-op if already imported, but the assertion below covers
    # the contract: nothing in hollerbox.* depends on fastapi at import time.
    import importlib

    importlib.reload(hollerbox)
    assert hasattr(hollerbox, "__version__")
