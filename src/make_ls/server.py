from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import __version__
from .analysis import (
    analyze_document,
    definition_for_position,
    hover_for_position,
    prepare_rename_for_position,
    rename_variable_for_position,
)
from .types import AnalyzedDocument


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

        analyzed = analyze_document(uri, document.version, document.source)
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

        analyzed = analyze_document(uri, None, path.read_text(encoding="utf-8"))
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

    def publish_document_diagnostics(self, uri: str) -> None:
        analyzed = self.analyze_uri(uri)
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=list(analyzed.diagnostics))
        )


def create_server() -> MakeLsLanguageServer:
    server = MakeLsLanguageServer()

    def did_open(ls: MakeLsLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)

    def did_change(ls: MakeLsLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)

    def did_close(ls: MakeLsLanguageServer, params: lsp.DidCloseTextDocumentParams) -> None:
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
            return hover_result

        documents = ls.included_documents(params.text_document.uri)
        return hover_for_position(document, params.position, documents[1:], source_lines)

    _ = server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)

    def definition(
        ls: MakeLsLanguageServer, params: lsp.DefinitionParams
    ) -> lsp.Location | list[lsp.Location] | None:
        document = ls.analyze_uri(params.text_document.uri)
        local_definition = definition_for_position(document, params.position)
        if local_definition is not None:
            return local_definition

        documents = ls.included_documents(params.text_document.uri)
        return definition_for_position(document, params.position, documents[1:])

    _ = server.feature(lsp.TEXT_DOCUMENT_DEFINITION)(definition)

    def prepare_rename(
        ls: MakeLsLanguageServer, params: lsp.PrepareRenameParams
    ) -> lsp.PrepareRenameResult | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        return prepare_rename_for_position(
            document,
            params.position,
            tuple(text_document.source.splitlines()),
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)(prepare_rename)

    def rename(ls: MakeLsLanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
        document = ls.analyze_uri(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        return rename_variable_for_position(
            document,
            params.position,
            params.new_name,
            tuple(text_document.source.splitlines()),
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_RENAME)(rename)

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
