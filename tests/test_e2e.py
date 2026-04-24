from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from make_ls import __main__ as cli

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from make_ls.types import AnalyzedDoc

WorkspaceTextEdit = lsp.TextEdit | lsp.AnnotatedTextEdit | lsp.SnippetTextEdit


def hover_value(hover: lsp.Hover) -> str:
    contents = hover.contents
    if isinstance(contents, lsp.MarkupContent):
        return contents.value
    if isinstance(contents, str):
        return contents
    raise AssertionError('expected markdown hover content')


def single_location(definition: lsp.Location | list[lsp.Location] | None) -> lsp.Location:
    if isinstance(definition, lsp.Location):
        return definition
    if isinstance(definition, list) and len(definition) == 1:
        return definition[0]
    raise AssertionError('expected a single definition location')


def location_set(locations: list[lsp.Location] | None) -> set[tuple[str, int, int]]:
    if locations is None:
        raise AssertionError('expected reference locations')
    return {
        (location.uri, location.range.start.line, location.range.start.character)
        for location in locations
    }


def workspace_edits_for_uri(
    workspace_edit: lsp.WorkspaceEdit,
    uri: str,
) -> Sequence[WorkspaceTextEdit]:
    if workspace_edit.changes is not None:
        return list(workspace_edit.changes[uri])

    if workspace_edit.document_changes is not None:
        for change in workspace_edit.document_changes:
            if isinstance(change, lsp.TextDocumentEdit) and change.text_document.uri == uri:
                return list(change.edits)

    raise AssertionError('expected edits for document')


def apply_text_edits(text: str, edits: Sequence[WorkspaceTextEdit]) -> str:
    line_offsets: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)
    line_offsets.append(offset)

    def position_offset(position: lsp.Position) -> int:
        return line_offsets[position.line] + position.character

    def edit_text(edit: WorkspaceTextEdit) -> str:
        if isinstance(edit, lsp.SnippetTextEdit):
            snippet = re.sub(r'\$\{\d+:([^}]*)\}', r'\1', edit.snippet.value)
            return re.sub(r'\$\d+', '', snippet)
        return edit.new_text

    updated = text
    for edit in sorted(
        edits,
        key=lambda item: (
            item.range.start.line,
            item.range.start.character,
            item.range.end.line,
            item.range.end.character,
        ),
        reverse=True,
    ):
        start_offset = position_offset(edit.range.start)
        end_offset = position_offset(edit.range.end)
        updated = updated[:start_offset] + edit_text(edit) + updated[end_offset:]
    return updated


def completion_by_label(items: Sequence[lsp.CompletionItem]) -> dict[str, lsp.CompletionItem]:
    return {item.label: item for item in items}


def completion_text_edit(item: lsp.CompletionItem) -> lsp.TextEdit:
    if not isinstance(item.text_edit, lsp.TextEdit):
        raise AssertionError('expected completion text edit')
    return item.text_edit


def completion_documentation_value(item: lsp.CompletionItem) -> str | None:
    documentation = item.documentation
    if documentation is None:
        return None
    if isinstance(documentation, lsp.MarkupContent):
        return documentation.value
    return documentation


@pytest.mark.asyncio
async def test_reports_makefile_syntax_diagnostics(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'all dep\n')
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message == 'Invalid Makefile syntax: `all dep`'


