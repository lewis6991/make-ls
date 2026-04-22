makels is a Makefile language server written in Python.

Current feature slice:

- hover for targets and variables
- go-to-definition for targets and variables
- Makefile syntax diagnostics
- shell syntax diagnostics for recipe lines

Implementation notes:

- Make parsing is handled by an owned line-based parser in `src/makels/analysis.py`.
- Shell recipe syntax is checked with `bash -n` after Make-specific normalization.
