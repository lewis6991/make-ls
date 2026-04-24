SHELL := /bin/sh

UV ?= uv
DIST_DIR ?= dist
RELEASE_CHANNEL ?= stable
RELEASE_RUN_NUMBER ?= 1
RELEASE_VERSION ?= $(shell $(UV) run python scripts/release_version.py compute --channel "$(RELEASE_CHANNEL)" --run-number "$(RELEASE_RUN_NUMBER)")

.PHONY: test
test:
	$(UV) run python -m pytest

.PHONY: check
check:
	$(UV) run basedpyright
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run python -m pytest

.PHONY: build
build:
	$(UV) build --out-dir "$(DIST_DIR)"

.PHONY: vscode-install
vscode-install:
	$(MAKE) -C editors/vscode install

.PHONY: vscode-check
vscode-check:
	$(MAKE) -C editors/vscode check

.PHONY: vscode-vsix
vscode-vsix:
	$(MAKE) -C editors/vscode vsix

.PHONY: release-stamp
release-stamp:
	$(UV) run python scripts/release_version.py stamp "$(RELEASE_VERSION)"

.PHONY: release-dist
release-dist: release-stamp
	$(UV) build --out-dir "$(DIST_DIR)"
