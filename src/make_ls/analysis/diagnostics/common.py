"""Shared helpers for recovered-model diagnostics."""

from __future__ import annotations

from pathlib import Path

from lsprotocol import types as lsp
from pygls.uris import to_fs_path

from make_ls.analysis.recovery import (
    CONDITIONAL_DIRECTIVES,
    declared_phony_targets,
    has_unescaped_line_continuation,
    recover_include_directives,
    recover_rules,
    recover_variable_assignments,
    slice_source_lines,
)
from make_ls.types import Span

SOURCE = 'make-ls'


def diagnostic_message(prefix: str, snippet: str) -> str:
    compact_snippet = ' '.join(snippet.split())
    if compact_snippet == '':
        return prefix

    if len(compact_snippet) > 40:
        compact_snippet = compact_snippet[:37] + '...'
    return f'{prefix}: `{compact_snippet}`'


def make_syntax_diagnostic(
    source_lines: list[str],
    start_line: int,
    end_line: int,
    *,
    code: str,
) -> lsp.Diagnostic:
    return lsp.Diagnostic(
        range=Span(start_line, 0, end_line, len(source_lines[end_line])).to_lsp_range(),
        message=diagnostic_message(
            'Invalid Makefile syntax',
            slice_source_lines(
                source_lines,
                start_line=start_line,
                start_character=0,
                end_line=end_line,
                end_character=len(source_lines[end_line]),
            ),
        ),
        code=code,
        severity=lsp.DiagnosticSeverity.Error,
        source=SOURCE,
    )


def block_diagnostic(
    source_lines: list[str],
    start_line: int,
    end_line: int,
    *,
    message: str,
    code: str,
) -> lsp.Diagnostic:
    return lsp.Diagnostic(
        range=Span(start_line, 0, end_line, len(source_lines[end_line])).to_lsp_range(),
        message=message,
        code=code,
        severity=lsp.DiagnosticSeverity.Error,
        source=SOURCE,
    )


def uri_base_directory(uri: str) -> Path | None:
    path = to_fs_path(uri)
    if path is None:
        return None
    return Path(path).parent


def logical_top_level_text(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> str:
    parts: list[str] = []
    for line_number in range(start_line, end_line + 1):
        text = strip_make_comment(source_lines[line_number]).strip()
        if line_number < end_line and has_unescaped_line_continuation(text):
            text = text[:-1].rstrip()
        if text != '':
            parts.append(text)
    return ' '.join(parts)


def strip_make_comment(text: str) -> str:
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == '\\':
            escaped = True
            continue
        if character == '#':
            return text[:index]
    return text


def is_else_if_branch(remainder: str) -> bool:
    next_token = remainder.strip().split(maxsplit=1)
    return bool(next_token) and next_token[0] in CONDITIONAL_DIRECTIVES


def is_static_include_pattern(include_pattern: str) -> bool:
    return (
        '$(' not in include_pattern
        and '${' not in include_pattern
        and not any(character in include_pattern for character in '*?[]')
    )


def static_include_path(base_directory: Path | None, include_pattern: str) -> Path | None:
    if not is_static_include_pattern(include_pattern):
        return None

    candidate_path = Path(include_pattern)
    if candidate_path.is_absolute():
        return candidate_path
    if base_directory is None:
        return None
    return base_directory / include_pattern


def resolved_static_include_paths(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for include_pattern in include_patterns:
        candidate_path = static_include_path(base_directory, include_pattern)
        if candidate_path is None:
            continue
        if candidate_path.is_file():
            resolved_paths.append(candidate_path)

    return tuple(resolved_paths)


def prerequisite_exists(base_directory: Path, name: str) -> bool:
    candidate_path = Path(name) if Path(name).is_absolute() else base_directory / name
    try:
        return candidate_path.exists()
    except OSError:
        return False


def matches_target_names(name: str, target_names: set[str] | frozenset[str]) -> bool:
    return any(matches_target_name(name, target_name) for target_name in target_names)


def matches_target_name(name: str, target_name: str) -> bool:
    if '%' not in target_name:
        return name == target_name

    prefix, _, suffix = target_name.partition('%')
    return (
        name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix) + len(suffix)
    )


def included_target_names(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[frozenset[str], frozenset[str]]:
    targets: set[str] = set()
    phony_targets: set[str] = set()
    seen_paths: set[Path] = set()
    for path in resolved_static_include_paths(base_directory, include_patterns):
        _extend_included_target_names(path, seen_paths, targets, phony_targets)
    return frozenset(targets), frozenset(phony_targets)


def included_variable_names(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> frozenset[str]:
    variable_names: set[str] = set()
    seen_paths: set[Path] = set()
    for path in resolved_static_include_paths(base_directory, include_patterns):
        _extend_included_variable_names(path, seen_paths, variable_names)
    return frozenset(variable_names)


def _extend_included_target_names(
    path: Path,
    seen_paths: set[Path],
    targets: set[str],
    phony_targets: set[str],
) -> None:
    resolved_path = path.resolve()
    if resolved_path in seen_paths:
        return
    seen_paths.add(resolved_path)

    try:
        source_lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return

    rule_recovery = recover_rules(source_lines, {})
    targets.update(definition.name for definition in rule_recovery.definitions)
    phony_targets.update(declared_phony_targets(rule_recovery.definitions))

    include_recovery = recover_include_directives(source_lines)
    for include_path in resolved_static_include_paths(
        path.parent,
        tuple(include.path for include in include_recovery.includes),
    ):
        _extend_included_target_names(include_path, seen_paths, targets, phony_targets)


def _extend_included_variable_names(
    path: Path,
    seen_paths: set[Path],
    variable_names: set[str],
) -> None:
    resolved_path = path.resolve()
    if resolved_path in seen_paths:
        return
    seen_paths.add(resolved_path)

    try:
        source_lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return

    assignment_recovery = recover_variable_assignments(source_lines, {})
    variable_names.update(definition.name for definition in assignment_recovery.definitions)

    include_recovery = recover_include_directives(source_lines)
    for include_path in resolved_static_include_paths(
        path.parent,
        tuple(include.path for include in include_recovery.includes),
    ):
        _extend_included_variable_names(include_path, seen_paths, variable_names)
