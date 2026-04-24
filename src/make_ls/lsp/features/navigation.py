"""Definition, references, and rename handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from lsprotocol import types as lsp

from make_ls.analysis.navigation import (
    def_for_pos,
    prep_rename_for_pos,
    refs_for_pos,
    rename_var_for_pos,
)

if TYPE_CHECKING:
    from make_ls.lsp.protocols import FeatureServer, WorkspaceProtocol
    from make_ls.types import AnalyzedDoc

LOGGER = logging.getLogger(__name__)


def register(server: FeatureServer) -> None:
    _ = server.feature(lsp.TEXT_DOCUMENT_DEFINITION)(definition)
    _ = server.feature(lsp.TEXT_DOCUMENT_REFERENCES)(references)
    _ = server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)(prepare_rename)
    _ = server.feature(lsp.TEXT_DOCUMENT_RENAME)(rename)


def definition(
    ls: FeatureServer, params: lsp.DefinitionParams
) -> lsp.Location | list[lsp.Location] | None:
    document = ls.analyze_uri(params.text_document.uri)
    local_definition = def_for_pos(document, params.position)
    if local_definition is not None:
        LOGGER.debug(
            'textDocument/definition uri=%s position=%d:%d result=local locations=%d',
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            1 if isinstance(local_definition, lsp.Location) else len(local_definition),
        )
        return local_definition

    documents = ls.included_documents(params.text_document.uri)
    definition_result = def_for_pos(document, params.position, documents[1:])
    LOGGER.debug(
        'textDocument/definition uri=%s position=%d:%d result=%s locations=%d includes=%d',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        'included' if definition_result is not None else 'miss',
        0
        if definition_result is None
        else 1
        if isinstance(definition_result, lsp.Location)
        else len(definition_result),
        len(documents) - 1,
    )
    return definition_result


def references(ls: FeatureServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    occurrence = document.occurrence_at(params.position.line, params.position.character)
    related_documents: tuple[AnalyzedDoc, ...] = ()
    if occurrence is not None and occurrence.kind == 'target':
        related_documents = ls.included_documents(params.text_document.uri)[1:]

    reference_result = refs_for_pos(
        document,
        params.position,
        tuple(text_document.source.splitlines()),
        related_documents,
        include_declaration=params.context.include_declaration,
    )
    LOGGER.debug(
        'textDocument/references uri=%s position=%d:%d include_declaration=%s '
        'locations=%d includes=%d',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        params.context.include_declaration,
        0 if reference_result is None else len(reference_result),
        len(related_documents),
    )
    return reference_result


def prepare_rename(
    ls: FeatureServer, params: lsp.PrepareRenameParams
) -> lsp.PrepareRenameResult | None:
    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    rename_result = prep_rename_for_pos(
        document,
        params.position,
        tuple(text_document.source.splitlines()),
    )
    LOGGER.debug(
        'textDocument/prepareRename uri=%s position=%d:%d result=%s',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        rename_result is not None,
    )
    return rename_result


def rename(ls: FeatureServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    document = ls.analyze_uri(params.text_document.uri)
    workspace = cast('WorkspaceProtocol', ls.workspace)
    text_document = workspace.get_text_document(params.text_document.uri)
    workspace_edit = rename_var_for_pos(
        document,
        params.position,
        params.new_name,
        tuple(text_document.source.splitlines()),
    )
    LOGGER.debug(
        'textDocument/rename uri=%s position=%d:%d new_name=%s changes=%d',
        params.text_document.uri,
        params.position.line + 1,
        params.position.character + 1,
        params.new_name,
        0
        if workspace_edit is None or workspace_edit.changes is None
        else sum(len(edits) for edits in workspace_edit.changes.values()),
    )
    return workspace_edit
