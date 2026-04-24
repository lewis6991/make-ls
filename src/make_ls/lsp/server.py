"""pygls server wiring over the shared Makefile analysis pipeline.

The server schedules shell-free analysis on change, re-enables shell checks on
open and save, caches analyzed open and included files, and only follows
include paths that can be resolved statically.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from make_ls._version import __version__
from make_ls.analysis import analyze_document

from .features.code_actions import register as register_code_action_feature
from .features.completion import register as register_completion_feature
from .features.hover import register as register_hover_feature
from .features.lifecycle import register as register_lifecycle_feature
from .features.navigation import register as register_navigation_features

if TYPE_CHECKING:
    from make_ls.types import AnalyzedDoc

LOGGER = logging.getLogger(__name__)


def _server_version() -> str:
    try:
        return version('make-ls')
    except PackageNotFoundError:
        return __version__


class MakeLsLanguageServer(LanguageServer):
    """Language server with cached `AnalyzedDoc` snapshots for open and included files."""

    def __init__(self) -> None:
        super().__init__('make-ls', _server_version())  # pyright: ignore[reportUnknownMemberType]
        self._documents: dict[str, AnalyzedDoc] = {}
        self._disk_signatures: dict[str, tuple[int, int]] = {}

    def analyze_uri(self, uri: str) -> AnalyzedDoc:
        """Analyze an open document version without shelling out on edit paths."""
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

    def analyze_path(self, path: Path) -> AnalyzedDoc:
        """Analyze an on-disk include target and reuse it while its stat signature matches."""
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
            path.read_text(encoding='utf-8'),
            include_shell_diagnostics=False,
        )
        self._documents[uri] = analyzed
        self._disk_signatures[uri] = signature
        return analyzed

    def included_documents(self, uri: str) -> tuple[AnalyzedDoc, ...]:
        """Follow statically resolved include paths starting from one open document."""
        current_document = self.analyze_uri(uri)
        current_path = _path_from_uri(uri)
        related_documents: list[AnalyzedDoc] = []
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
        related_documents: list[AnalyzedDoc],
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
        """Publish diagnostics, opting into shell checks only on slower safe points."""
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
            'textDocument/publishDiagnostics uri=%s count=%d',
            uri,
            len(analyzed.diagnostics),
        )
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=list(analyzed.diagnostics))
        )


def create_server() -> MakeLsLanguageServer:
    """Create the language server and register its LSP feature handlers."""
    server = MakeLsLanguageServer()
    register_lifecycle_feature(server)
    register_hover_feature(server)
    register_completion_feature(server)
    register_navigation_features(server)
    register_code_action_feature(server)
    return server


def _path_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _path_from_uri(uri: str) -> Path:
    path = to_fs_path(uri)
    if path is None:
        raise ValueError(f'expected filesystem URI, got {uri!r}')
    return Path(path)


def _resolved_include_paths(
    base_directory: Path,
    include_patterns: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for include_pattern in include_patterns:
        if (
            '$(' in include_pattern
            or '${' in include_pattern
            or any(character in include_pattern for character in '*?[]')
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
