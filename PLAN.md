# MakeLS Plan

Build a small, typed Makefile language server in Python.

Use:

- `uv`
- `pygls` and `lsprotocol`
- `ruff`
- `basedpyright`
- `pytest`

Keep the code direct. Own the Make parser. Use `bash -n` for recipe syntax checks. Avoid abstraction creep.

Current scope:

- hover and go-to-definition for targets and variables
- hover for common GNU Make directives, functions, builtin variables, and special targets
- Makefile syntax diagnostics
- recipe shell syntax diagnostics
- same-workspace target lookup

Next:

1. Add include-aware workspace resolution.
2. Broaden GNU Make coverage for includes, pattern rules, and prerequisite shapes.
3. Add more end-to-end coverage for document changes and workspace behavior.
4. Only then consider editor extras like completion or semantic tokens.

Update this file only when scope or direction changes.
