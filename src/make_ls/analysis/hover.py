"""Hover rendering over recovered symbols plus builtin GNU Make docs.

Hover resolves from the local analyzed document first, then falls back to
related included documents or builtin directive, function, and variable docs.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from make_ls.builtin_docs import (
    BUILTIN_VARIABLE_DOCS,
    DIRECTIVE_DOCS,
    FUNCTION_DOCS,
    SPECIAL_TARGET_DOCS,
)
from make_ls.types import Span

from .navigation import pattern_target_definitions, resolve_variable_definition

if TYPE_CHECKING:
    from make_ls.builtin_docs import BuiltinDoc
    from make_ls.types import AnalyzedDoc, TargetDef, VarDef

BUILTIN_DIRECTIVE_TOKEN_RE = re.compile(r'-?[A-Za-z][A-Za-z0-9-]*')
BUILTIN_FUNCTION_NAME_RE = re.compile(r'[A-Za-z][A-Za-z0-9-]*')
BUILTIN_AUTOMATIC_VARIABLE_RE = re.compile(
    r'\$(?P<simple>[@%<?^+*|])|\$\((?P<paren>[@%<?^+*|][DF]?)\)|\$\{(?P<brace>[@%<?^+*|][DF]?)\}'
)


def hover_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    related_documents: tuple[AnalyzedDoc, ...] = (),
    source_lines: tuple[str, ...] | None = None,
) -> lsp.Hover | None:
    """Resolve hover content from local data first, then builtin fallbacks."""
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return _builtin_hover_for_position(source_lines, position)

    if occurrence.kind == 'target':
        builtin_target_doc = SPECIAL_TARGET_DOCS.get(occurrence.name)
        if builtin_target_doc is not None:
            return _render_builtin_hover_result(occurrence.span, builtin_target_doc)

        definitions = _hover_target_definitions(document, related_documents, occurrence.name)
        if not definitions:
            return None

        definition_document, definition = definitions[0]
        # Repeated Make rules can split prerequisites and recipes across separate
        # definitions. Keep definition hovers tied to the concrete rule under the
        # cursor, but prefer a recipe-bearing rule for plain references.
        if occurrence.role == 'definition' and definition_document.uri == document.uri:
            for candidate_document, candidate in definitions:
                if candidate.name_span == occurrence.span:
                    definition_document = candidate_document
                    definition = candidate
                    break
        else:
            for candidate_document, candidate in definitions:
                if candidate.recipe_text is not None:
                    definition_document = candidate_document
                    definition = candidate
                    break

        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value=_render_target_hover(definition_document, definition, len(definitions)),
            ),
            range=occurrence.span.to_lsp_range(),
        )

    definition = resolve_variable_definition(
        document,
        occurrence.name,
        occurrence.span.start_line,
        occurrence.span.start_character,
    )
    if definition is None:
        builtin_variable_doc = BUILTIN_VARIABLE_DOCS.get(occurrence.name)
        if builtin_variable_doc is None:
            return None
        return _render_builtin_hover_result(occurrence.span, builtin_variable_doc)

    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=_render_variable_hover(definition),
        ),
        range=occurrence.span.to_lsp_range(),
    )


def _builtin_hover_for_position(
    source_lines: tuple[str, ...] | None,
    position: lsp.Position,
) -> lsp.Hover | None:
    if source_lines is None or position.line >= len(source_lines):
        return None

    line_text = source_lines[position.line]
    builtin_match = _builtin_directive_match(line_text, position.line, position.character)
    if builtin_match is None:
        builtin_match = _builtin_function_match(line_text, position.line, position.character)
    if builtin_match is None:
        builtin_match = _builtin_automatic_variable_match(
            line_text,
            position.line,
            position.character,
        )
    if builtin_match is None:
        return None

    span, builtin_doc = builtin_match
    return _render_builtin_hover_result(span, builtin_doc)


def _builtin_directive_match(
    line_text: str,
    line_number: int,
    character: int,
) -> tuple[Span, BuiltinDoc] | None:
    if line_text.lstrip(' ').startswith(('\t', '#')):
        return None

    tokens = tuple(BUILTIN_DIRECTIVE_TOKEN_RE.finditer(line_text))
    if not tokens:
        return None

    candidate_tokens: list[re.Match[str]] = []
    first_token = tokens[0].group(0)
    if first_token in DIRECTIVE_DOCS:
        candidate_tokens.append(tokens[0])
    if (
        len(tokens) > 1
        and first_token in {'else', 'override'}
        and tokens[1].group(0) in DIRECTIVE_DOCS
    ):
        candidate_tokens.append(tokens[1])

    for token in candidate_tokens:
        if not (token.start() <= character < token.end()):
            continue
        return (
            Span(line_number, token.start(), line_number, token.end()),
            DIRECTIVE_DOCS[token.group(0)],
        )

    return None


def _builtin_function_match(
    line_text: str,
    line_number: int,
    character: int,
) -> tuple[Span, BuiltinDoc] | None:
    for index in range(len(line_text) - 1):
        if line_text[index] != '$' or line_text[index + 1] not in {'(', '{'}:
            continue
        if index > 0 and line_text[index - 1] == '$':
            continue

        name_match = BUILTIN_FUNCTION_NAME_RE.match(line_text, index + 2)
        if name_match is None:
            continue

        name = name_match.group(0)
        if name not in FUNCTION_DOCS:
            continue

        # Make functions separate the function name from its arguments with
        # whitespace, unlike variable references such as `$(CC)` or `${HOME}`.
        if name_match.end() >= len(line_text) or line_text[name_match.end()] not in {' ', '\t'}:
            continue
        if not (name_match.start() <= character < name_match.end()):
            continue

        return (
            Span(line_number, name_match.start(), line_number, name_match.end()),
            FUNCTION_DOCS[name],
        )

    return None


def _builtin_automatic_variable_match(
    line_text: str,
    line_number: int,
    character: int,
) -> tuple[Span, BuiltinDoc] | None:
    for match in BUILTIN_AUTOMATIC_VARIABLE_RE.finditer(line_text):
        if match.start() > 0 and line_text[match.start() - 1] == '$':
            continue
        if not (match.start() <= character < match.end()):
            continue

        name = match.group('simple') or match.group('paren') or match.group('brace')
        if name is None:
            continue

        builtin_doc = BUILTIN_VARIABLE_DOCS.get(name)
        if builtin_doc is None:
            continue

        return (
            Span(line_number, match.start(), line_number, match.end()),
            builtin_doc,
        )

    return None


def _render_builtin_hover_result(span: Span, builtin_doc: BuiltinDoc) -> lsp.Hover:
    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=_render_builtin_hover(builtin_doc),
        ),
        range=span.to_lsp_range(),
    )


def _hover_target_definitions(
    document: AnalyzedDoc,
    related_documents: tuple[AnalyzedDoc, ...],
    name: str,
) -> tuple[tuple[AnalyzedDoc, TargetDef], ...]:
    local_definitions = document.targets.get(name)
    if local_definitions:
        return tuple((document, definition) for definition in local_definitions)

    local_pattern_definitions = pattern_target_definitions(document, name)
    if local_pattern_definitions:
        return tuple((document, definition) for definition in local_pattern_definitions)

    matching_documents: list[tuple[AnalyzedDoc, tuple[TargetDef, ...]]] = []
    for related_document in related_documents:
        related_definitions = related_document.targets.get(name)
        if not related_definitions:
            continue
        matching_documents.append((related_document, related_definitions))
    if not matching_documents:
        for related_document in related_documents:
            related_definitions = pattern_target_definitions(related_document, name)
            if not related_definitions:
                continue
            matching_documents.append((related_document, related_definitions))

    if len(matching_documents) != 1:
        return ()

    related_document, related_definitions = matching_documents[0]
    return tuple((related_document, definition) for definition in related_definitions)


def _render_target_hover(
    document: AnalyzedDoc,
    definition: TargetDef,
    definition_count: int,
) -> str:
    prerequisites = _target_prerequisites(document, definition.name)
    lines = [f'```make\n{definition.rule_text}\n```']
    trailing_sections: list[str] = []
    if prerequisites:
        trailing_sections.append(
            f'Dependency Tree:\n\n{_render_dependency_tree(document, definition.name)}'
        )
    if definition_count > 1:
        trailing_sections.append(f'Definitions in document: {definition_count}')
    if not trailing_sections:
        return '\n'.join(lines)

    if definition.recipe_text is not None:
        # Emit explicit blank lines around the markdown rule so hover clients
        # render it as a real section break after recipe-bearing blocks.
        lines.extend(['', '---', ''])
    else:
        lines.append('')

    for index, section in enumerate(trailing_sections):
        if index > 0:
            lines.append('')
        lines.append(section)

    return '\n'.join(lines)


def _render_variable_hover(definition: VarDef) -> str:
    lines = [f'```make\n{definition.name} {definition.operator} {definition.value}\n```']
    if definition.documentation is not None:
        lines.append(definition.documentation)
    return '\n\n'.join(lines)


def _render_builtin_hover(builtin_doc: BuiltinDoc) -> str:
    kind_label = f'GNU Make {builtin_doc.kind}'
    return '\n\n'.join([f'```make\n{builtin_doc.signature}\n```', kind_label, builtin_doc.summary])


def _target_prerequisites(document: AnalyzedDoc, name: str) -> tuple[str, ...]:
    prerequisites: list[str] = []
    seen: set[str] = set()
    for definition in document.targets.get(name, ()):
        # Merge prerequisites across repeated target definitions because Make can
        # accumulate them across rules in the same file.
        for prerequisite in definition.prerequisites:
            if prerequisite in seen:
                continue
            seen.add(prerequisite)
            prerequisites.append(prerequisite)
    return tuple(prerequisites)


def _render_dependency_tree(document: AnalyzedDoc, root: str) -> str:
    lines = [root]
    shallowest_depths = _dependency_tree_shallowest_depths(document, root)
    dependency_lines, _ = _dependency_tree_lines(
        document,
        _target_prerequisites(document, root),
        ancestors={root},
        prefix='',
        expanded=set(),
        shallowest_depths=shallowest_depths,
        depth=1,
    )
    lines.extend(dependency_lines)
    # Use non-breaking spaces plus markdown hard breaks so the glyph tree stays
    # aligned outside a fenced block. Then style each label just enough to hint
    # at its role without falling back to noisy suffix tags.
    return '  \n'.join(_format_dependency_tree_line(document, line) for line in lines)


def _format_dependency_tree_line(document: AnalyzedDoc, line: str) -> str:
    branch_offset = max(line.rfind('└─ '), line.rfind('├─ '))
    if branch_offset == -1:
        prefix = ''
        label = line
    else:
        prefix = line[: branch_offset + 3].replace(' ', '\u00a0')
        label = line[branch_offset + 3 :]

    has_cycle = False
    if label.endswith(' (cycle)'):
        label = label[: -len(' (cycle)')]
        has_cycle = True

    has_suppressed_subtree = False
    if label.endswith(' ...'):
        label = label[: -len(' ...')]
        has_suppressed_subtree = True

    target_kind = _dependency_tree_target_kind(document, label)
    suppressed_text = ' ...' if has_suppressed_subtree else ''
    cycle_text = ' (cycle)' if has_cycle else ''
    return (
        f'{prefix}{_format_dependency_tree_label(label, target_kind)}{suppressed_text}{cycle_text}'
    )


def _dependency_tree_target_kind(document: AnalyzedDoc, name: str) -> str | None:
    if name in document.phony_targets:
        return 'phony'
    return 'file'


def _format_dependency_tree_label(label: str, target_kind: str | None) -> str:
    if target_kind == 'file':
        return f'`{label}`'
    if target_kind == 'phony':
        return f'*{_escape_markdown_emphasis(label)}*'
    return label


def _escape_markdown_emphasis(text: str) -> str:
    return text.replace('\\', '\\\\').replace('*', '\\*')


def _dependency_tree_lines(
    document: AnalyzedDoc,
    prerequisites: tuple[str, ...],
    *,
    ancestors: set[str],
    prefix: str,
    expanded: set[str],
    shallowest_depths: dict[str, int],
    depth: int,
) -> tuple[list[str], set[str]]:
    lines: list[str] = []
    expanded_here = set(expanded)
    for index, prerequisite in enumerate(prerequisites):
        is_last = index == len(prerequisites) - 1
        branch = '└─ ' if is_last else '├─ '
        line = f'{prefix}{branch}{prerequisite}'

        if prerequisite in ancestors:
            lines.append(f'{line} (cycle)')
            continue

        child_prerequisites = _target_prerequisites(document, prerequisite)
        if depth > shallowest_depths.get(prerequisite, depth) and child_prerequisites:
            lines.append(f'{line} ...')
            continue
        if prerequisite in expanded_here and child_prerequisites:
            # This branch was already expanded earlier in the hover tree, so
            # keep the edge visible but show that its children were collapsed.
            lines.append(f'{line} ...')
            continue

        lines.append(line)
        if not child_prerequisites:
            continue

        # Show every edge in the graph, but only expand a shared node the first
        # time it appears in the hover so later repeats stay as leaf references.
        child_lines, child_displayed = _dependency_tree_lines(
            document,
            child_prerequisites,
            ancestors=ancestors | {prerequisite},
            prefix=prefix + ('   ' if is_last else '│  '),
            expanded=expanded_here | {prerequisite},
            shallowest_depths=shallowest_depths,
            depth=depth + 1,
        )
        lines.extend(child_lines)
        expanded_here.update(child_displayed)
    return lines, expanded_here


def _dependency_tree_shallowest_depths(document: AnalyzedDoc, root: str) -> dict[str, int]:
    depths: dict[str, int] = {root: 0}
    pending: deque[tuple[str, int]] = deque([(root, 0)])

    while pending:
        node, depth = pending.popleft()
        for prerequisite in _target_prerequisites(document, node):
            next_depth = depth + 1
            if next_depth >= depths.get(prerequisite, next_depth + 1):
                continue
            depths[prerequisite] = next_depth
            pending.append((prerequisite, next_depth))

    return depths
