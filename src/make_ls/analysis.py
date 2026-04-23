from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass

from lsprotocol import types as lsp

from .builtin_docs import (
    BUILTIN_VARIABLE_DOCS,
    DIRECTIVE_DOCS,
    FUNCTION_DOCS,
    SPECIAL_TARGET_DOCS,
    BuiltinDoc,
)
from .types import (
    AnalyzedDocument,
    DocumentForm,
    FormKind,
    RecipeLine,
    Span,
    SymbolContext,
    SymbolContextKind,
    SymbolOccurrence,
    TargetDefinition,
    VariableDefinition,
    VariableGuard,
)

COMMENT_RE = re.compile(r"^[ ]*#(?P<text>.*)$")
TOKEN_RE = re.compile(r"\S+")
BUILTIN_DIRECTIVE_TOKEN_RE = re.compile(r"-?[A-Za-z][A-Za-z0-9-]*")
BUILTIN_FUNCTION_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
BUILTIN_AUTOMATIC_VARIABLE_RE = re.compile(
    r"\$(?P<simple>[@%<?^+*|])|\$\((?P<paren>[@%<?^+*|][DF]?)\)|\$\{(?P<brace>[@%<?^+*|][DF]?)\}"
)
ASSIGNMENT_RE = re.compile(
    r"^(?P<leading>[ ]*)(?P<prefix>(?:(?:export|override|private)\s+)*)"
    r"(?P<name>[A-Za-z0-9_.%/@+-]+)"
    r"[ ]*(?P<operator>[:+?!]?=)[ ]*(?P<value>.*)$"
)
VARIABLE_REFERENCE_RE = re.compile(
    r"\$\((?P<paren>[A-Za-z0-9_.%/@<?^+*|!-]+)\)"
    r"|\$\{(?P<brace>[A-Za-z0-9_.%/@<?^+*|!-]+)\}"
)
MAKE_AUTOMATIC_VARIABLE_RE = re.compile(
    r"\$\(([@%<?^+*|][DF]?)\)|\$\{([@%<?^+*|][DF]?)\}|\$([@%<?^+*|])"
)
VARIABLE_REFERENCE_DELIMITERS = {"(": ")", "{": "}"}
CONDITIONAL_DIRECTIVES = frozenset({"ifdef", "ifeq", "ifndef", "ifneq"})
CONDITIONAL_CONTROL_DIRECTIVES = CONDITIONAL_DIRECTIVES | frozenset({"else", "endif"})
RECIPE_BODY_DIRECTIVES = frozenset({"else", "endif", "ifdef", "ifeq", "ifndef", "ifneq"})
RULE_DIRECTIVES = frozenset(DIRECTIVE_DOCS)
INCLUDE_DIRECTIVES = frozenset({"include", "-include", "sinclude"})
VARIABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.%/@+-]+$")
EMPTY_CONDITIONAL_ARGUMENTS = frozenset({"", '""', "''"})


def analyze_document(
    uri: str,
    version: int | None,
    source: str,
    *,
    include_shell_diagnostics: bool = True,
) -> AnalyzedDocument:
    source_lines = source.splitlines()
    target_map: defaultdict[str, list[TargetDefinition]] = defaultdict(list)
    variable_map: defaultdict[str, list[VariableDefinition]] = defaultdict(list)
    phony_targets: set[str] = set()
    occurrences: list[SymbolOccurrence] = []
    forms: list[DocumentForm] = []
    recipe_lines: list[RecipeLine] = []
    (
        recovered_conditional_forms,
        recovered_conditional_occurrences,
        line_guards,
    ) = _recover_conditionals(source_lines)
    forms.extend(recovered_conditional_forms)
    _record_occurrences(occurrences, recovered_conditional_occurrences)
    recovered_includes, recovered_include_lines = _recover_include_directives(source_lines)
    (
        recovered_target_definitions,
        recovered_target_occurrences,
        recovered_rule_references,
        recovered_recipe_lines,
        recovered_rule_lines,
        recovered_rule_forms,
    ) = _recover_rules(source_lines, line_guards)
    phony_targets.update(_declared_phony_targets(recovered_target_definitions))
    forms.extend(recovered_rule_forms)
    recipe_lines.extend(recovered_recipe_lines)
    _record_occurrences(occurrences, recovered_target_occurrences)
    _record_occurrences(occurrences, recovered_rule_references)
    for definition in recovered_target_definitions:
        _record_target_definition(target_map, definition)

    (
        recovered_definitions,
        recovered_occurrences,
        recovered_assignment_lines,
        recovered_assignment_diagnostics,
        recovered_assignment_forms,
    ) = _recover_variable_assignments(source_lines, line_guards)
    forms.extend(recovered_assignment_forms)
    for definition in recovered_definitions:
        _record_variable_definition(
            variable_map,
            occurrences,
            definition,
            context=_symbol_context(
                "assignment",
                "assignment_definition",
                line_guards,
                definition.name_span.start_line,
            ),
        )
    _record_occurrences(occurrences, recovered_occurrences)

    make_diagnostics = _collect_make_syntax_diagnostics(
        source_lines,
        parsed_lines=recovered_rule_lines | recovered_assignment_lines | recovered_include_lines,
    )
    unknown_variable_diagnostics = _collect_unknown_variable_diagnostics(
        source,
        variable_map,
        occurrences,
    )
    shell_diagnostics = (
        _collect_shell_diagnostics(recipe_lines) if include_shell_diagnostics else []
    )

    return AnalyzedDocument(
        uri=uri,
        version=version,
        targets={name: tuple(definitions) for name, definitions in target_map.items()},
        variables={name: tuple(definitions) for name, definitions in variable_map.items()},
        includes=tuple(recovered_includes),
        phony_targets=frozenset(phony_targets),
        occurrences=tuple(occurrences),
        forms=tuple(forms),
        diagnostics=tuple(
            [
                *make_diagnostics,
                *recovered_assignment_diagnostics,
                *unknown_variable_diagnostics,
                *shell_diagnostics,
            ]
        ),
    )


def definition_for_position(
    document: AnalyzedDocument,
    position: lsp.Position,
    related_documents: tuple[AnalyzedDocument, ...] = (),
) -> lsp.Location | list[lsp.Location] | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == "target":
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


