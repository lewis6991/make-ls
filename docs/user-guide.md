# User Guide

`make-ls` is a Makefile language server with a matching batch checker. The
language server and the `check` subcommand share the same analyzer, so the
diagnostics and symbol understanding stay close across editor and CLI use.

## Feature support

### Editor features

- hover for targets, variables, GNU Make directives, functions, builtin
  variables, and special targets
- go to definition for targets and variables
- references for targets and variables
- variable rename with prepare-rename support
- quick fixes for a small set of common diagnostics
- diagnostics on open, change, and save

### What the features understand

- explicit `include`, `-include`, and `sinclude` directives
- nested static includes for target lookup
- pattern rules for target definition lookup
- leading comment blocks on variable assignments for variable hover docs
- recursive target dependency trees in target hover

### Current limits

- no completion yet
- variable rename is variable-only and stays within the current document
- target lookup through includes only works for static include paths
- no full GNU Make evaluation

## Diagnostics

`make-ls` currently reports both errors and warnings.

### Errors

- invalid Makefile syntax
- invalid variable references inside assignments, such as unterminated `$(...)`
  or `${...}` forms
- control-block issues:
  `Unexpected else directive`
  `Duplicate else directive`
  `Unexpected endif directive`
  `Unexpected endef directive`
  `Missing endif for conditional block`
  `Missing endef for define block`
- invalid shell syntax inside recipe lines

### Warnings

- unknown variable references
- automatic variables outside recipe context
- unresolved include paths
- unresolved prerequisites
- overriding recipes for the same target
- circular prerequisite cycles

### Diagnostic behavior notes

- builtin GNU Make variables and special targets are recognized
- environment variables are not reported as unknown variables
- unknown-variable warnings are suppressed in conditional branches that prove
  the exact variable is defined or nonempty
- prerequisite warnings are skipped when the prerequisite already exists as a
  file, is defined as a target, matches a pattern rule, or is found through a
  static include
- missing optional includes from `-include` and `sinclude` do not warn
- recipe shell checks are best-effort and depend on `bash` being available

## Quick fixes

Quick fixes currently exist for two diagnostics:

- `Unknown variable reference`
  creates an empty assignment such as `FEATURE :=`
- `Unresolved prerequisite`
  creates a stub target such as:

```make
dep:
	# TODO
```

When the client supports snippet workspace edits, the target stub places the
cursor on the `TODO` comment.

## The `check` subcommand

Use `make-ls check` to run the analyzer over files or directories without
starting LSP mode.

### Basic usage

```sh
make-ls check Makefile
make-ls check Makefile rules.mk
make-ls check .
make-ls check path/to/project
```

### What it scans

- files passed explicitly on the command line
- directories passed on the command line, recursively
- the current directory when no paths are given

When scanning directories, `make-ls` looks for:

- `Makefile`
- `makefile`
- `GNUmakefile`
- `*.mk`

Hidden directories are skipped.

### Output formats

The default format is text:

```sh
make-ls check .
```

Text output includes:

- file path
- line and column
- severity
- diagnostic message
- a small source snippet with a caret marker

TTY output uses color when available.

JSON output emits SARIF 2.1.0:

```sh
make-ls check --format json . > make-ls.sarif
```

### Exit codes

- `0`: no diagnostics found
- `1`: diagnostics found
- `2`: command or input error, such as a missing path, unreadable file, or no
  Makefiles found

## Include handling

Include support is intentionally conservative.

- static include paths can participate in target lookup and prerequisite checks
- nested static includes are followed
- paths containing variable expansion or glob characters are not resolved
- missing include files do not warn when GNU Make could remake them from an
  ordinary target

## Logging

Running `make-ls` without a subcommand starts the stdio server and writes logs
to the XDG state directory by default.

Useful flags:

```sh
make-ls --log-file /tmp/make-ls.log --log-level debug
make-ls --no-log-file
```

The `check` subcommand uses the same CLI process, but the logs are mainly useful
for LSP troubleshooting.

## VS Code

There is a VS Code extension under `editors/vscode`.

- build a local VSIX with `make vscode-vsix`
- point the extension at a checkout with `make-ls.server.repoRoot`
- or configure an explicit launch command with `make-ls.server.command`

## See also

- `README.md` for install and quick-start examples
- `editors/vscode/README.md` for extension setup and VSIX packaging
- `docs/architecture.md` for contributor-facing code structure
