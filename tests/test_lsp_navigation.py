from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession
from .lsp_test_utils import apply_text_edits, location_set, single_location

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_go_to_definition_for_prerequisite(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 0, 6)

    location = single_location(definition)
    assert location.range.start.line == 3
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_for_prerequisite_matching_pattern_rule(tmp_path: Path) -> None:
    text = 'build_all: build_alpha\n\t@echo done\n\nbuild_%:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 0, 12)

    location = single_location(definition)
    assert location.range.start.line == 3
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_for_prerequisite_falls_back_to_included_makefile(
    tmp_path: Path,
) -> None:
    remote_path = tmp_path / 'rules.mk'
    _ = remote_path.write_text('dep:\n\t@echo dep\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 2, 6)

    location = single_location(definition)
    assert location.uri == remote_path.as_uri()
    assert location.range.start.line == 0
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_for_ambiguous_included_target_returns_all_locations(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / 'a.mk'
    second_path = tmp_path / 'b.mk'
    _ = first_path.write_text('dep:\n\t@echo a\n', encoding='utf-8')
    _ = second_path.write_text('dep:\n\t@echo b\n', encoding='utf-8')
    text = 'include a.mk b.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 2, 6)

    assert isinstance(definition, list)
    assert {(location.uri, location.range.start.line) for location in definition} == {
        (first_path.as_uri(), 0),
        (second_path.as_uri(), 0),
    }


@pytest.mark.asyncio
async def test_go_to_definition_prefers_local_target_over_included_fallback(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text('dep:\n\t@echo remote\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n\ndep:\n\t@echo local\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 2, 6)

    location = single_location(definition)
    assert location.uri == uri
    assert location.range.start.line == 5
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_follows_nested_includes(tmp_path: Path) -> None:
    remote_path = tmp_path / 'more.mk'
    _ = remote_path.write_text('dep:\n\t@echo dep\n', encoding='utf-8')
    _ = (tmp_path / 'rules.mk').write_text('include more.mk\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 2, 6)

    location = single_location(definition)
    assert location.uri == remote_path.as_uri()
    assert location.range.start.line == 0
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_for_variable_reference(tmp_path: Path) -> None:
    text = 'FOO := hello\nBAR = $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 1, 7)

    location = single_location(definition)
    assert location.range.start.line == 0
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_references_for_target_excludes_declarations_when_requested(tmp_path: Path) -> None:
    text = 'all: dep\nother: dep\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        references = await session.references(uri, 2, 1, include_declaration=False)

    assert location_set(references) == {
        (uri, 0, 5),
        (uri, 1, 7),
    }


@pytest.mark.asyncio
async def test_references_for_target_follow_included_makefiles(tmp_path: Path) -> None:
    remote_path = tmp_path / 'rules.mk'
    _ = remote_path.write_text('dep:\n\t@echo dep\nother: dep\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        references = await session.references(uri, 2, 6, include_declaration=True)

    assert location_set(references) == {
        (uri, 2, 5),
        (remote_path.as_uri(), 0, 0),
        (remote_path.as_uri(), 2, 7),
    }


@pytest.mark.asyncio
async def test_references_for_variable_include_definition_and_references(
    tmp_path: Path,
) -> None:
    text = 'FOO := hello\nBAR = $(FOO)\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        references = await session.references(uri, 1, 8, include_declaration=True)

    assert location_set(references) == {
        (uri, 0, 0),
        (uri, 1, 8),
        (uri, 3, 9),
    }


@pytest.mark.asyncio
async def test_references_for_variable_skip_builtin_references_before_local_shadow(
    tmp_path: Path,
) -> None:
    text = 'all:\n\t@echo $(MAKE)\nMAKE := wrapper\nlater:\n\t@echo $(MAKE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        references = await session.references(uri, 2, 1, include_declaration=True)

    assert location_set(references) == {
        (uri, 2, 0),
        (uri, 4, 9),
    }


@pytest.mark.asyncio
async def test_prepare_rename_for_variable_reference_uses_inner_variable_range(
    tmp_path: Path,
) -> None:
    text = 'FOO := hello\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        result = await session.prepare_rename(uri, 2, 9)

    assert isinstance(result, lsp.PrepareRenamePlaceholder)
    assert result.placeholder == 'FOO'
    assert result.range.start.line == 2
    assert result.range.start.character == 9
    assert result.range.end.character == 12


@pytest.mark.asyncio
async def test_rename_variable_updates_definition_and_references(tmp_path: Path) -> None:
    text = 'FOO := hello\nBAR = $(FOO)\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        workspace_edit = await session.rename(uri, 1, 8, 'GREETING')

    assert workspace_edit is not None
    assert workspace_edit.changes is not None
    edits = list(workspace_edit.changes[uri])
    updated = apply_text_edits(text, edits)
    assert updated == 'GREETING := hello\nBAR = $(GREETING)\nall:\n\t@echo $(GREETING)\n'


@pytest.mark.asyncio
async def test_rename_variable_skips_builtin_references_before_local_shadow(
    tmp_path: Path,
) -> None:
    text = 'all:\n\t@echo $(MAKE)\nMAKE := wrapper\nlater:\n\t@echo $(MAKE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        workspace_edit = await session.rename(uri, 2, 1, 'TOOL')

    assert workspace_edit is not None
    assert workspace_edit.changes is not None
    edits = list(workspace_edit.changes[uri])
    updated = apply_text_edits(text, edits)
    assert updated == 'all:\n\t@echo $(MAKE)\nTOOL := wrapper\nlater:\n\t@echo $(TOOL)\n'
