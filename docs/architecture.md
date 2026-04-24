# Architecture

`make-ls` stays small by building a single recovered document model and letting
the CLI and LSP features read from that model.

Module docstrings are the source of truth for code-local behavior. This page
stays at the repo-shape level so it does not duplicate them.

## Code map

- `src/make_ls/__main__.py`: CLI entrypoints for stdio LSP mode and batch
  checking
- `src/make_ls/types.py`: shared recovered model centered on `AnalyzedDoc`
- `src/make_ls/analysis.py`: pipeline coordinator that builds one analyzed
  document snapshot
- `src/make_ls/_analysis_recovery.py`: recovery passes for conditionals,
  includes, rules, and assignments
- `src/make_ls/_analysis_diagnostics.py`: diagnostic passes over the recovered
  model
- `src/make_ls/_analysis_completion.py`: completion over recovered symbols plus
  lightweight line-context detection
- `src/make_ls/server.py`: LSP server wiring, caches, and included-document
  traversal
- `src/make_ls/_analysis_hover.py`: hover rendering and builtin GNU Make docs
- `src/make_ls/_analysis_navigation.py`: definition, references, and rename

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