@pytest.mark.asyncio
async def test_accepts_empty_variable_assignments(tmp_path: Path) -> None:
    text = 'EMPTY ?=\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_recovers_variable_assignments_when_parser_loses_sync(tmp_path: Path) -> None:
    text = """\
PREPEND_STDOUT = | awk '{ print "$(CYAN_DIM)$(1):$(NC)", $$0; fflush(); }'
COLOR_PATTERN = | $(SED) "s/$(1)/$$(printf "$(2)\\\\\\0$(NC)")/g"
VENV := .venv
all: $(VENV)
\t@echo ok
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 3, 8)
        definition = await session.definition(uri, 3, 8)

    assert all(diagnostic.severity != lsp.DiagnosticSeverity.Error for diagnostic in diagnostics)
    assert hover is not None
    assert 'VENV := .venv' in hover_value(hover)
    location = single_location(definition)
    assert location.range.start.line == 2
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_reports_unterminated_parenthesized_variable_reference_in_recovered_assignment(
    tmp_path: Path,
) -> None:
    text = 'BROKEN = $(BAR\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].message == 'Invalid variable reference in assignment: `$(BAR`'


@pytest.mark.asyncio
async def test_reports_unterminated_braced_variable_reference_in_recovered_assignment(
    tmp_path: Path,
) -> None:
    text = 'BROKEN = ${BAR\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].message.startswith('Invalid variable reference in assignment')


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference(tmp_path: Path) -> None:
    text = 'all:\n\t@echo $(missing_var)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unknown variable reference: `$(missing_var)`'


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


@pytest.mark.asyncio
async def test_warns_for_unresolved_prerequisite(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unresolved prerequisite: `dep`'


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
async def test_does_not_warn_for_existing_file_prerequisite(tmp_path: Path) -> None:
    _ = (tmp_path / 'dep').write_text('done\n', encoding='utf-8')
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_explicit_target_prerequisite(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_prerequisite_matching_pattern_rule(tmp_path: Path) -> None:
    text = 'build_all: build_alpha\n\t@echo done\n\nbuild_%:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_target_specific_variable_assignment(tmp_path: Path) -> None:
    text = 'suite/% : CASES=cases/suite\nsample/%: CASES=cases/sample\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_included_target_prerequisite(tmp_path: Path) -> None:
    _ = (tmp_path / 'rules.mk').write_text('dep:\n\t@echo dep\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unresolved_include(tmp_path: Path) -> None:
    text = 'include missing.mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unresolved include: `missing.mk`'


@pytest.mark.asyncio
async def test_does_not_warn_for_generated_include_target(tmp_path: Path) -> None:
    text = 'include deps.mk\n\ndeps.mk:\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_optional_missing_include(tmp_path: Path) -> None:
    text = '-include local.mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_phony_prerequisite(tmp_path: Path) -> None:
    text = '.PHONY: clean\nall: clean\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_dynamic_include(tmp_path: Path) -> None:
    text = 'include $(missing).mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unknown variable reference: `$(missing)`'


@pytest.mark.asyncio
async def test_warns_for_automatic_variable_reference_outside_recipe(tmp_path: Path) -> None:
    text = 'DEST := $@\nall:\n\t@echo $@\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Automatic variable outside recipe context: `$@`'


@pytest.mark.asyncio
async def test_does_not_warn_for_automatic_variable_reference_in_prerequisite(
    tmp_path: Path,
) -> None:
    text = 'all: $@\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_missing_endif(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nall:\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Missing endif for conditional block'


@pytest.mark.asyncio
async def test_warns_for_unexpected_endif(tmp_path: Path) -> None:
    text = 'endif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Unexpected endif directive'


@pytest.mark.asyncio
async def test_warns_for_duplicate_else(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nelse\nelse\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Duplicate else directive'


@pytest.mark.asyncio
async def test_accepts_else_ifeq_chain(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),one)\nX := 1\nelse ifeq ($(MODE),two)\nX := 2\nelse\nX := 3\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_missing_endef(tmp_path: Path) -> None:
    text = 'define BODY\n\t@echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Missing endef for define block'


@pytest.mark.asyncio
async def test_warns_for_unexpected_endef(tmp_path: Path) -> None:
    text = 'endef\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Unexpected endef directive'


@pytest.mark.asyncio
async def test_warns_for_overriding_recipe_for_target(tmp_path: Path) -> None:
    text = 'all:\n\t@echo one\n\nall:\n\t@echo two\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 3
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Overriding recipe for target: `all`'


@pytest.mark.asyncio
async def test_does_not_warn_for_overriding_double_colon_recipe(tmp_path: Path) -> None:
    text = 'all::\n\t@echo one\n\nall::\n\t@echo two\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_circular_prerequisite_cycle(tmp_path: Path) -> None:
    text = 'a: b\n\t@echo a\n\nb: a\n\t@echo b\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Circular prerequisite cycle: `a, b`'


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


@pytest.mark.asyncio
async def test_does_not_warn_for_environment_variable_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('MAKE_LS_TEST_ENV_VAR', '1')
    text = 'all:\n\t@echo $(MAKE_LS_TEST_ENV_VAR)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_uppercase_variable_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('OUTPUT_DECORATOR', raising=False)
    text = 'all:\n\t@echo $(OUTPUT_DECORATOR)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_does_not_warn_for_unknown_variable_reference_in_nonempty_guarded_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifneq ($(FEATURE),)\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_unknown_variable_reference_in_nonempty_else_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifeq ($(FEATURE),)\nelse\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_empty_guarded_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifeq ($(FEATURE),)\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_guarded_assignment_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifneq ($(FEATURE),)\nRESULT = $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_when_guard_variable_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    monkeypatch.delenv('OTHER', raising=False)
    text = 'ifneq ($(OTHER),)\nRESULT = $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_does_not_warn_for_forward_variable_reference(tmp_path: Path) -> None:
    text = 'BAR = $(foo)\nfoo := hello\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_accepts_make_automatic_variables_in_recipe_shell(tmp_path: Path) -> None:
    text = """\
