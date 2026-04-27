from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from pathlib import Path


def highlight_set(
    highlights: list[lsp.DocumentHighlight] | None,
) -> set[tuple[int, int, lsp.DocumentHighlightKind | None]]:
    if highlights is None:
        raise AssertionError('expected document highlights')
    return {
        (
            highlight.range.start.line,
            highlight.range.start.character,
            highlight.kind,
        )
        for highlight in highlights
    }


@pytest.mark.asyncio
async def test_document_highlight_for_target_marks_definition_and_references(
    tmp_path: Path,
) -> None:
    text = 'all: dep\nother: dep\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        highlights = await session.document_highlight(uri, 0, 6)

    assert highlight_set(highlights) == {
        (0, 5, lsp.DocumentHighlightKind.Read),
        (1, 7, lsp.DocumentHighlightKind.Read),
        (2, 0, lsp.DocumentHighlightKind.Write),
    }


@pytest.mark.asyncio
async def test_document_highlight_for_variable_uses_inner_reference_name_ranges(
    tmp_path: Path,
) -> None:
    text = 'FOO := hello\nBAR := $(FOO)\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        highlights = await session.document_highlight(uri, 1, 10)

    assert highlight_set(highlights) == {
        (0, 0, lsp.DocumentHighlightKind.Write),
        (1, 9, lsp.DocumentHighlightKind.Read),
        (3, 9, lsp.DocumentHighlightKind.Read),
    }


@pytest.mark.asyncio
async def test_document_highlight_for_variable_follows_included_definition_identity(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text('FEATURE := enabled\n', encoding='utf-8')
    text = 'include rules.mk\nall:\n\t@echo $(FEATURE)\nother:\n\t@echo $(FEATURE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        highlights = await session.document_highlight(uri, 2, 10)

    assert highlight_set(highlights) == {
        (2, 9, lsp.DocumentHighlightKind.Read),
        (4, 9, lsp.DocumentHighlightKind.Read),
    }


@pytest.mark.asyncio
async def test_document_highlight_skips_builtin_variable_reference_before_local_shadow(
    tmp_path: Path,
) -> None:
    text = 'all:\n\t@echo $(MAKE)\nMAKE := wrapper\nlater:\n\t@echo $(MAKE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        highlights = await session.document_highlight(uri, 1, 10)

    assert highlights is None
