"""Signature help for builtin GNU Make functions from raw line context.

Builtin function names are not recovered as document occurrences, so this lane
walks the current line directly and tracks nested variable references to keep
the innermost enclosing function under the cursor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lsprotocol import types as lsp

from make_ls.builtin_docs import FUNCTION_DOCS

from .recovery import VARIABLE_REFERENCE_DELIMITERS

BUILTIN_FUNCTION_NAME_RE = re.compile(r'[A-Za-z][A-Za-z0-9-]*')
FUNCTION_NAME_SEPARATOR_CHARACTERS = frozenset({' ', '\t'})
OPTIONAL_PARAMETER_RE = re.compile(r'^(?P<required>[^[]+)\[(?P<optional>,.+)\]$')


@dataclass(slots=True)
class _ReferenceFrame:
    closer: str
    function_name: str | None = None
    active_parameter: int = 0


def signature_help_for_pos(
    position: lsp.Position,
    source_lines: tuple[str, ...],
) -> lsp.SignatureHelp | None:
    """Return builtin function signature help for one cursor position."""
    if position.line >= len(source_lines):
        return None

    line_text = source_lines[position.line]
    character = min(position.character, len(line_text))
    function_context = _builtin_function_context(line_text, character)
    if function_context is None:
        return None

    function_name, active_parameter = function_context
    return _signature_help(function_name, active_parameter)


def _builtin_function_context(
    line_text: str,
    character: int,
) -> tuple[str, int] | None:
    stack: list[_ReferenceFrame] = []
    index = 0

    while index < character:
        if line_text[index] == '$' and index + 1 < len(line_text):
            next_character = line_text[index + 1]
            if next_character == '$':
                index += 2
                continue

            closer = VARIABLE_REFERENCE_DELIMITERS.get(next_character)
            if closer is not None:
                frame, index = _reference_frame(line_text, index, closer)
                stack.append(frame)
                continue

            index += 2
            continue

        if stack and line_text[index] == stack[-1].closer:
            _ = stack.pop()
            index += 1
            continue

        if stack and stack[-1].function_name is not None and line_text[index] == ',':
            stack[-1].active_parameter += 1
            index += 1
            continue

        index += 1

    # The cursor can sit inside a plain nested variable reference like `$(CC)`
    # while the surrounding function call is still the signature-help target.
    for frame in reversed(stack):
        if frame.function_name is not None:
            return frame.function_name, frame.active_parameter

    return None


def _reference_frame(
    line_text: str,
    reference_start: int,
    closer: str,
) -> tuple[_ReferenceFrame, int]:
    name_match = BUILTIN_FUNCTION_NAME_RE.match(line_text, reference_start + 2)
    if name_match is None:
        return _ReferenceFrame(closer), reference_start + 2

    function_name = name_match.group(0)
    if function_name not in FUNCTION_DOCS:
        return _ReferenceFrame(closer), reference_start + 2

    if (
        name_match.end() >= len(line_text)
        or line_text[name_match.end()] not in FUNCTION_NAME_SEPARATOR_CHARACTERS
    ):
        return _ReferenceFrame(closer), reference_start + 2

    index = name_match.end()
    while index < len(line_text) and line_text[index] in FUNCTION_NAME_SEPARATOR_CHARACTERS:
        index += 1

    return _ReferenceFrame(closer, function_name=function_name), index


def _signature_help(function_name: str, active_parameter: int) -> lsp.SignatureHelp:
    builtin_doc = FUNCTION_DOCS[function_name]
    parameters = _signature_parameters(builtin_doc.signature)
    bounded_active_parameter = None
    if parameters:
        bounded_active_parameter = min(active_parameter, len(parameters) - 1)

    signature = lsp.SignatureInformation(
        label=builtin_doc.signature,
        documentation=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f'GNU Make function\n\n{builtin_doc.summary}',
        ),
        parameters=parameters,
        active_parameter=bounded_active_parameter,
    )
    return lsp.SignatureHelp(
        signatures=[signature],
        active_signature=0,
        active_parameter=bounded_active_parameter,
    )


def _signature_parameters(
    signature: str,
) -> tuple[lsp.ParameterInformation, ...] | None:
    if len(signature) < 4 or signature[:2] not in {'$(', '${'}:
        return None

    body = signature[2:-1]
    _name, separator, arguments = body.partition(' ')
    if separator == '' or arguments == '':
        return None

    labels = _parameter_labels(arguments)
    if not labels:
        return None

    return tuple(lsp.ParameterInformation(label=label) for label in labels)


def _parameter_labels(arguments: str) -> tuple[str, ...]:
    parts: list[str] = []
    current: list[str] = []
    optional_depth = 0

    for current_character in arguments:
        if current_character == ',' and optional_depth == 0:
            parts.append(''.join(current).strip())
            current = []
            continue

        current.append(current_character)
        if current_character == '[':
            optional_depth += 1
        elif current_character == ']' and optional_depth > 0:
            optional_depth -= 1

    parts.append(''.join(current).strip())

    labels: list[str] = []
    for part in parts:
        if part == '':
            continue

        optional_match = OPTIONAL_PARAMETER_RE.fullmatch(part)
        if optional_match is None:
            labels.append(part)
            continue

        required = optional_match.group('required').strip()
        optional = optional_match.group('optional').strip().removeprefix(',').strip()
        if required != '':
            labels.append(required)
        if optional != '':
            labels.append(f'[{optional}]')

    return tuple(labels)
