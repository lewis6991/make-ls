from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .lsp_harness import LspSession
from .lsp_test_utils import hover_value

if TYPE_CHECKING:
    from pathlib import Path

    from make_ls.types import AnalyzedDoc


@pytest.mark.asyncio
async def test_hover_for_builtin_ifeq_directive(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nRESULT := yes\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nifeq (arg1, arg2)\n```')
    assert 'GNU Make directive' in value
    assert 'two expanded arguments are equal' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_else_directive(tmp_path: Path) -> None:
    text = 'ifeq ($(MODE),test)\nRESULT := yes\nelse\nRESULT := no\nendif\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nelse\n```')
    assert 'alternate branch of a conditional' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_define_directive(tmp_path: Path) -> None:
    text = 'define BODY\n\t@echo hi\nendef\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 2)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndefine variable\n```')
    assert 'multi-line variable definition' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_findstring_function(tmp_path: Path) -> None:
    text = 'X := $(findstring a,$(Y))\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(findstring find,in)\n```')
    assert 'Return `find` if it appears in `in`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_dir_function(tmp_path: Path) -> None:
    text = 'X := $(dir src/foo.c)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 8)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(dir names...)\n```')
    assert 'directory part of each file name' in value
    assert '`./`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_abspath_function(tmp_path: Path) -> None:
    text = 'X := $(abspath ../foo)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(abspath names...)\n```')
    assert 'absolute path' in value
    assert 'without resolving symlinks' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_make_variable(tmp_path: Path) -> None:
    text = 'all:\n\t$(MAKE) -C subdir\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 1, 4)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(MAKE)\n```')
    assert 'GNU Make variable' in value
    assert 'The name with which `make` was invoked' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_recursive_make_variables(tmp_path: Path) -> None:
    text = 'vars := $(MAKEOVERRIDES) $(MFLAGS)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        makeoverrides_hover = await session.hover(uri, 0, 11)
        mflags_hover = await session.hover(uri, 0, 28)

    assert diagnostics == []

    assert makeoverrides_hover is not None
    makeoverrides_value = hover_value(makeoverrides_hover)
    assert makeoverrides_value.startswith('```make\n$(MAKEOVERRIDES)\n```')
    assert 'command-line variable definitions' in makeoverrides_value
    assert '`MAKEFLAGS`' in makeoverrides_value

    assert mflags_hover is not None
    mflags_value = hover_value(mflags_hover)
    assert mflags_value.startswith('```make\n$(MFLAGS)\n```')
    assert 'Historical compatibility variable' in mflags_value
    assert '`MAKEFLAGS`' in mflags_value


@pytest.mark.asyncio
async def test_hover_for_builtin_special_variable_and_skips_unknown_warning(
    tmp_path: Path,
) -> None:
    text = 'goal := $(.DEFAULT_GOAL)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 12)

    assert diagnostics == []
    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(.DEFAULT_GOAL)\n```')
    assert 'current default goal' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_shellflags_variable_and_skips_unknown_warning(
    tmp_path: Path,
) -> None:
    text = 'flags := $(.SHELLFLAGS)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 13)

    assert diagnostics == []
    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n$(.SHELLFLAGS)\n```')
    assert 'Arguments passed to the shell used for recipes' in value
    assert '`-c`' in value


@pytest.mark.asyncio
async def test_hover_for_builtin_automatic_variables(tmp_path: Path) -> None:
    text = 'all: dep\n\tcp $< $@\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        first_prerequisite_hover = await session.hover(uri, 1, 5)
        target_hover = await session.hover(uri, 1, 8)

    assert first_prerequisite_hover is not None
    first_value = hover_value(first_prerequisite_hover)
    assert first_value.startswith('```make\n$<\n```')
    assert 'name of the first prerequisite' in first_value

    assert target_hover is not None
    target_value = hover_value(target_hover)
    assert target_value.startswith('```make\n$@\n```')
    assert 'file name of the target' in target_value


@pytest.mark.asyncio
async def test_builtin_variable_hover_does_not_override_local_definition(tmp_path: Path) -> None:
    text = 'MAKE := wrapper\nall:\n\t@echo $(MAKE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nMAKE := wrapper\n```')
    assert 'GNU Make variable' not in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference_falls_back_to_included_makefile(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text('FEATURE := enabled\n', encoding='utf-8')
    text = 'include rules.mk\nall:\n\t@echo $(FEATURE)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nFEATURE := enabled\n```')


