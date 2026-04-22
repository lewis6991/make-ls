makels is a Makefile language server written in Python.

Current feature slice:

- hover for targets and variables, with same-workspace fallback for targets
- hover for common GNU Make directives, functions, builtin variables, and special targets from the official manual
- go-to-definition for targets and variables, with same-workspace fallback for targets
- Makefile syntax diagnostics
- shell syntax diagnostics for recipe lines

Implementation notes:

- Make parsing is handled by an owned line-based parser in `src/makels/analysis.py`.
- Shell recipe syntax is checked with `bash -n` after Make-specific normalization.

Development:

- `uv sync --all-groups`
- `make check`
- `make test`
- `make build`

Release automation:

- `.github/workflows/ci.yml` runs commit lint plus the local `make check` gate.
- `.github/workflows/releases.yml` runs release-please for stable releases and updates a rolling nightly release on pushes to `main`.
- `.github/workflows/release-assets.yml` builds and uploads wheel and sdist assets from the same local release entrypoints used by `make`.
- Local release smoke path: `make release-dist RELEASE_CHANNEL=nightly RELEASE_RUN_NUMBER=42`
