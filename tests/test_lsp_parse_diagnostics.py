from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession
from .lsp_test_utils import hover_value, single_location

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_reports_makefile_syntax_diagnostics(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'all dep\n')
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message == 'Invalid Makefile syntax: `all dep`'


@pytest.mark.asyncio
async def test_accepts_empty_variable_assignments(tmp_path: Path) -> None:
    text = 'EMPTY ?=\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_recovers_variable_assignments_when_parser_loses_sync(tmp_path: Path) -> None:
    text = """\
PREPEND_STDOUT = | awk '{ print "$(CYAN_DIM)$(1):$(NC)", $$0; fflush(); }'
COLOR_PATTERN = | $(SED) "s/$(1)/$$(printf "$(2)\\\\\\0$(NC)")/g"
VENV := .venv
all: $(VENV)
\t@echo ok
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 3, 8)
        definition = await session.definition(uri, 3, 8)

    assert all(diagnostic.severity != lsp.DiagnosticSeverity.Error for diagnostic in diagnostics)
    assert hover is not None
    assert 'VENV := .venv' in hover_value(hover)
    location = single_location(definition)
    assert location.range.start.line == 2
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_reports_unterminated_parenthesized_variable_reference_in_recovered_assignment(
    tmp_path: Path,
) -> None:
    text = 'BROKEN = $(BAR\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].message == 'Invalid variable reference in assignment: `$(BAR`'


@pytest.mark.asyncio
async def test_reports_unterminated_braced_variable_reference_in_recovered_assignment(
    tmp_path: Path,
) -> None:
    text = 'BROKEN = ${BAR\nall:\n\t@echo ok\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].message.startswith('Invalid variable reference in assignment')


@pytest.mark.asyncio
async def test_warns_for_missing_endif(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nall:\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Missing endif for conditional block'


@pytest.mark.asyncio
async def test_warns_for_unexpected_endif(tmp_path: Path) -> None:
    text = 'endif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Unexpected endif directive'


@pytest.mark.asyncio
async def test_warns_for_duplicate_else(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nelse\nelse\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Duplicate else directive'


@pytest.mark.asyncio
async def test_accepts_else_ifeq_chain(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),one)\nX := 1\nelse ifeq ($(MODE),two)\nX := 2\nelse\nX := 3\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_warns_for_missing_endef(tmp_path: Path) -> None:
    text = 'define BODY\n\t@echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Missing endef for define block'


@pytest.mark.asyncio
async def test_warns_for_unexpected_endef(tmp_path: Path) -> None:
    text = 'endef\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 0
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Error
    assert diagnostics[0].message == 'Unexpected endef directive'


@pytest.mark.asyncio
async def test_accepts_make_automatic_variables_in_recipe_shell(tmp_path: Path) -> None:
    text = """\
all: dep
\tcp $< $@
\tprintf '%s\\n' $^
dep:
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_reports_shell_syntax_diagnostics_for_recipe_lines(tmp_path: Path) -> None:
    text = 'all:\n\t@if true; then echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message == 'Invalid shell syntax in recipe: `if true; then echo hi`'


@pytest.mark.asyncio
async def test_reports_multiline_shell_syntax_diagnostics(tmp_path: Path) -> None:
    text = 'all:\n\tif true; then \\\n\t  echo hi\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].message.startswith('Invalid shell syntax in recipe')


