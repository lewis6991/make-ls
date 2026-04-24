"""Validate conditional and define/endef block structure.

One pass owns the six related control-block diagnostics because splitting them
further would just repeat the same stack walk over the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final, override

from make_ls.analysis.recovery import (
    CONDITIONAL_DIRECTIVES,
    continues_previous_top_level_line,
    logical_top_level_end,
    starts_define_block,
)

from .base import DiagnosticChecker
from .common import block_diagnostic, is_else_if_branch, logical_top_level_text

if TYPE_CHECKING:
    from lsprotocol import types as lsp

    from .base import DiagnosticContext

UNEXPECTED_ELSE_DIAGNOSTIC_CODE = 'unexpected-else'
DUPLICATE_ELSE_DIAGNOSTIC_CODE = 'duplicate-else'
UNEXPECTED_ENDIF_DIAGNOSTIC_CODE = 'unexpected-endif'
UNEXPECTED_ENDEF_DIAGNOSTIC_CODE = 'unexpected-endef'
MISSING_ENDIF_DIAGNOSTIC_CODE = 'missing-endif'
MISSING_ENDEF_DIAGNOSTIC_CODE = 'missing-endef'


@dataclass(slots=True)
class _ConditionalControlFrame:
    start_line: int
    saw_terminal_else: bool = False


@final
class ControlBlockChecker(DiagnosticChecker):
    @override
    def check(self, context: DiagnosticContext) -> list[lsp.Diagnostic]:
        source_lines = context.source_lines
        diagnostics: list[lsp.Diagnostic] = []
        conditional_stack: list[_ConditionalControlFrame] = []
        define_start_line: int | None = None
        line_number = 0

        while line_number < len(source_lines):
            line = source_lines[line_number]
            stripped = line.strip()

            if define_start_line is not None:
                if stripped == 'endef':
                    define_start_line = None
                line_number += 1
                continue

            if stripped == '' or stripped.startswith('#'):
                line_number += 1
                continue

            if starts_define_block(stripped):
                define_start_line = line_number
                line_number += 1
                continue

            if line.startswith('\t') or continues_previous_top_level_line(
                source_lines,
                line_number,
            ):
                line_number += 1
                continue

            logical_end_line = logical_top_level_end(source_lines, line_number)
            logical_text = logical_top_level_text(source_lines, line_number, logical_end_line)
            first_token, _separator, remainder = logical_text.partition(' ')

            if first_token in CONDITIONAL_DIRECTIVES:
                conditional_stack.append(_ConditionalControlFrame(start_line=line_number))
            elif first_token == 'else':
                if not conditional_stack:
                    diagnostics.append(
                        block_diagnostic(
                            source_lines,
                            line_number,
                            logical_end_line,
                            message='Unexpected else directive',
                            code=UNEXPECTED_ELSE_DIAGNOSTIC_CODE,
                        )
                    )
                elif conditional_stack[-1].saw_terminal_else:
                    diagnostics.append(
                        block_diagnostic(
                            source_lines,
                            line_number,
                            logical_end_line,
                            message='Duplicate else directive',
                            code=DUPLICATE_ELSE_DIAGNOSTIC_CODE,
                        )
                    )
                elif not is_else_if_branch(remainder):
                    conditional_stack[-1].saw_terminal_else = True
            elif first_token == 'endif':
                if not conditional_stack:
                    diagnostics.append(
                        block_diagnostic(
                            source_lines,
                            line_number,
                            logical_end_line,
                            message='Unexpected endif directive',
                            code=UNEXPECTED_ENDIF_DIAGNOSTIC_CODE,
                        )
                    )
                else:
                    _ = conditional_stack.pop()
            elif first_token == 'endef':
                diagnostics.append(
                    block_diagnostic(
                        source_lines,
                        line_number,
                        logical_end_line,
                        message='Unexpected endef directive',
                        code=UNEXPECTED_ENDEF_DIAGNOSTIC_CODE,
                    )
                )

            line_number = logical_end_line + 1

        if define_start_line is not None:
            diagnostics.append(
                block_diagnostic(
                    source_lines,
                    define_start_line,
                    define_start_line,
                    message='Missing endef for define block',
                    code=MISSING_ENDEF_DIAGNOSTIC_CODE,
                )
            )

        diagnostics.extend(
            block_diagnostic(
                source_lines,
                frame.start_line,
                frame.start_line,
                message='Missing endif for conditional block',
                code=MISSING_ENDIF_DIAGNOSTIC_CODE,
            )
            for frame in reversed(conditional_stack)
        )

        return diagnostics
