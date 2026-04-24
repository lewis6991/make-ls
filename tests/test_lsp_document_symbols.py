from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_document_symbols_return_targets_and_variables_in_source_order(
    tmp_path: Path,
) -> None:
    text = 'FOO := hello\nall: dep\n\t@echo $(FOO)\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        symbols = await session.document_symbols(uri)

    assert [symbol.name for symbol in symbols] == ['FOO', 'all', 'dep']
    assert [symbol.kind for symbol in symbols] == [
        lsp.SymbolKind.Variable,
        lsp.SymbolKind.Object,
        lsp.SymbolKind.Object,
    ]

    foo_symbol = symbols[0]
    assert foo_symbol.range.start.line == 0
    assert foo_symbol.range.end.line == 0
    assert foo_symbol.selection_range.start.character == 0
    assert foo_symbol.selection_range.end.character == 3

    all_symbol = symbols[1]
    assert all_symbol.range.start.line == 1
    assert all_symbol.range.end.line == 2
    assert all_symbol.selection_range.start.line == 1
    assert all_symbol.selection_range.start.character == 0
    assert all_symbol.selection_range.end.character == 3

    dep_symbol = symbols[2]
    assert dep_symbol.range.start.line == 3
    assert dep_symbol.range.end.line == 4
    assert dep_symbol.selection_range.start.line == 3
    assert dep_symbol.selection_range.start.character == 0
    assert dep_symbol.selection_range.end.character == 3


@pytest.mark.asyncio
async def test_document_symbols_keep_grouped_targets_in_visible_header_order(
    tmp_path: Path,
) -> None:
    text = 'out1 \\\n  out2 &: dep\n\t@echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        symbols = await session.document_symbols(uri)

    assert [symbol.name for symbol in symbols] == ['out1', 'out2']

    first_symbol = symbols[0]
    assert first_symbol.range.start.line == 0
    assert first_symbol.range.end.line == 2
    assert first_symbol.selection_range.start.line == 0
    assert first_symbol.selection_range.start.character == 0
    assert first_symbol.selection_range.end.character == 4

    second_symbol = symbols[1]
    assert second_symbol.range.start.line == 0
    assert second_symbol.range.end.line == 2
    assert second_symbol.selection_range.start.line == 1
    assert second_symbol.selection_range.start.character == 2
    assert second_symbol.selection_range.end.character == 6
