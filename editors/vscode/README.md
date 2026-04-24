# make-ls

VS Code extension for the `make-ls` language server.

## What it does

The extension:

* starts `make-ls` over stdio for VS Code's built-in `makefile` language
* exposes a `make-ls: Restart Language Server` command
* lets you point VS Code at either a checked-out repo or an explicit command

It intentionally does not register its own Makefile grammar or file
associations. VS Code already has a `makefile` language id, so the extension
just attaches the language server to that surface.

## Build and install a VSIX

Build the extension package with:

```sh
make -C editors/vscode vsix
```

This writes `dist/make-ls-vscode-<version>.vsix`. Install it with:

```sh
code --install-extension /absolute/path/to/dist/make-ls-vscode-<version>.vsix --force
```

You can also use `Extensions: Install from VSIX...` in the VS Code UI.

## Configure the server

The extension does not bundle a frozen `make-ls` server yet. For reliable local
use, point it at a checkout that already has a prepared virtualenv:

```sh
uv sync
```

Then set:

```json
{
  "make-ls.server.repoRoot": "/absolute/path/to/make-ls"
}
```

With that setting in place, the extension launches:

```sh
/absolute/path/to/make-ls/.venv/bin/make-ls
```

If you want to bypass `repoRoot`, configure the command directly:

```json
{
  "make-ls.server.command": "/absolute/path/to/make-ls/.venv/bin/make-ls",
  "make-ls.server.args": []
}
```

If `make-ls.server.args` is empty, `make-ls.server.command` can also be a full
command line:

```json
{
  "make-ls.server.command": "/opt/homebrew/bin/uv run --directory=/absolute/path/to/make-ls make-ls",
  "make-ls.server.args": []
}
```

Quote any path that contains spaces.

Leave `make-ls.server.repoRoot` and `make-ls.server.cwd` empty to disable them.
`make-ls.server.cwd` accepts `${workspaceFolder}` and
`${workspaceFolderBasename}` placeholders.

## Fallback behavior

If neither `make-ls.server.command` nor `make-ls.server.repoRoot` is set, the
extension first looks for a bundled `server/make-ls` binary inside the
extension package and otherwise falls back to `make-ls` on `PATH`.

## Development host

The `F5` Extension Development Host flow still works, but the intended local
workflow is building and installing a VSIX.