all: dep
\tcp $< $@
\tprintf '%s\\n' $^
dep:
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_reports_shell_syntax_diagnostics_for_recipe_lines(tmp_path: Path) -> None:
    text = 'all:\n\t@if true; then echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message == 'Invalid shell syntax in recipe: `if true; then echo hi`'


@pytest.mark.asyncio
async def test_reports_multiline_shell_syntax_diagnostics(tmp_path: Path) -> None:
    text = 'all:\n\tif true; then \\\n\t  echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].message.startswith('Invalid shell syntax in recipe')


@pytest.mark.asyncio
async def test_did_change_still_republishes_non_shell_diagnostics(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'FOO := ok\nall:\n\t@echo $(FOO)\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.change_document(uri, 'FOO := ok\nall:\n\t@echo $(BAR)\n')
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_shell_syntax_diagnostics_return_on_save(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'all:\n\t@echo hi\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.change_document(uri, 'all:\n\t@if true; then echo hi\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.save_document(uri)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].message.startswith('Invalid shell syntax in recipe')


@pytest.mark.asyncio
async def test_server_advertises_document_save_notifications(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        assert session.initialize_result is not None
        capabilities = session.initialize_result.capabilities

    assert isinstance(capabilities.text_document_sync, lsp.TextDocumentSyncOptions)
    assert capabilities.text_document_sync.save == lsp.SaveOptions(include_text=False)


@pytest.mark.asyncio
async def test_accepts_multiline_recipe_continuations(tmp_path: Path) -> None:
    text = """\
prefix := /usr/local
pkglibdir := /usr/local/lib
MAJOR := 3
MINOR := 2
PATCH := 1

all:
\tsed \\
\t\t-e 's#PREFIX#$(prefix)#' \\
\t\t-e 's#LIBDIR#$(pkglibdir)#' \\
\t\t-e 's#VERSION#$(MAJOR).$(MINOR).$(PATCH)#' \\
\t\tlibutf8proc.pc.in > libutf8proc.pc
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_skips_unknown_variable_warning_for_computed_variable_names(
    tmp_path: Path,
) -> None:
    text = 'PAPER := a4\nall:\n\t@echo $(PAPEROPT_$(PAPER))\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_accepts_neovim_style_gnu_make_blocks(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq ($(UNIX_LIKE),FALSE)',
                '  SHELL := powershell.exe',
                'else',
                '  CMAKE := $(shell (command -v cmake3 || command -v cmake || echo cmake))',
                '  CMAKE_GENERATOR ?= "$(shell (command -v ninja > /dev/null 2>&1 '
                '&& echo "Ninja") || echo "Unix Makefiles")"',
                'endif',
                '',
                'iwyu:',
                '\tiwyu-fix-includes --only_re="src/nvim" --ignore_re="(src/nvim/eval/encode.c\\',
                '\t|src/nvim/auto/\\',
                '\t|src/nvim/os/lang.c\\',
                '\t|src/nvim/map.c\\',
                '\t)" --nosafe_headers < build/iwyu.log',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_recovers_targets_after_gnu_make_parser_desync(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq ($(UNIX_LIKE),FALSE)',
                '  SHELL := powershell.exe',
                'else',
                '  CMAKE := $(shell (command -v cmake3 || command -v cmake || echo cmake))',
                '  CMAKE_GENERATOR ?= "$(shell (command -v ninja > /dev/null 2>&1 '
                '&& echo "Ninja") || echo "Unix Makefiles")"',
                'endif',
                '',
                'nvim: deps',
                '\t$(CMAKE) --build build',
                '',
                'deps:',
                '\t@echo deps',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 7, 1)
        definition = await session.definition(uri, 7, 6)

    assert diagnostics == []
    assert hover is not None
    assert hover_value(hover).startswith('```make\nnvim: deps\n\t$(CMAKE) --build build\n```')
    location = single_location(definition)
    assert location.range.start.line == 10
    assert location.range.start.character == 0


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which('bash') is None, reason='requires bash for fallback shell syntax check'
)
async def test_accepts_nested_multiline_if_recipe(tmp_path: Path) -> None:
    text = """\
all:
\t@if [ -f build/.ran-cmake ]; then \\
\t  cached_prefix=$$(printf x); \\
\t  if ! [ "a" = "$$cached_prefix" ]; then \\
\t    printf '%s\\n' "$$cached_prefix"; \\
\t    rm -f build/.ran-cmake; \\
\t  fi \\
\tfi
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_shell_heavy_assignment_does_not_poison_later_rules(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq (Windows,$(TARGET_SYS))',
                'TARGET_TESTUNWIND=$(shell exec 2>/dev/null; echo '
                "'extern void b(void);int a(void){b();return 0;}' | $(TARGET_CC) -c -x c - "
                '-o tmpunwind.o && { grep -qa -e eh_frame -e __unwind_info tmpunwind.o || '
                'grep -qU -e eh_frame -e __unwind_info tmpunwind.o; } && echo E; rm -f '
                'tmpunwind.o)',
                'endif',
                '',
                'amalg:',
                '\t$(MAKE) all "LJCORE_O=ljamalg.o"',
                '',
                'clean:',
                '\t@echo clean',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 1)

    assert all(diagnostic.severity != lsp.DiagnosticSeverity.Error for diagnostic in diagnostics)
    assert hover is not None
    assert hover_value(hover).startswith('```make\namalg:\n\t$(MAKE) all "LJCORE_O=ljamalg.o"\n```')


@pytest.mark.asyncio
async def test_hover_for_builtin_ifeq_directive(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nRESULT := yes\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nifeq (arg1, arg2)\n```')
    assert 'GNU Make directive' in value
    assert 'two expanded arguments are equal' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_else_directive(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nRESULT := yes\nelse\nRESULT := no\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nelse\n```')
    assert 'alternate branch of a conditional' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_define_directive(tmp_path: Path) -> None:
    text = 'define BODY\n\t@echo hi\nendef\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 2)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndefine variable\n```')
    assert 'multi-line variable definition' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_findstring_function(tmp_path: Path) -> None:
    text = 'X := $(findstring a,$(Y))\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(findstring find,in)\n```')
    assert 'Return `find` if it appears in `in`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_dir_function(tmp_path: Path) -> None:
    text = 'X := $(dir src/foo.c)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 8)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(dir names...)\n```')
    assert 'directory part of each file name' in value
    assert '`./`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_abspath_function(tmp_path: Path) -> None:
    text = 'X := $(abspath ../foo)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(abspath names...)\n```')
    assert 'absolute path' in value
    assert 'without resolving symlinks' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_make_variable(tmp_path: Path) -> None:
    text = 'all:\n\t$(MAKE) -C subdir\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 1, 4)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(MAKE)\n```')
    assert 'GNU Make variable' in value
    assert 'The name with which `make` was invoked' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_recursive_make_variables(tmp_path: Path) -> None:
    text = 'vars := $(MAKEOVERRIDES) $(MFLAGS)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        makeoverrides_hover = await session.hover(uri, 0, 11)
        mflags_hover = await session.hover(uri, 0, 28)

    assert diagnostics == []

    assert makeoverrides_hover is not None
    makeoverrides_value = hover_value(makeoverrides_hover)
    assert makeoverrides_value.startswith('```make\n$(MAKEOVERRIDES)\n```')
    assert 'command-line variable definitions' in makeoverrides_value
    assert '`MAKEFLAGS`' in makeoverrides_value

    assert mflags_hover is not None
    mflags_value = hover_value(mflags_hover)
    assert mflags_value.startswith('```make\n$(MFLAGS)\n```')
    assert 'Historical compatibility variable' in mflags_value
    assert '`MAKEFLAGS`' in mflags_value


