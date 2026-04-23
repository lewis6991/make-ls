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


def test_analyze_document_recovers_grouped_targets_without_ampersand_target() -> None:
    document = analyze_document(
        "file:///Makefile",
        None,
        "out1 out2 &: dep\n\t@echo hi\n\ndep:\n\t@echo dep\n",
    )

    assert set(document.targets) == {"dep", "out1", "out2"}
    assert "&" not in document.targets
    assert document.targets["out1"][0].prerequisites == ("dep",)
    assert document.targets["out2"][0].prerequisites == ("dep",)
    assert document.diagnostics == ()


def test_analyze_document_recovers_grouped_targets_with_late_separator() -> None:
    document = analyze_document(
        "file:///Makefile",
        None,
        (
            "out1 \\\n"
            "  out2 &: dep \\\n"
            "  extra\n"
            "\t@echo hi\n"
            "\n"
            "dep:\n"
            "\t@echo dep\n"
            "extra:\n"
            "\t@echo extra\n"
        ),
    )

    assert set(document.targets) == {"dep", "extra", "out1", "out2"}
    assert document.targets["out1"][0].prerequisites == ("dep", "extra")
    assert document.targets["out1"][0].name_span.start_line == 0
    assert document.targets["out2"][0].prerequisites == ("dep", "extra")
    assert document.targets["out2"][0].name_span.start_line == 1
    assert document.diagnostics == ()
