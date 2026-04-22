# MakeLS Plan

## Goal

Build a Makefile language server in modern Python with:

- `uv` for environment and dependency management
- `pygls` and `lsprotocol` for the LSP transport and typed protocol models
- `basedpyright` for aggressive static analysis
- `ruff` for formatting and linting
- `pytest` for an end-to-end test suite

The first feature slice must cover:

- go-to-definition
- hover
- diagnostics for normal Makefile syntax
- diagnostics for shell syntax inside recipe lines

This project should stay small, typed, and easy to reason about. Prefer direct code paths over abstraction layers. Subtle logic should be commented.

## Product Scope

### Initial language features

1. Parse Makefiles into a lightweight semantic model.
2. Index target definitions and variable definitions.
3. Resolve symbol references for:
   - target names in prerequisite lists
   - variable references such as `$(FOO)` and `${FOO}`
4. Return hover information for targets and variables.
5. Return definition locations for targets and variables.
6. Publish diagnostics for:
   - malformed Makefile structure
   - malformed assignments and directives where detectable
   - undefined or suspicious references when the parser can prove them
   - shell syntax errors in recipe commands

### Initial file scope

Start with the currently opened Makefile document, then extend to related workspace files once the single-file path is solid. Support these filenames first:

- `Makefile`
- `makefile`
- `GNUmakefile`
- `*.mk`

### Non-goals for the first slice

Do not block on these before the server is useful:

- full GNU Make evaluation semantics
- macro expansion execution
- full include graph correctness
- completion
- rename
- references
- code actions
- semantic tokens

## Architecture

### LSP layer

Use `pygls` as the server framework and `lsprotocol` types for requests and responses.

The server entrypoint should be thin:

- create the server
- register handlers
- map document events to analysis
- publish diagnostics

Keep analysis logic out of handlers.

### Core modules

Proposed package layout:

```text
src/makels/
  __init__.py
  __main__.py
  server.py
  settings.py
  documents.py
  parser.py
  symbols.py
  analysis.py
  diagnostics.py
  hover.py
  definition.py
  shellcheck.py
  types.py
```

Keep modules narrow and direct. If two modules only call each other through tiny wrappers, collapse them.

### Parsing strategy

Use existing parser libraries instead of hand-writing a parser.

Preferred approach:

1. Use Tree-sitter for Makefile parsing.
2. Use Tree-sitter Bash or another real shell parser for recipe shell lines.

Why:

- concrete ranges for LSP diagnostics and definitions
- better resilience than regex-only parsing
- less reinvention

Implementation note:

- Recipes need special handling because Make syntax prefixes lines with tab-indented shell commands and may add command modifiers such as `@`, `-`, and `+`.
- Strip only the recipe control prefixes that are not part of the shell command before feeding the line to the shell parser.
- Document any lossy normalization in comments because it is subtle.

If the preferred Tree-sitter package set is awkward in Python, the fallback is:

- keep Tree-sitter for Makefiles
- use `bashlex` or another real shell parser for shell recipe syntax

Do not fall back to ad hoc shell regex parsing unless every library option is exhausted.

### Semantic model

The semantic layer should produce a compact, typed document model:

- targets
- variables
- include directives
- recipe blocks
- references with source ranges
- parse errors with source ranges

Each symbol should track:

- name
- kind
- definition range
- documentation source snippet
- source URI

Keep the model immutable after analysis where practical. Rebuild on document changes instead of maintaining clever incremental mutation until there is a proven performance problem.

### Hover strategy

Hover should provide small, useful summaries:

- target name
- prerequisite list when present
- first recipe line when present
- source location

For variables:

- variable name
- assignment operator
- assigned value preview
- source location

Hover output should be terse markdown. No essay mode.

### Definition strategy

Definition should resolve:

- target references in prerequisite lists to target definitions
- variable references to variable definitions in the same document

When multiple definitions exist:

- return all matching locations if the semantics are genuinely ambiguous
- otherwise prefer the nearest meaningful definition and document the rule in code comments

Start with same-document resolution. Workspace-wide resolution can come next once tests are stable.

### Diagnostics strategy

Diagnostics should come from two paths.

#### Make diagnostics

Source:

- parser errors
- semantic validation passes over the parsed tree

Examples:

- missing separators
- broken target or assignment shapes
- malformed variable references
- references that cannot be resolved when the syntax proves they are local names

Severity should stay conservative. Prefer high-confidence diagnostics over noisy guesses.

#### Shell diagnostics

Source:

- parse each logical recipe line with the shell parser

Requirements:

- handle escaped newlines within recipes
- ignore leading Make recipe control characters only when they are actually prefixes
- map shell parser errors back to original document ranges

