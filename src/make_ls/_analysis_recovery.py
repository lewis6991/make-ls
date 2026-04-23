from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from .builtin_docs import DIRECTIVE_DOCS
from .types import (
    DocForm,
    RecipeLine,
    Span,
    SymCtx,
    SymOcc,
    TargetDef,
    VarDef,
    VarGuard,
)

if TYPE_CHECKING:
    from .types import FormKind, SymCtxKind

COMMENT_RE = re.compile(r'^[ ]*#(?P<text>.*)$')
TOKEN_RE = re.compile(r'\S+')
ASSIGNMENT_RE = re.compile(
    r'^(?P<leading>[ ]*)(?P<prefix>(?:(?:export|override|private)\s+)*)'
    r'(?P<name>[A-Za-z0-9_.%/@+-]+)'
    r'[ ]*(?P<operator>[:+?!]?=)[ ]*(?P<value>.*)$'
)
VARIABLE_REFERENCE_RE = re.compile(
    r'\$\((?P<paren>[A-Za-z0-9_.%/@<?^+*|!-]+)\)'
    r'|\$\{(?P<brace>[A-Za-z0-9_.%/@<?^+*|!-]+)\}'
)
SIMPLE_AUTOMATIC_VARIABLE_RE = re.compile(r'\$(?P<simple>[@%<?^+*|])')
RECIPE_LOCAL_EVAL_RE = re.compile(r'^\$\(\s*eval\s+(?P<assignment>.+)\)\s*$')
VARIABLE_REFERENCE_DELIMITERS = {'(': ')', '{': '}'}
CONDITIONAL_DIRECTIVES = frozenset({'ifdef', 'ifeq', 'ifndef', 'ifneq'})
CONDITIONAL_CONTROL_DIRECTIVES = CONDITIONAL_DIRECTIVES | frozenset({'else', 'endif'})
RECIPE_BODY_DIRECTIVES = frozenset({'else', 'endif', 'ifdef', 'ifeq', 'ifndef', 'ifneq'})
RULE_DIRECTIVES = frozenset(DIRECTIVE_DOCS)
INCLUDE_DIRECTIVES = frozenset({'include', '-include', 'sinclude'})
VARIABLE_NAME_RE = re.compile(r'^[A-Za-z0-9_.%/@+-]+$')
EMPTY_CONDITIONAL_ARGUMENTS = frozenset({'', '""', "''"})


@dataclass(frozen=True, slots=True)
class ConditionalRecovery:
    forms: tuple[DocForm, ...]
    occurrences: tuple[SymOcc, ...]
    line_guards: dict[int, tuple[VarGuard, ...]]


@dataclass(frozen=True, slots=True)
class RecoveredInclude:
    path: str
    span: Span
    optional: bool


@dataclass(frozen=True, slots=True)
class IncludeRecovery:
    includes: tuple[RecoveredInclude, ...]
    occurrences: tuple[SymOcc, ...]
    parsed_lines: frozenset[int]


@dataclass(frozen=True, slots=True)
class RuleRecovery:
    definitions: tuple[TargetDef, ...]
    occurrences: tuple[SymOcc, ...]
    recipe_lines: tuple[RecipeLine, ...]
    parsed_lines: frozenset[int]
    forms: tuple[DocForm, ...]


@dataclass(frozen=True, slots=True)
class AssignmentRecovery:
    definitions: tuple[VarDef, ...]
    occurrences: tuple[SymOcc, ...]
    parsed_lines: frozenset[int]
    diagnostics: tuple[lsp.Diagnostic, ...]
    forms: tuple[DocForm, ...]


@dataclass(frozen=True, slots=True)
class _ConditionalFrame:
    current_guards: tuple[VarGuard, ...]
    else_guards: tuple[VarGuard, ...]