@pytest.mark.asyncio
async def test_hover_for_builtin_special_target_overrides_generic_target_hover(
    tmp_path: Path,
) -> None:
    text = '.PHONY: clean\nclean:\n\t@echo clean\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\n.PHONY: targets...\n```')
    assert 'always treated as phony targets' in value
    assert 'Dependency Tree:' not in value


@pytest.mark.asyncio
async def test_builtin_function_hover_does_not_override_variable_hover(tmp_path: Path) -> None:
    text = 'dir := build\nall:\n\t@echo $(dir)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndir := build\n```')
    assert 'GNU Make function' not in value


@pytest.mark.asyncio
async def test_hover_for_target_definition(tmp_path: Path) -> None:
    text = 'all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall: dep\n\t@echo done\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`all`  \n└─\u00a0`dep`' in value


@pytest.mark.asyncio
async def test_hover_for_multitarget_rule_keeps_full_rule_text(tmp_path: Path) -> None:
    text = 'all lint: dep\n\t@echo $^\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 5)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall lint: dep\n\t@echo $^\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`lint`  \n└─\u00a0`dep`' in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_includes_recursive_dependency_tree(
    tmp_path: Path,
) -> None:
    text = """\
all: dep tools
\t@echo done

dep: lib
\t@echo dep

tools: helper
\t@echo tools

lib:
\t@echo lib

helper:
\t@echo helper
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = (
        'Dependency Tree:\n\n'
        '`all`  \n'
        '├─\u00a0`dep`  \n'
        '│\u00a0\u00a0└─\u00a0`lib`  \n'
        '└─\u00a0`tools`  \n'
        '\u00a0\u00a0\u00a0└─\u00a0`helper`'
    )
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_deduplicates_shared_dependency_branches(
    tmp_path: Path,
) -> None:
    text = """\
all: build deps
\t@echo all

build: | deps
\t@echo build

deps: prep
\t@echo deps

prep:
\t@echo prep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = (
        'Dependency Tree:\n\n'
        '`all`  \n'
        '├─\u00a0`build`  \n'
        '│\u00a0\u00a0└─\u00a0`deps` ...  \n'
        '└─\u00a0`deps`  \n'
        '\u00a0\u00a0\u00a0└─\u00a0`prep`'
    )
    assert expected_tree in value
    assert (
        '│\u00a0\u00a0└─\u00a0`deps`  \n│\u00a0\u00a0\u00a0\u00a0\u00a0└─\u00a0`prep`' not in value
    )


@pytest.mark.asyncio
async def test_hover_for_target_definition_distinguishes_phony_and_path_targets(
    tmp_path: Path,
) -> None:
    text = """\
.PHONY: all clean
all: clean build/output.txt
\t@echo done

clean:
\t@echo clean
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 1, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = 'Dependency Tree:\n\n*all*  \n├─\u00a0*clean*  \n└─\u00a0`build/output.txt`'
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_honors_later_phony_declarations(
    tmp_path: Path,
) -> None:
    text = """\
all: nvim
\t@echo all

.PHONY: clean
clean:
\t@echo clean

.PHONY: nvim
nvim: clean
\t@echo nvim
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 8, 1)

    assert hover is not None
    value = hover_value(hover)
    expected_tree = 'Dependency Tree:\n\n*nvim*  \n└─\u00a0*clean*'
    assert expected_tree in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_marks_dependency_cycles(tmp_path: Path) -> None:
    text = """\
all: dep
\t@echo done

dep: all
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert (
        'Dependency Tree:\n\n`all`  \n└─\u00a0`dep`  \n\u00a0\u00a0\u00a0└─\u00a0`all` (cycle)'
        in value
    )


@pytest.mark.asyncio
async def test_hover_for_target_reference_includes_full_multiline_make_rule(
    tmp_path: Path,
) -> None:
    text = """\
all: lint_jenkins
\t@echo ok

lint_jenkins: jenkins-cli.jar
\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\
\t\tetc_dev/jenkins_lint \\
\t\t--cli $(PWD)/$^ \\
\t\t--user $(JENKINS_USER)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith(
        '```make\n'
        'lint_jenkins: jenkins-cli.jar\n'
        '\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\\n'
        '\t\tetc_dev/jenkins_lint \\\n'
        '\t\t--cli $(PWD)/$^ \\\n'
        '\t\t--user $(JENKINS_USER)\n'
        '```'
    )
    assert ('\n\n---\n\nDependency Tree:\n\n`lint_jenkins`  \n└─\u00a0`jenkins-cli.jar`') in value


