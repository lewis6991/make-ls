"""Compatibility wrapper for the packaged LSP server."""

from .lsp.server import MakeLsLanguageServer, create_server

__all__ = ['MakeLsLanguageServer', 'create_server']
