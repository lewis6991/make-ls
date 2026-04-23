from __future__ import annotations

import logging
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import __version__
from .analysis import (
    UNKNOWN_VARIABLE_DIAGNOSTIC_CODE,
    UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE,
    analyze_document,
    definition_for_position,
    hover_for_position,
    prepare_rename_for_position,
    references_for_position,
    rename_variable_for_position,
)
from .types import AnalyzedDocument, SymbolOccurrence

LOGGER = logging.getLogger(__name__)


def _server_version() -> str:
    try:
        return version("make-ls")
    except PackageNotFoundError:
        return __version__


class MakeLsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("make-ls", _server_version())  # pyright: ignore[reportUnknownMemberType]
        self._documents: dict[str, AnalyzedDocument] = {}
        self._disk_signatures: dict[str, tuple[int, int]] = {}

    def analyze_uri(self, uri: str) -> AnalyzedDocument:
        document = self.workspace.get_text_document(uri)
        cached = self._documents.get(uri)
        if cached is not None and cached.version == document.version:
            return cached

        # Recipe shell diagnostics shell out to `bash -n`, so keep the cached
        # edit-path analysis shell-free and only opt into them on open/save.
        analyzed = analyze_document(
            uri,
            document.version,
            document.source,
            include_shell_diagnostics=False,
        )
        self._documents[uri] = analyzed
        return analyzed

    def analyze_path(self, path: Path) -> AnalyzedDocument:
        uri = path.as_uri()
        if uri in self.workspace.text_documents:
            return self.analyze_uri(uri)

        signature = _path_signature(path)
        cached = self._documents.get(uri)
        if (
            cached is not None
            and cached.version is None
            and self._disk_signatures.get(uri) == signature
        ):
            return cached

        analyzed = analyze_document(
            uri,
            None,
            path.read_text(encoding="utf-8"),
            include_shell_diagnostics=False,
        )
        self._documents[uri] = analyzed
        self._disk_signatures[uri] = signature
        return analyzed

    def included_documents(self, uri: str) -> tuple[AnalyzedDocument, ...]:
        current_document = self.analyze_uri(uri)
        current_path = _path_from_uri(uri)
        related_documents: list[AnalyzedDocument] = []
        seen_paths = {current_path.resolve()}
        include_paths = _resolved_include_paths(current_path.parent, current_document.includes)
        for candidate_path in include_paths:
            try:
                self._extend_included_documents(candidate_path, seen_paths, related_documents)
            except (OSError, UnicodeDecodeError):
                continue

        return (current_document, *related_documents)

    def _extend_included_documents(
        self,
        path: Path,
        seen_paths: set[Path],
        related_documents: list[AnalyzedDocument],
    ) -> None:
        resolved_path = path.resolve()
        if resolved_path in seen_paths:
            return
        seen_paths.add(resolved_path)

        document = self.analyze_path(path)
        related_documents.append(document)
        for include_path in _resolved_include_paths(path.parent, document.includes):
            self._extend_included_documents(include_path, seen_paths, related_documents)

    def clear_uri(self, uri: str) -> None:
        _ = self._documents.pop(uri, None)
        _ = self._disk_signatures.pop(uri, None)

    def publish_document_diagnostics(self, uri: str, *, include_shell_diagnostics: bool) -> None:
        if include_shell_diagnostics:
            document = self.workspace.get_text_document(uri)
            analyzed = analyze_document(
                uri,
                document.version,
                document.source,
                include_shell_diagnostics=True,
            )
        else:
            analyzed = self.analyze_uri(uri)
        LOGGER.debug(
            "textDocument/publishDiagnostics uri=%s count=%d",
            uri,
            len(analyzed.diagnostics),
        )
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=list(analyzed.diagnostics))
        )