@pytest.mark.asyncio
async def test_hover_for_builtin_special_variable_and_skips_unknown_warning(
    tmp_path: Path,
) -> None:
    text = 'goal := $(.DEFAULT_GOAL)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 12)

    assert diagnostics == []
    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(.DEFAULT_GOAL)\n```')
    assert 'current default goal' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_shellflags_variable_and_skips_unknown_warning(
    tmp_path: Path,
) -> None:
    text = 'flags := $(.SHELLFLAGS)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 13)

    assert diagnostics == []
    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(.SHELLFLAGS)\n```')
    assert 'Arguments passed to the shell used for recipes' in value
    assert '`-c`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_automatic_variables(tmp_path: Path) -> None:
    text = 'all: dep\n\tcp $< $@\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        first_prerequisite_hover = await session.hover(uri, 1, 5)
        target_hover = await session.hover(uri, 1, 8)

    assert first_prerequisite_hover is not None
    first_value = hover_value(first_prerequisite_hover)
    assert first_value.startswith('```make\n$<\n```')
    assert 'name of the first prerequisite' in first_value

    assert target_hover is not None
    target_value = hover_value(target_hover)
    assert target_value.startswith('```make\n$@\n```')
    assert 'file name of the target' in target_value


@pytest.mark.asyncio
async def test_builtin_variable_hover_does_not_override_local_definition(tmp_path: Path) -> None:
    text = 'MAKE := wrapper\nall:\n\t@echo $(MAKE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nMAKE := wrapper\n```')
    assert 'GNU Make variable' not in value


