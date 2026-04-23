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
- quick fixes for unknown variables that add an empty assignment
- quick fixes for unresolved prerequisites that create a target stub recipe
- `check` subcommand for batch diagnostics
- hover for common GNU Make directives, functions, builtin variables, and special targets
- diagnostics for Makefile syntax
- diagnostics for unresolved plain prerequisites
- diagnostics for shell syntax inside recipes
- target lookup through explicit `include`, `-include`, and `sinclude` directives

## Limits

- no full GNU Make evaluation
- include resolution is still limited
- no completion yet

## Install

```sh
uv tool install make-ls
```

## Run

```sh
make-ls
```

In stdio LSP mode this writes logs to `$XDG_STATE_HOME/make-ls/`, or
`~/.local/state/make-ls/` when `XDG_STATE_HOME` is unset. The default file name
is a stable hash derived from the launch directory.

To override the log path:

```sh
make-ls --log-file /tmp/make-ls.log --log-level debug
```

To disable file logging entirely:

```sh
make-ls --no-log-file
```

Lint files or directories:

```sh
make-ls check Makefile rules.mk
make-ls check .
make-ls check --format json . > make-ls.sarif
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

With the default `cmd = { 'make-ls' }`, Neovim LSP logs land in a launch-path
specific file under the XDG state log directory.

## Development

```sh
make check
make test
make build
```
