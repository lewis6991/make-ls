from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession
from .lsp_test_utils import (
    completion_by_label,
    completion_documentation_value,
    completion_text_edit,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_completes_local_and_builtin_variables_inside_variable_reference(
    tmp_path: Path,
) -> None:
    text = 'MAKE_LOCAL := 1\nall:\n\t@echo $(MAK)\n'
    completion_character = text.splitlines()[2].index(')')

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        items = await session.completion(uri, 2, completion_character)

    items_by_label = completion_by_label(items)
    assert 'MAKE' in items_by_label
    assert 'MAKE_LOCAL' in items_by_label

    local_item = items_by_label['MAKE_LOCAL']
    assert local_item.kind == lsp.CompletionItemKind.Variable
    local_edit = completion_text_edit(local_item)
    assert local_edit.new_text == 'MAKE_LOCAL'
    assert local_edit.range.start.character == completion_character - 3
    assert local_edit.range.end.character == completion_character

    builtin_item = items_by_label['MAKE']
    assert builtin_item.kind == lsp.CompletionItemKind.Variable
    builtin_edit = completion_text_edit(builtin_item)
    assert builtin_edit.new_text == 'MAKE'


@pytest.mark.asyncio
async def test_completes_builtin_functions_inside_variable_reference(tmp_path: Path) -> None:
    text = 'all:\n\t@echo $(fi)\n'
    completion_character = text.splitlines()[1].index(')')

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        items = await session.completion(uri, 1, completion_character)

    items_by_label = completion_by_label(items)
    assert 'filter' in items_by_label
    assert 'findstring' in items_by_label

    filter_item = items_by_label['filter']
    assert filter_item.kind == lsp.CompletionItemKind.Function
    filter_edit = completion_text_edit(filter_item)
    assert filter_edit.new_text == 'filter '


@pytest.mark.asyncio
async def test_completion_documentation_does_not_repeat_detail_lines(tmp_path: Path) -> None:
    text = '# local docs\nMAKE_LOCAL := 1\nall:\n\t@echo $(MAK)\n'
    completion_character = text.splitlines()[3].index(')')

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        items = await session.completion(uri, 3, completion_character)

    items_by_label = completion_by_label(items)

    local_item = items_by_label['MAKE_LOCAL']
    assert local_item.detail == 'MAKE_LOCAL := 1'
    assert completion_documentation_value(local_item) == 'local docs'

    builtin_item = items_by_label['MAKE']
    assert builtin_item.detail == '$(MAKE)'
    builtin_documentation = completion_documentation_value(builtin_item)
    assert builtin_documentation is not None
    assert builtin_documentation.startswith('GNU Make variable\n\n')
    assert '$(MAKE)' not in builtin_documentation


@pytest.mark.asyncio
async def test_completes_directives_at_start_of_non_recipe_line(tmp_path: Path) -> None:
    text = 'inc\n'
    completion_character = len('inc')

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        items = await session.completion(uri, 0, completion_character)

    include_item = completion_by_label(items)['include']
    assert include_item.kind == lsp.CompletionItemKind.Keyword
    include_edit = completion_text_edit(include_item)
    assert include_edit.new_text == 'include'
    assert include_edit.range.start.character == 0
    assert include_edit.range.end.character == completion_character


@pytest.mark.asyncio
async def test_completes_local_and_included_targets_in_prerequisites(tmp_path: Path) -> None:
    _ = (tmp_path / 'rules.mk').write_text('dep:\n\t@echo dep\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: \n\t@echo done\nlocal:\n\t@echo ok\n'
    completion_character = len('all: ')

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        items = await session.completion(uri, 2, completion_character)

    items_by_label = completion_by_label(items)
    assert 'dep' in items_by_label
    assert 'local' in items_by_label

    dep_item = items_by_label['dep']
    assert dep_item.kind == lsp.CompletionItemKind.Reference
    dep_edit = completion_text_edit(dep_item)
    assert dep_edit.new_text == 'dep'
    assert dep_edit.range.start.character == completion_character
    assert dep_edit.range.end.character == completion_character
