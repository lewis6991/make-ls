"""Warn when later single-colon rules replace an earlier recipe."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from .base import DiagnosticContext

MIXED_RULE_SEPARATOR_DIAGNOSTIC_CODE = 'mixed-rule-separator'


@final
class OverridingRecipeChecker(DiagnosticChecker):
    CODE = 'overriding-recipe'
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        for name, definitions in context.target_map.items():
            if not definitions:
                continue

            first_separator_is_double_colon = definitions[0].is_double_colon
            mixed_rule_definitions = [
                definition
                for definition in definitions[1:]
                if definition.is_double_colon != first_separator_is_double_colon
            ]
            if mixed_rule_definitions:
                diagnostics.extend(
                    self.emit(
                        diagnostic_range=definition.name_span.to_lsp_range(),
                        message=diagnostic_message('Target has both : and :: rules', name),
                        code=MIXED_RULE_SEPARATOR_DIAGNOSTIC_CODE,
                        severity=lsp.DiagnosticSeverity.Error,
                    )
                    for definition in mixed_rule_definitions
                )
                continue

            if definitions[0].is_double_colon:
                continue

            recipe_definitions = [
                definition for definition in definitions if definition.recipe_text
            ]
            diagnostics.extend(
                self.emit(
                    diagnostic_range=definition.name_span.to_lsp_range(),
                    message=diagnostic_message('Overriding recipe for target', name),
                )
                for definition in recipe_definitions[1:]
            )
        return diagnostics
