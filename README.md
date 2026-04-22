# makels

`makels` is a Makefile language server written in Python.

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
uv run makels
```

Any editor that can start a stdio LSP can use it.

## Neovim

```lua
vim.lsp.config("makels", {
  cmd = { "uv", "run", "--directory", "/path/to/makels", "makels" },
  filetypes = { "make" },
  root_markers = { "Makefile", "makefile", "GNUmakefile", ".git" },
})

vim.lsp.enable("makels")
```

## Development

```sh
make check
make test
make build
```
