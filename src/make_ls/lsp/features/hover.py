"""Hover handler over local and included recovered documents."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from lsprotocol import types as lsp

from make_ls.analysis.hover import hover_for_pos

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer, WorkspaceProtocol

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)


def hover(ls: FeatureServer, params: lsp.HoverParams) -> lsp.Hover | None:
    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    source_lines = tuple(text_document.source.splitlines())
    hover_result = hover_for_pos(
        document,
        params.position,
        source_lines=source_lines,
    )
    if hover_result is not None:
        LOGGER.debug(
            'textDocument/hover uri=%s position=%d:%d result=local',
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
        )
        return hover_result

    documents = ls.included_documents(params.text_document.uri)
    hover_result = hover_for_pos(document, params.position, documents[1:], source_lines)
    LOGGER.debug(
        'textDocument/hover uri=%s position=%d:%d result=%s includes=%d',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        'included' if hover_result is not None else 'miss',
        len(documents) - 1,
    )
    return hover_result
