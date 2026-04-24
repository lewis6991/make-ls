from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

if TYPE_CHECKING:
    from collections.abc import Sequence

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
