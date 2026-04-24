"""Quick-fix code actions for common Makefile diagnostics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from lsprotocol import types as lsp

from make_ls.analysis.diagnostics.control_blocks import (
    MISSING_ENDEF_DIAGNOSTIC_CODE,
    MISSING_ENDIF_DIAGNOSTIC_CODE,
)
from make_ls.analysis.diagnostics.unknown_variable import UNKNOWN_VARIABLE_DIAGNOSTIC_CODE
from make_ls.analysis.diagnostics.unresolved_include import UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE
from make_ls.analysis.diagnostics.unresolved_prerequisite import (
    UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from make_ls.lsp.protocols import FeatureServer, WorkspaceProtocol
    from make_ls.types import AnalyzedDoc, SymOcc

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(
        lsp.TEXT_DOCUMENT_CODE_ACTION,
        lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
    )(code_action)


def code_action(ls: FeatureServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction] | None:
    if not _supports_quick_fix(params.context.only):
        return None

    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    actions = _unknown_variable_code_actions(
        document,
        params.text_document.uri,
        params.context.diagnostics,
    )
    actions.extend(
        _unresolved_prerequisite_code_actions(
            document,
            params.text_document.uri,
            text_document.source,
            _supports_snippet_workspace_edits(
                cast('lsp.ClientCapabilities', ls.client_capabilities)
            ),
            params.context.diagnostics,
        )
    )
    actions.extend(
        _unresolved_include_code_actions(
            params.text_document.uri,
            text_document.source,
            params.context.diagnostics,
        )
    )
    actions.extend(
        _missing_block_code_actions(
            params.text_document.uri,
            text_document.source,
            params.context.diagnostics,
        )
    )
    LOGGER.debug(
        'textDocument/codeAction uri=%s line=%d actions=%d diagnostics=%d',
        params.text_document.uri,
        params.range.start.line + 1,
        len(actions),
        len(params.context.diagnostics),
    )
    return actions or None


def _supports_quick_fix(kinds: Sequence[lsp.CodeActionKind | str] | None) -> bool:
    if kinds is None:
        return True
    return any(
        kind == lsp.CodeActionKind.QuickFix or kind == lsp.CodeActionKind.QuickFix.value
        for kind in kinds
    )


def _supports_snippet_workspace_edits(capabilities: lsp.ClientCapabilities) -> bool:
    workspace = capabilities.workspace
    if workspace is None or workspace.workspace_edit is None:
        return False

    workspace_edit = workspace.workspace_edit
    return bool(workspace_edit.document_changes and workspace_edit.snippet_edit_support)


def _unknown_variable_code_actions(
    document: AnalyzedDoc,
    uri: str,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    seen: set[tuple[str, int]] = set()
    for diagnostic in diagnostics:
        if diagnostic.code != UNKNOWN_VARIABLE_DIAGNOSTIC_CODE:
            continue

        occurrence = document.occurrence_at(
            diagnostic.range.start.line,
            diagnostic.range.start.character,
        )
        if occurrence is None or occurrence.kind != 'variable' or occurrence.role != 'reference':
            continue

        insertion_line = _empty_assignment_insertion_line(document, occurrence)
        seen_key = (occurrence.name, insertion_line)
        if seen_key in seen:
            continue
        seen.add(seen_key)

        actions.append(
            lsp.CodeAction(
                title=f'Add empty assignment for {occurrence.name}',
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=lsp.Range(
                                    start=lsp.Position(line=insertion_line, character=0),
                                    end=lsp.Position(line=insertion_line, character=0),
                                ),
                                new_text=f'{occurrence.name} :=\n',
                            )
                        ]
                    }
                ),
            )
        )

    return actions


def _unresolved_prerequisite_code_actions(
    document: AnalyzedDoc,
    uri: str,
    source: str,
    supports_snippet_workspace_edits: bool,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    seen: set[str] = set()
    for diagnostic in diagnostics:
        if diagnostic.code != UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE:
            continue

        occurrence = document.occurrence_at(
            diagnostic.range.start.line,
            diagnostic.range.start.character,
        )
        if occurrence is None or occurrence.kind != 'target' or occurrence.role != 'reference':
            continue
        if occurrence.name in seen:
            continue
        seen.add(occurrence.name)

        workspace_edit = _target_template_workspace_edit(
            uri,
            document.version,
            source,
            occurrence.name,
            supports_snippet_workspace_edits=supports_snippet_workspace_edits,
        )
        actions.append(
            lsp.CodeAction(
                title=f'Create target for {occurrence.name}',
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=False,
                edit=workspace_edit,
            )
        )

    return actions


def _unresolved_include_code_actions(
    uri: str,
    source: str,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    source_lines = tuple(source.splitlines())
    actions: list[lsp.CodeAction] = []
    seen_lines: set[int] = set()
    for diagnostic in diagnostics:
        if diagnostic.code != UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE:
            continue
        line_number = diagnostic.range.start.line
        if line_number in seen_lines or line_number >= len(source_lines):
            continue

        line_text = source_lines[line_number]
        directive_start = len(line_text) - len(line_text.lstrip(' '))
        if not line_text[directive_start:].startswith('include'):
            continue
        seen_lines.add(line_number)
        actions.append(
            lsp.CodeAction(
                title='Change include to -include',
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=lsp.Range(
                                    start=lsp.Position(
                                        line=line_number,
                                        character=directive_start,
                                    ),
                                    end=lsp.Position(
                                        line=line_number,
                                        character=directive_start + len('include'),
                                    ),
                                ),
                                new_text='-include',
                            )
                        ]
                    }
                ),
            )
        )

    return actions


def _missing_block_code_actions(
    uri: str,
    source: str,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    for diagnostic in diagnostics:
        if diagnostic.code not in {
            MISSING_ENDEF_DIAGNOSTIC_CODE,
            MISSING_ENDIF_DIAGNOSTIC_CODE,
        }:
            continue
        closer = 'endef' if diagnostic.code == MISSING_ENDEF_DIAGNOSTIC_CODE else 'endif'
        actions.append(
            lsp.CodeAction(
                title=f'Insert missing {closer}',
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=lsp.Range(
                                    start=_document_end_position(source),
                                    end=_document_end_position(source),
                                ),
                                new_text=_eof_append_text(source, f'{closer}\n'),
                            )
                        ]
                    }
                ),
            )
        )
    return actions


def _empty_assignment_insertion_line(
    document: AnalyzedDoc,
    occurrence: SymOcc,
) -> int:
    if occurrence.context is None:
        return occurrence.span.start_line

    for form in document.forms:
        if form.kind != occurrence.context.form_kind:
            continue
        if form.span.contains(occurrence.span.start_line, occurrence.span.start_character):
            return form.span.start_line
    return occurrence.span.start_line


def _target_template_workspace_edit(
    uri: str,
    version: int | None,
    source: str,
    target_name: str,
    *,
    supports_snippet_workspace_edits: bool,
) -> lsp.WorkspaceEdit:
    insert_range = lsp.Range(
        start=_document_end_position(source),
        end=_document_end_position(source),
    )
    prefix = _target_template_prefix(source)
    if supports_snippet_workspace_edits:
        # SnippetTextEdit requires documentChanges and lets the client place the
        # cursor on the recipe comment instead of leaving a dead stub behind.
        return lsp.WorkspaceEdit(
            document_changes=[
                lsp.TextDocumentEdit(
                    text_document=lsp.OptionalVersionedTextDocumentIdentifier(
                        uri=uri,
                        version=version,
                    ),
                    edits=[
                        lsp.SnippetTextEdit(
                            range=insert_range,
                            snippet=lsp.StringValue(f'{prefix}{target_name}:\n\t# ${{1:TODO}}\n'),
                        )
                    ],
                )
            ]
        )

    return lsp.WorkspaceEdit(
        changes={
            uri: [
                lsp.TextEdit(
                    range=insert_range,
                    new_text=f'{prefix}{target_name}:\n\t# TODO\n',
                )
            ]
        }
    )


def _target_template_prefix(source: str) -> str:
    if source.endswith('\n\n') or source == '':
        return ''
    if source.endswith('\n'):
        return '\n'
    return '\n\n'


def _document_end_position(source: str) -> lsp.Position:
    source_lines = source.splitlines()
    if not source_lines:
        return lsp.Position(line=0, character=0)
    if source.endswith('\n'):
        return lsp.Position(line=len(source_lines), character=0)
    return lsp.Position(line=len(source_lines) - 1, character=len(source_lines[-1]))


def _eof_append_text(source: str, text: str) -> str:
    if source == '' or source.endswith('\n'):
        return text
    return f'\n{text}'