@pytest.mark.asyncio
async def test_hover_for_builtin_special_target_overrides_generic_target_hover(
    tmp_path: Path,
) -> None:
    text = '.PHONY: clean\nclean:\n\t@echo clean\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n.PHONY: targets...\n```')
    assert 'always treated as phony targets' in value
    assert 'Dependency Tree:' not in value


@pytest.mark.asyncio
async def test_builtin_function_hover_does_not_override_variable_hover(tmp_path: Path) -> None:
    text = 'dir := build\nall:\n\t@echo $(dir)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndir := build\n```')
    assert 'GNU Make function' not in value


@pytest.mark.asyncio
async def test_hover_for_target_definition(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall: dep\n\t@echo done\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`all`  \n└─\u00a0`dep`' in value


@pytest.mark.asyncio
async def test_hover_for_multitarget_rule_keeps_full_rule_text(tmp_path: Path) -> None:
    text = 'all lint: dep\n\t@echo $^\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 5)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall lint: dep\n\t@echo $^\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`lint`  \n└─\u00a0`dep`' in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_includes_recursive_dependency_tree(
    tmp_path: Path,
) -> None:
    text = """\
all: dep tools
\t@echo done

dep: lib
\t@echo dep

tools: helper
\t@echo tools

lib:
\t@echo lib

helper:
\t@echo helper
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = (
        'Dependency Tree:\n\n'
        '`all`  \n'
        '├─\u00a0`dep`  \n'
        '│\u00a0\u00a0└─\u00a0`lib`  \n'
        '└─\u00a0`tools`  \n'
        '\u00a0\u00a0\u00a0└─\u00a0`helper`'
    )
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_deduplicates_shared_dependency_branches(
    tmp_path: Path,
) -> None:
    text = """\
all: build deps
\t@echo all

build: | deps
\t@echo build

deps: prep
\t@echo deps

prep:
\t@echo prep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = (
        'Dependency Tree:\n\n'
        '`all`  \n'
        '├─\u00a0`build`  \n'
        '│\u00a0\u00a0└─\u00a0`deps` ...  \n'
        '└─\u00a0`deps`  \n'
        '\u00a0\u00a0\u00a0└─\u00a0`prep`'
    )
    assert expected_tree in value
    assert (
        '│\u00a0\u00a0└─\u00a0`deps`  \n│\u00a0\u00a0\u00a0\u00a0\u00a0└─\u00a0`prep`' not in value
    )


@pytest.mark.asyncio
async def test_hover_for_target_definition_distinguishes_phony_and_path_targets(
    tmp_path: Path,
) -> None:
    text = """\
.PHONY: all clean
all: clean build/output.txt
\t@echo done

clean:
\t@echo clean
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 1, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = 'Dependency Tree:\n\n*all*  \n├─\u00a0*clean*  \n└─\u00a0`build/output.txt`'
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_honors_later_phony_declarations(
    tmp_path: Path,
) -> None:
    text = """\
all: nvim
\t@echo all

.PHONY: clean
clean:
\t@echo clean

.PHONY: nvim
nvim: clean
\t@echo nvim
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 8, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = 'Dependency Tree:\n\n*nvim*  \n└─\u00a0*clean*'
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_marks_dependency_cycles(tmp_path: Path) -> None:
    text = """\
all: dep
\t@echo done

dep: all
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert (
        'Dependency Tree:\n\n`all`  \n└─\u00a0`dep`  \n\u00a0\u00a0\u00a0└─\u00a0`all` (cycle)'
        in value
    )


@pytest.mark.asyncio
async def test_hover_for_target_reference_includes_full_multiline_make_rule(
    tmp_path: Path,
) -> None:
    text = """\
all: lint_jenkins
\t@echo ok

lint_jenkins: jenkins-cli.jar
\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\
\t\tetc_dev/jenkins_lint \\
\t\t--cli $(PWD)/$^ \\
\t\t--user $(JENKINS_USER)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith(
        '```make\n'
        'lint_jenkins: jenkins-cli.jar\n'
        '\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\\n'
        '\t\tetc_dev/jenkins_lint \\\n'
        '\t\t--cli $(PWD)/$^ \\\n'
        '\t\t--user $(JENKINS_USER)\n'
        '```'
    )
    assert ('\n\n---\n\nDependency Tree:\n\n`lint_jenkins`  \n└─\u00a0`jenkins-cli.jar`') in value


@pytest.mark.asyncio
async def test_hover_for_target_reference_falls_back_to_included_makefile(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text(
        'dep: tool\n\t@echo dep\n\ntool:\n\t@echo tool\n',
        encoding='utf-8',
    )
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndep: tool\n\t@echo dep\n```')
    assert 'Dependency Tree:\n\n`dep`  \n└─\u00a0`tool`' in value


@pytest.mark.asyncio
async def test_hover_for_local_target_does_not_follow_includes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text('all:\n\t@echo remote\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)

        def fail_included_documents(_uri: str) -> tuple[AnalyzedDoc, ...]:
            raise AssertionError('local hover should not follow includes')

        monkeypatch.setattr(session.server, 'included_documents', fail_included_documents)
        hover = await session.hover(uri, 2, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall: dep\n\t@echo done\n```')


@pytest.mark.asyncio
async def test_hover_for_ambiguous_included_target_returns_none(tmp_path: Path) -> None:
    _ = (tmp_path / 'a.mk').write_text('dep:\n\t@echo a\n', encoding='utf-8')
    _ = (tmp_path / 'b.mk').write_text('dep:\n\t@echo b\n', encoding='utf-8')
    text = 'include a.mk b.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is None


@pytest.mark.asyncio
async def test_hover_for_target_reference_follows_nested_includes(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'more.mk').write_text('tool:\n\t@echo tool\n', encoding='utf-8')
    _ = (tmp_path / 'rules.mk').write_text(
        'include more.mk\n\ndep: tool\n\t@echo dep\n',
        encoding='utf-8',
    )
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndep: tool\n\t@echo dep\n```')


@pytest.mark.asyncio
async def test_hover_for_target_reference_ignores_following_conditional_block(
    tmp_path: Path,
) -> None:
    text = """\
release: dep
\t@echo $@

ifeq ($(X),1)
Y := 1
endif

publish: release
\t@echo ok

dep:
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 7, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nrelease: dep\n\t@echo $@\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`release`  \n└─\u00a0`dep`' in value
    assert 'ifeq ($(X),1)' not in value
    assert 'Y := 1' not in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_includes_full_multiline_make_rule(
    tmp_path: Path,
) -> None:
    text = """\
lint_jenkins: jenkins-cli.jar
\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\
\t\tetc_dev/jenkins_lint \\
\t\t--cli $(PWD)/$^ \\
\t\t--user $(JENKINS_USER)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith(
        '```make\n'
        'lint_jenkins: jenkins-cli.jar\n'
        '\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\\n'
        '\t\tetc_dev/jenkins_lint \\\n'
        '\t\t--cli $(PWD)/$^ \\\n'
        '\t\t--user $(JENKINS_USER)\n'
        '```'
    )
    assert ('\n\n---\n\nDependency Tree:\n\n`lint_jenkins`  \n└─\u00a0`jenkins-cli.jar`') in value
    assert 'Recipe:\n```sh\n' not in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference(tmp_path: Path) -> None:
    text = 'FOO := hello\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nFOO := hello\n```')
    assert 'Value:' not in value


