SHELL := /bin/sh

ROOT_DIR := $(abspath ../..)
PYTHON ?= python3
NPM ?= npm
DIST_DIR ?= $(ROOT_DIR)/dist
VSCODE_VERSION ?= $(shell \
	$(PYTHON) -c 'import json; from pathlib import Path; print(json.loads(Path("package.json").read_text())["version"])')
VSCODE_VSIX_NAME ?= make-ls-vscode-$(VSCODE_VERSION).vsix

.PHONY: install
install:
	$(NPM) ci

.PHONY: check
check: install
	$(NPM) run check

.PHONY: package-vsix
package-vsix: check
	mkdir -p "$(DIST_DIR)"
	$(NPM) exec --package @vscode/vsce -- vsce package -o "$(DIST_DIR)/$(VSCODE_VSIX_NAME)"

.PHONY: vsix
vsix: package-vsix