def recover_conditionals(source_lines: list[str]) -> ConditionalRecovery:
    forms: list[DocForm] = []
    occurrences: list[SymOcc] = []
    line_guards: dict[int, tuple[VarGuard, ...]] = {}
    condition_stack: list[_ConditionalFrame] = []
    line_number = 0
    in_define_block = False

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        active_guards = _active_condition_guards(condition_stack)

        if starts_define_block(stripped):
            in_define_block = True
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue
        if in_define_block:
            if active_guards:
                line_guards[line_number] = active_guards
            if stripped == 'endef':
                in_define_block = False
            line_number += 1
            continue

        if line.startswith('\t'):
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue

        if continues_previous_top_level_line(source_lines, line_number):
            if active_guards:
                line_guards[line_number] = active_guards
            line_number += 1
            continue

        logical_end_line = logical_top_level_end(source_lines, line_number)
        logical_text = ''
        for logical_line in range(line_number, logical_end_line + 1):
            text = _strip_make_comment(source_lines[logical_line]).strip()
            if logical_line < logical_end_line and has_unescaped_line_continuation(text):
                text = text[:-1].rstrip()
            if text != '':
                logical_text += (' ' if logical_text else '') + text

        first_token, _separator, _remainder = logical_text.partition(' ')
        if first_token in CONDITIONAL_CONTROL_DIRECTIVES:
            if first_token in CONDITIONAL_DIRECTIVES:
                forms.append(
                    DocForm(
                        kind='conditional',
                        span=Span(
                            line_number,
                            0,
                            logical_end_line,
                            len(source_lines[logical_end_line]),
                        ),
                    )
                )
                context = SymCtx(
                    form_kind='conditional',
                    kind='conditional_test',
                    active_guards=active_guards,
                )
                for directive_line in range(line_number, logical_end_line + 1):
                    occurrences.extend(
                        _recover_variable_references_from_text(
                            source_lines[directive_line],
                            directive_line,
                            context=context,
                        )
                    )
                current_guards, else_guards = _conditional_branch_guards(logical_text)
                condition_stack.append(
                    _ConditionalFrame(
                        current_guards=current_guards,
                        else_guards=else_guards,
                    )
                )
            elif first_token == 'else':
                if condition_stack:
                    current_guards = condition_stack[-1].current_guards
                    else_guards = condition_stack[-1].else_guards
                    condition_stack[-1] = _ConditionalFrame(
                        current_guards=else_guards,
                        else_guards=current_guards,
                    )
            elif first_token == 'endif' and condition_stack:
                _ = condition_stack.pop()

            line_number = logical_end_line + 1
            continue

        if active_guards:
            for guarded_line in range(line_number, logical_end_line + 1):
                line_guards[guarded_line] = active_guards
        line_number = logical_end_line + 1

    return ConditionalRecovery(
        forms=tuple(forms),
        occurrences=tuple(occurrences),
        line_guards=line_guards,
    )


def recover_rules(
    source_lines: list[str],
    line_guards: dict[int, tuple[VarGuard, ...]],
) -> RuleRecovery:
    definitions: list[TargetDef] = []
    occurrences: list[SymOcc] = []
    recipe_lines: list[RecipeLine] = []
    parsed_lines: set[int] = set()
    forms: list[DocForm] = []
    line_number = 0
    in_define_block = False

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == 'endef':
                in_define_block = False
            line_number += 1
            continue

        if line.startswith('\t') or continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        recovered_rule = _recover_rule(source_lines, line_number, line_guards)
        if recovered_rule is None:
            line_number += 1
            continue

        (
            recovered_definitions,
            recovered_occurrences,
            recovered_recipe_lines,
            next_line_number,
            recovered_rule_form,
        ) = recovered_rule
        definitions.extend(recovered_definitions)
        occurrences.extend(recovered_occurrences)
        recipe_lines.extend(recovered_recipe_lines)
        forms.append(recovered_rule_form)
        parsed_lines.update(range(line_number, next_line_number))
        line_number = next_line_number

    return RuleRecovery(
        definitions=tuple(definitions),
        occurrences=tuple(occurrences),
        recipe_lines=tuple(recipe_lines),
        parsed_lines=frozenset(parsed_lines),
        forms=tuple(forms),
    )


