# PyInstaller spec for the macOS HollerBox menu-bar app.
#
# Build with:
#   cd web && npm run build     # produces web/dist
#   cd app && uv sync --extra build
#   cd app && uv run pyinstaller HollerBox.spec --clean --noconfirm
#
# Output: `app/dist/HollerBox.app` — drag into /Applications.

# ruff: noqa: F821  (PyInstaller exposes Analysis/PYZ/EXE/BUNDLE as builtins)
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821
REPO_ROOT = SPEC_DIR.parent
WEB_DIST = REPO_ROOT / "web" / "dist"
TEMPLATES_DIR = REPO_ROOT / "workflows" / "templates"
LOGO = REPO_ROOT / "assets" / "logo.png"

datas = []
if WEB_DIST.is_dir():
    datas.append((str(WEB_DIST), "web/dist"))
if TEMPLATES_DIR.is_dir():
    datas.append((str(TEMPLATES_DIR), "workflows/templates"))
if LOGO.is_file():
    datas.append((str(LOGO), "assets"))

hiddenimports = [
    # Steps + providers register themselves on import — PyInstaller's
    # static analysis doesn't catch the registry side-effects, so list
    # them explicitly.
    "hollerbox.steps.shell",
    "hollerbox.steps.python_step",
    "hollerbox.steps.http",
    "hollerbox.steps.files",
    "hollerbox.steps.llm",
    "hollerbox.steps.image",
    "hollerbox.providers.anthropic",
    "hollerbox.providers.openai",
    "hollerbox.providers.openai_image",
    "hollerbox.providers.gemini_image",
    "hollerbox.providers.ollama",
    "hollerbox.providers.mock",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]


a = Analysis(  # noqa: F821
    [str(SPEC_DIR / "launcher.py")],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure, a.zipped_data)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HollerBox",
    console=False,
    debug=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="HollerBox",
)

app = BUNDLE(  # noqa: F821
    coll,
    name="HollerBox.app",
    icon=None,  # ship a real .icns later; for now macOS uses a default
    bundle_identifier="com.brandbox.hollerbox",
    info_plist={
        "LSUIElement": True,           # menu-bar only, no Dock icon
        "CFBundleShortVersionString": "0.0.1",
        "NSHighResolutionCapable": True,
    },
)
