"""Report top-level lines that no recovery pass claimed."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final, override

from make_ls.analysis.recovery import (
    RULE_DIRECTIVES,
    continues_previous_top_level_line,
    logical_top_level_end,
    starts_define_block,
)

from .base import DiagnosticChecker
from .common import make_syntax_diagnostic

if TYPE_CHECKING:
    from lsprotocol import types as lsp

    from .base import DiagnosticContext


@final
class MakeSyntaxChecker(DiagnosticChecker):
    CODE: ClassVar[str | None] = 'invalid-makefile-syntax'

    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        source_lines = context.source_lines
        code = self.CODE
        assert code is not None
        diagnostics: list[lsp.Diagnostic] = []
        in_define_block = False
        line_number = 0
        while line_number < len(source_lines):
            line = source_lines[line_number]
            stripped = line.strip()
            if line_number in context.parsed_lines or stripped == '' or stripped.startswith('#'):
                line_number += 1
                continue

            if starts_define_block(stripped):
                in_define_block = True
                line_number += 1
                continue

            if in_define_block:
                if stripped == 'endef':
                    in_define_block = False
                line_number += 1
                continue

            if line.startswith('\t'):
                diagnostics.append(
                    make_syntax_diagnostic(
                        source_lines,
                        line_number,
                        line_number,
                        code=code,
                    )
                )
                line_number += 1
                continue

            if continues_previous_top_level_line(source_lines, line_number):
                line_number += 1
                continue

            logical_end_line = logical_top_level_end(source_lines, line_number)
            # The owned parser does not model directives or eager top-level function
            # calls, but they are valid Make syntax and should not produce noise.
            if _is_tolerated_top_level_line(stripped):
                line_number = logical_end_line + 1
                continue

            diagnostics.append(
                make_syntax_diagnostic(
                    source_lines,
                    line_number,
                    logical_end_line,
                    code=code,
                )
            )
            line_number = logical_end_line + 1

        return diagnostics


def _is_tolerated_top_level_line(stripped_line: str) -> bool:
    if stripped_line.startswith(('$(', '${')):
        return True
    first_token = stripped_line.split(maxsplit=1)[0]
    return first_token in RULE_DIRECTIVES
