# make-ls plan

Build a small, typed Makefile language server in Python.

Use:

- `uv`
- `pygls` and `lsprotocol`
- `ruff`
- `basedpyright`
- `pytest`

Keep the code direct. Own the Make parser. Use `bash -n` for recipe syntax checks. Avoid abstraction creep.

Current scope:

- hover, go-to-definition, and references for targets and variables
- hover for common GNU Make directives, functions, builtin variables, and special targets
- variable rename
- `check` subcommand for batch diagnostics
- Makefile syntax diagnostics
- recipe shell syntax diagnostics
- target lookup through explicit include directives

Next:

1. Broaden GNU Make coverage for include path expansion, pattern rules, and prerequisite shapes.
2. Add more end-to-end coverage for document changes and include-heavy layouts.
3. Only then consider editor extras like completion or semantic tokens.

Update this file only when scope or direction changes.
