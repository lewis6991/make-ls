"""Warn for missing static includes that are not remade by local targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from .base import DiagnosticChecker
from .common import (
    included_target_names,
    is_static_include_pattern,
    matches_target_names,
    static_include_path,
    uri_base_directory,
)

if TYPE_CHECKING:
    from .base import DiagnosticContext


@final
class UnresolvedIncludeChecker(DiagnosticChecker):
    CODE = 'unresolved-include'
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        diagnostics: list[lsp.Diagnostic] = []
        base_directory = uri_base_directory(context.uri)
        included_targets: tuple[frozenset[str], frozenset[str]] | None = None

        for include in context.includes:
            if include.optional or not is_static_include_pattern(include.path):
                continue

            if matches_target_names(include.path, context.target_names):
                continue

            candidate_path = static_include_path(base_directory, include.path)
            if candidate_path is None:
                continue
            try:
                if candidate_path.exists():
                    continue
            except OSError:
                continue

            if base_directory is not None and context.include_patterns:
                if included_targets is None:
                    included_targets = included_target_names(
                        base_directory,
                        context.include_patterns,
                    )
                # GNU Make can remake missing include files from ordinary targets.
                if matches_target_names(include.path, included_targets[0]):
                    continue

            diagnostics.append(
                self.emit(
                    diagnostic_range=include.span.to_lsp_range(),
                    message=f'Unresolved include: `{include.path}`',
                )
            )

        return diagnostics