def recover_include_directives(source_lines: list[str]) -> IncludeRecovery:
    includes: list[RecoveredInclude] = []
    occurrences: list[SymOcc] = []
    parsed_lines: set[int] = set()
    in_define_block = False
    line_number = 0

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == 'endef':
                in_define_block = False
            line_number += 1
            continue

        if line.startswith('\t') or continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        logical_end_line = logical_top_level_end(source_lines, line_number)
        recovered_includes = _recover_include_paths(
            source_lines,
            line_number,
            logical_end_line,
        )
        if not recovered_includes:
            line_number = logical_end_line + 1
            continue

        includes.extend(recovered_includes)
        for include in recovered_includes:
            occurrences.extend(
                _recover_variable_references_from_text(
                    include.path,
                    include.span.start_line,
                    include.span.start_character,
                )
            )
        parsed_lines.update(range(line_number, logical_end_line + 1))
        line_number = logical_end_line + 1

    return IncludeRecovery(
        includes=tuple(includes),
        occurrences=tuple(occurrences),
        parsed_lines=frozenset(parsed_lines),
    )


def recover_variable_assignments(
    source_lines: list[str],
    line_guards: dict[int, tuple[VarGuard, ...]],
) -> AssignmentRecovery:
    definitions: list[VarDef] = []
    occurrences: list[SymOcc] = []
    parsed_lines: set[int] = set()
    diagnostics: list[lsp.Diagnostic] = []
    forms: list[DocForm] = []
    line_number = 0
    in_define_block = False

    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if starts_define_block(stripped):
            in_define_block = True
            line_number += 1
            continue
        if in_define_block:
            if stripped == 'endef':
                in_define_block = False
            line_number += 1
            continue

        if line.startswith('\t') or continues_previous_top_level_line(source_lines, line_number):
            line_number += 1
            continue

        match = ASSIGNMENT_RE.match(line)
        if match is None:
            line_number += 1
            continue

        end_line = logical_top_level_end(source_lines, line_number)
        name = match.group('name')
        operator = match.group('operator')
        value_start = match.start('value')
        value = _assignment_value_text(source_lines, line_number, value_start, end_line)
        name_span = Span(line_number, match.start('name'), line_number, match.end('name'))
        assignment_span = Span(
            line_number,
            match.start('name'),
            end_line,
            len(source_lines[end_line]),
        )

        definitions.append(
            _with_variable_comments(
                VarDef(
                    name=name,
                    name_span=name_span,
                    assignment_span=assignment_span,
                    operator=operator,
                    value=value,
                ),
                source_lines,
            )
        )
        occurrences.append(
            SymOcc(
                kind='variable',
                role='definition',
                name=name,
                span=name_span,
                context=_symbol_context(
                    'assignment',
                    'assignment_definition',
                    line_guards,
                    name_span.start_line,
                ),
            )
        )
        forms.append(DocForm(kind='assignment', span=assignment_span))
        parsed_lines.update(range(line_number, end_line + 1))

        if end_line == line_number:
            diagnostics.extend(
                _recover_assignment_value_diagnostics(
                    line,
                    line_number,
                    value_start,
                    match.group('value'),
                )
            )
        occurrences.extend(
            _recover_variable_references_from_assignment_lines(
                source_lines,
                line_number,
                value_start,
                end_line,
                line_guards,
            )
        )
        line_number = end_line + 1

    return AssignmentRecovery(
        definitions=tuple(definitions),
        occurrences=tuple(occurrences),
        parsed_lines=frozenset(parsed_lines),
        diagnostics=tuple(diagnostics),
        forms=tuple(forms),
    )


def declared_phony_targets(definitions: tuple[TargetDef, ...]) -> tuple[str, ...]:
    # Make allows repeated `.PHONY:` declarations, and later ones are additive.
    phony_targets: list[str] = []
    for definition in definitions:
        if definition.name == '.PHONY':
            phony_targets.extend(definition.prerequisites)
    return tuple(phony_targets)


