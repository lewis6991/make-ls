"""Shared checker protocol for recovered-model diagnostics."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, final

from lsprotocol import types as lsp

if TYPE_CHECKING:
    from make_ls.analysis.recovery import RecoveredInclude
    from make_ls.types import RecipeLine, SymOcc, TargetDef, VarDef

SOURCE = 'make-ls'


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    uri: str
    source: str
    source_lines: list[str]
    target_map: dict[str, tuple[TargetDef, ...]]
    variable_map: dict[str, tuple[VarDef, ...]]
    target_names: frozenset[str]
    phony_targets: frozenset[str]
    occurrences: tuple[SymOcc, ...]
    includes: tuple[RecoveredInclude, ...]
    include_patterns: tuple[str, ...]
    parsed_lines: frozenset[int]
    recipe_lines: tuple[RecipeLine, ...]
    assignment_diagnostics: tuple[lsp.Diagnostic, ...]
    include_shell_diagnostics: bool


class DiagnosticChecker(ABC):
    CODE: ClassVar[str | None] = None
    SEVERITY: ClassVar[lsp.DiagnosticSeverity] = lsp.DiagnosticSeverity.Warning

    @abstractmethod
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        raise NotImplementedError

    @final
    def emit(
        self,
        *,
        diagnostic_range: lsp.Range,
        message: str,
        code: str | None = None,
        severity: lsp.DiagnosticSeverity | None = None,
    ) -> lsp.Diagnostic:
        diagnostic_code = self.CODE if code is None else code
        if diagnostic_code is None:
            raise ValueError('diagnostic code is required')
        return lsp.Diagnostic(
            range=diagnostic_range,
            message=message,
            code=diagnostic_code,
            severity=self.SEVERITY if severity is None else severity,
            source=SOURCE,
        )
