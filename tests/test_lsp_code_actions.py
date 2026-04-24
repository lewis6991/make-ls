from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession
from .lsp_test_utils import apply_text_edits, workspace_edits_for_uri

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_unresolved_prerequisite_code_action_creates_target_at_eof(
    tmp_path: Path,
) -> None:
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        actions = await session.code_actions(uri, diagnostics[0].range, diagnostics)

    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, lsp.CodeAction)
    assert action.title == 'Create target for dep'
    assert action.kind == lsp.CodeActionKind.QuickFix
    assert action.is_preferred is False
    assert action.edit is not None
    edits = workspace_edits_for_uri(action.edit, uri)
    assert len(edits) == 1
    assert isinstance(edits[0], lsp.SnippetTextEdit)
    assert edits[0].snippet.value == '\ndep:\n\t# ${1:TODO}\n'
    updated = apply_text_edits(text, edits)
    assert updated == 'all: dep\n\t@echo done\n\ndep:\n\t# TODO\n'


@pytest.mark.asyncio
async def test_unresolved_path_prerequisite_code_action_creates_target_at_eof(
    tmp_path: Path,
) -> None:
    text = 'all: build/out.o\n\t@echo done'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        actions = await session.code_actions(uri, diagnostics[0].range, diagnostics)

    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, lsp.CodeAction)
    assert action.title == 'Create target for build/out.o'
    assert action.edit is not None
    edits = workspace_edits_for_uri(action.edit, uri)
    assert len(edits) == 1
    assert isinstance(edits[0], lsp.SnippetTextEdit)
    assert edits[0].snippet.value == '\n\nbuild/out.o:\n\t# ${1:TODO}\n'
    updated = apply_text_edits(text, edits)
    assert updated == 'all: build/out.o\n\t@echo done\n\nbuild/out.o:\n\t# TODO\n'


@pytest.mark.asyncio
async def test_unresolved_prerequisite_code_action_falls_back_without_snippet_support(
    tmp_path: Path,
) -> None:
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path, snippet_edit_support=False) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        actions = await session.code_actions(uri, diagnostics[0].range, diagnostics)

    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, lsp.CodeAction)
    assert action.edit is not None
    edits = workspace_edits_for_uri(action.edit, uri)
    assert len(edits) == 1
    assert isinstance(edits[0], lsp.TextEdit)
    assert edits[0].new_text == '\ndep:\n\t# TODO\n'
    updated = apply_text_edits(text, edits)
    assert updated == 'all: dep\n\t@echo done\n\ndep:\n\t# TODO\n'


@pytest.mark.asyncio
async def test_unknown_variable_code_action_adds_empty_assignment_before_rule(
    tmp_path: Path,
) -> None:
    text = 'PREFIX := /usr\nall:\n\t@echo $(FEATURE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        actions = await session.code_actions(uri, diagnostics[0].range, diagnostics)

    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, lsp.CodeAction)
    assert action.title == 'Add empty assignment for FEATURE'
    assert action.kind == lsp.CodeActionKind.QuickFix
    assert action.edit is not None
    updated = apply_text_edits(text, workspace_edits_for_uri(action.edit, uri))
    assert updated == 'PREFIX := /usr\nFEATURE :=\nall:\n\t@echo $(FEATURE)\n'


@pytest.mark.asyncio
async def test_make_syntax_diagnostic_has_no_code_actions(tmp_path: Path) -> None:
    text = 'all dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        actions = await session.code_actions(uri, diagnostics[0].range, diagnostics)

    assert actions == []