def starts_define_block(stripped_line: str) -> bool:
    return stripped_line.startswith(('define ', 'define\t'))


def continues_previous_top_level_line(source_lines: list[str], line_number: int) -> bool:
    if line_number == 0:
        return False
    previous_line = source_lines[line_number - 1]
    return not previous_line.startswith('\t') and has_unescaped_line_continuation(previous_line)


def logical_top_level_end(source_lines: list[str], start_line: int) -> int:
    end_line = start_line
    while has_unescaped_line_continuation(source_lines[end_line]) and end_line + 1 < len(
        source_lines
    ):
        end_line += 1
    return end_line


def slice_source_lines(
    source_lines: list[str],
    *,
    start_line: int,
    start_character: int,
    end_line: int,
    end_character: int,
) -> str:
    if start_line == end_line:
        return source_lines[start_line][start_character:end_character]

    parts = [source_lines[start_line][start_character:]]
    parts.extend(source_lines[line_number] for line_number in range(start_line + 1, end_line))
    parts.append(source_lines[end_line][:end_character])
    return '\n'.join(parts)


def has_unescaped_line_continuation(text: str) -> bool:
    stripped = text.rstrip()
    trailing_backslashes = len(stripped) - len(stripped.rstrip('\\'))
    return trailing_backslashes % 2 == 1


def slice_text_span(text: str, span: Span) -> str:
    lines = text.splitlines()
    if not lines:
        return ''
    if span.start_line == span.end_line:
        return lines[span.start_line][span.start_character : span.end_character]

    parts = [lines[span.start_line][span.start_character :]]
    parts.extend(lines[line_number] for line_number in range(span.start_line + 1, span.end_line))
    parts.append(lines[span.end_line][: span.end_character])
    return '\n'.join(parts)


def _active_condition_guards(
    condition_stack: list[_ConditionalFrame],
) -> tuple[VarGuard, ...]:
    return tuple(guard for frame in condition_stack for guard in frame.current_guards)


def _conditional_branch_guards(
    logical_text: str,
) -> tuple[tuple[VarGuard, ...], tuple[VarGuard, ...]]:
    first_token, _separator, remainder = logical_text.partition(' ')
    remainder = remainder.strip()

    if first_token in {'ifdef', 'ifndef'}:
        if VARIABLE_NAME_RE.fullmatch(remainder) is None:
            return (), ()
        if first_token == 'ifdef':
            return (
                (VarGuard(remainder, 'defined'),),
                (VarGuard(remainder, 'undefined'),),
            )
        return (
            (VarGuard(remainder, 'undefined'),),
            (VarGuard(remainder, 'defined'),),
        )

    if first_token not in {'ifeq', 'ifneq'}:
        return (), ()

    left, right = _conditional_arguments(remainder)
    if left is None or right is None:
        return (), ()

    name: str | None = None
    if _conditional_argument_is_empty(left):
        name = _simple_variable_reference_name(right)
    elif _conditional_argument_is_empty(right):
        name = _simple_variable_reference_name(left)
    if name is None:
        return (), ()

    if first_token == 'ifneq':
        return (
            (VarGuard(name, 'nonempty'),),
            (VarGuard(name, 'empty'),),
        )
    return (
        (VarGuard(name, 'empty'),),
        (VarGuard(name, 'nonempty'),),
    )


def _conditional_arguments(text: str) -> tuple[str | None, str | None]:
    if not (text.startswith('(') and text.endswith(')')):
        return None, None
    arguments = text[1:-1]
    separator_index = arguments.find(',')
    if separator_index == -1:
        return None, None
    return arguments[:separator_index].strip(), arguments[separator_index + 1 :].strip()


def _conditional_argument_is_empty(text: str) -> bool:
    return text in EMPTY_CONDITIONAL_ARGUMENTS


def _simple_variable_reference_name(text: str) -> str | None:
    match = VARIABLE_REFERENCE_RE.fullmatch(text)
    if match is None:
        return None
    return match.group('paren') or match.group('brace')


