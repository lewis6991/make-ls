from __future__ import annotations

from collections import defaultdict

import tree_sitter_bash
import tree_sitter_make
from lsprotocol import types as lsp
from tree_sitter import Language, Node, Parser

from .types import (
    AnalyzedDocument,
    RecipeLine,
    Span,
    SymbolOccurrence,
    TargetDefinition,
    VariableDefinition,
)

MAKE_LANGUAGE = Language(tree_sitter_make.language())
BASH_LANGUAGE = Language(tree_sitter_bash.language())


def analyze_document(uri: str, version: int | None, source: str) -> AnalyzedDocument:
    root = _parse_with_language(MAKE_LANGUAGE, source)
    target_map: defaultdict[str, list[TargetDefinition]] = defaultdict(list)
    variable_map: defaultdict[str, list[VariableDefinition]] = defaultdict(list)
    occurrences: list[SymbolOccurrence] = []
    recipe_lines: list[RecipeLine] = []

    for node in root.named_children:
        if node.type == "variable_assignment":
            variable_definition = _parse_variable_definition(node)
            variable_map[variable_definition.name].append(variable_definition)
            occurrences.append(
                SymbolOccurrence(
                    kind="variable",
                    role="definition",
                    name=variable_definition.name,
                    span=variable_definition.name_span,
                )
            )
            occurrences.extend(_collect_variable_references(node))
            continue

        if node.type != "rule":
            continue

        (
            target_definitions,
            target_occurrences,
            reference_occurrences,
            rule_recipe_lines,
        ) = _parse_rule(node)
        recipe_lines.extend(rule_recipe_lines)
        occurrences.extend(target_occurrences)
        occurrences.extend(reference_occurrences)

        for definition in target_definitions:
            target_map[definition.name].append(definition)

    make_diagnostics = _collect_syntax_diagnostics(root, "Invalid Makefile syntax")
    shell_diagnostics = _collect_shell_diagnostics(recipe_lines)

    return AnalyzedDocument(
        uri=uri,
        version=version,
        targets={name: tuple(definitions) for name, definitions in target_map.items()},
        variables={name: tuple(definitions) for name, definitions in variable_map.items()},
        occurrences=tuple(occurrences),
        diagnostics=tuple([*make_diagnostics, *shell_diagnostics]),
    )


def definition_for_position(
    document: AnalyzedDocument, position: lsp.Position
) -> lsp.Location | list[lsp.Location] | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == "target":
        definitions = document.targets.get(occurrence.name)
        if not definitions:
            return None

        locations = [
            lsp.Location(uri=document.uri, range=definition.name_span.to_lsp_range())
            for definition in definitions
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


def hover_for_position(document: AnalyzedDocument, position: lsp.Position) -> lsp.Hover | None:
    occurrence = document.occurrence_at(position.line, position.character)
    if occurrence is None:
        return None

    if occurrence.kind == "target":
        definitions = document.targets.get(occurrence.name)
        if not definitions:
            return None

        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value=_render_target_hover(definitions[0], len(definitions)),
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
        return None

    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=_render_variable_hover(definition),
        ),
        range=occurrence.span.to_lsp_range(),
    )


def resolve_variable_definition(
    document: AnalyzedDocument, name: str, line: int, character: int
) -> VariableDefinition | None:
    definitions = document.variables.get(name)
    if not definitions:
        return None

    best_match: VariableDefinition | None = None
    for definition in definitions:
        if (definition.name_span.start_line, definition.name_span.start_character) <= (
            line,
            character,
        ):
            best_match = definition

    # Make variable expansion rules are context-sensitive. For navigation, the least
    # surprising fallback is the closest earlier definition when one exists.
    return best_match if best_match is not None else definitions[0]


def _parse_with_language(language: Language, source: str) -> Node:
    parser = Parser(language)
    return parser.parse(source.encode("utf-8")).root_node


