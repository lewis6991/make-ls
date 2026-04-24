from __future__ import annotations

import pytest

from make_ls.analysis import analyze_document
from make_ls.types import VarGuard


def test_analyze_document_recovers_contextual_symbol_sites() -> None:
    document = analyze_document(
        'file:///Makefile',
        None,
        'ifneq ($(FEATURE),)\nRESULT := $(FEATURE)\nendif\n',
    )

    assert [form.kind for form in document.forms] == ['conditional', 'assignment']

    test_occurrence = next(
        occurrence
        for occurrence in document.occurrences
        if occurrence.span.start_line == 0 and occurrence.name == 'FEATURE'
    )
    assert test_occurrence.context is not None
    assert test_occurrence.context.form_kind == 'conditional'
    assert test_occurrence.context.kind == 'conditional_test'

    guarded_occurrence = next(
        occurrence
        for occurrence in document.occurrences
        if occurrence.span.start_line == 1
        and occurrence.role == 'reference'
        and occurrence.name == 'FEATURE'
    )
    assert guarded_occurrence.context is not None
    assert guarded_occurrence.context.form_kind == 'assignment'
    assert guarded_occurrence.context.kind == 'assignment_value'
    assert guarded_occurrence.context.active_guards == (VarGuard('FEATURE', 'nonempty'),)


def test_analyze_document_recovers_grouped_targets_without_ampersand_target() -> None:
    document = analyze_document(
        'file:///Makefile',
        None,
        'out1 out2 &: dep\n\t@echo hi\n\ndep:\n\t@echo dep\n',
    )

    assert set(document.targets) == {'dep', 'out1', 'out2'}
    assert '&' not in document.targets
    assert document.targets['out1'][0].prerequisites == ('dep',)
    assert document.targets['out2'][0].prerequisites == ('dep',)
    assert document.diagnostics == ()


def test_analyze_document_recovers_grouped_targets_with_late_separator() -> None:
    document = analyze_document(
        'file:///Makefile',
        None,
        (
            'out1 \\\n'
            '  out2 &: dep \\\n'
            '  extra\n'
            '\t@echo hi\n'
            '\n'
            'dep:\n'
            '\t@echo dep\n'
            'extra:\n'
            '\t@echo extra\n'
        ),
    )

    assert set(document.targets) == {'dep', 'extra', 'out1', 'out2'}
    assert document.targets['out1'][0].prerequisites == ('dep', 'extra')
    assert document.targets['out1'][0].name_span.start_line == 0
    assert document.targets['out2'][0].prerequisites == ('dep', 'extra')
    assert document.targets['out2'][0].name_span.start_line == 1
    assert document.diagnostics == ()


def test_analyze_document_allows_direct_recipe_local_eval_variables() -> None:
    document = analyze_document(
        'file:///Makefile',
        None,
        (
            '.venv_%:\n'
            '\t$(eval OS=$(word 1,$(subst _, ,$*)))\n'
            '\t$(eval ARCH=$(word 2,$(subst _, ,$*)))\n'
            "\tprintf '%s %s\\n' $(OS) $(ARCH)\n"
            '\n'
            'other:\n'
            "\tprintf '%s\\n' $(OS)\n"
        ),
    )

    assert len(document.diagnostics) == 1
    assert document.diagnostics[0].message == 'Unknown variable reference: `$(OS)`'
    assert document.diagnostics[0].range.start.line == 6


@pytest.mark.parametrize(
    ('source', 'expected_codes'),
    [
        ('all dep\n', ('invalid-makefile-syntax',)),
        ('FOO := $(BAR\n', ('invalid-variable-reference-in-assignment',)),
        ('else\nall:\n\t@echo hi\n', ('unexpected-else',)),
        ('ifdef FOO\nelse\nelse\nendif\n', ('duplicate-else',)),
        ('endif\n', ('unexpected-endif',)),
        ('endef\n', ('unexpected-endef',)),
        ('ifdef FOO\nall:\n\t@echo hi\n', ('missing-endif',)),
        ('define FOO\nbar\n', ('missing-endef',)),
        ('all:\n\tif true; then echo hi\n', ('invalid-shell-syntax',)),
        ('all:\n\t@echo $(__MAKE_LS_MISSING_VAR__)\n', ('unknown-variable',)),
        ('OUT := $@\n', ('automatic-variable-outside-recipe',)),
        ('include missing.mk\n', ('unresolved-include',)),
        ('all: __make_ls_missing_dep__\n\t@echo hi\n', ('unresolved-prerequisite',)),
        ('all:\n\t@echo first\nall:\n\t@echo second\n', ('overriding-recipe',)),
        ('all:\n\t@echo one\nall::\n\t@echo two\n', ('mixed-rule-separator',)),
        ('a: b\n\t@:\nb: a\n\t@:\n', ('circular-prerequisite',)),
    ],
)
def test_analyze_document_sets_codes_for_all_diagnostics(
    source: str,
    expected_codes: tuple[str, ...],
) -> None:
    document = analyze_document(
        'file:///definitely-not-a-real-make-ls-test-dir/Makefile',
        None,
        source,
    )

    assert tuple(diagnostic.code for diagnostic in document.diagnostics) == expected_codes
