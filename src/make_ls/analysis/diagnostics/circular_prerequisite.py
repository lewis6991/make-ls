"""Detect circular prerequisite graphs among recovered targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from collections import defaultdict

    from make_ls.types import TargetDef

    from .base import DiagnosticContext


@final
class CircularPrerequisiteChecker(DiagnosticChecker):
    CODE = 'circular-prerequisite'
    SEVERITY = lsp.DiagnosticSeverity.Warning

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        graph = _target_dependency_graph(context.target_map)
        reverse_graph = _reverse_target_dependency_graph(graph)
        diagnostics: list[lsp.Diagnostic] = []
        seen_components: set[frozenset[str]] = set()

        for name in graph:
            component = frozenset(
                _reachable_targets(graph, name) & _reachable_targets(reverse_graph, name)
            )
            if component in seen_components:
                continue
            seen_components.add(component)

            if len(component) == 1 and name not in graph[name]:
                continue

            anchor = min(component)
            message = (
                diagnostic_message('Circular prerequisite', anchor)
                if len(component) == 1
                else diagnostic_message('Circular prerequisite cycle', ', '.join(sorted(component)))
            )
            diagnostics.append(
                self.emit(
                    diagnostic_range=context.target_map[anchor][0].name_span.to_lsp_range(),
                    message=message,
                )
            )

        return diagnostics


def _target_dependency_graph(
    target_map: dict[str, tuple[TargetDef, ...]] | defaultdict[str, list[TargetDef]],
) -> dict[str, tuple[str, ...]]:
    target_names = set(target_map)
    graph: dict[str, tuple[str, ...]] = {}
    for name, definitions in target_map.items():
        prerequisites: list[str] = []
        seen: set[str] = set()
        for definition in definitions:
            for prerequisite in definition.prerequisites:
                if prerequisite not in target_names or prerequisite in seen:
                    continue
                seen.add(prerequisite)
                prerequisites.append(prerequisite)
        graph[name] = tuple(prerequisites)
    return graph


def _reverse_target_dependency_graph(
    graph: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    reversed_edges: dict[str, list[str]] = {name: [] for name in graph}
    for source, prerequisites in graph.items():
        for prerequisite in prerequisites:
            reversed_edges[prerequisite].append(source)
    return {name: tuple(prerequisites) for name, prerequisites in reversed_edges.items()}


def _reachable_targets(
    graph: dict[str, tuple[str, ...]],
    start: str,
) -> set[str]:
    seen = {start}
    pending = [start]
    while pending:
        current = pending.pop()
        for neighbor in graph.get(current, ()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            pending.append(neighbor)
    return seen
