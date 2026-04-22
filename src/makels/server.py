from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from .analysis import analyze_document, definition_for_position, hover_for_position
from .types import AnalyzedDocument


def _server_version() -> str:
    try:
        return version("makels")
    except PackageNotFoundError:
        return "0.1.0"


class MakelsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("makels", _server_version())  # pyright: ignore[reportUnknownMemberType]
        self._documents: dict[str, AnalyzedDocument] = {}

    def analyze_uri(self, uri: str) -> AnalyzedDocument:
        document = self.workspace.get_text_document(uri)
        cached = self._documents.get(uri)
        if cached is not None and cached.version == document.version:
            return cached

        analyzed = analyze_document(uri, document.version, document.source)
        self._documents[uri] = analyzed
        return analyzed

    def clear_uri(self, uri: str) -> None:
        _ = self._documents.pop(uri, None)

    def publish_document_diagnostics(self, uri: str) -> None:
        analyzed = self.analyze_uri(uri)
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=list(analyzed.diagnostics))
        )


def create_server() -> MakelsLanguageServer:
    server = MakelsLanguageServer()

    def did_open(ls: MakelsLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)

    def did_change(ls: MakelsLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)

    def did_close(ls: MakelsLanguageServer, params: lsp.DidCloseTextDocumentParams) -> None:
        ls.clear_uri(params.text_document.uri)
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(did_close)

    def hover(ls: MakelsLanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
        document = ls.analyze_uri(params.text_document.uri)
        return hover_for_position(document, params.position)

    _ = server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)

    def definition(
        ls: MakelsLanguageServer, params: lsp.DefinitionParams
    ) -> lsp.Location | list[lsp.Location] | None:
        document = ls.analyze_uri(params.text_document.uri)
        return definition_for_position(document, params.position)

    _ = server.feature(lsp.TEXT_DOCUMENT_DEFINITION)(definition)

    return server
