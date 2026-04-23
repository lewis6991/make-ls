from __future__ import annotations

from make_ls.analysis import analyze_document
from make_ls.types import VariableGuard


def test_analyze_document_recovers_contextual_symbol_sites() -> None:
    document = analyze_document(
        "file:///Makefile",
        None,
        "ifneq ($(FEATURE),)\nRESULT := $(FEATURE)\nendif\n",
    )

    assert [form.kind for form in document.forms] == ["conditional", "assignment"]

    test_occurrence = next(
        occurrence
        for occurrence in document.occurrences
        if occurrence.span.start_line == 0 and occurrence.name == "FEATURE"
    )
    assert test_occurrence.context is not None
    assert test_occurrence.context.form_kind == "conditional"
    assert test_occurrence.context.kind == "conditional_test"

    guarded_occurrence = next(
        occurrence
        for occurrence in document.occurrences
        if occurrence.span.start_line == 1
        and occurrence.role == "reference"
        and occurrence.name == "FEATURE"
    )
    assert guarded_occurrence.context is not None
    assert guarded_occurrence.context.form_kind == "assignment"
    assert guarded_occurrence.context.kind == "assignment_value"
    assert guarded_occurrence.context.active_guards == (
        VariableGuard("FEATURE", "nonempty"),
    )
