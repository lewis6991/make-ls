"""Warn when later single-colon rules replace an earlier recipe."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from .base import DiagnosticContext


@final
class OverridingRecipeChecker(DiagnosticChecker):
    CODE = 'overriding-recipe'
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        for name, definitions in context.target_map.items():
            if any(definition.is_double_colon for definition in definitions):
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
