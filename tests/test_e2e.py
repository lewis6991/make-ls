from __future__ import annotations

from pathlib import Path

import pytest
from lsprotocol import types as lsp

from .lsp_harness import LspSession


def hover_value(hover: lsp.Hover) -> str:
    contents = hover.contents
    if isinstance(contents, lsp.MarkupContent):
        return contents.value
    if isinstance(contents, str):
        return contents
    raise AssertionError("expected markdown hover content")


def single_location(definition: lsp.Location | list[lsp.Location] | None) -> lsp.Location:
    if isinstance(definition, lsp.Location):
        return definition
    if isinstance(definition, list) and len(definition) == 1:
        return definition[0]
    raise AssertionError("expected a single definition location")


@pytest.mark.asyncio
async def test_reports_makefile_syntax_diagnostics(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", "all dep\n")
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message.startswith("Invalid Makefile syntax")


@pytest.mark.asyncio
async def test_accepts_empty_variable_assignments(tmp_path: Path) -> None:
    text = "EMPTY ?=\nall:\n\t@echo ok\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert diagnostics == []


@pytest.mark.asyncio
async def test_reports_shell_syntax_diagnostics_for_recipe_lines(tmp_path: Path) -> None:
    text = "all:\n\t@if true; then echo hi\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].message.startswith("Invalid shell syntax in recipe")


@pytest.mark.asyncio
async def test_reports_multiline_shell_syntax_diagnostics(tmp_path: Path) -> None:
    text = "all:\n\tif true; then \\\n\t  echo hi\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        diagnostics = await session.wait_for_diagnostics(uri)

    assert len(diagnostics) == 1
    assert diagnostics[0].range.start.line == 1
    assert diagnostics[0].message.startswith("Invalid shell syntax in recipe")


@pytest.mark.asyncio
async def test_hover_for_target_definition(tmp_path: Path) -> None:
    text = "all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 0, 1)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith("```make\nall\n```")
    assert "Prerequisites: dep" in value
    assert "Recipe: `echo done`" in value


@pytest.mark.asyncio
async def test_hover_for_variable_reference(tmp_path: Path) -> None:
    text = "FOO := hello\nall:\n\t@echo $(FOO)\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        _ = await session.wait_for_diagnostics(uri)
        hover = await session.hover(uri, 2, 9)

    assert hover is not None
    value = hover_value(hover)
    assert value.startswith("```make\nFOO := hello\n```")
    assert "Value: `hello`" in value


@pytest.mark.asyncio
async def test_go_to_definition_for_prerequisite(tmp_path: Path) -> None:
    text = "all: dep\n\t@echo done\n\ndep:\n\t@echo dep\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 0, 6)

    location = single_location(definition)
    assert location.range.start.line == 3
    assert location.range.start.character == 0


@pytest.mark.asyncio
async def test_go_to_definition_for_variable_reference(tmp_path: Path) -> None:
    text = "FOO := hello\nBAR = $(FOO)\n"

    async with LspSession(tmp_path) as session:
        uri = await session.open_document("Makefile", text)
        _ = await session.wait_for_diagnostics(uri)
        definition = await session.definition(uri, 1, 7)

    location = single_location(definition)
    assert location.range.start.line == 0
    assert location.range.start.character == 0
