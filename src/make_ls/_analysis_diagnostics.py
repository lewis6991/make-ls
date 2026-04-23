from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from lsprotocol import types as lsp
from pygls.uris import to_fs_path

from . import _analysis_recovery as recovery
from .builtin_docs import BUILTIN_VARIABLE_DOCS, SPECIAL_TARGET_DOCS
from .types import RecipeLine, Span, SymCtx, SymOcc, VarDef

MAKE_AUTOMATIC_VARIABLE_RE = re.compile(
    r"\$\(([@%<?^+*|][DF]?)\)|\$\{([@%<?^+*|][DF]?)\}|\$([@%<?^+*|])"
)
UNKNOWN_VARIABLE_DIAGNOSTIC_CODE = "unknown-variable"
UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE = "unresolved-include"
UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE = "unresolved-prerequisite"


def collect_shell_diagnostics(recipe_lines: tuple[RecipeLine, ...]) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    for recipe_group in _logical_recipe_lines(recipe_lines):
        command_text = "\n".join(line.command_text for line in recipe_group)
        if command_text.strip() == "":
            continue

        is_valid = _shell_syntax_is_valid(command_text)
        if is_valid is None or is_valid:
            continue

        first_line = recipe_group[0]
        diagnostics.append(
            lsp.Diagnostic(
                range=Span(
                    first_line.span.start_line,
                    first_line.prefix_length,
                    first_line.span.start_line,
                    len(first_line.raw_text),
                ).to_lsp_range(),
                message=_diagnostic_message("Invalid shell syntax in recipe", command_text),
                severity=lsp.DiagnosticSeverity.Error,
                source="make-ls",
            )
        )

    return diagnostics


