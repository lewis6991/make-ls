"""Recovery-first analysis pipeline shared by the CLI and LSP server.

The pipeline stays deliberately flat:

1. split the source into lines
2. recover conditionals, includes, rules, and variable assignments
3. build shared target, variable, and occurrence maps
4. run diagnostic passes over the recovered model
5. return one `AnalyzedDoc` snapshot for downstream features
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from make_ls.types import AnalyzedDoc

from .diagnostics import collect_diagnostics
from .diagnostics.base import DiagnosticContext
from .recovery import (
    declared_phony_targets,
    recover_conditionals,
    recover_include_directives,
    recover_rules,
    recover_variable_assignments,
)

if TYPE_CHECKING:
    from make_ls.types import SymOcc, TargetDef, VarDef

__all__ = ['analyze_document']


def analyze_document(
    uri: str,
    version: int | None,
    source: str,
    *,
    include_shell_diagnostics: bool = True,
) -> AnalyzedDoc:
    """Recover one Makefile into an `AnalyzedDoc` and all derived diagnostics."""
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

    targets = {name: tuple(definitions) for name, definitions in target_map.items()}
    variables = {name: tuple(definitions) for name, definitions in variable_map.items()}
    target_names = frozenset(targets)
    phony_target_names = frozenset(phony_targets)
    document_occurrences = tuple(occurrences)
    include_patterns = tuple(include.path for include in include_recovery.includes)
    parsed_lines = frozenset(
        rule_recovery.parsed_lines
        | assignment_recovery.parsed_lines
        | include_recovery.parsed_lines
    )
    diagnostic_context = DiagnosticContext(
        uri=uri,
        source=source,
        source_lines=source_lines,
        target_map=targets,
        variable_map=variables,
        target_names=target_names,
        phony_targets=phony_target_names,
        occurrences=document_occurrences,
        includes=include_recovery.includes,
        include_patterns=include_patterns,
        parsed_lines=parsed_lines,
        recipe_lines=rule_recovery.recipe_lines,
        assignment_diagnostics=assignment_recovery.diagnostics,
        include_shell_diagnostics=include_shell_diagnostics,
    )
    diagnostics = collect_diagnostics(diagnostic_context)

    return AnalyzedDoc(
        uri=uri,
        version=version,
        targets=targets,
        variables=variables,
        includes=include_patterns,
        phony_targets=phony_target_names,
        occurrences=document_occurrences,
        forms=(
            *conditional_recovery.forms,
            *rule_recovery.forms,
            *assignment_recovery.forms,
        ),
        diagnostics=diagnostics,
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
