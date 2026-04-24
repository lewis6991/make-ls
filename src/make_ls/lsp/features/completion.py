"""Completion handler over recovered symbols and line context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from lsprotocol import types as lsp

from make_ls.analysis.completion import complete_for_pos

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer, WorkspaceProtocol

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(
        lsp.TEXT_DOCUMENT_COMPLETION,
        lsp.CompletionOptions(trigger_characters=['$', '(', '{', ':']),
    )(completion)


def completion(ls: FeatureServer, params: lsp.CompletionParams) -> list[lsp.CompletionItem] | None:
    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    source_lines = tuple(text_document.source.splitlines())
    related_documents = ls.included_documents(params.text_document.uri)[1:]
    completion_items = complete_for_pos(
        document,
        params.position,
        source_lines,
        related_documents,
    )
    LOGGER.debug(
        'textDocument/completion uri=%s position=%d:%d items=%d includes=%d',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        0 if completion_items is None else len(completion_items),
        len(related_documents),
    )
    return completion_items
