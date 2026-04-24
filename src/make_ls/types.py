"""Shared recovered document model for the analyzer, CLI, and LSP server.

`AnalyzedDoc` is the main seam in the codebase. Features are expected to read
recovered structure from this model instead of reparsing source text on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lsprotocol import types as lsp

FormKind = Literal['assignment', 'conditional', 'rule']
SymKind = Literal['target', 'variable']
SymRole = Literal['definition', 'reference']
SymCtxKind = Literal[
    'assignment_definition',
    'assignment_value',
    'conditional_test',
    'prerequisite',
    'recipe',
    'target_definition',
]
VarGuardKind = Literal['defined', 'empty', 'nonempty', 'undefined']


@dataclass(frozen=True, slots=True)
class Span:
    """Half-open source range used by recovered data and LSP responses."""

    start_line: int
    start_character: int
    end_line: int
    end_character: int

    def contains(self, line: int, character: int) -> bool:
        if (line, character) < (self.start_line, self.start_character):
            return False
        return (line, character) < (self.end_line, self.end_character)

    def to_lsp_range(self) -> lsp.Range:
        return lsp.Range(
            start=lsp.Position(line=self.start_line, character=self.start_character),
            end=lsp.Position(line=self.end_line, character=self.end_character),
        )


@dataclass(frozen=True, slots=True)
class TargetDef:
    """Recovered target definition from a Make rule header."""

    name: str
    name_span: Span
    rule_span: Span
    prerequisites: tuple[str, ...]
    rule_text: str
    recipe_text: str | None
    is_double_colon: bool = False


@dataclass(frozen=True, slots=True)
class VarDef:
    """Recovered variable assignment plus any attached comment documentation."""

    name: str
    name_span: Span
    assignment_span: Span
    operator: str
    value: str
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class VarGuard:
    """Simple variable guard inferred from a top-level conditional branch."""

    name: str
    kind: VarGuardKind


@dataclass(frozen=True, slots=True)
class SymCtx:
    """Local form and guard context for a recovered symbol occurrence."""

    form_kind: FormKind
    kind: SymCtxKind
    active_guards: tuple[VarGuard, ...] = ()


@dataclass(frozen=True, slots=True)
class DocForm:
    """Recovered top-level form span used by diagnostics and fixes."""

    kind: FormKind
    span: Span


@dataclass(frozen=True, slots=True)
class SymOcc:
    """Recovered target or variable occurrence consumed by editor features."""

    kind: SymKind
    role: SymRole
    name: str
    span: Span
    context: SymCtx | None = None


@dataclass(frozen=True, slots=True)
class RecipeLine:
    """Recipe line with both raw source text and shell-check command text."""

    span: Span
    raw_text: str
    command_text: str
    prefix_length: int
    rule_start_line: int


@dataclass(frozen=True, slots=True)
class AnalyzedDoc:
    """Single-file analysis snapshot shared across diagnostics and LSP features."""

    uri: str
    version: int | None
    targets: dict[str, tuple[TargetDef, ...]]
    variables: dict[str, tuple[VarDef, ...]]
    includes: tuple[str, ...]
    phony_targets: frozenset[str]
    occurrences: tuple[SymOcc, ...]
    forms: tuple[DocForm, ...]
    diagnostics: tuple[lsp.Diagnostic, ...]

    def occurrence_at(self, line: int, character: int) -> SymOcc | None:
        """Return the recovered occurrence covering a source position, if any."""
        for occurrence in self.occurrences:
            if occurrence.span.contains(line, character):
                return occurrence
        return None
