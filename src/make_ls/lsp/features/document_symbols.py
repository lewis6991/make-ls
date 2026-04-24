"""Document symbol handler over recovered target and variable definitions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from make_ls.analysis.document_symbols import document_symbols

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)(symbols)


def symbols(
    ls: FeatureServer,
    params: lsp.DocumentSymbolParams,
) -> list[lsp.DocumentSymbol]:
    symbol_list = document_symbols(ls.analyze_uri(params.text_document.uri))
    LOGGER.debug(
        'textDocument/documentSymbol uri=%s symbols=%d',
        params.text_document.uri,
        len(symbol_list),
    )
    return symbol_list
