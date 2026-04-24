# Architecture

`make-ls` stays small by building a single recovered document model and letting
the CLI and LSP features read from that model.

Module docstrings are the source of truth for code-local behavior. This page
stays at the repo-shape level so it does not duplicate them.

## Code map

- `src/make_ls/__main__.py`: CLI entrypoints for stdio LSP mode and batch
  checking
- `src/make_ls/types.py`: shared recovered model centered on `AnalyzedDoc`
- `src/make_ls/analysis/__init__.py`: pipeline coordinator that builds one
  analyzed document snapshot
- `src/make_ls/analysis/recovery.py`: recovery passes for conditionals,
  includes, rules, and assignments
- `src/make_ls/analysis/diagnostics/*.py`: one diagnostic pass per module over
  the recovered model
- `src/make_ls/analysis/completion.py`: completion over recovered symbols plus
  lightweight line-context detection
- `src/make_ls/analysis/hover.py`: hover rendering and builtin GNU Make docs
- `src/make_ls/analysis/navigation.py`: definition, references, and rename
- `src/make_ls/lsp/server.py`: LSP server state, caches, and included-document
  traversal
- `src/make_ls/lsp/features/*.py`: per-feature LSP handlers wired by the server
- `src/make_ls/server.py`: compatibility wrapper for the packaged LSP server

## Tests

The test split mirrors the runtime split:

- `tests/test_analysis.py` covers the document model and focused analyzer cases.
- `tests/test_cli.py` covers the CLI surface, help, checker behavior, and JSON
  output.
- `tests/test_lsp_*.py` covers LSP behavior end to end, split by feature.

For narrow analyzer work, start with `tests/test_analysis.py`. For changes that
affect actual editor behavior, prove them in the relevant `tests/test_lsp_*.py`
module.

## Related notes

- `README.md` is the user-facing package doc.
- `PLAN.md` tracks the current analyzer direction and near-term modeling work.
