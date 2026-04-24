"""Type-only protocols shared by LSP feature modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from lsprotocol import types as lsp

    from make_ls.types import AnalyzedDoc

_Handler = TypeVar('_Handler', bound=Callable[..., object])


class TextDocumentProtocol(Protocol):
    version: int | None
    source: str


class WorkspaceProtocol(Protocol):
    def get_text_document(self, uri: str) -> TextDocumentProtocol: ...


class FeatureServer(Protocol):
    @property
    def workspace(self) -> object: ...

    @property
    def client_capabilities(self) -> object: ...

    def feature(
        self,
        feature_name: str,
        options: object | None = None,
    ) -> Callable[[_Handler], _Handler]: ...

    def analyze_uri(self, uri: str) -> AnalyzedDoc: ...
    def included_documents(self, uri: str) -> tuple[AnalyzedDoc, ...]: ...
    def publish_document_diagnostics(
        self,
        uri: str,
        *,
        include_shell_diagnostics: bool,
    ) -> None: ...
    def clear_uri(self, uri: str) -> None: ...
    def text_document_publish_diagnostics(
        self,
        params: lsp.PublishDiagnosticsParams,
    ) -> None: ...
