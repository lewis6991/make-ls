"""Signature help handler for builtin GNU Make functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from lsprotocol import types as lsp

from make_ls.analysis.signature_help import signature_help_for_pos

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer, WorkspaceProtocol

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(
        lsp.TEXT_DOCUMENT_SIGNATURE_HELP,
        lsp.SignatureHelpOptions(
            trigger_characters=[' ', ','],
            retrigger_characters=[','],
        ),
    )(signature_help)


def signature_help(
    ls: FeatureServer,
    params: lsp.SignatureHelpParams,
) -> lsp.SignatureHelp | None:
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    source_lines = tuple(text_document.source.splitlines())
    signature_result = signature_help_for_pos(params.position, source_lines)
    LOGGER.debug(
        'textDocument/signatureHelp uri=%s position=%d:%d result=%s',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        'hit' if signature_result is not None else 'miss',
    )
    return signature_result
