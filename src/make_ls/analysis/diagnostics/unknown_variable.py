"""Warn on unresolved variable references that are not context-suppressed."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from make_ls.analysis.recovery import ASSIGNMENT_RE, RECIPE_LOCAL_EVAL_RE, slice_text_span
from make_ls.builtin_docs import BUILTIN_VARIABLE_DOCS

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from make_ls.types import RecipeLine, SymCtx

    from .base import DiagnosticContext

UNKNOWN_VARIABLE_DIAGNOSTIC_CODE = 'unknown-variable'


@final
class UnknownVariableChecker(DiagnosticChecker):
    CODE = UNKNOWN_VARIABLE_DIAGNOSTIC_CODE
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        recipe_local_variables = _recipe_local_eval_variables(context.recipe_lines)
        for occurrence in context.occurrences:
            if occurrence.kind != 'variable' or occurrence.role != 'reference':
                continue
            if occurrence.name in context.variable_map:
                continue
            if (
                occurrence.context is not None
                and occurrence.context.kind == 'recipe'
                and occurrence.name in recipe_local_variables.get(occurrence.span.start_line, ())
            ):
                continue
            occurrence_text = slice_text_span(context.source, occurrence.span)
            if not _should_warn_for_unknown_variable(
                occurrence.name,
                occurrence_text,
                occurrence.context,
            ):
                continue

            diagnostics.append(
                self.emit(
                    diagnostic_range=occurrence.span.to_lsp_range(),
                    message=diagnostic_message('Unknown variable reference', occurrence_text),
                )
            )
        return diagnostics


def _recipe_local_eval_assignment_name(command_text: str) -> str | None:
    match = RECIPE_LOCAL_EVAL_RE.match(command_text.strip())
    if match is None:
        return None

    assignment_match = ASSIGNMENT_RE.match(match.group('assignment').strip())
    if assignment_match is None:
        return None
    return assignment_match.group('name')


def _recipe_local_eval_variables(
    recipe_lines: tuple[RecipeLine, ...],
) -> dict[int, frozenset[str]]:
    variables_by_line: dict[int, frozenset[str]] = {}
    current_rule_start_line: int | None = None
    current_variables: set[str] = set()

    for recipe_line in recipe_lines:
        if recipe_line.rule_start_line != current_rule_start_line:
            current_rule_start_line = recipe_line.rule_start_line
            current_variables = set()

        variables_by_line[recipe_line.span.start_line] = frozenset(current_variables)
        assignment_name = _recipe_local_eval_assignment_name(recipe_line.command_text)
        if assignment_name is not None:
            current_variables.add(assignment_name)

    return variables_by_line


def _should_warn_for_unknown_variable(
    name: str,
    occurrence_text: str,
    context: SymCtx | None,
) -> bool:
    if name.isdigit():
        return False
    if occurrence_text.startswith('${'):
        return False
    if '$(' in name or '${' in name:
        return False
    if name in BUILTIN_VARIABLE_DOCS:
        return False
    if _is_make_automatic_variable_name(name):
        return False
    if context is not None:
        if context.kind == 'conditional_test':
            return False
        # Only suppress when the active guard proves this exact variable is
        # present. That keeps typoed guard names warning while allowing guarded
        # uses such as `ifneq ($(VAR),)` then `$(VAR)`.
        if any(
            guard.name == name and guard.kind in {'defined', 'nonempty'}
            for guard in context.active_guards
        ):
            return False
    return name not in os.environ


def _is_make_automatic_variable_name(name: str) -> bool:
    if name == '':
        return False
    if name[0] not in '@%<?^+*|':
        return False
    return name[1:] in {'', 'D', 'F'}
