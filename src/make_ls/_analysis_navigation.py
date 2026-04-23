from __future__ import annotations

from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from . import _analysis_recovery as recovery
from .types import Span

if TYPE_CHECKING:
    from .types import AnalyzedDoc, SymOcc, TargetDef, VarDef


def def_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    related_documents: tuple[AnalyzedDoc, ...] = (),
) -> lsp.Location | list[lsp.Location] | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == 'target':
        definitions = _definition_target_definitions(document, related_documents, occurrence.name)
        if not definitions:
            return None

        locations = [
            lsp.Location(uri=source_document.uri, range=definition.name_span.to_lsp_range())
            for source_document, definition in definitions
        ]
        if len(locations) == 1:
            return locations[0]
        return locations

    definition = resolve_variable_definition(
        document,
        occurrence.name,
        occurrence.span.start_line,
        occurrence.span.start_character,
    )
    if definition is None:
        return None

    return lsp.Location(uri=document.uri, range=definition.name_span.to_lsp_range())


def refs_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    source_lines: tuple[str, ...],
    related_documents: tuple[AnalyzedDoc, ...] = (),
    *,
    include_declaration: bool,
) -> list[lsp.Location] | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == 'target':
        definitions = _definition_target_definitions(document, related_documents, occurrence.name)
        if occurrence.role == 'reference' and not definitions:
            return []

        return _target_references(
            (document, *related_documents),
            occurrence.name,
            include_declaration=include_declaration,
        )

    if occurrence.role == 'reference' and (
        _strict_variable_definition_at_position(
            document,
            occurrence.name,
            occurrence.span.start_line,
            occurrence.span.start_character,
        )
        is None
    ):
        return []

    return _variable_references(
        document,
        occurrence.name,
        source_lines,
        include_declaration=include_declaration,
    )


def prep_rename_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    source_lines: tuple[str, ...],
) -> lsp.PrepareRenameResult | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None or occurrence.kind != 'variable':
        return None
    if not _is_renameable_variable_occurrence(document, occurrence):
        return None

    name_span = _variable_name_span_for_occurrence(occurrence, source_lines)
    if name_span is None:
        return None

    return lsp.PrepareRenamePlaceholder(
        range=name_span.to_lsp_range(),
        placeholder=occurrence.name,
    )


def rename_var_for_pos(
    document: AnalyzedDoc,
    position: lsp.Position,
    new_name: str,
    source_lines: tuple[str, ...],
) -> lsp.WorkspaceEdit | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None or occurrence.kind != 'variable':
        return None
    if not _is_renameable_variable_occurrence(document, occurrence):
        return None
    if recovery.VARIABLE_NAME_RE.fullmatch(new_name) is None:
        return None

    edits: list[lsp.TextEdit] = []
    edited_spans: set[Span] = set()
    for definition in document.variables.get(occurrence.name, ()):
        if definition.name_span in edited_spans:
            continue
        edits.append(lsp.TextEdit(range=definition.name_span.to_lsp_range(), new_text=new_name))
        edited_spans.add(definition.name_span)

    for reference in document.occurrences:
        if reference.kind != 'variable' or reference.role != 'reference':
            continue
        if reference.name != occurrence.name:
            continue
        if not _is_renameable_variable_occurrence(document, reference):
            continue

        name_span = _variable_name_span_for_occurrence(reference, source_lines)
        if name_span is None or name_span in edited_spans:
            continue
        edits.append(lsp.TextEdit(range=name_span.to_lsp_range(), new_text=new_name))
        edited_spans.add(name_span)

    if not edits:
        return None

    return lsp.WorkspaceEdit(changes={document.uri: edits})


def resolve_variable_definition(
    document: AnalyzedDoc,
    name: str,
    line: int,
    character: int,
) -> VarDef | None:
    definitions = document.variables.get(name)
    if not definitions:
        return None

    best_match = _latest_variable_definition_before_position(definitions, line, character)

    # Make variable expansion rules are context-sensitive. For navigation, the least
    # surprising fallback is the closest earlier definition when one exists.
    return best_match if best_match is not None else definitions[0]


def pattern_target_definitions(
    document: AnalyzedDoc,
    name: str,
) -> tuple[TargetDef, ...]:
    definitions: list[TargetDef] = []
    for target_name, target_definitions in document.targets.items():
        if '%' not in target_name or not _matches_target_name(name, target_name):
            continue
        definitions.extend(target_definitions)
    return tuple(definitions)