def _symbol_context(
    form_kind: FormKind,
    kind: SymCtxKind,
    line_guards: dict[int, tuple[VarGuard, ...]],
    line_number: int,
) -> SymCtx:
    return SymCtx(
        form_kind=form_kind,
        kind=kind,
        active_guards=line_guards.get(line_number, ()),
    )


def _recover_rule(
    source_lines: list[str],
    start_line: int,
    line_guards: dict[int, tuple[VarGuard, ...]],
) -> (
    tuple[
        list[TargetDef],
        list[SymOcc],
        list[RecipeLine],
        int,
        DocForm,
    ]
    | None
):
    header_lines = [source_lines[start_line]]
    header_end_line = start_line
    while has_unescaped_line_continuation(header_lines[-1]) and (
        header_end_line + 1 < len(source_lines)
    ):
        next_line = source_lines[header_end_line + 1]
        if next_line.startswith('\t'):
            break
        header_lines.append(next_line)
        header_end_line += 1

    if not _can_start_rule(header_lines[0]):
        return None
    (
        separator_line_index,
        separator_start,
        separator_width,
        is_double_colon,
    ) = _recover_rule_separator(header_lines)
    if separator_line_index is None:
        return None

    prerequisites = _recover_prerequisites(
        header_lines,
        separator_line_index,
        separator_start,
        separator_width,
    )

    target_definitions: list[TargetDef] = []
    occurrences: list[SymOcc] = []
    header_text = '\n'.join(header_lines)
    rule_recipe_lines: list[RecipeLine] = []
    next_line_number = header_end_line + 1
    previous_recipe_continues = False
    while next_line_number < len(source_lines):
        next_line = source_lines[next_line_number]
        stripped_next_line = next_line.strip()
        if next_line.startswith('\t'):
            recipe_line = _recipe_line_from_source(next_line_number, next_line, start_line)
            rule_recipe_lines.append(recipe_line)
            previous_recipe_continues = has_unescaped_line_continuation(recipe_line.command_text)
            next_line_number += 1
            continue
        if previous_recipe_continues:
            recipe_line = _continued_recipe_line_from_source(
                next_line_number,
                next_line,
                start_line,
            )
            rule_recipe_lines.append(recipe_line)
            previous_recipe_continues = has_unescaped_line_continuation(recipe_line.command_text)
            next_line_number += 1
            continue
        if (
            stripped_next_line == ''
            or stripped_next_line.startswith('#')
            or _is_recipe_body_directive(stripped_next_line)
        ) and _rule_body_continues(source_lines, next_line_number):
            next_line_number += 1
            continue
        break

    recipe_text = '\n'.join(line.raw_text for line in rule_recipe_lines) or None
    rule_end_line = rule_recipe_lines[-1].span.end_line if rule_recipe_lines else header_end_line
    rule_end_character = (
        rule_recipe_lines[-1].span.end_character
        if rule_recipe_lines
        else len(source_lines[header_end_line])
    )
    rule_span = Span(start_line, 0, rule_end_line, rule_end_character)
    rule_text = header_text if recipe_text is None else f'{header_text}\n{recipe_text}'
    for line_index, line in enumerate(header_lines[: separator_line_index + 1]):
        target_text = line[:separator_start] if line_index == separator_line_index else line
        for match in TOKEN_RE.finditer(target_text):
            target_name = match.group(0)
            if target_name == '\\':
                continue

            line_number = start_line + line_index
            name_span = Span(line_number, match.start(), line_number, match.end())
            definition = TargetDef(
                name=target_name,
                name_span=name_span,
                rule_span=rule_span,
                prerequisites=prerequisites,
                rule_text=rule_text,
                recipe_text=recipe_text,
                is_double_colon=is_double_colon,
            )
            target_definitions.append(definition)
            occurrences.append(
                SymOcc(
                    kind='target',
                    role='definition',
                    name=target_name,
                    span=name_span,
                    context=_symbol_context('rule', 'target_definition', line_guards, line_number),
                )
            )

    if not target_definitions:
        return None

    occurrences.extend(
        _recover_prerequisite_occurrences(
            header_lines,
            start_line,
            separator_line_index,
            separator_start,
            separator_width,
            line_guards,
        )
    )
    for recipe_line in rule_recipe_lines:
        occurrences.extend(
            _recover_variable_references_from_text(
                recipe_line.raw_text,
                recipe_line.span.start_line,
                context=_symbol_context('rule', 'recipe', line_guards, recipe_line.span.start_line),
            )
        )

    return (
        target_definitions,
        occurrences,
        rule_recipe_lines,
        next_line_number,
        DocForm(kind='rule', span=rule_span),
    )


