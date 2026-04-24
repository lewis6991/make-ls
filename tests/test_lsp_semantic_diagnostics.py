from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference(tmp_path: Path) -> None:
    text = 'all:\n\t@echo $(missing_var)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unknown variable reference: `$(missing_var)`'


@pytest.mark.asyncio
async def test_warns_for_unresolved_prerequisite(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unresolved prerequisite: `dep`'


@pytest.mark.asyncio
async def test_does_not_warn_for_existing_file_prerequisite(tmp_path: Path) -> None:
    _ = (tmp_path / 'dep').write_text('done\n', encoding='utf-8')
    text = 'all: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_explicit_target_prerequisite(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_prerequisite_matching_pattern_rule(tmp_path: Path) -> None:
    text = 'build_all: build_alpha\n\t@echo done\n\nbuild_%:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_target_specific_variable_assignment(tmp_path: Path) -> None:
    text = 'suite/% : CASES=cases/suite\nsample/%: CASES=cases/sample\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_included_target_prerequisite(tmp_path: Path) -> None:
    _ = (tmp_path / 'rules.mk').write_text('dep:\n\t@echo dep\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_variable_defined_in_included_makefile(tmp_path: Path) -> None:
    _ = (tmp_path / 'rules.mk').write_text('FEATURE := enabled\n', encoding='utf-8')
    text = 'include rules.mk\n\nall:\n\t@echo $(FEATURE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unresolved_include(tmp_path: Path) -> None:
    text = 'include missing.mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unresolved include: `missing.mk`'


@pytest.mark.asyncio
async def test_does_not_warn_for_generated_include_target(tmp_path: Path) -> None:
    text = 'include deps.mk\n\ndeps.mk:\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_optional_missing_include(tmp_path: Path) -> None:
    text = '-include local.mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_phony_prerequisite(tmp_path: Path) -> None:
    text = '.PHONY: clean\nall: clean\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_dynamic_include(tmp_path: Path) -> None:
    text = 'include $(missing).mk\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Unknown variable reference: `$(missing)`'


@pytest.mark.asyncio
async def test_warns_for_automatic_variable_reference_outside_recipe(tmp_path: Path) -> None:
    text = 'DEST := $@\nall:\n\t@echo $@\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].range.start.character == 8
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Automatic variable outside recipe context: `$@`'


@pytest.mark.asyncio
async def test_does_not_warn_for_automatic_variable_reference_in_prerequisite(
    tmp_path: Path,
) -> None:
    text = 'all: $@\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_overriding_recipe_for_target(tmp_path: Path) -> None:
    text = 'all:\n\t@echo one\n\nall:\n\t@echo two\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 3
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Overriding recipe for target: `all`'


@pytest.mark.asyncio
async def test_does_not_warn_for_overriding_double_colon_recipe(tmp_path: Path) -> None:
    text = 'all::\n\t@echo one\n\nall::\n\t@echo two\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_errors_for_target_with_both_single_and_double_colon_rules(tmp_path: Path) -> None:
    text = 'all:\n\t@echo one\n\nall::\n\t@echo two\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 3
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Target has both : and :: rules: `all`'


@pytest.mark.asyncio
async def test_warns_for_circular_prerequisite_cycle(tmp_path: Path) -> None:
    text = 'a: b\n\t@echo a\n\nb: a\n\t@echo b\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message == 'Circular prerequisite cycle: `a, b`'


@pytest.mark.asyncio
async def test_does_not_warn_for_environment_variable_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('MAKE_LS_TEST_ENV_VAR', '1')
    text = 'all:\n\t@echo $(MAKE_LS_TEST_ENV_VAR)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_uppercase_variable_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('OUTPUT_DECORATOR', raising=False)
    text = 'all:\n\t@echo $(OUTPUT_DECORATOR)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_does_not_warn_for_unknown_variable_reference_in_nonempty_guarded_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifneq ($(FEATURE),)\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_does_not_warn_for_unknown_variable_reference_in_nonempty_else_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifeq ($(FEATURE),)\nelse\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_empty_guarded_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifeq ($(FEATURE),)\nall:\n\t@echo $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_in_guarded_assignment_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    text = 'ifneq ($(FEATURE),)\nRESULT = $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_unknown_variable_reference_when_guard_variable_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('FEATURE', raising=False)
    monkeypatch.delenv('OTHER', raising=False)
    text = 'ifneq ($(OTHER),)\nRESULT = $(FEATURE)\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_does_not_warn_for_forward_variable_reference(tmp_path: Path) -> None:
    text = 'BAR = $(foo)\nfoo := hello\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_skips_unknown_variable_warning_for_computed_variable_names(
    tmp_path: Path,
) -> None:
    text = 'PAPER := a4\nall:\n\t@echo $(PAPEROPT_$(PAPER))\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []
