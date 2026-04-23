# make-ls plan

## Goal

Give `make-ls` a richer symbol model so diagnostics and editor features can
reason about symbol context instead of piling on span-only heuristics.

The immediate target is conditional context:

- know whether a symbol is in a conditional test or a guarded body
- know which simple guards are active for a symbol use
- use that for unknown-variable warnings first

## Constraints

- keep the analyzer recovery-first and direct
- do not replace the owned parser with a bigger AST system
- preserve the existing LSP behavior while the model grows underneath it
- keep nuanced guard logic commented at the decision point

## Phases

1. Add recovered forms and contextual symbol sites to `AnalyzedDocument`.
2. Recover top-level conditional guards and thread them onto symbol sites.
3. Move unknown-variable warnings onto the contextual model.
4. Migrate references, rename, and hover to use the richer symbol context.
5. Broaden recovered forms later for includes, `define`, and more GNU Make
   shapes once the conditional path is stable.

## Current execution

Land phases 1 to 3 in a reviewable slice:

- add typed forms and symbol context
- recover conditional test/body context and simple guards
- suppress unknown-variable warnings only when the active guard proves the
  variable is meant to exist, such as `ifneq ($(VAR),)` and `ifdef VAR`