def collect_make_syntax_diagnostics(
    source_lines: list[str],
    *,
    parsed_lines: frozenset[int],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    in_define_block = False
    line_number = 0
    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if line_number in parsed_lines or stripped == "" or stripped.startswith("#"):
            line_number += 1
            continue

        if recovery.starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue

        if in_define_block:
            if stripped == "endef":
                in_define_block = False
            line_number += 1
            continue

        if line.startswith("\t"):
            diagnostics.append(_make_syntax_diagnostic(source_lines, line_number, line_number))
            line_number += 1
            continue

        if recovery.continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        logical_end_line = recovery.logical_top_level_end(source_lines, line_number)
        # The owned parser does not model directives or eager top-level function
        # calls, but they are valid Make syntax and should not produce noise.
        if _is_tolerated_top_level_line(stripped):
            line_number = logical_end_line + 1
            continue

        diagnostics.append(_make_syntax_diagnostic(source_lines, line_number, logical_end_line))
        line_number = logical_end_line + 1

    return diagnostics


def collect_unknown_variable_diagnostics(
    source: str,
    variable_map: dict[str, list[VarDef]] | defaultdict[str, list[VarDef]],
    occurrences: list[SymOcc],
    recipe_lines: tuple[RecipeLine, ...],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    recipe_local_variables = _recipe_local_eval_variables(recipe_lines)
    for occurrence in occurrences:
        if occurrence.kind != "variable" or occurrence.role != "reference":
            continue
        if occurrence.name in variable_map:
            continue
        if (
            occurrence.context is not None
            and occurrence.context.kind == "recipe"
            and occurrence.name in recipe_local_variables.get(occurrence.span.start_line, ())
        ):
            continue
        occurrence_text = recovery.slice_text_span(source, occurrence.span)
        if not _should_warn_for_unknown_variable(
            occurrence.name,
            occurrence_text,
            occurrence.context,
        ):
            continue

        diagnostics.append(
            lsp.Diagnostic(
                range=occurrence.span.to_lsp_range(),
                message=_diagnostic_message("Unknown variable reference", occurrence_text),
                code=UNKNOWN_VARIABLE_DIAGNOSTIC_CODE,
                severity=lsp.DiagnosticSeverity.Warning,
                source="make-ls",
            )
        )
    return diagnostics


def collect_unresolved_include_diagnostics(
    uri: str,
    includes: tuple[recovery.RecoveredInclude, ...],
    target_names: set[str],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    base_directory = _uri_base_directory(uri)
    include_patterns = tuple(include.path for include in includes)
    included_targets: tuple[frozenset[str], frozenset[str]] | None = None

    for include in includes:
        if include.optional or not _should_warn_for_unresolved_include(include.path):
            continue

        if _matches_target_names(include.path, target_names):
            continue

        candidate_path = _static_include_path(base_directory, include.path)
        if candidate_path is None:
            continue
        try:
            if candidate_path.exists():
                continue
        except OSError:
            continue

        if base_directory is not None and include_patterns:
            if included_targets is None:
                included_targets = _included_target_names(base_directory, include_patterns)
            # GNU Make can remake missing include files from ordinary targets.
            if _matches_target_names(include.path, included_targets[0]):
                continue

        diagnostics.append(
            lsp.Diagnostic(
                range=include.span.to_lsp_range(),
                message=f"Unresolved include: `{include.path}`",
                code=UNRESOLVED_INCLUDE_DIAGNOSTIC_CODE,
                severity=lsp.DiagnosticSeverity.Warning,
                source="make-ls",
            )
        )

    return diagnostics


def collect_unresolved_prerequisite_diagnostics(
    uri: str,
    occurrences: list[SymOcc],
    target_names: set[str],
    phony_targets: set[str],
    include_patterns: tuple[str, ...],
) -> list[lsp.Diagnostic]:
    diagnostics: list[lsp.Diagnostic] = []
    base_directory = _uri_base_directory(uri)
    included_targets: tuple[frozenset[str], frozenset[str]] | None = None
    for occurrence in occurrences:
        if occurrence.kind != "target" or occurrence.role != "reference":
            continue
        if occurrence.context is None or occurrence.context.kind != "prerequisite":
            continue
        if not _should_warn_for_unresolved_prerequisite(occurrence.name):
            continue
        if _matches_target_names(occurrence.name, target_names) or occurrence.name in phony_targets:
            continue
        if base_directory is not None and _prerequisite_exists(base_directory, occurrence.name):
            continue
        if base_directory is not None and include_patterns:
            if included_targets is None:
                included_targets = _included_target_names(base_directory, include_patterns)
            if (
                _matches_target_names(occurrence.name, included_targets[0])
                or occurrence.name in included_targets[1]
            ):
                continue

        diagnostics.append(
            lsp.Diagnostic(
                range=occurrence.span.to_lsp_range(),
                message=_diagnostic_message("Unresolved prerequisite", occurrence.name),
                code=UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE,
                severity=lsp.DiagnosticSeverity.Warning,
                source="make-ls",
            )
        )
    return diagnostics


def _make_syntax_diagnostic(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> lsp.Diagnostic:
    return lsp.Diagnostic(
        range=Span(start_line, 0, end_line, len(source_lines[end_line])).to_lsp_range(),
        message=_diagnostic_message(
            "Invalid Makefile syntax",
            recovery.slice_source_lines(
                source_lines,
                start_line=start_line,
                start_character=0,
                end_line=end_line,
                end_character=len(source_lines[end_line]),
            ),
        ),
        severity=lsp.DiagnosticSeverity.Error,
        source="make-ls",
    )


def _uri_base_directory(uri: str) -> Path | None:
    path = to_fs_path(uri)
    if path is None:
        return None
    return Path(path).parent


def _is_static_include_pattern(include_pattern: str) -> bool:
    return (
        "$(" not in include_pattern
        and "${" not in include_pattern
        and not any(character in include_pattern for character in "*?[]")
    )


def _should_warn_for_unresolved_include(name: str) -> bool:
    return _is_static_include_pattern(name)


def _should_warn_for_unresolved_prerequisite(name: str) -> bool:
    if name in SPECIAL_TARGET_DOCS:
        return False
    return not any(character in name for character in "%*?[]$()")


def _matches_target_names(name: str, target_names: set[str] | frozenset[str]) -> bool:
    return any(_matches_target_name(name, target_name) for target_name in target_names)


def _matches_target_name(name: str, target_name: str) -> bool:
    if "%" not in target_name:
        return name == target_name

    prefix, _, suffix = target_name.partition("%")
    return (
        name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix) + len(suffix)
    )


def _prerequisite_exists(base_directory: Path, name: str) -> bool:
    candidate_path = Path(name) if Path(name).is_absolute() else base_directory / name
    try:
        return candidate_path.exists()
    except OSError:
        return False


def _static_include_path(base_directory: Path | None, include_pattern: str) -> Path | None:
    if not _is_static_include_pattern(include_pattern):
        return None

    candidate_path = Path(include_pattern)
    if candidate_path.is_absolute():
        return candidate_path
    if base_directory is None:
        return None
    return base_directory / include_pattern


def _included_target_names(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[frozenset[str], frozenset[str]]:
    targets: set[str] = set()
    phony_targets: set[str] = set()
    seen_paths: set[Path] = set()
    for path in _resolved_static_include_paths(base_directory, include_patterns):
        _extend_included_target_names(path, seen_paths, targets, phony_targets)
    return frozenset(targets), frozenset(phony_targets)


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
        source_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return

    rule_recovery = recovery.recover_rules(source_lines, {})
    targets.update(definition.name for definition in rule_recovery.definitions)
    phony_targets.update(recovery.declared_phony_targets(rule_recovery.definitions))

    include_recovery = recovery.recover_include_directives(source_lines)
    for include_path in _resolved_static_include_paths(
        path.parent,
        tuple(include.path for include in include_recovery.includes),
    ):
        _extend_included_target_names(include_path, seen_paths, targets, phony_targets)


def _resolved_static_include_paths(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for include_pattern in include_patterns:
        candidate_path = _static_include_path(base_directory, include_pattern)
        if candidate_path is None:
            continue
        if candidate_path.is_file():
            resolved_paths.append(candidate_path)

    return tuple(resolved_paths)


def _is_tolerated_top_level_line(stripped_line: str) -> bool:
    if stripped_line.startswith("$(") or stripped_line.startswith("${"):
        return True
    first_token = stripped_line.split(maxsplit=1)[0]
    return first_token in recovery.RULE_DIRECTIVES


def _recipe_local_eval_assignment_name(command_text: str) -> str | None:
    match = recovery.RECIPE_LOCAL_EVAL_RE.match(command_text.strip())
    if match is None:
        return None

    assignment_match = recovery.ASSIGNMENT_RE.match(match.group("assignment").strip())
    if assignment_match is None:
        return None
    return assignment_match.group("name")


def _recipe_local_eval_variables(
    recipe_lines: tuple[RecipeLine, ...],
) -> dict[int, frozenset[str]]:
    variables_by_line: dict[int, frozenset[str]] = {}
    current_rule_start_line: int | None = None
    current_variables: set[str] = set()

    for recipe_line in recipe_lines:
        if recipe_line.rule_start_line != current_rule_start_line:
            current_rule_start_line = recipe_line.rule_start_line
            current_variables = set()

        variables_by_line[recipe_line.span.start_line] = frozenset(current_variables)
        assignment_name = _recipe_local_eval_assignment_name(recipe_line.command_text)
        if assignment_name is not None:
            current_variables.add(assignment_name)

    return variables_by_line


def _should_warn_for_unknown_variable(
    name: str,
    occurrence_text: str,
    context: SymCtx | None,
) -> bool:
    if name.isdigit():
        return False
    if occurrence_text.startswith("${"):
        return False
    if "$(" in name or "${" in name:
        return False
    if name in BUILTIN_VARIABLE_DOCS:
        return False
    if _is_make_automatic_variable_name(name):
        return False
    if context is not None:
        if context.kind == "conditional_test":
            return False
        # Only suppress when the active guard proves this exact variable is
        # present. That keeps typoed guard names warning while allowing guarded
        # uses such as `ifneq ($(VAR),)` then `$(VAR)`.
        if any(
            guard.name == name and guard.kind in {"defined", "nonempty"}
            for guard in context.active_guards
        ):
            return False
    return name not in os.environ


def _is_make_automatic_variable_name(name: str) -> bool:
    if name == "":
        return False
    if name[0] not in "@%<?^+*|":
        return False
    return name[1:] in {"", "D", "F"}


def _logical_recipe_lines(recipe_lines: tuple[RecipeLine, ...]) -> list[list[RecipeLine]]:
    groups: list[list[RecipeLine]] = []
    current_group: list[RecipeLine] = []

    for recipe_line in recipe_lines:
        current_group.append(recipe_line)
        if recovery.has_unescaped_line_continuation(recipe_line.command_text):
            continue

        groups.append(current_group)
        current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def _normalize_recipe_for_shell(command_text: str) -> str:
    # Bash does not understand Make's automatic variables such as `$<` or `$^`.
    # Replace them with a same-width shell expansion so parser ranges stay stable.
    return MAKE_AUTOMATIC_VARIABLE_RE.sub("$a", command_text)


def _shell_syntax_is_valid(command_text: str) -> bool | None:
    validation_text = _normalize_recipe_for_shell(command_text).replace("$$", "$")
    try:
        result = subprocess.run(
            ["bash", "-n"],
            input=validation_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return result.returncode == 0


def _diagnostic_message(prefix: str, snippet: str) -> str:
    compact_snippet = " ".join(snippet.split())
    if compact_snippet == "":
        return prefix

    if len(compact_snippet) > 40:
        compact_snippet = compact_snippet[:37] + "..."
    return f"{prefix}: `{compact_snippet}`"