def create_server() -> MakeLsLanguageServer:
    server = MakeLsLanguageServer()

    def did_open(ls: MakeLsLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        LOGGER.debug(
            "textDocument/didOpen uri=%s version=%s",
            params.text_document.uri,
            params.text_document.version,
        )
        ls.publish_document_diagnostics(
            params.text_document.uri,
            include_shell_diagnostics=True,
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)

    def did_change(ls: MakeLsLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
        LOGGER.debug(
            "textDocument/didChange uri=%s version=%s changes=%d",
            params.text_document.uri,
            params.text_document.version,
            len(params.content_changes),
        )
        ls.publish_document_diagnostics(
            params.text_document.uri,
            include_shell_diagnostics=False,
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)

    def did_save(ls: MakeLsLanguageServer, params: lsp.DidSaveTextDocumentParams) -> None:
        LOGGER.debug("textDocument/didSave uri=%s", params.text_document.uri)
        ls.publish_document_diagnostics(
            params.text_document.uri,
            include_shell_diagnostics=True,
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_SAVE, lsp.SaveOptions(include_text=False))(
        did_save
    )

    def did_close(ls: MakeLsLanguageServer, params: lsp.DidCloseTextDocumentParams) -> None:
        LOGGER.debug("textDocument/didClose uri=%s", params.text_document.uri)
        ls.clear_uri(params.text_document.uri)
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(did_close)

    def hover(ls: MakeLsLanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        source_lines = tuple(text_document.source.splitlines())
        hover_result = hover_for_position(
            document,
            params.position,
            source_lines=source_lines,
        )
        if hover_result is not None:
            LOGGER.debug(
                "textDocument/hover uri=%s position=%d:%d result=local",
                params.text_document.uri,
                params.position.line + 1,
                params.position.character + 1,
            )
            return hover_result

        documents = ls.included_documents(params.text_document.uri)
        hover_result = hover_for_position(document, params.position, documents[1:], source_lines)
        LOGGER.debug(
            "textDocument/hover uri=%s position=%d:%d result=%s includes=%d",
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            "included" if hover_result is not None else "miss",
            len(documents) - 1,
        )
        return hover_result

    _ = server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)

    def definition(
        ls: MakeLsLanguageServer, params: lsp.DefinitionParams
    ) -> lsp.Location | list[lsp.Location] | None:
        document = ls.analyze_uri(params.text_document.uri)
        local_definition = definition_for_position(document, params.position)
        if local_definition is not None:
            LOGGER.debug(
                "textDocument/definition uri=%s position=%d:%d result=local locations=%d",
                params.text_document.uri,
                params.position.line + 1,
                params.position.character + 1,
                1 if isinstance(local_definition, lsp.Location) else len(local_definition),
            )
            return local_definition

        documents = ls.included_documents(params.text_document.uri)
        definition_result = definition_for_position(document, params.position, documents[1:])
        LOGGER.debug(
            "textDocument/definition uri=%s position=%d:%d result=%s locations=%d includes=%d",
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            "included" if definition_result is not None else "miss",
            0
            if definition_result is None
            else 1 if isinstance(definition_result, lsp.Location) else len(definition_result),
            len(documents) - 1,
        )
        return definition_result

    _ = server.feature(lsp.TEXT_DOCUMENT_DEFINITION)(definition)

    def references(
        ls: MakeLsLanguageServer, params: lsp.ReferenceParams
    ) -> list[lsp.Location] | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        occurrence = document.occurrence_at(params.position.line, params.position.character)
        related_documents: tuple[AnalyzedDocument, ...] = ()
        if occurrence is not None and occurrence.kind == "target":
            related_documents = ls.included_documents(params.text_document.uri)[1:]

        reference_result = references_for_position(
            document,
            params.position,
            tuple(text_document.source.splitlines()),
            related_documents,
            include_declaration=params.context.include_declaration,
        )
        LOGGER.debug(
            "textDocument/references uri=%s position=%d:%d include_declaration=%s "
            "locations=%d includes=%d",
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            params.context.include_declaration,
            0 if reference_result is None else len(reference_result),
            len(related_documents),
        )
        return reference_result

    _ = server.feature(lsp.TEXT_DOCUMENT_REFERENCES)(references)

    def prepare_rename(
        ls: MakeLsLanguageServer, params: lsp.PrepareRenameParams
    ) -> lsp.PrepareRenameResult | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        rename_result = prepare_rename_for_position(
            document,
            params.position,
            tuple(text_document.source.splitlines()),
        )
        LOGGER.debug(
            "textDocument/prepareRename uri=%s position=%d:%d result=%s",
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            rename_result is not None,
        )
        return rename_result

    _ = server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)(prepare_rename)

    def rename(ls: MakeLsLanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        workspace_edit = rename_variable_for_position(
            document,
            params.position,
            params.new_name,
            tuple(text_document.source.splitlines()),
        )
        LOGGER.debug(
            "textDocument/rename uri=%s position=%d:%d new_name=%s changes=%d",
            params.text_document.uri,
            params.position.line + 1,
            params.position.character + 1,
            params.new_name,
            0
            if workspace_edit is None or workspace_edit.changes is None
            else sum(len(edits) for edits in workspace_edit.changes.values()),
        )
        return workspace_edit

    _ = server.feature(lsp.TEXT_DOCUMENT_RENAME)(rename)

    def code_action(
        ls: MakeLsLanguageServer, params: lsp.CodeActionParams
    ) -> list[lsp.CodeAction] | None:
        if not _supports_quick_fix(params.context.only):
            return None

        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        actions = _unknown_variable_code_actions(
            document,
            params.text_document.uri,
            params.context.diagnostics,
        )
        actions.extend(
            _unresolved_prerequisite_code_actions(
                document,
                params.text_document.uri,
                text_document.source,
                _supports_snippet_workspace_edits(ls.client_capabilities),
                params.context.diagnostics,
            )
        )
        LOGGER.debug(
            "textDocument/codeAction uri=%s line=%d actions=%d diagnostics=%d",
            params.text_document.uri,
            params.range.start.line + 1,
            len(actions),
            len(params.context.diagnostics),
        )
        return actions or None

    _ = server.feature(
        lsp.TEXT_DOCUMENT_CODE_ACTION,
        lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
    )(code_action)

    return server


def _path_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _path_from_uri(uri: str) -> Path:
    path = to_fs_path(uri)
    if path is None:
        raise ValueError(f"expected filesystem URI, got {uri!r}")
    return Path(path)


def _resolved_include_paths(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for include_pattern in include_patterns:
        if (
            "$(" in include_pattern
            or "${" in include_pattern
            or any(character in include_pattern for character in "*?[]")
        ):
            continue

        candidate_path = (
            Path(include_pattern)
            if Path(include_pattern).is_absolute()
            else base_directory / include_pattern
        )
        if candidate_path.is_file():
            resolved_paths.append(candidate_path)

    return tuple(resolved_paths)


def _supports_quick_fix(kinds: Sequence[lsp.CodeActionKind | str] | None) -> bool:
    if kinds is None:
        return True
    return any(
        kind == lsp.CodeActionKind.QuickFix or kind == lsp.CodeActionKind.QuickFix.value
        for kind in kinds
    )


def _supports_snippet_workspace_edits(capabilities: lsp.ClientCapabilities) -> bool:
    workspace = capabilities.workspace
    if workspace is None or workspace.workspace_edit is None:
        return False

    workspace_edit = workspace.workspace_edit
    return bool(workspace_edit.document_changes and workspace_edit.snippet_edit_support)


def _unknown_variable_code_actions(
    document: AnalyzedDocument,
    uri: str,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    seen: set[tuple[str, int]] = set()
    for diagnostic in diagnostics:
        if diagnostic.code != UNKNOWN_VARIABLE_DIAGNOSTIC_CODE:
            continue

        occurrence = document.occurrence_at(
            diagnostic.range.start.line,
            diagnostic.range.start.character,
        )
        if occurrence is None or occurrence.kind != "variable" or occurrence.role != "reference":
            continue

        insertion_line = _empty_assignment_insertion_line(document, occurrence)
        seen_key = (occurrence.name, insertion_line)
        if seen_key in seen:
            continue
        seen.add(seen_key)

        actions.append(
            lsp.CodeAction(
                title=f"Add empty assignment for {occurrence.name}",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=lsp.Range(
                                    start=lsp.Position(line=insertion_line, character=0),
                                    end=lsp.Position(line=insertion_line, character=0),
                                ),
                                new_text=f"{occurrence.name} :=\n",
                            )
                        ]
                    }
                ),
            )
        )

    return actions