def references_for_position(
    document: AnalyzedDocument,
    position: lsp.Position,
    source_lines: tuple[str, ...],
    related_documents: tuple[AnalyzedDocument, ...] = (),
    *,
    include_declaration: bool,
) -> list[lsp.Location] | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == "target":
        definitions = _definition_target_definitions(document, related_documents, occurrence.name)
        if occurrence.role == "reference" and not definitions:
            return []

        return _target_references(
            (document, *related_documents),
            occurrence.name,
            include_declaration=include_declaration,
        )

    if occurrence.role == "reference" and (
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


def prepare_rename_for_position(
    document: AnalyzedDocument,
    position: lsp.Position,
    source_lines: tuple[str, ...],
) -> lsp.PrepareRenameResult | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None or occurrence.kind != "variable":
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


def rename_variable_for_position(
    document: AnalyzedDocument,
    position: lsp.Position,
    new_name: str,
    source_lines: tuple[str, ...],
) -> lsp.WorkspaceEdit | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None or occurrence.kind != "variable":
        return None
    if not _is_renameable_variable_occurrence(document, occurrence):
        return None
    if VARIABLE_NAME_RE.fullmatch(new_name) is None:
        return None

    edits: list[lsp.TextEdit] = []
    edited_spans: set[Span] = set()
    for definition in document.variables.get(occurrence.name, ()):
        if definition.name_span in edited_spans:
            continue
        edits.append(lsp.TextEdit(range=definition.name_span.to_lsp_range(), new_text=new_name))
        edited_spans.add(definition.name_span)

    for reference in document.occurrences:
        if reference.kind != "variable" or reference.role != "reference":
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


def hover_for_position(
    document: AnalyzedDocument,
    position: lsp.Position,
    related_documents: tuple[AnalyzedDocument, ...] = (),
    source_lines: tuple[str, ...] | None = None,
) -> lsp.Hover | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return _builtin_hover_for_position(source_lines, position)

    if occurrence.kind == "target":
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
        if occurrence.role == "definition" and definition_document.uri == document.uri:
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


def _is_renameable_variable_occurrence(
    document: AnalyzedDocument,
    occurrence: SymbolOccurrence,
) -> bool:
    if occurrence.kind != "variable":
        return False
    if occurrence.role == "definition":
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
    occurrence: SymbolOccurrence,
    source_lines: tuple[str, ...],
) -> Span | None:
    if occurrence.kind != "variable":
        return None
    if occurrence.role == "definition":
        return occurrence.span
    if occurrence.span.start_line >= len(source_lines):
        return None

    line_text = source_lines[occurrence.span.start_line]
    occurrence_text = line_text[occurrence.span.start_character : occurrence.span.end_character]
    if (
        occurrence_text.startswith("$(")
        and occurrence_text.endswith(")")
        and len(occurrence_text) >= 3
    ) or (
        occurrence_text.startswith("${")
        and occurrence_text.endswith("}")
        and len(occurrence_text) >= 3
    ):
        return Span(
            occurrence.span.start_line,
            occurrence.span.start_character + 2,
            occurrence.span.end_line,
            occurrence.span.end_character - 1,
        )
    return None


def _builtin_hover_for_position(
    source_lines: tuple[str, ...] | None, position: lsp.Position
) -> lsp.Hover | None:
    if source_lines is None or position.line >= len(source_lines):
        return None

    line_text = source_lines[position.line]
    builtin_match = _builtin_directive_match(line_text, position.line, position.character)
    if builtin_match is None:
        builtin_match = _builtin_function_match(line_text, position.line, position.character)
    if builtin_match is None:
        builtin_match = _builtin_automatic_variable_match(
            line_text, position.line, position.character
        )
    if builtin_match is None:
        return None

    span, builtin_doc = builtin_match
    return _render_builtin_hover_result(span, builtin_doc)


def _builtin_directive_match(
    line_text: str, line_number: int, character: int
) -> tuple[Span, BuiltinDoc] | None:
    if line_text.lstrip(" ").startswith(("\t", "#")):
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
        and first_token in {"else", "override"}
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
    line_text: str, line_number: int, character: int
) -> tuple[Span, BuiltinDoc] | None:
    for index in range(len(line_text) - 1):
        if line_text[index] != "$" or line_text[index + 1] not in {"(", "{"}:
            continue
        if index > 0 and line_text[index - 1] == "$":
            continue

        name_match = BUILTIN_FUNCTION_NAME_RE.match(line_text, index + 2)
        if name_match is None:
            continue

        name = name_match.group(0)
        if name not in FUNCTION_DOCS:
            continue

        # Make functions separate the function name from its arguments with
        # whitespace, unlike variable references such as `$(CC)` or `${HOME}`.
        if name_match.end() >= len(line_text) or line_text[name_match.end()] not in {" ", "\t"}:
            continue
        if not (name_match.start() <= character < name_match.end()):
            continue

        return (
            Span(line_number, name_match.start(), line_number, name_match.end()),
            FUNCTION_DOCS[name],
        )

    return None


def _builtin_automatic_variable_match(
    line_text: str, line_number: int, character: int
) -> tuple[Span, BuiltinDoc] | None:
    for match in BUILTIN_AUTOMATIC_VARIABLE_RE.finditer(line_text):
        if match.start() > 0 and line_text[match.start() - 1] == "$":
            continue
        if not (match.start() <= character < match.end()):
            continue

        name = match.group("simple") or match.group("paren") or match.group("brace")
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


def resolve_variable_definition(
    document: AnalyzedDocument, name: str, line: int, character: int
) -> VariableDefinition | None:
    definitions = document.variables.get(name)
    if not definitions:
        return None

    best_match = _latest_variable_definition_before_position(definitions, line, character)

    # Make variable expansion rules are context-sensitive. For navigation, the least
    # surprising fallback is the closest earlier definition when one exists.
    return best_match if best_match is not None else definitions[0]


def _latest_variable_definition_before_position(
    definitions: tuple[VariableDefinition, ...],
    line: int,
    character: int,
) -> VariableDefinition | None:
    best_match: VariableDefinition | None = None
    for definition in definitions:
        if (definition.name_span.start_line, definition.name_span.start_character) <= (
            line,
            character,
        ):
            best_match = definition
    return best_match


def _strict_variable_definition_at_position(
    document: AnalyzedDocument,
    name: str,
    line: int,
    character: int,
) -> VariableDefinition | None:
    definitions = document.variables.get(name)
    if not definitions:
        return None
    return _latest_variable_definition_before_position(definitions, line, character)


