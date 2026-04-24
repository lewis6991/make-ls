from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from pathlib import Path

    from lsprotocol import types as lsp


def signature_parameter_labels(signature: lsp.SignatureInformation) -> list[str]:
    labels: list[str] = []
    for parameter in signature.parameters or ():
        assert isinstance(parameter.label, str)
        labels.append(parameter.label)
    return labels


def signature_documentation_value(signature: lsp.SignatureInformation) -> str | None:
    documentation = signature.documentation
    if documentation is None or isinstance(documentation, str):
        return documentation
    return documentation.value


@pytest.mark.asyncio
async def test_signature_help_for_builtin_subst_function(tmp_path: Path) -> None:
    text = 'RESULT := $(subst from,to,text)\n'
    character = text.index('from') + 1

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        _ = await session.wait_for_diagnostics(uri)
        signature_help = await session.signature_help(uri, 0, character)

    assert signature_help is not None
    assert signature_help.active_signature == 0
    assert signature_help.active_parameter == 0

    signature = signature_help.signatures[0]
    assert signature.label == '$(subst from,to,text)'
    assert signature_parameter_labels(signature) == ['from', 'to', 'text']

    documentation = signature_documentation_value(signature)
    assert documentation is not None
    assert documentation.startswith('GNU Make function\n\n')
    assert 'Replace every occurrence of `from` with `to` in `text`.' in documentation


@pytest.mark.asyncio
async def test_signature_help_tracks_optional_if_else_parameter(tmp_path: Path) -> None:
    text = 'MODE := yes\nRESULT := $(if $(MODE),then,else)\n'
    line_text = text.splitlines()[1]
    character = line_text.index('else') + 1

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        signature_help = await session.signature_help(uri, 1, character)

    assert diagnostics == []
    assert signature_help is not None
    assert signature_help.active_parameter == 2

    signature = signature_help.signatures[0]
    assert signature.active_parameter == 2
    assert signature.label == '$(if condition,then[,else])'
    assert signature_parameter_labels(signature) == ['condition', 'then', '[else]']


@pytest.mark.asyncio
async def test_signature_help_prefers_innermost_builtin_function(tmp_path: Path) -> None:
    text = 'VALUE :=  value  \nRESULT := $(subst from,$(strip $(VALUE)),text)\n'
    line_text = text.splitlines()[1]
    character = line_text.index('VALUE') + 1

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        signature_help = await session.signature_help(uri, 1, character)

    assert diagnostics == []
    assert signature_help is not None
    assert signature_help.active_parameter == 0

    signature = signature_help.signatures[0]
    assert signature.label == '$(strip string)'
    assert signature_parameter_labels(signature) == ['string']


@pytest.mark.asyncio
async def test_signature_help_skips_plain_variable_references(tmp_path: Path) -> None:
    text = 'RESULT := $(MAKE)\n'
    character = text.index('MAKE') + 1

    async with LspSession(tmp_path) as session:
        uri = await session.open_document('Makefile', text)
        diagnostics = await session.wait_for_diagnostics(uri)
        signature_help = await session.signature_help(uri, 0, character)

    assert diagnostics == []
    assert signature_help is None