def _unresolved_prerequisite_code_actions(
    document: AnalyzedDocument,
    uri: str,
    source: str,
    supports_snippet_workspace_edits: bool,
    diagnostics: Sequence[lsp.Diagnostic],
) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    seen: set[str] = set()
    for diagnostic in diagnostics:
        if diagnostic.code != UNRESOLVED_PREREQUISITE_DIAGNOSTIC_CODE:
            continue

        occurrence = document.occurrence_at(
            diagnostic.range.start.line,
            diagnostic.range.start.character,
        )
        if occurrence is None or occurrence.kind != "target" or occurrence.role != "reference":
            continue
        if occurrence.name in seen:
            continue
        seen.add(occurrence.name)

        workspace_edit = _target_template_workspace_edit(
            uri,
            document.version,
            source,
            occurrence.name,
            supports_snippet_workspace_edits=supports_snippet_workspace_edits,
        )
        actions.append(
            lsp.CodeAction(
                title=f"Create target for {occurrence.name}",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[diagnostic],
                is_preferred=False,
                edit=workspace_edit,
            )
        )

    return actions


def _empty_assignment_insertion_line(
    document: AnalyzedDocument,
    occurrence: SymbolOccurrence,
) -> int:
    if occurrence.context is None:
        return occurrence.span.start_line

    for form in document.forms:
        if form.kind != occurrence.context.form_kind:
            continue
        if form.span.contains(occurrence.span.start_line, occurrence.span.start_character):
            return form.span.start_line
    return occurrence.span.start_line


