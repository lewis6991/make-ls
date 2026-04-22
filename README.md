# make-ls

[![CI](https://github.com/lewis6991/makels/actions/workflows/ci.yml/badge.svg)](https://github.com/lewis6991/makels/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/make-ls)](https://pypi.org/project/make-ls/)
[![Python](https://img.shields.io/pypi/pyversions/make-ls)](https://pypi.org/project/make-ls/)
[![License](https://img.shields.io/github/license/lewis6991/makels)](LICENSE)

`make-ls` is a Makefile language server written in Python.

It uses an owned Make parser and checks recipe shell syntax with `bash -n`.

## Features

- hover, go-to-definition, and references for targets and variables
- variable rename
- hover for common GNU Make directives, functions, builtin variables, and special targets
- diagnostics for Makefile syntax
- diagnostics for shell syntax inside recipes
- target lookup through explicit `include`, `-include`, and `sinclude` directives

## Limits

- no full GNU Make evaluation
- include resolution is still limited
- no completion or code actions yet

## Install

```sh
uv tool install make-ls
```

## Run

```sh
make-ls
```

For local development:

```sh
uv sync --all-groups
uv run make-ls
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

## Development

```sh
make check
make test
make build
```
