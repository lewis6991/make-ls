from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from lsprotocol import types as lsp
from pygls.lsp.client import LanguageClient
from pygls.protocol import JsonRPCProtocol
from pygls.protocol.json_rpc import RPCMessage

from makels.server import MakelsLanguageServer, create_server


class InMemoryWriter:
    def __init__(self, peer: JsonRPCProtocol, loop: asyncio.AbstractEventLoop) -> None:
        self._peer = peer
        self._loop = loop

    def write(self, data: bytes) -> None:
        payload = cast("dict[str, object]", json.loads(data.decode("utf-8")))
        message = cast("RPCMessage", self._peer.structure_message(payload))
        _ = self._loop.call_soon(self._peer.handle_message, message)

    def close(self) -> None:
        return None


class LspSession:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.server: MakelsLanguageServer = create_server()
        self.client = LanguageClient("makels-tests", "0.1.0")
        self.diagnostics: asyncio.Queue[lsp.PublishDiagnosticsParams] = asyncio.Queue()

        def capture_diagnostics(
            _client: LanguageClient, params: lsp.PublishDiagnosticsParams
        ) -> None:
            _ = self.diagnostics.put_nowait(params)

        self._diagnostics_handler: object = self.client.feature(
            lsp.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS
        )(capture_diagnostics)

    async def __aenter__(self) -> LspSession:
        loop = asyncio.get_running_loop()
        self.server.protocol.set_writer(
            InMemoryWriter(self.client.protocol, loop),
            include_headers=False,
        )
        self.client.protocol.set_writer(
            InMemoryWriter(self.server.protocol, loop),
            include_headers=False,
        )

        _ = await self.client.initialize_async(
            lsp.InitializeParams(
                process_id=None,
                root_uri=self.root.as_uri(),
                capabilities=lsp.ClientCapabilities(),
                workspace_folders=[],
            )
        )
        self.client.initialized(lsp.InitializedParams())
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.server.shutdown()
        await self.client.stop()

    async def open_document(self, relative_path: str, text: str) -> str:
        path = self.root / relative_path
        _ = path.write_text(text, encoding="utf-8")
        uri = path.as_uri()

        self.client.text_document_did_open(
            lsp.DidOpenTextDocumentParams(
                text_document=lsp.TextDocumentItem(
                    uri=uri,
                    language_id="make",
                    version=1,
                    text=text,
                )
            )
        )
        return uri

    async def wait_for_diagnostics(self, uri: str) -> list[lsp.Diagnostic]:
        while True:
            params = await asyncio.wait_for(self.diagnostics.get(), timeout=1)
            if params.uri == uri:
                return list(params.diagnostics)

    async def hover(self, uri: str, line: int, character: int) -> lsp.Hover | None:
        return await self.client.text_document_hover_async(
            lsp.HoverParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
            )
        )

    async def definition(
        self, uri: str, line: int, character: int
    ) -> lsp.Location | list[lsp.Location] | None:
        result = await self.client.text_document_definition_async(
            lsp.DefinitionParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
            )
        )
        if result is None or isinstance(result, lsp.Location):
            return result
        return [location for location in result if isinstance(location, lsp.Location)]