def _can_start_rule(line: str) -> bool:
    stripped = line.lstrip()
    if stripped == '' or stripped.startswith('#'):
        return False
    if stripped.split(maxsplit=1)[0] in RULE_DIRECTIVES:
        return False
    return ASSIGNMENT_RE.match(line) is None


def _recover_rule_separator(header_lines: list[str]) -> tuple[int | None, int, int, bool]:
    for line_index, line in enumerate(header_lines):
        separator_start, separator_width, is_double_colon = _recover_rule_separator_in_line(line)
        if separator_start is not None:
            return line_index, separator_start, separator_width, is_double_colon
    return None, 0, 0, False


def _recover_rule_separator_in_line(line: str) -> tuple[int | None, int, bool]:
    separator_index = line.find(':')
    if separator_index == -1:
        return None, 0, False
    if separator_index + 1 < len(line) and line[separator_index + 1] == '=':
        return None, 0, False
    if separator_index > 0 and line[separator_index - 1] in '?+!':
        return None, 0, False

    separator_start = separator_index
    is_double_colon = line[separator_index : separator_index + 2] == '::'
    separator_width = 2 if is_double_colon else 1
    if separator_index > 0 and line[separator_index - 1] == '&':
        separator_start -= 1
        separator_width += 1

    return separator_start, separator_width, is_double_colon


def _recover_prerequisites(
    header_lines: list[str],
    separator_line_index: int,
    separator_start: int,
    separator_width: int,
) -> tuple[str, ...]:
    prerequisites: list[str] = []
    for line_index, line in enumerate(header_lines):
        if line_index < separator_line_index:
            continue
        if line_index == separator_line_index:
            text = line[separator_start + separator_width :]
        else:
            text = line
        text = text.split(';', 1)[0]
        if line_index == separator_line_index and _is_target_specific_variable_assignment(text):
            return ()
        for match in TOKEN_RE.finditer(text):
            token = match.group(0)
            if token in {'\\', '|'}:
                continue
            if token.startswith('#'):
                break
            if '$(' in token or '${' in token:
                continue
            prerequisites.append(token)
    return tuple(prerequisites)


def _recover_prerequisite_occurrences(
    header_lines: list[str],
    start_line: int,
    separator_line_index: int,
    separator_start: int,
    separator_width: int,
    line_guards: dict[int, tuple[VarGuard, ...]],
) -> list[SymOcc]:
    occurrences: list[SymOcc] = []
    for line_offset, line in enumerate(header_lines):
        if line_offset < separator_line_index:
            continue
        if line_offset == separator_line_index:
            text = line[separator_start + separator_width :]
            start_character = separator_start + separator_width
        else:
            text = line
            start_character = 0
        text = text.split(';', 1)[0]
        if line_offset == separator_line_index and _is_target_specific_variable_assignment(text):
            return []
        line_number = start_line + line_offset

        occurrences.extend(
            _recover_variable_references_from_text(
                text,
                line_number,
                start_character,
                context=_symbol_context('rule', 'prerequisite', line_guards, line_number),
            )
        )
        for match in TOKEN_RE.finditer(text):
            token = match.group(0)
            if token in {'\\', '|'}:
                continue
            if token.startswith('#'):
                break
            if '$(' in token or '${' in token:
                continue
            occurrences.append(
                SymOcc(
                    kind='target',
                    role='reference',
                    name=token,
                    span=Span(
                        line_number,
                        start_character + match.start(),
                        line_number,
                        start_character + match.end(),
                    ),
                    context=_symbol_context('rule', 'prerequisite', line_guards, line_number),
                )
            )

    return occurrences


