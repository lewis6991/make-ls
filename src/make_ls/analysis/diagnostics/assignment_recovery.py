"""Expose assignment-recovery diagnostics through the checker runner."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from make_ls.analysis.recovery import INVALID_VARIABLE_REFERENCE_IN_ASSIGNMENT_DIAGNOSTIC_CODE

from .base import DiagnosticChecker

if TYPE_CHECKING:
    from lsprotocol import types as lsp

    from .base import DiagnosticContext


@final
class AssignmentRecoveryChecker(DiagnosticChecker):
    CODE = INVALID_VARIABLE_REFERENCE_IN_ASSIGNMENT_DIAGNOSTIC_CODE

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        return list(context.assignment_diagnostics)
