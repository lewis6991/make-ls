# make-ls

[![CI](https://github.com/lewis6991/makels/actions/workflows/ci.yml/badge.svg)](https://github.com/lewis6991/makels/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/make-ls)](https://pypi.org/project/make-ls/)
[![Python](https://img.shields.io/pypi/pyversions/make-ls)](https://pypi.org/project/make-ls/)
[![License](https://img.shields.io/github/license/lewis6991/makels)](LICENSE)

`make-ls` is a Makefile language server.

## Install

```sh
uv tool install make-ls
```

## Quick Start

Start the stdio language server:

```sh
make-ls
```

Run the batch checker:

```sh
make-ls check .
make-ls check --format json . > make-ls.sarif
```

## Neovim

```lua
vim.lsp.config('make-ls', {
  cmd = { 'make-ls' },
  filetypes = { 'make' },
  root_markers = { 'Makefile' },
})

vim.lsp.enable("make-ls")
```

## VS Code

See [editors/vscode/README.md](editors/vscode/README.md) for the VS Code
extension, settings, and VSIX packaging flow.

## Docs

- [User Guide](docs/user-guide.md) for features, diagnostics, `check`, logging,
  and limits
- [VS Code](editors/vscode/README.md)
- [Architecture](docs/architecture.md)

## Development

```sh
uv sync --all-groups
make check
make test
make build
make vscode-vsix
```
