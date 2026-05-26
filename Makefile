.DEFAULT_GOAL := help

.PHONY: help setup test backend-test web-test dev backend-dev web-dev api app app-run app-build ci ruff clean

help:
	@echo "HollerBox dev commands:"
	@echo ""
	@echo "  make setup         One-shot bootstrap (calls ./setup.sh)"
	@echo "  make test          Run backend + web tests"
	@echo "  make backend-test  Run only backend tests (pytest)"
	@echo "  make web-test      Run only web tests (vitest)"
	@echo "  make ruff          Lint backend with ruff (auto-fixable only)"
	@echo "  make ci            Run everything CI runs (ruff + tests + builds)"
	@echo "  make api           Start the HTTP API on http://127.0.0.1:8787"
	@echo "  make dev           Start the web dev server (http://127.0.0.1:5173)"
	@echo "  make app           Build the web UI + start API serving everything on http://127.0.0.1:8787"
	@echo "  make app-run       Run the macOS menu-bar launcher in dev mode (no PyInstaller bundle)"
	@echo "  make app-build     Build HollerBox.app via PyInstaller (output in app/dist/)"
	@echo "  make clean         Remove caches, .venv, node_modules, build artifacts"
	@echo ""
	@echo "  (For the engine CLI itself, use 'cd backend && uv run hollerbox ...')"

setup:
	@./setup.sh

backend-test:
	@cd backend && uv run pytest

web-test:
	@cd web && npm test

test: backend-test web-test

ruff:
	@cd backend && uv run ruff check . --fix

api:
	@cd backend && uv run hollerbox-api

app:
	@cd web && npm run build
	@cd backend && HOLLERBOX_API_RELOAD=0 uv run hollerbox-api

app-run:
	@cd web && npm run build
	@cd app && uv run python launcher.py

app-build: app/HollerBox.icns
	@cd web && npm run build
	@cd app && uv sync --extra build
	@cd app && uv run pyinstaller HollerBox.spec --clean --noconfirm
	@echo "Built: $(CURDIR)/app/dist/HollerBox.app"

# Generate the macOS app icon from the source logo. Requires `sips` and
# `iconutil` (both ship with macOS by default). Re-runs whenever the
# logo source is newer than the produced .icns.
app/HollerBox.icns: assets/logo.png
	@echo "Generating $(CURDIR)/app/HollerBox.icns from $<"
	@rm -rf app/HollerBox.iconset
	@mkdir -p app/HollerBox.iconset
	@sips -z 16 16     $< --out app/HollerBox.iconset/icon_16x16.png      > /dev/null
	@sips -z 32 32     $< --out app/HollerBox.iconset/icon_16x16@2x.png   > /dev/null
	@sips -z 32 32     $< --out app/HollerBox.iconset/icon_32x32.png      > /dev/null
	@sips -z 64 64     $< --out app/HollerBox.iconset/icon_32x32@2x.png   > /dev/null
	@sips -z 128 128   $< --out app/HollerBox.iconset/icon_128x128.png    > /dev/null
	@sips -z 256 256   $< --out app/HollerBox.iconset/icon_128x128@2x.png > /dev/null
	@sips -z 256 256   $< --out app/HollerBox.iconset/icon_256x256.png    > /dev/null
	@sips -z 512 512   $< --out app/HollerBox.iconset/icon_256x256@2x.png > /dev/null
	@sips -z 512 512   $< --out app/HollerBox.iconset/icon_512x512.png    > /dev/null
	@sips -z 1024 1024 $< --out app/HollerBox.iconset/icon_512x512@2x.png > /dev/null
	@iconutil -c icns app/HollerBox.iconset -o app/HollerBox.icns
	@rm -rf app/HollerBox.iconset

dev:
	@cd web && npm run dev

ci:
	@cd backend && uv run ruff check . && uv run pytest
	@cd web && npm run build && npm test

clean:
	@rm -rf backend/.venv backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	@rm -rf web/node_modules web/dist web/.vite
	@find . -type d -name __pycache__ -not -path './.git/*' -not -path '*/node_modules/*' -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned: .venv, node_modules, dist, caches"
