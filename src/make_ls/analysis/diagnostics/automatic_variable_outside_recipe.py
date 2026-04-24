"""Warn when automatic variables appear outside safe recipe contexts."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from make_ls.analysis.recovery import slice_text_span

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from make_ls.types import SymCtx

    from .base import DiagnosticContext


@final
class AutomaticVariableOutsideRecipeChecker(DiagnosticChecker):
    CODE = 'automatic-variable-outside-recipe'
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        for occurrence in context.occurrences:
            if occurrence.kind != 'variable' or occurrence.role != 'reference':
                continue
            if not _is_make_automatic_variable_name(occurrence.name):
                continue
            if not _should_warn_for_automatic_variable(occurrence.context):
                continue

            diagnostics.append(
                self.emit(
                    diagnostic_range=occurrence.span.to_lsp_range(),
                    message=diagnostic_message(
                        'Automatic variable outside recipe context',
                        slice_text_span(context.source, occurrence.span),
                    ),
                )
            )
        return diagnostics


def _should_warn_for_automatic_variable(context: SymCtx | None) -> bool:
    if context is None:
        return True
    if context.kind == 'recipe':
        return False
    # `.SECONDEXPANSION` can make automatic variables valid in prerequisites,
    # so keep this warning focused on contexts that are reliably suspicious.
    return context.kind != 'prerequisite'


def _is_make_automatic_variable_name(name: str) -> bool:
    if name == '':
        return False
    if name[0] not in '@%<?^+*|':
        return False
    return name[1:] in {'', 'D', 'F'}
