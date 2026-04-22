from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import __version__
from .analysis import analyze_document, definition_for_position, hover_for_position
from .types import AnalyzedDocument

MAKEFILE_PATTERNS = ("Makefile", "makefile", "GNUmakefile", "*.mk")


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
        self._workspace_file_cache: dict[Path, tuple[Path, ...]] = {}

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

    def workspace_documents(self, uri: str) -> tuple[AnalyzedDocument, ...]:
        current_document = self.analyze_uri(uri)
        current_path = _path_from_uri(uri)
        root = self.workspace_root_for_uri(uri)
        if root is None:
            return (current_document,)

        related_documents: list[AnalyzedDocument] = []
        for candidate_path in self.workspace_makefiles(root, current_path):
            try:
                related_documents.append(self.analyze_path(candidate_path))
            except (OSError, UnicodeDecodeError):
                continue

        return (current_document, *related_documents)

    def workspace_makefiles(self, root: Path, current_path: Path) -> tuple[Path, ...]:
        cached = self._workspace_file_cache.get(root)
        if cached is None:
            discovered_paths: set[Path] = set()
            for pattern in MAKEFILE_PATTERNS:
                discovered_paths.update(path for path in root.rglob(pattern) if path.is_file())
            cached = tuple(sorted(discovered_paths))
            self._workspace_file_cache[root] = cached

        candidates = [path for path in cached if path != current_path]
        candidates.sort(key=lambda path: _workspace_path_sort_key(current_path, path))
        return tuple(candidates)

    def workspace_root_for_uri(self, uri: str) -> Path | None:
        current_path = _path_from_uri(uri)
        roots = [_path_from_uri(folder.uri) for folder in self.workspace.folders.values()]
        root_path = self.workspace.root_path
        if root_path is not None:
            roots.append(Path(root_path))
        if not roots:
            return current_path.parent

        matching_roots = [root for root in roots if current_path.is_relative_to(root)]
        if not matching_roots:
            return current_path.parent
        return max(matching_roots, key=lambda root: len(root.parts))

    def invalidate_workspace_cache(self, uri: str) -> None:
        root = self.workspace_root_for_uri(uri)
        if root is not None:
            _ = self._workspace_file_cache.pop(root, None)

    def clear_uri(self, uri: str) -> None:
        _ = self._documents.pop(uri, None)
        _ = self._disk_signatures.pop(uri, None)
        self.invalidate_workspace_cache(uri)

    def publish_document_diagnostics(self, uri: str) -> None:
        analyzed = self.analyze_uri(uri)
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=list(analyzed.diagnostics))
        )


def create_server() -> MakeLsLanguageServer:
    server = MakeLsLanguageServer()

    def did_open(ls: MakeLsLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        ls.invalidate_workspace_cache(params.text_document.uri)
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)

    def did_change(ls: MakeLsLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
        ls.invalidate_workspace_cache(params.text_document.uri)
        ls.publish_document_diagnostics(params.text_document.uri)

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)

    def did_close(ls: MakeLsLanguageServer, params: lsp.DidCloseTextDocumentParams) -> None:
        ls.clear_uri(params.text_document.uri)
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(did_close)

    def hover(ls: MakeLsLanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
        documents = ls.workspace_documents(params.text_document.uri)
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        return hover_for_position(
            documents[0],
            params.position,
            documents[1:],
            tuple(text_document.source.splitlines()),
        )

    _ = server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)

    def definition(
        ls: MakeLsLanguageServer, params: lsp.DefinitionParams
    ) -> lsp.Location | list[lsp.Location] | None:
        documents = ls.workspace_documents(params.text_document.uri)
        return definition_for_position(documents[0], params.position, documents[1:])

    _ = server.feature(lsp.TEXT_DOCUMENT_DEFINITION)(definition)

    return server


def _path_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _path_from_uri(uri: str) -> Path:
    path = to_fs_path(uri)
    if path is None:
        raise ValueError(f"expected filesystem URI, got {uri!r}")
    return Path(path)


def _workspace_path_sort_key(current_path: Path, candidate_path: Path) -> tuple[int, int, str]:
    current_directory = current_path.parent
    same_directory = candidate_path.parent == current_directory
    return (
        0 if same_directory else 1,
        _path_distance(current_directory, candidate_path.parent),
        str(candidate_path),
    )


def _path_distance(left: Path, right: Path) -> int:
    shared_parts = 0
    for left_part, right_part in zip(left.parts, right.parts, strict=False):
        if left_part != right_part:
            break
        shared_parts += 1
    return (len(left.parts) - shared_parts) + (len(right.parts) - shared_parts)
