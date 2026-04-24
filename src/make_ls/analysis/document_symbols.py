"""Document symbol rendering over recovered Makefile definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lsprotocol import types as lsp

if TYPE_CHECKING:
    from make_ls.types import AnalyzedDoc, TargetDef, VarDef


def document_symbols(document: AnalyzedDoc) -> list[lsp.DocumentSymbol]:
    symbols: list[tuple[int, int, lsp.DocumentSymbol]] = []

    symbols.extend(
        (
            definition.name_span.start_line,
            definition.name_span.start_character,
            _target_symbol(definition),
        )
        for definitions in document.targets.values()
        for definition in definitions
    )

    symbols.extend(
        (
            definition.name_span.start_line,
            definition.name_span.start_character,
            _variable_symbol(definition),
        )
        for definitions in document.variables.values()
        for definition in definitions
    )

    # Grouped targets share one rule span, so order by the concrete name span
    # the user sees in the buffer instead of the shared enclosing range.
    symbols.sort(key=lambda entry: (entry[0], entry[1]))
    return [symbol for _line, _character, symbol in symbols]


def _target_symbol(definition: TargetDef) -> lsp.DocumentSymbol:
    return lsp.DocumentSymbol(
        name=definition.name,
        kind=lsp.SymbolKind.Object,
        range=definition.rule_span.to_lsp_range(),
        selection_range=definition.name_span.to_lsp_range(),
    )


def _variable_symbol(definition: VarDef) -> lsp.DocumentSymbol:
    return lsp.DocumentSymbol(
        name=definition.name,
        kind=lsp.SymbolKind.Variable,
        range=definition.assignment_span.to_lsp_range(),
        selection_range=definition.name_span.to_lsp_range(),
    )
