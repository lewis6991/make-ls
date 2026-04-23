from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ._analysis_diagnostics import (
    UNKNOWN_VARIABLE_DIAGNOSTIC_CODE,
    UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE,
    UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE,
    collect_automatic_variable_diagnostics,
    collect_circular_prerequisite_diagnostics,
    collect_control_block_diagnostics,
    collect_make_syntax_diagnostics,
    collect_overriding_recipe_diagnostics,
    collect_shell_diagnostics,
    collect_unknown_variable_diagnostics,
    collect_unresolved_include_diagnostics,
    collect_unresolved_prerequisite_diagnostics,
)
from ._analysis_hover import hover_for_pos
from ._analysis_navigation import (
    def_for_pos,
    prep_rename_for_pos,
    refs_for_pos,
    rename_var_for_pos,
    resolve_variable_definition,
)
from ._analysis_recovery import (
    declared_phony_targets,
    recover_conditionals,
    recover_include_directives,
    recover_rules,
    recover_variable_assignments,
)
from .types import AnalyzedDoc

if TYPE_CHECKING:
    from .types import SymOcc, TargetDef, VarDef

__all__ = [
    'UNKNOWN_VARIABLE_DIAGNOSTIC_CODE',
    'UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE',
    'UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE',
    'analyze_document',
    'def_for_pos',
    'hover_for_pos',
    'prep_rename_for_pos',
    'refs_for_pos',
    'rename_var_for_pos',
    'resolve_variable_definition',
]


def analyze_document(
    uri: str,
    version: int | None,
    source: str,
    *,
    include_shell_diagnostics: bool = True,
) -> AnalyzedDoc:
    source_lines = source.splitlines()
    target_map: defaultdict[str, list[TargetDef]] = defaultdict(list)
    variable_map: defaultdict[str, list[VarDef]] = defaultdict(list)
    phony_targets: set[str] = set()
    occurrences: list[SymOcc] = []

    conditional_recovery = recover_conditionals(source_lines)
    include_recovery = recover_include_directives(source_lines)
    rule_recovery = recover_rules(source_lines, conditional_recovery.line_guards)
    assignment_recovery = recover_variable_assignments(
        source_lines,
        conditional_recovery.line_guards,
    )

    for definition in rule_recovery.definitions:
        _record_target_def(target_map, definition)
    for definition in assignment_recovery.definitions:
        _record_var_def(variable_map, definition)

    phony_targets.update(declared_phony_targets(rule_recovery.definitions))
    _record_occs(occurrences, conditional_recovery.occurrences)
    _record_occs(occurrences, include_recovery.occurrences)
    _record_occs(occurrences, rule_recovery.occurrences)
    _record_occs(occurrences, assignment_recovery.occurrences)

    target_names = set(target_map)
    include_patterns = tuple(include.path for include in include_recovery.includes)

    control_block_diagnostics = collect_control_block_diagnostics(source_lines)
    make_diagnostics = collect_make_syntax_diagnostics(
        source_lines,
        parsed_lines=(
            rule_recovery.parsed_lines
            | assignment_recovery.parsed_lines
            | include_recovery.parsed_lines
        ),
    )
    unknown_variable_diagnostics = collect_unknown_variable_diagnostics(
        source,
        variable_map,
        occurrences,
        rule_recovery.recipe_lines,
    )
    automatic_variable_diagnostics = collect_automatic_variable_diagnostics(source, occurrences)
    unresolved_include_diagnostics = collect_unresolved_include_diagnostics(
        uri,
        include_recovery.includes,
        target_names,
    )
    unresolved_prerequisite_diagnostics = collect_unresolved_prerequisite_diagnostics(
        uri,
        occurrences,
        target_names,
        phony_targets,
        include_patterns,
    )
    overriding_recipe_diagnostics = collect_overriding_recipe_diagnostics(target_map)
    circular_prerequisite_diagnostics = collect_circular_prerequisite_diagnostics(target_map)
    shell_diagnostics = (
        collect_shell_diagnostics(rule_recovery.recipe_lines) if include_shell_diagnostics else []
    )

    return AnalyzedDoc(
        uri=uri,
        version=version,
        targets={name: tuple(definitions) for name, definitions in target_map.items()},
        variables={name: tuple(definitions) for name, definitions in variable_map.items()},
        includes=include_patterns,
        phony_targets=frozenset(phony_targets),
        occurrences=tuple(occurrences),
        forms=(
            *conditional_recovery.forms,
            *rule_recovery.forms,
            *assignment_recovery.forms,
        ),
        diagnostics=(
            *control_block_diagnostics,
            *make_diagnostics,
            *assignment_recovery.diagnostics,
            *unknown_variable_diagnostics,
            *automatic_variable_diagnostics,
            *unresolved_include_diagnostics,
            *unresolved_prerequisite_diagnostics,
            *overriding_recipe_diagnostics,
            *circular_prerequisite_diagnostics,
            *shell_diagnostics,
        ),
    )


def _record_var_def(
    variable_map: defaultdict[str, list[VarDef]],
    definition: VarDef,
) -> None:
    if any(
        existing.name_span == definition.name_span for existing in variable_map[definition.name]
    ):
        return
    variable_map[definition.name].append(definition)


def _record_target_def(
    target_map: defaultdict[str, list[TargetDef]],
    definition: TargetDef,
) -> None:
    if any(existing.name_span == definition.name_span for existing in target_map[definition.name]):
        return
    target_map[definition.name].append(definition)


def _record_occs(
    occurrences: list[SymOcc],
    new_occurrences: tuple[SymOcc, ...],
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