Do not attempt full environment-aware shell linting yet. Syntax diagnostics are enough for the first cut.

## Project Layout And Tooling

### Python version

Target Python 3.12+ unless a dependency forces a different floor.

### `uv`

Use `uv` for:

- project initialization
- dependency locking
- running tools

Expected commands later:

- `uv sync`
- `uv run basedpyright`
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run pytest`

### `pyproject.toml`

Configure:

- package metadata
- runtime dependencies
- dev dependencies
- `ruff`
- `basedpyright`
- `pytest`

Keep config in `pyproject.toml` unless a tool strongly benefits from a separate file.

### Typing and linting rules

Bias toward strictness. This is a vibe-coded project, so static analysis should catch as much slop as possible.

Required posture:

- strict `basedpyright`
- no untyped defs in core code
- avoid `Any`
- explicit dataclasses or typed tuples for structured analysis data
- fix lint issues instead of suppressing them

When a suppression is unavoidable, add a short reason.

## Test Strategy

Tests must prove the actual LSP behavior, not just helper functions.

### Test layers

1. Parser and analysis unit tests
2. LSP-level end-to-end tests

### End-to-end test expectations

Spin up the server in-process and exercise JSON-RPC/LSP flows through the server surface rather than calling feature helpers directly.

Cover at least:

- open document and receive Makefile diagnostics
- open document and receive shell diagnostics for recipe lines
- hover on a target definition
- hover on a variable reference
- go-to-definition from a prerequisite
- go-to-definition from a variable reference
- multi-line recipe shell syntax failure reporting

If a thin helper is needed to drive the server in tests, keep it in the tests package and keep it small.

### Fixture strategy

Use compact inline Makefile samples unless a test becomes unreadable. For larger cases, use fixture files under `tests/fixtures/`.

Prefer explicit expected ranges over snapshot blobs.

## Delivery Plan

### Phase 1: bootstrap

1. Initialize `uv` project structure.
2. Add runtime and dev dependencies.
3. Create package layout.
4. Configure `ruff`, `basedpyright`, and pytest.

Exit criteria:

- project installs with `uv sync`
- empty test suite runs
- lint and typecheck commands run cleanly

### Phase 2: parsing and document analysis

1. Integrate the Makefile parser.
2. Build the typed document model.
3. Extract target, variable, recipe, and reference nodes.
4. Surface parse diagnostics.

Exit criteria:

- parser-backed analysis works on representative Makefiles
- parser errors map to stable document ranges

### Phase 3: shell diagnostics

1. Integrate the shell parser.
2. Normalize recipe command prefixes.
3. Parse recipe shell commands.
4. Map shell syntax failures to diagnostics.

Exit criteria:

- recipe shell syntax errors publish with useful ranges
- false positives for command prefixes are covered by tests

### Phase 4: hover and go-to-definition

1. Implement symbol resolution.
2. Add hover rendering.
3. Add definition lookup.
4. Wire handlers into the LSP server.

Exit criteria:

- target and variable hover work
- target and variable definition lookup work

### Phase 5: end-to-end hardening

1. Add in-process LSP tests.
2. Add focused fixture coverage for tricky Make syntax.
3. Tighten typing and linting until clean.

Exit criteria:

- `pytest`, `ruff`, and `basedpyright` all pass
- test suite covers the first feature slice end to end

## Risks And Design Notes

### GNU Make syntax is messy

Make has context-sensitive parsing rules. The first version should aim for useful correctness on common patterns, not full GNU Make emulation.

### Shell parsing inside recipes is lossy

Make prefixes and line continuations can distort the raw shell command. Keep the normalization rules explicit and heavily tested.

### Include handling can sprawl fast

Do not start with a global workspace graph unless it is needed for the first feature slice. Same-document correctness is more important than premature workspace cleverness.

### Diagnostics can get noisy

Only emit diagnostics when the parser or the semantic pass can justify them with high confidence.

## Definition Of Done For The First Milestone

The first milestone is complete when the repo contains:

- a runnable LSP server package
- `uv`-managed project metadata
- strict `basedpyright` and `ruff` configuration
- Makefile parser-backed diagnostics
- recipe shell syntax diagnostics
- hover for targets and variables
- go-to-definition for targets and variables
- an end-to-end pytest suite covering the supported flows

And these commands pass:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run basedpyright`
- `uv run pytest`

## Session Rules

Every session working in this repo must:

1. Read `PLAN.md`.
2. Read `STATUS.md`.
3. Update `STATUS.md` before starting substantial work.
4. Update `STATUS.md` again before ending the session.

`STATUS.md` is the source of truth for handoff state. `PLAN.md` is the durable design and execution plan.
