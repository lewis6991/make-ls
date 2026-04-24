"""Document lifecycle handlers for diagnostics and cache invalidation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)
    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)
    _ = server.feature(lsp.TEXT_DOCUMENT_DID_SAVE, lsp.SaveOptions(include_text=False))(did_save)
    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(did_close)


def did_open(ls: FeatureServer, params: lsp.DidOpenTextDocumentParams) -> None:
    LOGGER.debug(
        'textDocument/didOpen uri=%s version=%s',
        params.text_document.uri,
        params.text_document.version,
    )
    ls.publish_document_diagnostics(
        params.text_document.uri,
        include_shell_diagnostics=True,
    )


def did_change(ls: FeatureServer, params: lsp.DidChangeTextDocumentParams) -> None:
    LOGGER.debug(
        'textDocument/didChange uri=%s version=%s changes=%d',
        params.text_document.uri,
        params.text_document.version,
        len(params.content_changes),
    )
    ls.publish_document_diagnostics(
        params.text_document.uri,
        include_shell_diagnostics=False,
    )


def did_save(ls: FeatureServer, params: lsp.DidSaveTextDocumentParams) -> None:
    LOGGER.debug('textDocument/didSave uri=%s', params.text_document.uri)
    ls.publish_document_diagnostics(
        params.text_document.uri,
        include_shell_diagnostics=True,
    )


def did_close(ls: FeatureServer, params: lsp.DidCloseTextDocumentParams) -> None:
    LOGGER.debug('textDocument/didClose uri=%s', params.text_document.uri)
    ls.clear_uri(params.text_document.uri)
    ls.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
    )