def _is_target_specific_variable_assignment(text: str) -> bool:
    stripped = text.strip()
    return stripped != '' and ASSIGNMENT_RE.fullmatch(stripped) is not None


def _recover_variable_references_from_text(
    text: str,
    line_number: int,
    start_character: int = 0,
    *,
    context: SymCtx | None = None,
) -> list[SymOcc]:
    occurrences: list[SymOcc] = []
    for reference in VARIABLE_REFERENCE_RE.finditer(text):
        reference_name = reference.group('paren') or reference.group('brace')
        if reference_name is None:
            continue
        occurrences.append(
            SymOcc(
                kind='variable',
                role='reference',
                name=reference_name,
                span=Span(
                    line_number,
                    start_character + reference.start(),
                    line_number,
                    start_character + reference.end(),
                ),
                context=context,
            )
        )
    for reference in SIMPLE_AUTOMATIC_VARIABLE_RE.finditer(text):
        if reference.start() > 0 and text[reference.start() - 1] == '$':
            continue

        occurrences.append(
            SymOcc(
                kind='variable',
                role='reference',
                name=reference.group('simple'),
                span=Span(
                    line_number,
                    start_character + reference.start(),
                    line_number,
                    start_character + reference.end(),
                ),
                context=context,
            )
        )
    occurrences.sort(key=lambda occurrence: occurrence.span.start_character)
    return occurrences