def _parse_rule(
    node: Node,
) -> tuple[
    list[TargetDefinition],
    list[SymbolOccurrence],
    list[SymbolOccurrence],
    list[RecipeLine],
]:
    targets_node: Node | None = None
    prerequisites_node: Node | None = None
    recipe_node: Node | None = None

    for child in node.named_children:
        if child.type == "targets":
            targets_node = child
        elif child.type == "prerequisites":
            prerequisites_node = child
        elif child.type == "recipe":
            recipe_node = child

    if targets_node is None:
        return [], [], [], []

    recipe_lines = _extract_recipe_lines(recipe_node)
    recipe_preview = _first_recipe_preview(recipe_lines)
    prerequisites = _word_children(prerequisites_node)

    target_definitions: list[TargetDefinition] = []
    occurrences: list[SymbolOccurrence] = []
    for target_node in targets_node.named_children:
        if target_node.type != "word":
            continue

        name = _node_text(target_node)
        definition = TargetDefinition(
            name=name,
            name_span=_span_from_node(target_node),
            rule_span=_span_from_node(node),
            prerequisites=prerequisites,
            recipe_preview=recipe_preview,
        )
        target_definitions.append(definition)
        occurrences.append(
            SymbolOccurrence(
                kind="target",
                role="definition",
                name=name,
                span=definition.name_span,
            )
        )

    reference_occurrences: list[SymbolOccurrence] = []
    if prerequisites_node is not None:
        for child in prerequisites_node.named_children:
            if child.type == "word":
                reference_occurrences.append(
                    SymbolOccurrence(
                        kind="target",
                        role="reference",
                        name=_node_text(child),
                        span=_span_from_node(child),
                    )
                )
            elif child.type == "variable_reference":
                reference_occurrences.extend(_collect_variable_references(child))

    if recipe_node is not None:
        reference_occurrences.extend(_collect_variable_references(recipe_node))

    return target_definitions, occurrences, reference_occurrences, recipe_lines


def _parse_variable_definition(node: Node) -> VariableDefinition:
    name_node = node.child_by_field_name("name")
    operator_node = node.child_by_field_name("operator")
    value_node = node.child_by_field_name("value")

    if name_node is None or operator_node is None:
        raise ValueError("variable_assignment node is missing required fields")

    return VariableDefinition(
        name=_node_text(name_node),
        name_span=_span_from_node(name_node),
        assignment_span=_span_from_node(node),
        operator=_node_text(operator_node),
        value="" if value_node is None else _node_text(value_node).strip(),
    )


def _collect_variable_references(node: Node) -> list[SymbolOccurrence]:
    occurrences: list[SymbolOccurrence] = []
    for reference in _iter_nodes(node, wanted_type="variable_reference"):
        name_node = reference.named_children[0] if reference.named_children else None
        if name_node is None:
            continue

        occurrences.append(
            SymbolOccurrence(
                kind="variable",
                role="reference",
                name=_node_text(name_node),
                span=_span_from_node(reference),
            )
        )

    return occurrences


def _extract_recipe_lines(recipe_node: Node | None) -> list[RecipeLine]:
    if recipe_node is None:
        return []

    recipe_lines: list[RecipeLine] = []
    for child in recipe_node.named_children:
        if child.type != "recipe_line":
            continue

        raw_text = _node_text(child)
        prefix_length, command_text = _strip_recipe_prefix(raw_text)
        recipe_lines.append(
            RecipeLine(
                span=_span_from_node(child),
                raw_text=raw_text,
                command_text=command_text,
                prefix_length=prefix_length,
            )
        )

    return recipe_lines


def _collect_shell_diagnostics(recipe_lines: list[RecipeLine]) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    for recipe_line in recipe_lines:
        if recipe_line.command_text.strip() == "":
            continue

        root = _parse_with_language(BASH_LANGUAGE, recipe_line.command_text)
        for error_node in _iter_error_nodes(root):
            diagnostics.append(
                lsp.Diagnostic(
                    range=_recipe_error_span(recipe_line, error_node).to_lsp_range(),
                    message=_diagnostic_message(
                        "Invalid shell syntax in recipe",
                        _node_text(error_node),
                    ),
                    severity=lsp.DiagnosticSeverity.Error,
                    source="makels",
                )
            )

    return diagnostics


