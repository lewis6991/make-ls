"""Recovered-model diagnostics split into small focused passes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .assignment_recovery import AssignmentRecoveryChecker
from .automatic_variable_outside_recipe import AutomaticVariableOutsideRecipeChecker
from .circular_prerequisite import CircularPrerequisiteChecker
from .control_blocks import ControlBlockChecker
from .make_syntax import MakeSyntaxChecker
from .overriding_recipe import OverridingRecipeChecker
from .shell_syntax import ShellSyntaxChecker
from .unknown_variable import UnknownVariableChecker
from .unresolved_include import UnresolvedIncludeChecker
from .unresolved_prerequisite import UnresolvedPrerequisiteChecker

if TYPE_CHECKING:
    from lsprotocol import types as lsp

    from .base import DiagnosticContext

_DIAGNOSTIC_CHECKERS = (
    ControlBlockChecker(),
    MakeSyntaxChecker(),
    AssignmentRecoveryChecker(),
    UnknownVariableChecker(),
    AutomaticVariableOutsideRecipeChecker(),
    UnresolvedIncludeChecker(),
    UnresolvedPrerequisiteChecker(),
    OverridingRecipeChecker(),
    CircularPrerequisiteChecker(),
    ShellSyntaxChecker(),
)


def collect_diagnostics(context: DiagnosticContext) -> tuple[lsp.Diagnostic, ...]:
    diagnostics: list[lsp.Diagnostic] = []
    for checker in _DIAGNOSTIC_CHECKERS:
        diagnostics.extend(checker.check(context))
    return tuple(diagnostics)