def _target_template_workspace_edit(
    uri: str,
    version: int | None,
    source: str,
    target_name: str,
    *,
    supports_snippet_workspace_edits: bool,
) -> lsp.WorkspaceEdit:
    insert_range = lsp.Range(
        start=_document_end_position(source),
        end=_document_end_position(source),
    )
    prefix = _target_template_prefix(source)
    if supports_snippet_workspace_edits:
        # SnippetTextEdit requires documentChanges and lets the client place the
        # cursor on the recipe comment instead of leaving a dead stub behind.
        return lsp.WorkspaceEdit(
            document_changes=[
                lsp.TextDocumentEdit(
                    text_document=lsp.OptionalVersionedTextDocumentIdentifier(
                        uri=uri,
                        version=version,
                    ),
                    edits=[
                        lsp.SnippetTextEdit(
                            range=insert_range,
                            snippet=lsp.StringValue(
                                f"{prefix}{target_name}:\n\t# ${{1:TODO}}\n"
                            ),
                        )
                    ],
                )
            ]
        )

    return lsp.WorkspaceEdit(
        changes={
            uri: [
                lsp.TextEdit(
                    range=insert_range,
                    new_text=f"{prefix}{target_name}:\n\t# TODO\n",
                )
            ]
        }
    )


def _target_template_prefix(source: str) -> str:
    if source.endswith("\n\n") or source == "":
        return ""
    if source.endswith("\n"):
        return "\n"
    return "\n\n"


def _document_end_position(source: str) -> lsp.Position:
    source_lines = source.splitlines()
    if not source_lines:
        return lsp.Position(line=0, character=0)
    if source.endswith("\n"):
        return lsp.Position(line=len(source_lines), character=0)
    return lsp.Position(line=len(source_lines) - 1, character=len(source_lines[-1]))