def _collect_syntax_diagnostics(root: Node, prefix: str) -> list[lsp.Diagnostic]:
    return [
        lsp.Diagnostic(
            range=_span_from_node(error_node).to_lsp_range(),
            message=_diagnostic_message(prefix, _node_text(error_node)),
            severity=lsp.DiagnosticSeverity.Error,
            source="makels",
        )
        for error_node in _iter_error_nodes(root)
    ]


def _iter_error_nodes(node: Node) -> list[Node]:
    if node.is_error or node.is_missing:
        return [node]

    errors: list[Node] = []
    for child in node.children:
        if child.is_error or child.is_missing or child.has_error:
            errors.extend(_iter_error_nodes(child))
    return errors


def _iter_nodes(node: Node, *, wanted_type: str) -> list[Node]:
    matches: list[Node] = []
    if node.type == wanted_type:
        matches.append(node)

    for child in node.children:
        matches.extend(_iter_nodes(child, wanted_type=wanted_type))

    return matches


def _first_recipe_preview(recipe_lines: list[RecipeLine]) -> str | None:
    for recipe_line in recipe_lines:
        preview = " ".join(part for part in recipe_line.command_text.splitlines() if part).strip()
        if preview:
            return preview
    return None


def _strip_recipe_prefix(raw_text: str) -> tuple[int, str]:
    prefix_length = 0
    # Make strips these control prefixes before invoking the shell. They are not
    # part of the shell program, so diagnostics must parse the remainder instead.
    while prefix_length < len(raw_text) and raw_text[prefix_length] in "@+-":
        prefix_length += 1

    return prefix_length, raw_text[prefix_length:]


def _span_from_node(node: Node) -> Span:
    return Span(
        start_line=node.start_point[0],
        start_character=node.start_point[1],
        end_line=node.end_point[0],
        end_character=node.end_point[1],
    )


def _node_text(node: Node) -> str:
    text = node.text
    if text is None:
        raise ValueError(f"node {node.type!r} does not have backing source text")
    return text.decode("utf-8")


def _word_children(node: Node | None) -> tuple[str, ...]:
    if node is None:
        return ()
    return tuple(_node_text(child) for child in node.named_children if child.type == "word")


def _recipe_error_span(recipe_line: RecipeLine, error_node: Node) -> Span:
    relative = _span_from_node(error_node)

    start_character = relative.start_character
    end_character = relative.end_character
    if relative.start_line == 0:
        start_character += recipe_line.span.start_character + recipe_line.prefix_length
    if relative.end_line == 0:
        end_character += recipe_line.span.start_character + recipe_line.prefix_length

    return Span(
        start_line=recipe_line.span.start_line + relative.start_line,
        start_character=start_character,
        end_line=recipe_line.span.start_line + relative.end_line,
        end_character=end_character,
    )


def _diagnostic_message(prefix: str, snippet: str) -> str:
    compact_snippet = " ".join(snippet.split())
    if compact_snippet == "":
        return prefix

    if len(compact_snippet) > 40:
        compact_snippet = compact_snippet[:37] + "..."
    return f"{prefix} near `{compact_snippet}`"


def _render_target_hover(definition: TargetDefinition, definition_count: int) -> str:
    lines = [f"```make\n{definition.name}\n```"]
    if definition.prerequisites:
        lines.append(f"Prerequisites: {', '.join(definition.prerequisites)}")
    if definition.recipe_preview is not None:
        lines.append(f"Recipe: `{definition.recipe_preview}`")
    if definition_count > 1:
        lines.append(f"Definitions in document: {definition_count}")
    return "\n\n".join(lines)


def _render_variable_hover(definition: VariableDefinition) -> str:
    lines = [f"```make\n{definition.name} {definition.operator} {definition.value}\n```"]
    if definition.value != "":
        lines.append(f"Value: `{definition.value}`")
    return "\n\n".join(lines)
