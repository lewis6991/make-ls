from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lsprotocol import types as lsp

from make_ls import __main__ as cli

from .lsp_harness import LspSession

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_server_advertises_document_save_notifications(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        assert session.initialize_result is not None
        capabilities = session.initialize_result.capabilities

    assert isinstance(capabilities.text_document_sync, lsp.TextDocumentSyncOptions)
    assert capabilities.text_document_sync.save == lsp.SaveOptions(include_text=False)


@pytest.mark.asyncio
async def test_server_advertises_prepare_rename_support(tmp_path: Path) -> None:
    async with LspSession(tmp_path) as session:
        initialize_result = session.initialize_result

    assert initialize_result is not None
    rename_provider = initialize_result.capabilities.rename_provider
    assert isinstance(rename_provider, lsp.RenameOptions)
    assert rename_provider.prepare_provider is True


@pytest.mark.asyncio
async def test_server_writes_lsp_logs_when_configured(tmp_path: Path) -> None:
    log_path = tmp_path / 'make-ls.log'
    cli.configure_logging(log_path, 'debug')

    try:
        async with LspSession(tmp_path) as session:
            uri = await session.open_document('Makefile', 'FOO := hello\nall:\n\t@echo $(FOO)\n')
            _ = await session.wait_for_diagnostics(uri)
            _ = await session.hover(uri, 2, 9)
            _ = await session.definition(uri, 2, 9)
    finally:
        cli.configure_logging(None, 'debug')

    log_text = log_path.read_text(encoding='utf-8')
    assert 'textDocument/didOpen' in log_text
    assert f'uri={uri}' in log_text
    assert 'textDocument/publishDiagnostics' in log_text
    assert 'textDocument/hover' in log_text
    assert 'textDocument/definition' in log_text
