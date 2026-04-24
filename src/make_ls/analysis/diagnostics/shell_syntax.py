"""Validate logical recipe groups with `bash -n` when possible."""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, final, override

from lsprotocol import types as lsp

from make_ls.analysis.recovery import has_unescaped_line_continuation

from .base import DiagnosticChecker
from .common import diagnostic_message

if TYPE_CHECKING:
    from make_ls.types import RecipeLine

    from .base import DiagnosticContext

MAKE_AUTOMATIC_VARIABLE_RE = re.compile(
    r'\$\(([@%<?^+*|][DF]?)\)|\$\{([@%<?^+*|][DF]?)\}|\$([@%<?^+*|])'
)


@final
class ShellSyntaxChecker(DiagnosticChecker):
    CODE = 'invalid-shell-syntax'
    SEVERITY = lsp.DiagnosticSeverity.Error

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        if not context.include_shell_diagnostics:
            return []

        diagnostics: list[lsp.Diagnostic] = []
        for recipe_group in _logical_recipe_lines(context.recipe_lines):
            command_text = '\n'.join(line.command_text for line in recipe_group)
            if command_text.strip() == '':
                continue

            is_valid = _shell_syntax_is_valid(command_text)
            if is_valid is None or is_valid:
                continue

            first_line = recipe_group[0]
            diagnostics.append(
                self.emit(
                    diagnostic_range=lsp.Range(
                        start=lsp.Position(
                            line=first_line.span.start_line,
                            character=first_line.prefix_length,
                        ),
                        end=lsp.Position(
                            line=first_line.span.start_line,
                            character=len(first_line.raw_text),
                        ),
                    ),
                    message=diagnostic_message('Invalid shell syntax in recipe', command_text),
                ),
            )
        return diagnostics


def _logical_recipe_lines(recipe_lines: tuple[RecipeLine, ...]) -> list[list[RecipeLine]]:
    groups: list[list[RecipeLine]] = []
    current_group: list[RecipeLine] = []

    for recipe_line in recipe_lines:
        current_group.append(recipe_line)
        if has_unescaped_line_continuation(recipe_line.command_text):
            continue

        groups.append(current_group)
        current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def _normalize_recipe_for_shell(command_text: str) -> str:
    # Bash does not understand Make's automatic variables such as `$<` or `$^`.
    # Replace them with a same-width shell expansion so parser ranges stay stable.
    return MAKE_AUTOMATIC_VARIABLE_RE.sub('$a', command_text)


def _shell_syntax_is_valid(command_text: str) -> bool | None:
    validation_text = _normalize_recipe_for_shell(command_text).replace('$$', '$')
    try:
        result = subprocess.run(
            ['bash', '-n'],
            input=validation_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return result.returncode == 0
