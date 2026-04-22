from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lsprotocol import types as lsp

SymbolKind = Literal["target", "variable"]
SymbolRole = Literal["definition", "reference"]


@dataclass(frozen=True, slots=True)
class Span:
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
class TargetDefinition:
    name: str
    name_span: Span
    rule_span: Span
    prerequisites: tuple[str, ...]
    rule_text: str
    recipe_text: str | None


@dataclass(frozen=True, slots=True)
class VariableDefinition:
    name: str
    name_span: Span
    assignment_span: Span
    operator: str
    value: str
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolOccurrence:
    kind: SymbolKind
    role: SymbolRole
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class RecipeLine:
    span: Span
    raw_text: str
    command_text: str
    prefix_length: int


@dataclass(frozen=True, slots=True)
class AnalyzedDocument:
    uri: str
    version: int | None
    targets: dict[str, tuple[TargetDefinition, ...]]
    variables: dict[str, tuple[VariableDefinition, ...]]
    includes: tuple[str, ...]
    phony_targets: frozenset[str]
    occurrences: tuple[SymbolOccurrence, ...]
    diagnostics: tuple[lsp.Diagnostic, ...]

    def occurrence_at(self, line: int, character: int) -> SymbolOccurrence | None:
        for occurrence in self.occurrences:
            if occurrence.span.contains(line, character):
                return occurrence
        return None