def _latest_variable_definition_before_position(
    definitions: tuple[VarDef, ...],
    line: int,
    character: int,
) -> VarDef | None:
    best_match: VarDef | None = None
    for definition in definitions:
        if (definition.name_span.start_line, definition.name_span.start_character) <= (
            line,
            character,
        ):
            best_match = definition
    return best_match


def _strict_variable_definition_at_position(
    document: AnalyzedDoc,
    name: str,
    line: int,
    character: int,
) -> VarDef | None:
    definitions = document.variables.get(name)
    if not definitions:
        return None
    return _latest_variable_definition_before_position(definitions, line, character)


def _definition_target_definitions(
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

    definitions: list[tuple[AnalyzedDoc, TargetDef]] = []
    for related_document in related_documents:
        related_definitions = related_document.targets.get(name)
        if not related_definitions:
            continue
        definitions.extend((related_document, definition) for definition in related_definitions)
    if definitions:
        return tuple(definitions)

    for related_document in related_documents:
        related_definitions = pattern_target_definitions(related_document, name)
        if not related_definitions:
            continue
        definitions.extend((related_document, definition) for definition in related_definitions)

    return tuple(definitions)


def _target_references(
    documents: tuple[AnalyzedDoc, ...],
    name: str,
    *,
    include_declaration: bool,
) -> list[lsp.Location]:
    locations: list[lsp.Location] = []
    seen: set[tuple[str, Span]] = set()
    for source_document in documents:
        for occurrence in source_document.occurrences:
            if occurrence.kind != 'target' or occurrence.name != name:
                continue
            if not include_declaration and occurrence.role != 'reference':
                continue
            _append_location(locations, seen, source_document.uri, occurrence.span)

    return locations


def _variable_references(
    document: AnalyzedDoc,
    name: str,
    source_lines: tuple[str, ...],
    *,
    include_declaration: bool,
) -> list[lsp.Location]:
    locations: list[lsp.Location] = []
    seen: set[tuple[str, Span]] = set()

    if include_declaration:
        for definition in document.variables.get(name, ()):
            _append_location(locations, seen, document.uri, definition.name_span)

    # Variable expansion is still modeled conservatively, so references follow
    # the same same-document, local-definition rules as rename.
    for occurrence in document.occurrences:
        if occurrence.kind != 'variable' or occurrence.role != 'reference':
            continue
        if occurrence.name != name:
            continue
        if (
            _strict_variable_definition_at_position(
                document,
                name,
                occurrence.span.start_line,
                occurrence.span.start_character,
            )
            is None
        ):
            continue

        name_span = _variable_name_span_for_occurrence(occurrence, source_lines)
        if name_span is None:
            continue
        _append_location(locations, seen, document.uri, name_span)

    return locations


def _is_renameable_variable_occurrence(
    document: AnalyzedDoc,
    occurrence: SymOcc,
) -> bool:
    if occurrence.kind != 'variable':
        return False
    if occurrence.role == 'definition':
        return occurrence.name in document.variables

    # Rename should only touch references that resolve to a local variable
    # definition, so builtin names like `$(MAKE)` and unresolved refs stay put.
    return (
        _strict_variable_definition_at_position(
            document,
            occurrence.name,
            occurrence.span.start_line,
            occurrence.span.start_character,
        )
        is not None
    )


def _variable_name_span_for_occurrence(
    occurrence: SymOcc,
    source_lines: tuple[str, ...],
) -> Span | None:
    if occurrence.kind != 'variable':
        return None
    if occurrence.role == 'definition':
        return occurrence.span
    if occurrence.span.start_line >= len(source_lines):
        return None

    line_text = source_lines[occurrence.span.start_line]
    occurrence_text = line_text[occurrence.span.start_character : occurrence.span.end_character]
    if (
        occurrence_text.startswith('$(')
        and occurrence_text.endswith(')')
        and len(occurrence_text) >= 3
    ) or (
        occurrence_text.startswith('${')
        and occurrence_text.endswith('}')
        and len(occurrence_text) >= 3
    ):
        return Span(
            occurrence.span.start_line,
            occurrence.span.start_character + 2,
            occurrence.span.end_line,
            occurrence.span.end_character - 1,
        )
    return None


def _append_location(
    locations: list[lsp.Location],
    seen: set[tuple[str, Span]],
    uri: str,
    span: Span,
) -> None:
    key = (uri, span)
    if key in seen:
        return

    locations.append(lsp.Location(uri=uri, range=span.to_lsp_range()))
    seen.add(key)


def _matches_target_name(name: str, target_name: str) -> bool:
    if '%' not in target_name:
        return name == target_name

    prefix, _, suffix = target_name.partition('%')
    return (
        name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix) + len(suffix)
    )