@pytest.mark.asyncio
async def test_hover_for_target_reference_falls_back_to_included_makefile(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text(
        'dep: tool\n\t@echo dep\n\ntool:\n\t@echo tool\n',
        encoding='utf-8',
    )
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndep: tool\n\t@echo dep\n```')
    assert 'Dependency Tree:\n\n`dep`  \n└─\u00a0`tool`' in value


@pytest.mark.asyncio
async def test_hover_for_local_target_does_not_follow_includes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = (tmp_path / 'rules.mk').write_text('all:\n\t@echo remote\n', encoding='utf-8')
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n\ndep:\n\t@echo dep\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)

        def fail_included_documents(_uri: str) -> tuple[AnalyzedDoc, ...]:
            raise AssertionError('local hover should not follow includes')

        monkeypatch.setattr(session.server, 'included_documents', fail_included_documents)
        hover = await session.hover(uri, 2, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nall: dep\n\t@echo done\n```')


@pytest.mark.asyncio
async def test_hover_for_ambiguous_included_target_returns_none(tmp_path: Path) -> None:
    _ = (tmp_path / 'a.mk').write_text('dep:\n\t@echo a\n', encoding='utf-8')
    _ = (tmp_path / 'b.mk').write_text('dep:\n\t@echo b\n', encoding='utf-8')
    text = 'include a.mk b.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is None


@pytest.mark.asyncio
async def test_hover_for_target_reference_follows_nested_includes(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / 'more.mk').write_text('tool:\n\t@echo tool\n', encoding='utf-8')
    _ = (tmp_path / 'rules.mk').write_text(
        'include more.mk\n\ndep: tool\n\t@echo dep\n',
        encoding='utf-8',
    )
    text = 'include rules.mk\n\nall: dep\n\t@echo done\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 6)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\ndep: tool\n\t@echo dep\n```')


@pytest.mark.asyncio
async def test_hover_for_target_reference_ignores_following_conditional_block(
    tmp_path: Path,
) -> None:
    text = """\
release: dep
\t@echo $@

ifeq ($(X),1)
Y := 1
endif

publish: release
\t@echo ok

dep:
\t@echo dep
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 7, 10)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nrelease: dep\n\t@echo $@\n```')
    assert '\n\n---\n\nDependency Tree:\n\n`release`  \n└─\u00a0`dep`' in value
    assert 'ifeq ($(X),1)' not in value
    assert 'Y := 1' not in value


@pytest.mark.asyncio
async def test_hover_for_target_definition_includes_full_multiline_make_rule(
    tmp_path: Path,
) -> None:
    text = """\
lint_jenkins: jenkins-cli.jar
\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\
\t\tetc_dev/jenkins_lint \\
\t\t--cli $(PWD)/$^ \\
\t\t--user $(JENKINS_USER)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith(
        '```make\n'
        'lint_jenkins: jenkins-cli.jar\n'
        '\t$(MRUN) +swdev +oracle/openjdk/17.0.4.1 \\\n'
        '\t\tetc_dev/jenkins_lint \\\n'
        '\t\t--cli $(PWD)/$^ \\\n'
        '\t\t--user $(JENKINS_USER)\n'
        '```'
    )
    assert ('\n\n---\n\nDependency Tree:\n\n`lint_jenkins`  \n└─\u00a0`jenkins-cli.jar`') in value
    assert 'Recipe:\n```sh\n' not in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference(tmp_path: Path) -> None:
    text = 'FOO := hello\nall:\n\t@echo $(FOO)\n'

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nFOO := hello\n```')
    assert 'Value:' not in value


@pytest.mark.asyncio
async def test_hover_for_multiline_variable_reference_does_not_duplicate_value(
    tmp_path: Path,
) -> None:
    text = """\
DECORATE = \\
    first \\
    second
all:
\t@echo $(DECORATE)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 11)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nDECORATE = \\')
    assert 'first \\\n    second' in value
    assert 'Value:' not in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference_includes_leading_comments(
    tmp_path: Path,
) -> None:
    text = """\
# Path to the local virtualenv.
# Used by lint and test targets.
VENV := .venv
all:
\t@echo $(VENV)
"""

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 4, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith('```make\nVENV := .venv\n```')
    assert 'Path to the local virtualenv.\nUsed by lint and test targets.' in value
    assert 'Value:' not in value
