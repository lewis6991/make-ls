"""Completion logic over recovered Makefile symbols and raw line context.

Completion stays recovery-first: the recovered document provides the candidate
sets, while lightweight line inspection decides whether the cursor is
completing a variable or function name, a directive, or a prerequisite target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from make_ls.builtin_docs import BUILTIN_VARIABLE_DOCS, DIRECTIVE_DOCS, FUNCTION_DOCS

from .navigation import resolve_related_variable_definition
from .recovery import ASSIGNMENT_RE, CONDITIONAL_DIRECTIVES, VARIABLE_REFERENCE_DELIMITERS

if TYPE_CHECKING:
    from make_ls.builtin_docs import BuiltinDoc
    from make_ls.types import AnalyzedDoc, SymOcc, VarDef

DIRECTIVE_NAMES = tuple(sorted(DIRECTIVE_DOCS))
FUNCTION_NAMES = tuple(sorted(FUNCTION_DOCS))
SECOND_TOKEN_DIRECTIVES = {
    'else': tuple(sorted(CONDITIONAL_DIRECTIVES)),
    'override': ('define',),
}
DIRECTIVE_NAME_CHARACTERS = frozenset(
    '-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
)
VARIABLE_NAME_CHARACTERS = frozenset(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.%/@<?^+*|!-'
)


@dataclass(frozen=True, slots=True)
class _CompletionContext:
    start_character: int
    end_character: int
    prefix: str


def complete_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    source_lines: tuple[str, ...],
    related_documents: tuple[AnalyzedDoc, ...] = (),
) -> list[lsp.CompletionItem] | None:
    """Return completion items for the cursor position when the context is understood."""
    if position.line > len(source_lines):
        return None

    line_text = source_lines[position.line] if position.line < len(source_lines) else ''
    character = min(position.character, len(line_text))

    variable_context = _variable_completion_context(line_text, character)
    if variable_context is not None:
        items = _variable_completion_items(
            document,
            position,
            variable_context,
            related_documents,
        )
        return items or None

    prerequisite_context = _prerequisite_completion_context(
        document, line_text, position, character
    )
    if prerequisite_context is not None:
        items = _target_completion_items(
            document, related_documents, position.line, prerequisite_context
        )
        return items or None

    directive_context = _directive_completion_context(line_text, character)
    if directive_context is not None:
        context, directive_names = directive_context
        items = _directive_completion_items(position.line, context, directive_names)
        return items or None

    return None


def _variable_completion_context(line_text: str, character: int) -> _CompletionContext | None:
    open_references: list[tuple[int, str]] = []
    index = 0
    while index < character:
        if line_text[index] == '$' and index + 1 < character:
            next_character = line_text[index + 1]
            if next_character == '$':
                index += 2
                continue

            expected_closer = VARIABLE_REFERENCE_DELIMITERS.get(next_character)
            if expected_closer is not None:
                open_references.append((index, expected_closer))
                index += 2
                continue

            index += 2
            continue

        if open_references and line_text[index] == open_references[-1][1]:
            _ = open_references.pop()
        index += 1

    if not open_references:
        return None

    reference_start, _expected_closer = open_references[-1]
    name_start = reference_start + 2
    prefix = line_text[name_start:character]
    if any(current not in VARIABLE_NAME_CHARACTERS for current in prefix):
        return None

    name_end = character
    while name_end < len(line_text) and line_text[name_end] in VARIABLE_NAME_CHARACTERS:
        name_end += 1

    return _CompletionContext(
        start_character=name_start,
        end_character=name_end,
        prefix=prefix,
    )


def _prerequisite_completion_context(
    document: AnalyzedDoc,
    line_text: str,
    position: lsp.Position,
    character: int,
) -> _CompletionContext | None:
    occurrence = _completion_occurrence(document, position.line, character)
    if (
        occurrence is not None
        and occurrence.kind == 'target'
        and occurrence.context is not None
        and occurrence.context.kind == 'prerequisite'
    ):
        return _CompletionContext(
            start_character=occurrence.span.start_character,
            end_character=occurrence.span.end_character,
            prefix=line_text[occurrence.span.start_character : character],
        )

    if line_text.startswith('\t') or line_text.lstrip(' ').startswith('#'):
        return None

    separator_start, separator_width = _rule_separator_in_line(line_text)
    if separator_start is None:
        return None

    prerequisite_start = separator_start + separator_width
    if character < prerequisite_start:
        return None

    remainder = line_text[prerequisite_start:]
    if _is_target_specific_variable_assignment(remainder):
        return None

    semicolon_index = line_text.find(';', prerequisite_start)
    if semicolon_index != -1 and semicolon_index < character:
        return None

    comment_index = line_text.find('#', prerequisite_start)
    if comment_index != -1 and comment_index < character:
        return None

    start_character = character
    while start_character > prerequisite_start and _is_target_completion_character(
        line_text[start_character - 1]
    ):
        start_character -= 1

    end_character = character
    while end_character < len(line_text) and _is_target_completion_character(
        line_text[end_character]
    ):
        end_character += 1

    return _CompletionContext(
        start_character=start_character,
        end_character=end_character,
        prefix=line_text[start_character:character],
    )


def _directive_completion_context(
    line_text: str,
    character: int,
) -> tuple[_CompletionContext, tuple[str, ...]] | None:
    if line_text.lstrip(' ').startswith(('\t', '#')):
        return None

    comment_index = line_text.find('#')
    if comment_index != -1 and comment_index < character:
        return None

    token_start = len(line_text) - len(line_text.lstrip(' '))
    if character < token_start:
        return None

    first_token_end = token_start
    while (
        first_token_end < len(line_text) and line_text[first_token_end] in DIRECTIVE_NAME_CHARACTERS
    ):
        first_token_end += 1

    if character <= first_token_end:
        return (
            _CompletionContext(
                start_character=token_start,
                end_character=first_token_end,
                prefix=line_text[token_start:character],
            ),
            DIRECTIVE_NAMES,
        )

    first_token = line_text[token_start:first_token_end]
    second_token_names = SECOND_TOKEN_DIRECTIVES.get(first_token)
    if second_token_names is None:
        return None

    second_token_start = first_token_end
    while second_token_start < len(line_text) and line_text[second_token_start] == ' ':
        second_token_start += 1

    if character < second_token_start:
        return (
            _CompletionContext(
                start_character=character,
                end_character=character,
                prefix='',
            ),
            second_token_names,
        )

    second_token_end = second_token_start
    while (
        second_token_end < len(line_text)
        and line_text[second_token_end] in DIRECTIVE_NAME_CHARACTERS
    ):
        second_token_end += 1

    if character <= second_token_end:
        return (
            _CompletionContext(
                start_character=second_token_start,
                end_character=second_token_end,
                prefix=line_text[second_token_start:character],
            ),
            second_token_names,
        )

    return None


def _variable_completion_items(
    document: AnalyzedDoc,
    position: lsp.Position,
    context: _CompletionContext,
    related_documents: tuple[AnalyzedDoc, ...],
) -> list[lsp.CompletionItem]:
    completion_range = _completion_range(position.line, context)
    items: list[lsp.CompletionItem] = []
    seen_variable_names: set[str] = set()
    index = 0
    for source_document in (document, *related_documents):
        for name in sorted(source_document.variables):
            if not name.startswith(context.prefix) or name in seen_variable_names:
                continue
            definition_result = resolve_related_variable_definition(
                source_document,
                name,
                position.line,
                position.character,
            )
            if definition_result is None:
                continue
            definition_document, definition = definition_result
            seen_variable_names.add(name)
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Variable,
                    detail=(
                        _assignment_detail(definition)
                        if definition_document.uri == document.uri
                        else _variable_completion_detail(definition_document.uri, definition)
                    ),
                    documentation=_variable_documentation(definition),
                    sort_text=f'0-{index:04d}-{name}',
                    text_edit=lsp.TextEdit(range=completion_range, new_text=name),
                )
            )
            index += 1

    builtin_variable_names = [
        name
        for name in sorted(BUILTIN_VARIABLE_DOCS)
        if name not in seen_variable_names and name.startswith(context.prefix)
    ]
    for index, name in enumerate(builtin_variable_names):
        builtin_doc = BUILTIN_VARIABLE_DOCS[name]
        items.append(
            lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Variable,
                detail=builtin_doc.signature,
                documentation=_builtin_documentation(builtin_doc),
                sort_text=f'1-{index:04d}-{name}',
                text_edit=lsp.TextEdit(range=completion_range, new_text=name),
            )
        )

    function_names = [name for name in FUNCTION_NAMES if name.startswith(context.prefix)]
    for index, name in enumerate(function_names):
        builtin_doc = FUNCTION_DOCS[name]
        items.append(
            lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Function,
                detail=builtin_doc.signature,
                documentation=_builtin_documentation(builtin_doc),
                sort_text=f'2-{index:04d}-{name}',
                text_edit=lsp.TextEdit(range=completion_range, new_text=f'{name} '),
            )
        )

    return items


def _directive_completion_items(
    line_number: int,
    context: _CompletionContext,
    directive_names: tuple[str, ...],
) -> list[lsp.CompletionItem]:
    completion_range = _completion_range(line_number, context)
    items: list[lsp.CompletionItem] = []
    for index, name in enumerate(directive_names):
        if not name.startswith(context.prefix):
            continue
        builtin_doc = DIRECTIVE_DOCS[name]
        items.append(
            lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Keyword,
                detail=builtin_doc.signature,
                documentation=_builtin_documentation(builtin_doc),
                sort_text=f'{index:04d}-{name}',
                text_edit=lsp.TextEdit(range=completion_range, new_text=name),
            )
        )
    return items


def _target_completion_items(
    document: AnalyzedDoc,
    related_documents: tuple[AnalyzedDoc, ...],
    line_number: int,
    context: _CompletionContext,
) -> list[lsp.CompletionItem]:
    completion_range = _completion_range(line_number, context)
    items: list[lsp.CompletionItem] = []
    seen_names: set[str] = set()

    for source_document in (document, *related_documents):
        for name, definitions in sorted(source_document.targets.items()):
            if name in seen_names or not name.startswith(context.prefix):
                continue
            if '%' in name:
                continue
            seen_names.add(name)
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Reference,
                    detail=_target_detail(source_document.uri, definitions[0].rule_text),
                    sort_text=f'0-{len(items):04d}-{name}',
                    text_edit=lsp.TextEdit(range=completion_range, new_text=name),
                )
            )

        for name in sorted(source_document.phony_targets):
            if name in seen_names or not name.startswith(context.prefix):
                continue
            seen_names.add(name)
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Reference,
                    detail='phony target',
                    sort_text=f'1-{len(items):04d}-{name}',
                    text_edit=lsp.TextEdit(range=completion_range, new_text=name),
                )
            )

    return items


def _completion_occurrence(
    document: AnalyzedDoc,
    line: int,
    character: int,
) -> SymOcc | None:
    occurrence = document.occurrence_at(line, character)
    if occurrence is not None or character == 0:
        return occurrence
    return document.occurrence_at(line, character - 1)


def _completion_range(line_number: int, context: _CompletionContext) -> lsp.Range:
    return lsp.Range(
        start=lsp.Position(line=line_number, character=context.start_character),
        end=lsp.Position(line=line_number, character=context.end_character),
    )


def _variable_documentation(definition: VarDef) -> lsp.MarkupContent | None:
    if definition.documentation is None:
        return None
    return lsp.MarkupContent(
        kind=lsp.MarkupKind.Markdown,
        value=definition.documentation,
    )


def _builtin_documentation(builtin_doc: BuiltinDoc) -> lsp.MarkupContent:
    return lsp.MarkupContent(
        kind=lsp.MarkupKind.Markdown,
        value=f'GNU Make {builtin_doc.kind}\n\n{builtin_doc.summary}',
    )


def _assignment_detail(definition: VarDef) -> str:
    value = ' '.join(definition.value.split())
    if value == '':
        return f'{definition.name} {definition.operator}'
    if len(value) > 60:
        value = value[:57] + '...'
    return f'{definition.name} {definition.operator} {value}'


def _variable_completion_detail(uri: str, definition: VarDef) -> str:
    detail = _assignment_detail(definition)
    source_name = uri.rsplit('/', 1)[-1]
    return detail if source_name == 'Makefile' else f'{source_name}: {detail}'


def _target_detail(uri: str, rule_text: str) -> str:
    header = rule_text.splitlines()[0]
    source_name = uri.rsplit('/', 1)[-1]
    return f'{source_name}: {header}'


def _rule_separator_in_line(line: str) -> tuple[int | None, int]:
    separator_index = line.find(':')
    if separator_index == -1:
        return None, 0
    if separator_index + 1 < len(line) and line[separator_index + 1] == '=':
        return None, 0
    if separator_index > 0 and line[separator_index - 1] in '?+!':
        return None, 0

    separator_width = 2 if line[separator_index : separator_index + 2] == '::' else 1
    if separator_index > 0 and line[separator_index - 1] == '&':
        return separator_index - 1, separator_width + 1
    return separator_index, separator_width


def _is_target_specific_variable_assignment(text: str) -> bool:
    stripped = text.strip()
    return stripped != '' and ASSIGNMENT_RE.fullmatch(stripped) is not None


def _is_target_completion_character(character: str) -> bool:
    return not character.isspace() and character not in ';#|$'
