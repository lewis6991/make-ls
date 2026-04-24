"""Warn on prerequisite references that resolve to neither targets nor files."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from make_ls.builtin_docs import SPECIAL_TARGET_DOCS

from .base import DiagnosticChecker
from .common import (
    diagnostic_message,
    included_target_names,
    matches_target_names,
    prerequisite_exists,
    uri_base_directory,
)

if TYPE_CHECKING:
    from .base import DiagnosticContext

UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE = 'unresolved-prerequisite'


@final
class UnresolvedPrerequisiteChecker(DiagnosticChecker):
    CODE = UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        base_directory = uri_base_directory(context.uri)
        included_targets: tuple[frozenset[str], frozenset[str]] | None = None
        for occurrence in context.occurrences:
            if occurrence.kind != 'target' or occurrence.role != 'reference':
                continue
            if occurrence.context is None or occurrence.context.kind != 'prerequisite':
                continue
            if not _should_warn_for_unresolved_prerequisite(occurrence.name):
                continue
            if (
                matches_target_names(occurrence.name, context.target_names)
                or occurrence.name in context.phony_targets
            ):
                continue
            if base_directory is not None and prerequisite_exists(base_directory, occurrence.name):
                continue
            if base_directory is not None and context.include_patterns:
                if included_targets is None:
                    included_targets = included_target_names(
                        base_directory,
                        context.include_patterns,
                    )
                if (
                    matches_target_names(occurrence.name, included_targets[0])
                    or occurrence.name in included_targets[1]
                ):
                    continue

            diagnostics.append(
                self.emit(
                    diagnostic_range=occurrence.span.to_lsp_range(),
                    message=diagnostic_message('Unresolved prerequisite', occurrence.name),
                )
            )
        return diagnostics


def _should_warn_for_unresolved_prerequisite(name: str) -> bool:
    if name in SPECIAL_TARGET_DOCS:
        return False
    return not any(character in name for character in '%*?[]$()')
