# make-ls

[![CI](https://github.com/lewis6991/makels/actions/workflows/ci.yml/badge.svg)](https://github.com/lewis6991/makels/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/make-ls)](https://pypi.org/project/make-ls/)
[![Python](https://img.shields.io/pypi/pyversions/make-ls)](https://pypi.org/project/make-ls/)
[![License](https://img.shields.io/github/license/lewis6991/makels)](LICENSE)

`make-ls` is a Makefile language server written in Python.

It is still early, but it is already useful for real Makefiles. The server uses
an owned line-based Make parser and checks recipe shell syntax with `bash -n`.

## What it does

- hover for targets and variables
- hover for common GNU Make directives, functions, builtin variables, and special targets
- go-to-definition for targets and variables
- diagnostics for Makefile syntax
- diagnostics for shell syntax inside recipes
- same-workspace target lookup across `Makefile`, `makefile`, `GNUmakefile`, and `*.mk`

## What it does not do yet

- full GNU Make evaluation
- include-aware workspace resolution
- completion, rename, references, or code actions

## Run it

```sh
uv sync --all-groups
uv run make-ls
```

Any editor that can start a stdio LSP can use it.

## Neovim

```lua
vim.lsp.config("make-ls", {
  cmd = { "uv", "run", "--directory", "/path/to/make-ls", "make-ls" },
  filetypes = { "make" },
  root_markers = { "Makefile", "makefile", "GNUmakefile", ".git" },
})

vim.lsp.enable("make-ls")
```

## Development

```sh
make check
make test
make build
```

## Release

Stable releases from `.github/workflows/releases.yml` publish GitHub assets and
upload the tagged distribution to PyPI with trusted publishing. Configure PyPI
to trust `.github/workflows/releases.yml` and, if you keep it, the `pypi`
environment.