@pytest.mark.asyncio
async def test_did_change_still_republishes_non_shell_diagnostics(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'FOO := ok\nall:\n\t@echo $(FOO)\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.change_document(uri, 'FOO := ok\nall:\n\t@echo $(BAR)\n')
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 2
    assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning
    assert diagnostics[0].message.startswith('Unknown variable reference')


@pytest.mark.asyncio
async def test_shell_syntax_diagnostics_return_on_save(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', 'all:\n\t@echo hi\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.change_document(uri, 'all:\n\t@if true; then echo hi\n')
        diagnostics = await session.wait_for_diagnostics(uri)
        assert diagnostics == []

        await session.save_document(uri)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].message.startswith('Invalid shell syntax in recipe')


@pytest.mark.asyncio
async def test_accepts_multiline_recipe_continuations(tmp_path: Path) -> None:
    text = """\
prefix := /usr/local
pkglibdir := /usr/local/lib
MAJOR := 3
MINOR := 2
PATCH := 1

all:
\tsed \\
\t\t-e 's#PREFIX#$(prefix)#' \\
\t\t-e 's#LIBDIR#$(pkglibdir)#' \\
\t\t-e 's#VERSION#$(MAJOR).$(MINOR).$(PATCH)#' \\
\t\tlibutf8proc.pc.in > libutf8proc.pc
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_accepts_neovim_style_gnu_make_blocks(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq ($(UNIX_LIKE),FALSE)',
                '  SHELL := powershell.exe',
                'else',
                '  CMAKE := $(shell (command -v cmake3 || command -v cmake || echo cmake))',
                '  CMAKE_GENERATOR ?= "$(shell (command -v ninja > /dev/null 2>&1 '
                '&& echo "Ninja") || echo "Unix Makefiles")"',
                'endif',
                '',
                'iwyu:',
                '\tiwyu-fix-includes --only_re="src/nvim" --ignore_re="(src/nvim/eval/encode.c\\',
                '\t|src/nvim/auto/\\',
                '\t|src/nvim/os/lang.c\\',
                '\t|src/nvim/map.c\\',
                '\t)" --nosafe_headers < build/iwyu.log',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_recovers_targets_after_gnu_make_parser_desync(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq ($(UNIX_LIKE),FALSE)',
                '  SHELL := powershell.exe',
                'else',
                '  CMAKE := $(shell (command -v cmake3 || command -v cmake || echo cmake))',
                '  CMAKE_GENERATOR ?= "$(shell (command -v ninja > /dev/null 2>&1 '
                '&& echo "Ninja") || echo "Unix Makefiles")"',
                'endif',
                '',
                'nvim: deps',
                '\t$(CMAKE) --build build',
                '',
                'deps:',
                '\t@echo deps',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 7, 1)
        definition = await session.definition(uri, 7, 6)

    assert diagnostics == []
    assert hover is not None
    assert hover_value(hover).startswith('```make\nnvim: deps\n\t$(CMAKE) --build build\n```')
    location = single_location(definition)
    assert location.range.start.line == 10
    assert location.range.start.character == 0


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which('bash') is None, reason='requires bash for fallback shell syntax check'
)
async def test_accepts_nested_multiline_if_recipe(tmp_path: Path) -> None:
    text = """\
all:
\t@if [ -f build/.ran-cmake ]; then \\
\t  cached_prefix=$$(printf x); \\
\t  if ! [ "a" = "$$cached_prefix" ]; then \\
\t    printf '%s\\n' "$$cached_prefix"; \\
\t    rm -f build/.ran-cmake; \\
\t  fi \\
\tfi
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_shell_heavy_assignment_does_not_poison_later_rules(tmp_path: Path) -> None:
    text = (
        '\n'.join(
            [
                'ifeq (Windows,$(TARGET_SYS))',
                'TARGET_TESTUNWIND=$(shell exec 2>/dev/null; echo '
                "'extern void b(void);int a(void){b();return 0;}' | $(TARGET_CC) -c -x c - "
                '-o tmpunwind.o && { grep -qa -e eh_frame -e __unwind_info tmpunwind.o || '
                'grep -qU -e eh_frame -e __unwind_info tmpunwind.o; } && echo E; rm -f '
                'tmpunwind.o)',
                'endif',
                '',
                'amalg:',
                '\t$(MAKE) all "LJCORE_O=ljamalg.o"',
                '',
                'clean:',
                '\t@echo clean',
            ]
        )
        + '\n'
    )

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 1)

    assert all(diagnostic.severity != lsp.DiagnosticSeverity.Error for diagnostic in diagnostics)
    assert hover is not None
    assert hover_value(hover).startswith('```make\namalg:\n\t$(MAKE) all "LJCORE_O=ljamalg.o"\n```')