@pytest.mark.asyncio
async def test_hover_for_multiline_variable_reference_does_not_duplicate_value(
    tmp_path: Path,
) -> None:
    text = """\
DECORATE = \\
    first \\
    second
all:
\t@echo $(DECORATE)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 11)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nDECORATE = \\')
    assert 'first \\\n    second' in value
    assert 'Value:' not in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference_includes_leading_comments(
    tmp_path: Path,
) -> None:
    text = """\
# Path to the local virtualenv.
# Used by lint and test targets.
VENV := .venv
all:
\t@echo $(VENV)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nVENV := .venv\n```')
    assert 'Path to the local virtualenv.\nUsed by lint and test targets.' in value
    assert 'Value:' not in value


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
async def test_server_advertises_prepare_rename_support(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        initialize_result = session.initialize_result

    assert initialize_result is not None
    rename_provider = initialize_result.capabilities.rename_provider
    assert isinstance(rename_provider, lsp.RenameOptions)
    assert rename_provider.prepare_provider is True


@pytest.mark.asyncio
async def test_server_writes_lsp_logs_when_configured(tmp_path: Path) -> None:
    log_path = tmp_path / 'make-ls.log'
    cli.configure_logging(log_path, 'debug')

    try:
        async with LspSession(tmp_path) as session:
            uri = await session.open_document('Makefile', 'FOO := hello\nall:\n\t@echo $(FOO)\n')
            _ = await session.wait_for_diagnostics(uri)
            _ = await session.hover(uri, 2, 9)
            _ = await session.definition(uri, 2, 9)
    finally:
        cli.configure_logging(None, 'debug')

    log_text = log_path.read_text(encoding='utf-8')
    assert 'textDocument/didOpen' in log_text
    assert f'uri={uri}' in log_text
    assert 'textDocument/publishDiagnostics' in log_text
    assert 'textDocument/hover' in log_text
    assert 'textDocument/definition' in log_text


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