def _definition_target_definitions(
    document: AnalyzedDocument,
    related_documents: tuple[AnalyzedDocument, ...],
    name: str,
) -> tuple[tuple[AnalyzedDocument, TargetDefinition], ...]:
    local_definitions = document.targets.get(name)
    if local_definitions:
        return tuple((document, definition) for definition in local_definitions)

    definitions: list[tuple[AnalyzedDocument, TargetDefinition]] = []
    for related_document in related_documents:
        related_definitions = related_document.targets.get(name)
        if not related_definitions:
            continue
        definitions.extend((related_document, definition) for definition in related_definitions)

    return tuple(definitions)


def _target_references(
    documents: tuple[AnalyzedDocument, ...],
    name: str,
    *,
    include_declaration: bool,
) -> list[lsp.Location]:
    locations: list[lsp.Location] = []
    seen: set[tuple[str, Span]] = set()
    for source_document in documents:
        for occurrence in source_document.occurrences:
            if occurrence.kind != "target" or occurrence.name != name:
                continue
            if not include_declaration and occurrence.role != "reference":
                continue
            _append_location(locations, seen, source_document.uri, occurrence.span)

    return locations


def _variable_references(
    document: AnalyzedDocument,
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
        if occurrence.kind != "variable" or occurrence.role != "reference":
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


def _hover_target_definitions(
    document: AnalyzedDocument,
    related_documents: tuple[AnalyzedDocument, ...],
    name: str,
) -> tuple[tuple[AnalyzedDocument, TargetDefinition], ...]:
    local_definitions = document.targets.get(name)
    if local_definitions:
        return tuple((document, definition) for definition in local_definitions)

    matching_documents: list[tuple[AnalyzedDocument, tuple[TargetDefinition, ...]]] = []
    for related_document in related_documents:
        related_definitions = related_document.targets.get(name)
        if not related_definitions:
            continue
        matching_documents.append((related_document, related_definitions))

    if len(matching_documents) != 1:
        return ()

    related_document, related_definitions = matching_documents[0]
    return tuple((related_document, definition) for definition in related_definitions)


def _with_variable_comments(
    definition: VariableDefinition,
    source_lines: list[str],
) -> VariableDefinition:
    documentation = _leading_comment_block(
        source_lines,
        definition.assignment_span.start_line,
    )
    if documentation is None:
        return definition

    return VariableDefinition(
        name=definition.name,
        name_span=definition.name_span,
        assignment_span=definition.assignment_span,
        operator=definition.operator,
        value=definition.value,
        documentation=documentation,
    )


def _record_variable_definition(
    variable_map: defaultdict[str, list[VariableDefinition]],
    occurrences: list[SymbolOccurrence],
    definition: VariableDefinition,
    *,
    context: SymbolContext | None = None,
) -> None:
    if any(
        existing.name_span == definition.name_span for existing in variable_map[definition.name]
    ):
        return

    variable_map[definition.name].append(definition)
    _record_occurrences(
        occurrences,
        [
            SymbolOccurrence(
                kind="variable",
                role="definition",
                name=definition.name,
                span=definition.name_span,
                context=context,
            )
        ],
    )


def _record_target_definition(
    target_map: defaultdict[str, list[TargetDefinition]],
    definition: TargetDefinition,
) -> None:
    if any(existing.name_span == definition.name_span for existing in target_map[definition.name]):
        return
    target_map[definition.name].append(definition)


def _record_occurrences(
    occurrences: list[SymbolOccurrence],
    new_occurrences: list[SymbolOccurrence],
) -> None:
    seen = {
        (occurrence.kind, occurrence.role, occurrence.name, occurrence.span)
        for occurrence in occurrences
    }
    for occurrence in new_occurrences:
        key = (occurrence.kind, occurrence.role, occurrence.name, occurrence.span)
        if key in seen:
            continue
        occurrences.append(occurrence)
        seen.add(key)


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


@dataclass(frozen=True, slots=True)
class _ConditionalFrame:
    current_guards: tuple[VariableGuard, ...]
    else_guards: tuple[VariableGuard, ...]


def _recover_conditionals(
    source_lines: list[str],
) -> tuple[list[DocumentForm], list[SymbolOccurrence], dict[int, tuple[VariableGuard, ...]]]:
    forms: list[DocumentForm] = []
    occurrences: list[SymbolOccurrence] = []
    line_guards: dict[int, tuple[VariableGuard, ...]] = {}
    condition_stack: list[_ConditionalFrame] = []
    line_number = 0
    in_define_block = False

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        active_guards = _active_condition_guards(condition_stack)

        if _starts_define_block(stripped):
            in_define_block = True
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue
        if in_define_block:
            if active_guards:
                line_guards[line_number] = active_guards
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t"):
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue

        if _continues_previous_top_level_line(source_lines, line_number):
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue

        logical_end_line = _logical_top_level_end(source_lines, line_number)
        logical_text = ""
        for logical_line in range(line_number, logical_end_line + 1):
            text = _strip_make_comment(source_lines[logical_line]).strip()
            if logical_line < logical_end_line and text.endswith("\\"):
                text = text[:-1].rstrip()
            if text != "":
                logical_text += (" " if logical_text else "") + text

        first_token, _separator, _remainder = logical_text.partition(" ")
        if first_token in CONDITIONAL_CONTROL_DIRECTIVES:
            if first_token in CONDITIONAL_DIRECTIVES:
                forms.append(
                    DocumentForm(
                        kind="conditional",
                        span=Span(
                            line_number,
                            0,
                            logical_end_line,
                            len(source_lines[logical_end_line]),
                        ),
                    )
                )
                context = SymbolContext(
                    form_kind="conditional",
                    kind="conditional_test",
                    active_guards=active_guards,
                )
                for directive_line in range(line_number, logical_end_line + 1):
                    occurrences.extend(
                        _recover_variable_references_from_text(
                            source_lines[directive_line],
                            directive_line,
                            context=context,
                        )
                    )
                current_guards, else_guards = _conditional_branch_guards(logical_text)
                condition_stack.append(
                    _ConditionalFrame(
                        current_guards=current_guards,
                        else_guards=else_guards,
                    )
                )
            elif first_token == "else":
                if condition_stack:
                    current_guards = condition_stack[-1].current_guards
                    else_guards = condition_stack[-1].else_guards
                    condition_stack[-1] = _ConditionalFrame(
                        current_guards=else_guards,
                        else_guards=current_guards,
                    )
            elif first_token == "endif" and condition_stack:
                _ = condition_stack.pop()

            line_number = logical_end_line + 1
            continue

        if active_guards:
            for guarded_line in range(line_number, logical_end_line + 1):
                line_guards[guarded_line] = active_guards
        line_number = logical_end_line + 1

    return forms, occurrences, line_guards


def _active_condition_guards(
    condition_stack: list[_ConditionalFrame],
) -> tuple[VariableGuard, ...]:
    return tuple(
        guard
        for frame in condition_stack
        for guard in frame.current_guards
    )


def _conditional_branch_guards(
    logical_text: str,
) -> tuple[tuple[VariableGuard, ...], tuple[VariableGuard, ...]]:
    first_token, _separator, remainder = logical_text.partition(" ")
    remainder = remainder.strip()

    if first_token in {"ifdef", "ifndef"}:
        if VARIABLE_NAME_RE.fullmatch(remainder) is None:
            return (), ()
        if first_token == "ifdef":
            return (
                (VariableGuard(remainder, "defined"),),
                (VariableGuard(remainder, "undefined"),),
            )
        return (
            (VariableGuard(remainder, "undefined"),),
            (VariableGuard(remainder, "defined"),),
        )

    if first_token not in {"ifeq", "ifneq"}:
        return (), ()

    left, right = _conditional_arguments(remainder)
    if left is None or right is None:
        return (), ()

    name: str | None = None
    if _conditional_argument_is_empty(left):
        name = _simple_variable_reference_name(right)
    elif _conditional_argument_is_empty(right):
        name = _simple_variable_reference_name(left)
    if name is None:
        return (), ()

    if first_token == "ifneq":
        return (
            (VariableGuard(name, "nonempty"),),
            (VariableGuard(name, "empty"),),
        )
    return (
        (VariableGuard(name, "empty"),),
        (VariableGuard(name, "nonempty"),),
    )


def _conditional_arguments(text: str) -> tuple[str | None, str | None]:
    if not (text.startswith("(") and text.endswith(")")):
        return None, None
    arguments = text[1:-1]
    separator_index = arguments.find(",")
    if separator_index == -1:
        return None, None
    return arguments[:separator_index].strip(), arguments[separator_index + 1 :].strip()


def _conditional_argument_is_empty(text: str) -> bool:
    return text in EMPTY_CONDITIONAL_ARGUMENTS


def _simple_variable_reference_name(text: str) -> str | None:
    match = VARIABLE_REFERENCE_RE.fullmatch(text)
    if match is None:
        return None
    return match.group("paren") or match.group("brace")


def _symbol_context(
    form_kind: FormKind,
    kind: SymbolContextKind,
    line_guards: dict[int, tuple[VariableGuard, ...]],
    line_number: int,
) -> SymbolContext:
    return SymbolContext(
        form_kind=form_kind,
        kind=kind,
        active_guards=line_guards.get(line_number, ()),
    )


def _collect_shell_diagnostics(recipe_lines: list[RecipeLine]) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    for recipe_group in _logical_recipe_lines(recipe_lines):
        command_text = "\n".join(line.command_text for line in recipe_group)
        if command_text.strip() == "":
            continue

        is_valid = _shell_syntax_is_valid(command_text)
        if is_valid is None or is_valid:
            continue

        first_line = recipe_group[0]
        diagnostics.append(
            lsp.Diagnostic(
                range=Span(
                    first_line.span.start_line,
                    first_line.prefix_length,
                    first_line.span.start_line,
                    len(first_line.raw_text),
                ).to_lsp_range(),
                message=_diagnostic_message("Invalid shell syntax in recipe", command_text),
                severity=lsp.DiagnosticSeverity.Error,
                source="make-ls",
            )
        )

    return diagnostics


def _collect_make_syntax_diagnostics(
    source_lines: list[str],
    *,
    parsed_lines: set[int],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    in_define_block = False
    line_number = 0
    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if line_number in parsed_lines or stripped == "" or stripped.startswith("#"):
            line_number += 1
            continue

        if _starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue

        if in_define_block:
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t"):
            diagnostics.append(_make_syntax_diagnostic(source_lines, line_number, line_number))
            line_number += 1
            continue

        if _continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        logical_end_line = _logical_top_level_end(source_lines, line_number)
        # The owned parser does not model directives or eager top-level function
        # calls, but they are valid Make syntax and should not produce noise.
        if _is_tolerated_top_level_line(stripped):
            line_number = logical_end_line + 1
            continue

        diagnostics.append(_make_syntax_diagnostic(source_lines, line_number, logical_end_line))
        line_number = logical_end_line + 1

    return diagnostics


def _collect_unknown_variable_diagnostics(
    source: str,
    variable_map: dict[str, list[VariableDefinition]] | defaultdict[str, list[VariableDefinition]],
    occurrences: list[SymbolOccurrence],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    for occurrence in occurrences:
        if occurrence.kind != "variable" or occurrence.role != "reference":
            continue
        if occurrence.name in variable_map:
            continue
        occurrence_text = _slice_text_span(source, occurrence.span)
        if not _should_warn_for_unknown_variable(
            occurrence.name,
            occurrence_text,
            occurrence.context,
        ):
            continue

        diagnostics.append(
            lsp.Diagnostic(
                range=occurrence.span.to_lsp_range(),
                message=_diagnostic_message(
                    "Unknown variable reference",
                    occurrence_text,
                ),
                severity=lsp.DiagnosticSeverity.Warning,
                source="make-ls",
            )
        )
    return diagnostics


def _make_syntax_diagnostic(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> lsp.Diagnostic:
    return lsp.Diagnostic(
        range=Span(start_line, 0, end_line, len(source_lines[end_line])).to_lsp_range(),
        message=_diagnostic_message(
            "Invalid Makefile syntax",
            _slice_source_lines(
                source_lines,
                start_line=start_line,
                start_character=0,
                end_line=end_line,
                end_character=len(source_lines[end_line]),
            ),
        ),
        severity=lsp.DiagnosticSeverity.Error,
        source="make-ls",
    )


def _is_tolerated_top_level_line(stripped_line: str) -> bool:
    if stripped_line.startswith("$(") or stripped_line.startswith("${"):
        return True
    first_token = stripped_line.split(maxsplit=1)[0]
    return first_token in RULE_DIRECTIVES


def _strip_recipe_prefix(raw_text: str) -> tuple[int, str]:
    prefix_length = 0
    # Make strips these control prefixes before invoking the shell. They are not
    # part of the shell program, so diagnostics must parse the remainder instead.
    while prefix_length < len(raw_text) and raw_text[prefix_length] in "@+-":
        prefix_length += 1

    return prefix_length, raw_text[prefix_length:]


def _recover_rules(
    source_lines: list[str],
    line_guards: dict[int, tuple[VariableGuard, ...]],
) -> tuple[
    list[TargetDefinition],
    list[SymbolOccurrence],
    list[SymbolOccurrence],
    list[RecipeLine],
    set[int],
    list[DocumentForm],
]:
    definitions: list[TargetDefinition] = []
    target_occurrences: list[SymbolOccurrence] = []
    reference_occurrences: list[SymbolOccurrence] = []
    recipe_lines: list[RecipeLine] = []
    parsed_lines: set[int] = set()
    forms: list[DocumentForm] = []
    line_number = 0
    in_define_block = False

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if _starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t") or _continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        recovered_rule = _recover_rule(source_lines, line_number, line_guards)
        if recovered_rule is None:
            line_number += 1
            continue

        (
            recovered_definitions,
            recovered_target_occurrences,
            recovered_reference_occurrences,
            recovered_recipe_lines,
            next_line_number,
            recovered_rule_form,
        ) = recovered_rule
        definitions.extend(recovered_definitions)
        target_occurrences.extend(recovered_target_occurrences)
        reference_occurrences.extend(recovered_reference_occurrences)
        recipe_lines.extend(recovered_recipe_lines)
        forms.append(recovered_rule_form)
        parsed_lines.update(range(line_number, next_line_number))
        line_number = next_line_number

    return definitions, target_occurrences, reference_occurrences, recipe_lines, parsed_lines, forms


def _recover_rule(
    source_lines: list[str],
    start_line: int,
    line_guards: dict[int, tuple[VariableGuard, ...]],
) -> (
    tuple[
        list[TargetDefinition],
        list[SymbolOccurrence],
        list[SymbolOccurrence],
        list[RecipeLine],
        int,
        DocumentForm,
    ]
    | None
):
    header_lines = [source_lines[start_line]]
    header_end_line = start_line
    while _has_unescaped_line_continuation(header_lines[-1]) and (
        header_end_line + 1 < len(source_lines)
    ):
        next_line = source_lines[header_end_line + 1]
        if next_line.startswith("\t"):
            break
        header_lines.append(next_line)
        header_end_line += 1

    separator_index, separator_width = _recover_rule_separator(header_lines[0])
    if separator_index is None:
        return None

    target_definitions: list[TargetDefinition] = []
    target_occurrences: list[SymbolOccurrence] = []
    reference_occurrences: list[SymbolOccurrence] = []
    header_text = "\n".join(header_lines)
    rule_recipe_lines: list[RecipeLine] = []
    next_line_number = header_end_line + 1
    previous_recipe_continues = False
    while next_line_number < len(source_lines):
        next_line = source_lines[next_line_number]
        stripped_next_line = next_line.strip()
        if next_line.startswith("\t"):
            recipe_line = _recipe_line_from_source(next_line_number, next_line)
            rule_recipe_lines.append(recipe_line)
            previous_recipe_continues = _has_unescaped_line_continuation(recipe_line.command_text)
            next_line_number += 1
            continue
        if previous_recipe_continues:
            recipe_line = _continued_recipe_line_from_source(next_line_number, next_line)
            rule_recipe_lines.append(recipe_line)
            previous_recipe_continues = _has_unescaped_line_continuation(recipe_line.command_text)
            next_line_number += 1
            continue
        if (
            stripped_next_line == ""
            or stripped_next_line.startswith("#")
            or _is_recipe_body_directive(stripped_next_line)
        ) and _rule_body_continues(source_lines, next_line_number):
            next_line_number += 1
            continue
        break

    recipe_text = "\n".join(line.raw_text for line in rule_recipe_lines) or None
    rule_end_line = rule_recipe_lines[-1].span.end_line if rule_recipe_lines else header_end_line
    rule_end_character = (
        rule_recipe_lines[-1].span.end_character
        if rule_recipe_lines
        else len(source_lines[header_end_line])
    )
    rule_span = Span(start_line, 0, rule_end_line, rule_end_character)
    rule_text = header_text if recipe_text is None else f"{header_text}\n{recipe_text}"
    targets_text = header_lines[0][:separator_index]
    if targets_text.strip() == "":
        return None

    for match in TOKEN_RE.finditer(targets_text):
        target_name = match.group(0)
        if target_name == "\\":
            continue

        name_span = Span(start_line, match.start(), start_line, match.end())
        definition = TargetDefinition(
            name=target_name,
            name_span=name_span,
            rule_span=rule_span,
            prerequisites=_recover_prerequisites(header_lines, separator_index, separator_width),
            rule_text=rule_text,
            recipe_text=recipe_text,
        )
        target_definitions.append(definition)
        target_occurrences.append(
            SymbolOccurrence(
                kind="target",
                role="definition",
                name=target_name,
                span=name_span,
                context=_symbol_context("rule", "target_definition", line_guards, start_line),
            )
        )

    reference_occurrences.extend(
        _recover_prerequisite_occurrences(
            header_lines,
            start_line,
            separator_index,
            separator_width,
            line_guards,
        )
    )
    for recipe_line in rule_recipe_lines:
        reference_occurrences.extend(
            _recover_variable_references_from_text(
                recipe_line.raw_text,
                recipe_line.span.start_line,
                context=_symbol_context("rule", "recipe", line_guards, recipe_line.span.start_line),
            )
        )

    return (
        target_definitions,
        target_occurrences,
        reference_occurrences,
        rule_recipe_lines,
        next_line_number,
        DocumentForm(kind="rule", span=rule_span),
    )


def _recover_rule_separator(line: str) -> tuple[int | None, int]:
    stripped = line.lstrip()
    if stripped == "" or stripped.startswith("#"):
        return None, 0
    if stripped.split(maxsplit=1)[0] in RULE_DIRECTIVES:
        return None, 0
    if ASSIGNMENT_RE.match(line) is not None:
        return None, 0

    separator_index = line.find(":")
    if separator_index == -1:
        return None, 0
    if separator_index + 1 < len(line) and line[separator_index + 1] == "=":
        return None, 0
    if separator_index > 0 and line[separator_index - 1] in "?+!":
        return None, 0

    separator_width = 2 if line[separator_index : separator_index + 2] == "::" else 1
    return separator_index, separator_width


def _recover_prerequisites(
    header_lines: list[str],
    separator_index: int,
    separator_width: int,
) -> tuple[str, ...]:
    prerequisites: list[str] = []
    for line_index, line in enumerate(header_lines):
        text = line[separator_index + separator_width :] if line_index == 0 else line
        text = text.split(";", 1)[0]
        for match in TOKEN_RE.finditer(text):
            token = match.group(0)
            if token in {"\\", "|"}:
                continue
            if token.startswith("#"):
                break
            if "$(" in token or "${" in token:
                continue
            prerequisites.append(token)
    return tuple(prerequisites)


def _recover_prerequisite_occurrences(
    header_lines: list[str],
    start_line: int,
    separator_index: int,
    separator_width: int,
    line_guards: dict[int, tuple[VariableGuard, ...]],
) -> list[SymbolOccurrence]:
    occurrences: list[SymbolOccurrence] = []
    for line_offset, line in enumerate(header_lines):
        if line_offset == 0:
            text = line[separator_index + separator_width :]
            start_character = separator_index + separator_width
        else:
            text = line
            start_character = 0
        text = text.split(";", 1)[0]
        line_number = start_line + line_offset

        occurrences.extend(
            _recover_variable_references_from_text(
                text,
                line_number,
                start_character,
                context=_symbol_context("rule", "prerequisite", line_guards, line_number),
            )
        )
        for match in TOKEN_RE.finditer(text):
            token = match.group(0)
            if token in {"\\", "|"}:
                continue
            if token.startswith("#"):
                break
            if "$(" in token or "${" in token:
                continue
            occurrences.append(
                SymbolOccurrence(
                    kind="target",
                    role="reference",
                    name=token,
                    span=Span(
                        line_number,
                        start_character + match.start(),
                        line_number,
                        start_character + match.end(),
                    ),
                    context=_symbol_context("rule", "prerequisite", line_guards, line_number),
                )
            )

    return occurrences


def _recover_variable_references_from_text(
    text: str,
    line_number: int,
    start_character: int = 0,
    *,
    context: SymbolContext | None = None,
) -> list[SymbolOccurrence]:
    occurrences: list[SymbolOccurrence] = []
    for reference in VARIABLE_REFERENCE_RE.finditer(text):
        reference_name = reference.group("paren") or reference.group("brace")
        if reference_name is None:
            continue
        occurrences.append(
            SymbolOccurrence(
                kind="variable",
                role="reference",
                name=reference_name,
                span=Span(
                    line_number,
                    start_character + reference.start(),
                    line_number,
                    start_character + reference.end(),
                ),
                context=context,
            )
        )
    return occurrences


def _recover_include_directives(source_lines: list[str]) -> tuple[list[str], set[int]]:
    includes: list[str] = []
    parsed_lines: set[int] = set()
    in_define_block = False
    line_number = 0

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if _starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t") or _continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        logical_end_line = _logical_top_level_end(source_lines, line_number)
        recovered_include_paths = _recover_include_paths(
            source_lines,
            line_number,
            logical_end_line,
        )
        if not recovered_include_paths:
            line_number = logical_end_line + 1
            continue

        includes.extend(recovered_include_paths)
        parsed_lines.update(range(line_number, logical_end_line + 1))
        line_number = logical_end_line + 1

    return includes, parsed_lines


def _recover_include_paths(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> tuple[str, ...]:
    logical_parts: list[str] = []
    for line_number in range(start_line, end_line + 1):
        text = _strip_make_comment(source_lines[line_number]).strip()
        if line_number < end_line and text.endswith("\\"):
            text = text[:-1].rstrip()
        logical_parts.append(text)

    logical_text = " ".join(part for part in logical_parts if part)
    if logical_text == "":
        return ()

    first_token, _separator, remainder = logical_text.partition(" ")
    if first_token not in INCLUDE_DIRECTIVES:
        return ()

    return tuple(token for token in remainder.split() if token != "")


def _strip_make_comment(text: str) -> str:
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "#":
            return text[:index]
    return text


def _starts_define_block(stripped_line: str) -> bool:
    return stripped_line.startswith("define ") or stripped_line.startswith("define\t")


def _continues_previous_top_level_line(source_lines: list[str], line_number: int) -> bool:
    if line_number == 0:
        return False
    previous_line = source_lines[line_number - 1]
    return not previous_line.startswith("\t") and _has_unescaped_line_continuation(previous_line)


def _logical_top_level_end(source_lines: list[str], start_line: int) -> int:
    end_line = start_line
    while _has_unescaped_line_continuation(source_lines[end_line]) and end_line + 1 < len(
        source_lines
    ):
        end_line += 1
    return end_line


def _is_recipe_body_directive(stripped_line: str) -> bool:
    if stripped_line == "":
        return False
    return stripped_line.split(maxsplit=1)[0] in RECIPE_BODY_DIRECTIVES


def _rule_body_continues(source_lines: list[str], start_line: int) -> bool:
    line_number = start_line
    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#") or _is_recipe_body_directive(stripped):
            line_number += 1
            continue
        return line.startswith("\t")
    return False


def _recipe_line_from_source(line_number: int, raw_text: str) -> RecipeLine:
    recipe_prefix_length = 1
    control_prefix_length, command_text = _strip_recipe_prefix(raw_text[recipe_prefix_length:])
    return RecipeLine(
        span=Span(line_number, 0, line_number, len(raw_text)),
        raw_text=raw_text,
        command_text=command_text,
        prefix_length=recipe_prefix_length + control_prefix_length,
    )


def _continued_recipe_line_from_source(line_number: int, raw_text: str) -> RecipeLine:
    return RecipeLine(
        span=Span(line_number, 0, line_number, len(raw_text)),
        raw_text=raw_text,
        command_text=raw_text,
        prefix_length=0,
    )


def _slice_source_lines(
    source_lines: list[str],
    *,
    start_line: int,
    start_character: int,
    end_line: int,
    end_character: int,
) -> str:
    if start_line == end_line:
        return source_lines[start_line][start_character:end_character]

    parts = [source_lines[start_line][start_character:]]
    for line_number in range(start_line + 1, end_line):
        parts.append(source_lines[line_number])
    parts.append(source_lines[end_line][:end_character])
    return "\n".join(parts)


def _recover_variable_assignments(
    source_lines: list[str],
    line_guards: dict[int, tuple[VariableGuard, ...]],
) -> tuple[
    list[VariableDefinition],
    list[SymbolOccurrence],
    set[int],
    list[lsp.Diagnostic],
    list[DocumentForm],
]:
    definitions: list[VariableDefinition] = []
    occurrences: list[SymbolOccurrence] = []
    recovered_lines: set[int] = set()
    diagnostics: list[lsp.Diagnostic] = []
    forms: list[DocumentForm] = []

    line_number = 0
    in_define_block = False
    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if _starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t") or _continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        match = ASSIGNMENT_RE.match(line)
        if match is None:
            line_number += 1
            continue

        end_line = _logical_top_level_end(source_lines, line_number)
        name = match.group("name")
        operator = match.group("operator")
        value_start = match.start("value")
        value = _assignment_value_text(source_lines, line_number, value_start, end_line)
        name_span = Span(line_number, match.start("name"), line_number, match.end("name"))
        assignment_span = Span(
            line_number,
            match.start("name"),
            end_line,
            len(source_lines[end_line]),
        )

        definitions.append(
            _with_variable_comments(
                VariableDefinition(
                    name=name,
                    name_span=name_span,
                    assignment_span=assignment_span,
                    operator=operator,
                    value=value,
                ),
                source_lines,
            )
        )
        forms.append(DocumentForm(kind="assignment", span=assignment_span))
        recovered_lines.update(range(line_number, end_line + 1))

        if end_line == line_number:
            diagnostics.extend(
                _recover_assignment_value_diagnostics(
                    line,
                    line_number,
                    value_start,
                    match.group("value"),
                )
            )
        occurrences.extend(
            _recover_variable_references_from_assignment_lines(
                source_lines,
                line_number,
                value_start,
                end_line,
                line_guards,
            )
        )
        line_number = end_line + 1

    return definitions, occurrences, recovered_lines, diagnostics, forms


def _assignment_value_text(
    source_lines: list[str],
    start_line: int,
    value_start: int,
    end_line: int,
) -> str:
    if start_line == end_line:
        return source_lines[start_line][value_start:].strip()

    return _slice_source_lines(
        source_lines,
        start_line=start_line,
        start_character=value_start,
        end_line=end_line,
        end_character=len(source_lines[end_line]),
    ).rstrip()


def _recover_variable_references_from_assignment_lines(
    source_lines: list[str],
    start_line: int,
    value_start: int,
    end_line: int,
    line_guards: dict[int, tuple[VariableGuard, ...]],
) -> list[SymbolOccurrence]:
    occurrences = _recover_variable_references_from_text(
        source_lines[start_line][value_start:],
        start_line,
        value_start,
        context=_symbol_context("assignment", "assignment_value", line_guards, start_line),
    )
    for line_number in range(start_line + 1, end_line + 1):
        occurrences.extend(
            _recover_variable_references_from_text(
                source_lines[line_number],
                line_number,
                context=_symbol_context("assignment", "assignment_value", line_guards, line_number),
            )
        )
    return occurrences


def _diagnostic_message(prefix: str, snippet: str) -> str:
    compact_snippet = " ".join(snippet.split())
    if compact_snippet == "":
        return prefix

    if len(compact_snippet) > 40:
        compact_snippet = compact_snippet[:37] + "..."
    return f"{prefix} near `{compact_snippet}`"


def _render_target_hover(
    document: AnalyzedDocument,
    definition: TargetDefinition,
    definition_count: int,
) -> str:
    prerequisites = _target_prerequisites(document, definition.name)
    lines = [f"```make\n{definition.rule_text}\n```"]
    trailing_sections: list[str] = []
    if prerequisites:
        trailing_sections.append(
            f"Dependency Tree:\n\n{_render_dependency_tree(document, definition.name)}"
        )
    if definition_count > 1:
        trailing_sections.append(f"Definitions in document: {definition_count}")
    if not trailing_sections:
        return "\n".join(lines)

    if definition.recipe_text is not None:
        # Emit explicit blank lines around the markdown rule so hover clients
        # render it as a real section break after recipe-bearing blocks.
        lines.extend(["", "---", ""])
    else:
        lines.append("")

    for index, section in enumerate(trailing_sections):
        if index > 0:
            lines.append("")
        lines.append(section)

    return "\n".join(lines)


def _render_variable_hover(definition: VariableDefinition) -> str:
    lines = [f"```make\n{definition.name} {definition.operator} {definition.value}\n```"]
    if definition.documentation is not None:
        lines.append(definition.documentation)
    return "\n\n".join(lines)


def _render_builtin_hover(builtin_doc: BuiltinDoc) -> str:
    kind_label = f"GNU Make {builtin_doc.kind}"
    return "\n\n".join([f"```make\n{builtin_doc.signature}\n```", kind_label, builtin_doc.summary])


def _leading_comment_block(source_lines: list[str], line_number: int) -> str | None:
    comment_lines: list[str] = []

    for current_line in range(line_number - 1, -1, -1):
        match = COMMENT_RE.match(source_lines[current_line])
        if match is None:
            break

        text = match.group("text")
        if text.startswith(" "):
            text = text[1:]
        comment_lines.append(text.rstrip())

    if not comment_lines:
        return None

    comment_lines.reverse()
    return "\n".join(comment_lines)


def _target_prerequisites(document: AnalyzedDocument, name: str) -> tuple[str, ...]:
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


def _render_dependency_tree(document: AnalyzedDocument, root: str) -> str:
    lines = [root]
    shallowest_depths = _dependency_tree_shallowest_depths(document, root)
    dependency_lines, _ = _dependency_tree_lines(
        document,
        _target_prerequisites(document, root),
        ancestors={root},
        prefix="",
        expanded=set(),
        shallowest_depths=shallowest_depths,
        depth=1,
    )
    lines.extend(dependency_lines)
    # Use non-breaking spaces plus markdown hard breaks so the glyph tree stays
    # aligned outside a fenced block. Then style each label just enough to hint
    # at its role without falling back to noisy suffix tags.
    return "  \n".join(_format_dependency_tree_line(document, line) for line in lines)


def _format_dependency_tree_line(document: AnalyzedDocument, line: str) -> str:
    branch_offset = max(line.rfind("└─ "), line.rfind("├─ "))
    if branch_offset == -1:
        prefix = ""
        label = line
    else:
        prefix = line[: branch_offset + 3].replace(" ", "\u00a0")
        label = line[branch_offset + 3 :]

    has_cycle = False
    if label.endswith(" (cycle)"):
        label = label[: -len(" (cycle)")]
        has_cycle = True

    has_suppressed_subtree = False
    if label.endswith(" ..."):
        label = label[: -len(" ...")]
        has_suppressed_subtree = True

    target_kind = _dependency_tree_target_kind(document, label)
    suppressed_text = " ..." if has_suppressed_subtree else ""
    cycle_text = " (cycle)" if has_cycle else ""
    return (
        f"{prefix}{_format_dependency_tree_label(label, target_kind)}{suppressed_text}{cycle_text}"
    )


def _dependency_tree_target_kind(document: AnalyzedDocument, name: str) -> str | None:
    if name in document.phony_targets:
        return "phony"
    return "file"


def _format_dependency_tree_label(label: str, target_kind: str | None) -> str:
    if target_kind == "file":
        return f"`{label}`"
    if target_kind == "phony":
        return f"*{_escape_markdown_emphasis(label)}*"
    return label


def _escape_markdown_emphasis(text: str) -> str:
    return text.replace("\\", "\\\\").replace("*", "\\*")


def _declared_phony_targets(definitions: list[TargetDefinition]) -> tuple[str, ...]:
    # Make allows repeated `.PHONY:` declarations, and later ones are additive.
    phony_targets: list[str] = []
    for definition in definitions:
        if definition.name == ".PHONY":
            phony_targets.extend(definition.prerequisites)
    return tuple(phony_targets)


def _dependency_tree_lines(
    document: AnalyzedDocument,
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
        branch = "└─ " if is_last else "├─ "
        line = f"{prefix}{branch}{prerequisite}"

        if prerequisite in ancestors:
            lines.append(f"{line} (cycle)")
            continue

        child_prerequisites = _target_prerequisites(document, prerequisite)
        if depth > shallowest_depths.get(prerequisite, depth) and child_prerequisites:
            lines.append(f"{line} ...")
            continue
        if prerequisite in expanded_here and child_prerequisites:
            # This branch was already expanded earlier in the hover tree, so
            # keep the edge visible but show that its children were collapsed.
            lines.append(f"{line} ...")
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
            prefix=prefix + ("   " if is_last else "│  "),
            expanded=expanded_here | {prerequisite},
            shallowest_depths=shallowest_depths,
            depth=depth + 1,
        )
        lines.extend(child_lines)
        expanded_here.update(child_displayed)
    return lines, expanded_here


def _dependency_tree_shallowest_depths(document: AnalyzedDocument, root: str) -> dict[str, int]:
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


def _should_warn_for_unknown_variable(
    name: str,
    occurrence_text: str,
    context: SymbolContext | None,
) -> bool:
    if name.isdigit():
        return False
    if occurrence_text.startswith("${"):
        return False
    if "$(" in name or "${" in name:
        return False
    if name in BUILTIN_VARIABLE_DOCS:
        return False
    if _is_make_automatic_variable_name(name):
        return False
    if context is not None:
        if context.kind == "conditional_test":
            return False
        # Only suppress when the active guard proves this exact variable is
        # present. That keeps typoed guard names warning while allowing guarded
        # uses such as `ifneq ($(VAR),)` then `$(VAR)`.
        if any(
            guard.name == name and guard.kind in {"defined", "nonempty"}
            for guard in context.active_guards
        ):
            return False
    return name not in os.environ


def _is_make_automatic_variable_name(name: str) -> bool:
    if name == "":
        return False
    if name[0] not in "@%<?^+*|":
        return False
    return name[1:] in {"", "D", "F"}


def _recover_assignment_value_diagnostics(
    line: str,
    line_number: int,
    value_start: int,
    value: str,
) -> list[lsp.Diagnostic]:
    if _has_unescaped_line_continuation(value):
        return []

    open_references: list[tuple[int, str]] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "$" and index + 1 < len(value):
            next_character = value[index + 1]
            if next_character == "$":
                index += 2
                continue

            expected_closer = VARIABLE_REFERENCE_DELIMITERS.get(next_character)
            if expected_closer is not None:
                open_references.append((index, expected_closer))
                index += 2
                continue

            # Single-character variables such as `$@` and `$x` are valid Make syntax.
            index += 2
            continue

        if open_references and character == open_references[-1][1]:
            _ = open_references.pop()
        index += 1

    if not open_references:
        return []

    reference_start, _expected_closer = open_references[0]
    return [
        lsp.Diagnostic(
            range=Span(
                line_number,
                value_start + reference_start,
                line_number,
                len(line),
            ).to_lsp_range(),
            message=_diagnostic_message(
                "Invalid variable reference in assignment",
                value[reference_start:],
            ),
            severity=lsp.DiagnosticSeverity.Error,
            source="make-ls",
        )
    ]


def _has_unescaped_line_continuation(text: str) -> bool:
    stripped = text.rstrip()
    trailing_backslashes = len(stripped) - len(stripped.rstrip("\\"))
    return trailing_backslashes % 2 == 1


def _logical_recipe_lines(recipe_lines: list[RecipeLine]) -> list[list[RecipeLine]]:
    groups: list[list[RecipeLine]] = []
    current_group: list[RecipeLine] = []

    for recipe_line in recipe_lines:
        current_group.append(recipe_line)
        if _has_unescaped_line_continuation(recipe_line.command_text):
            continue

        groups.append(current_group)
        current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def _normalize_recipe_for_shell(command_text: str) -> str:
    # Bash does not understand Make's automatic variables such as `$<` or `$^`.
    # Replace them with a same-width shell expansion so parser ranges stay stable.
    return MAKE_AUTOMATIC_VARIABLE_RE.sub("$a", command_text)


def _shell_syntax_is_valid(command_text: str) -> bool | None:
    validation_text = _normalize_recipe_for_shell(command_text).replace("$$", "$")
    try:
        result = subprocess.run(
            ["bash", "-n"],
            input=validation_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return result.returncode == 0


def _slice_text_span(text: str, span: Span) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    if span.start_line == span.end_line:
        return lines[span.start_line][span.start_character : span.end_character]

    parts = [lines[span.start_line][span.start_character :]]
    for line_number in range(span.start_line + 1, span.end_line):
        parts.append(lines[line_number])
    parts.append(lines[span.end_line][: span.end_character])
    return "\n".join(parts)
