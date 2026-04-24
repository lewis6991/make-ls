from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast, final

from lsprotocol import types as lsp
from pygls.lsp.client import LanguageClient

from make_ls.server import create_server

if TYPE_CHECKING:
    from pathlib import Path

    from pygls.protocol import JsonRPCProtocol
    from pygls.protocol.json_rpc import RPCMessage

    from make_ls.server import MakeLsLanguageServer


@final
class InMemoryWriter:
    def __init__(self, peer: JsonRPCProtocol, loop: asyncio.AbstractEventLoop) -> None:
        self._peer: JsonRPCProtocol = peer
        self._loop: asyncio.AbstractEventLoop = loop

    def write(self, data: bytes) -> None:
        payload = cast('dict[str, object]', json.loads(data.decode('utf-8')))
        message = cast('RPCMessage', self._peer.structure_message(payload))
        _ = self._loop.call_soon(self._peer.handle_message, message)

    def close(self) -> None:
        return None


@final
class LspSession:
    def __init__(self, root: Path, *, snippet_edit_support: bool = True) -> None:
        self.root: Path = root
        self.snippet_edit_support: bool = snippet_edit_support
        self.server: MakeLsLanguageServer = create_server()
        self.client: LanguageClient = LanguageClient('make-ls-tests', '0.1.0')
        self.diagnostics: asyncio.Queue[lsp.PublishDiagnosticsParams] = asyncio.Queue()
        self.initialize_result: lsp.InitializeResult | None = None
        self._versions: dict[str, int] = {}

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

        # Neovim advertises rename.prepareSupport, which changes how pygls
        # reports rename capabilities during initialize.
        self.initialize_result = await self.client.initialize_async(
            lsp.InitializeParams(
                process_id=None,
                root_uri=self.root.as_uri(),
                capabilities=lsp.ClientCapabilities(
                    workspace=lsp.WorkspaceClientCapabilities(
                        workspace_edit=lsp.WorkspaceEditClientCapabilities(
                            document_changes=self.snippet_edit_support,
                            snippet_edit_support=self.snippet_edit_support,
                        )
                    ),
                    text_document=lsp.TextDocumentClientCapabilities(
                        rename=lsp.RenameClientCapabilities(prepare_support=True)
                    ),
                ),
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
        _ = path.write_text(text, encoding='utf-8')
        uri = path.as_uri()
        self._versions[uri] = 1

        self.client.text_document_did_open(
            lsp.DidOpenTextDocumentParams(
                text_document=lsp.TextDocumentItem(
                    uri=uri,
                    language_id='make',
                    version=1,
                    text=text,
                )
            )
        )
        return uri

    async def change_document(self, uri: str, text: str) -> None:
        version = self._versions[uri] + 1
        self._versions[uri] = version
        self.client.text_document_did_change(
            lsp.DidChangeTextDocumentParams(
                text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=version),
                content_changes=[lsp.TextDocumentContentChangeWholeDocument(text=text)],
            )
        )

    async def save_document(self, uri: str) -> None:
        self.client.text_document_did_save(
            lsp.DidSaveTextDocumentParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
            )
        )

    async def wait_for_diagnostics(self, uri: str) -> list[lsp.Diagnostic]:
        while True:
            params = await asyncio.wait_for(self.diagnostics.get(), timeout=1)
            if params.uri == uri:
                return list(params.diagnostics)

    async def code_actions(
        self,
        uri: str,
        target_range: lsp.Range,
        diagnostics: list[lsp.Diagnostic],
    ) -> list[lsp.CodeAction | lsp.Command]:
        result = await self.client.text_document_code_action_async(
            lsp.CodeActionParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                range=target_range,
                context=lsp.CodeActionContext(
                    diagnostics=diagnostics,
                    only=[lsp.CodeActionKind.QuickFix],
                ),
            )
        )
        return [] if result is None else list(result)

    async def hover(self, uri: str, line: int, character: int) -> lsp.Hover | None:
        return await self.client.text_document_hover_async(
            lsp.HoverParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
            )
        )

    async def completion(self, uri: str, line: int, character: int) -> list[lsp.CompletionItem]:
        result = await self.client.text_document_completion_async(
            lsp.CompletionParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
            )
        )
        if result is None:
            return []
        if isinstance(result, lsp.CompletionList):
            return list(result.items)
        return list(result)

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

    async def references(
        self,
        uri: str,
        line: int,
        character: int,
        *,
        include_declaration: bool,
    ) -> list[lsp.Location] | None:
        result = await self.client.text_document_references_async(
            lsp.ReferenceParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
                context=lsp.ReferenceContext(include_declaration=include_declaration),
            )
        )
        return None if result is None else list(result)

    async def prepare_rename(
        self, uri: str, line: int, character: int
    ) -> lsp.PrepareRenameResult | None:
        return await self.client.text_document_prepare_rename_async(
            lsp.PrepareRenameParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
            )
        )

    async def rename(
        self, uri: str, line: int, character: int, new_name: str
    ) -> lsp.WorkspaceEdit | None:
        return await self.client.text_document_rename_async(
            lsp.RenameParams(
                text_document=lsp.TextDocumentIdentifier(uri=uri),
                position=lsp.Position(line=line, character=character),
                new_name=new_name,
            )
        )