def _recover_include_paths(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> tuple[RecoveredInclude, ...]:
    tokens: list[tuple[str, Span]] = []
    for line_number in range(start_line, end_line + 1):
        text = _strip_make_comment(source_lines[line_number])
        if line_number < end_line and has_unescaped_line_continuation(text):
            text = text.rstrip()[:-1]

        tokens.extend(
            (
                token.group(),
                Span(line_number, token.start(), line_number, token.end()),
            )
            for token in TOKEN_RE.finditer(text)
        )

    if not tokens:
        return ()

    directive, _directive_span = tokens[0]
    if directive not in INCLUDE_DIRECTIVES:
        return ()

    return tuple(
        RecoveredInclude(
            path=token,
            span=span,
            optional=directive != 'include',
        )
        for token, span in tokens[1:]
    )


def _strip_make_comment(text: str) -> str:
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


def _is_recipe_body_directive(stripped_line: str) -> bool:
    if stripped_line == '':
        return False
    return stripped_line.split(maxsplit=1)[0] in RECIPE_BODY_DIRECTIVES


def _rule_body_continues(source_lines: list[str], start_line: int) -> bool:
    line_number = start_line
    while line_number < len(source_lines):
        line = source_lines[line_number]
        stripped = line.strip()
        if stripped == '' or stripped.startswith('#') or _is_recipe_body_directive(stripped):
            line_number += 1
            continue
        return line.startswith('\t')
    return False


def _recipe_line_from_source(line_number: int, raw_text: str, rule_start_line: int) -> RecipeLine:
    recipe_prefix_length = 1
    control_prefix_length, command_text = _strip_recipe_prefix(raw_text[recipe_prefix_length:])
    return RecipeLine(
        span=Span(line_number, 0, line_number, len(raw_text)),
        raw_text=raw_text,
        command_text=command_text,
        prefix_length=recipe_prefix_length + control_prefix_length,
        rule_start_line=rule_start_line,
    )


def _continued_recipe_line_from_source(
    line_number: int,
    raw_text: str,
    rule_start_line: int,
) -> RecipeLine:
    return RecipeLine(
        span=Span(line_number, 0, line_number, len(raw_text)),
        raw_text=raw_text,
        command_text=raw_text,
        prefix_length=0,
        rule_start_line=rule_start_line,
    )


def _strip_recipe_prefix(raw_text: str) -> tuple[int, str]:
    prefix_length = 0
    # Make strips these control prefixes before invoking the shell. They are not
    # part of the shell program, so diagnostics must parse the remainder instead.
    while prefix_length < len(raw_text) and raw_text[prefix_length] in '@+-':
        prefix_length += 1

    return prefix_length, raw_text[prefix_length:]


def _assignment_value_text(
    source_lines: list[str],
    start_line: int,
    value_start: int,
    end_line: int,
) -> str:
    if start_line == end_line:
        return source_lines[start_line][value_start:].strip()

    return slice_source_lines(
        source_lines,
        start_line=start_line,
        start_character=value_start,
        end_line=end_line,
        end_character=len(source_lines[end_line]),
    ).rstrip()


def _recover_variable_references_from_assignment_lines(
    source_lines: list[str],
    start_line: int,
    value_start: int,
    end_line: int,
    line_guards: dict[int, tuple[VarGuard, ...]],
) -> list[SymOcc]:
    occurrences = _recover_variable_references_from_text(
        source_lines[start_line][value_start:],
        start_line,
        value_start,
        context=_symbol_context('assignment', 'assignment_value', line_guards, start_line),
    )
    for line_number in range(start_line + 1, end_line + 1):
        occurrences.extend(
            _recover_variable_references_from_text(
                source_lines[line_number],
                line_number,
                context=_symbol_context('assignment', 'assignment_value', line_guards, line_number),
            )
        )
    return occurrences


def _with_variable_comments(
    definition: VarDef,
    source_lines: list[str],
) -> VarDef:
    documentation = _leading_comment_block(
        source_lines,
        definition.assignment_span.start_line,
    )
    if documentation is None:
        return definition

    return VarDef(
        name=definition.name,
        name_span=definition.name_span,
        assignment_span=definition.assignment_span,
        operator=definition.operator,
        value=definition.value,
        documentation=documentation,
    )


def _leading_comment_block(source_lines: list[str], line_number: int) -> str | None:
    comment_lines: list[str] = []

    for current_line in range(line_number - 1, -1, -1):
        match = COMMENT_RE.match(source_lines[current_line])
        if match is None:
            break

        text = match.group('text').removeprefix(' ')
        comment_lines.append(text.rstrip())

    if not comment_lines:
        return None

    comment_lines.reverse()
    return '\n'.join(comment_lines)


def _recover_assignment_value_diagnostics(
    line: str,
    line_number: int,
    value_start: int,
    value: str,
) -> list[lsp.Diagnostic]:
    if has_unescaped_line_continuation(value):
        return []

    open_references: list[tuple[int, str]] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == '$' and index + 1 < len(value):
            next_character = value[index + 1]
            if next_character == '$':
                index += 2
                continue

            expected_closer = VARIABLE_REFERENCE_DELIMITERS.get(next_character)
            if expected_closer is not None:
                open_references.append((index, expected_closer))
                index += 2
                continue

            # Single-character variables such as `$@` and `$x` are valid Make syntax.
            index += 2
            continue

        if open_references and character == open_references[-1][1]:
            _ = open_references.pop()
        index += 1

    if not open_references:
        return []

    reference_start, _expected_closer = open_references[0]
    return [
        lsp.Diagnostic(
            range=Span(
                line_number,
                value_start + reference_start,
                line_number,
                len(line),
            ).to_lsp_range(),
            message=_diagnostic_message(
                'Invalid variable reference in assignment',
                value[reference_start:],
            ),
            severity=lsp.DiagnosticSeverity.Error,
            source='make-ls',
        )
    ]


def _diagnostic_message(prefix: str, snippet: str) -> str:
    compact_snippet = ' '.join(snippet.split())
    if compact_snippet == '':
        return prefix

    if len(compact_snippet) > 40:
        compact_snippet = compact_snippet[:37] + '...'
    return f'{prefix}: `{compact_snippet}`'
