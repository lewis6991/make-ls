from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from lsprotocol import types as lsp

from .analysis import analyze_document
from .server import create_server

MAKEFILE_FILENAMES = frozenset({"Makefile", "makefile", "GNUmakefile"})


class MakeLsArgs(argparse.Namespace):
    command: str | None
    paths: list[str]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(
        list(argv) if argv is not None else None,
        namespace=MakeLsArgs(),
    )
    if args.command == "check":
        return _run_check(args.paths, stdout=sys.stdout, stderr=sys.stderr)

    create_server().start_io()
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make-ls",
        description="Makefile language server. Run without a subcommand to start stdio LSP.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="check [paths ...]")
    check_parser = subparsers.add_parser(
        "check",
        help="Run make-ls diagnostics over files or directories.",
    )
    _ = check_parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to check. Defaults to the current directory.",
    )
    return parser


def _run_check(
    raw_paths: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    files = _check_files(raw_paths, stderr=stderr)
    if files is None:
        return 2
    if not files:
        print("make-ls: no Makefiles found", file=stderr)
        return 2

    diagnostics_found = False
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            print(f"make-ls: failed to read {path}: {error}", file=stderr)
            return 2

        analyzed = analyze_document(path.resolve().as_uri(), None, source)
        for diagnostic in analyzed.diagnostics:
            diagnostics_found = True
            print(_format_diagnostic(path, diagnostic), file=stdout)

    return 1 if diagnostics_found else 0


def _check_files(
    raw_paths: Sequence[str],
    *,
    stderr: TextIO,
) -> list[Path] | None:
    paths = [Path(raw_path) for raw_path in raw_paths] if raw_paths else [Path(".")]
    files: list[Path] = []
    seen: set[Path] = set()

    for path in paths:
        if not path.exists():
            print(f"make-ls: path not found: {path}", file=stderr)
            return None

        if path.is_file():
            _append_unique_path(files, seen, path)
            continue

        if not path.is_dir():
            print(f"make-ls: unsupported path: {path}", file=stderr)
            return None

        for candidate in _discover_makefiles(path):
            _append_unique_path(files, seen, candidate)

    return files


def _discover_makefiles(root: Path) -> list[Path]:
    discovered: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in sorted(filenames):
            if _is_makefile_name(filename):
                discovered.append(Path(directory, filename))

    return discovered


def _is_makefile_name(name: str) -> bool:
    return name in MAKEFILE_FILENAMES or name.endswith(".mk")


def _append_unique_path(files: list[Path], seen: set[Path], path: Path) -> None:
    resolved_path = path.resolve()
    if resolved_path in seen:
        return

    files.append(path)
    seen.add(resolved_path)


def _format_diagnostic(path: Path, diagnostic: lsp.Diagnostic) -> str:
    start = diagnostic.range.start
    severity = _diagnostic_severity_name(diagnostic.severity)
    message = " ".join(diagnostic.message.splitlines())
    return f"{_display_path(path)}:{start.line + 1}:{start.character + 1}: {severity}: {message}"


def _display_path(path: Path) -> str:
    resolved_path = path.resolve()
    current_directory = Path.cwd().resolve()
    try:
        return str(resolved_path.relative_to(current_directory))
    except ValueError:
        return str(path)


def _diagnostic_severity_name(severity: lsp.DiagnosticSeverity | int | None) -> str:
    if severity == lsp.DiagnosticSeverity.Error:
        return "error"
    if severity == lsp.DiagnosticSeverity.Warning:
        return "warning"
    if severity == lsp.DiagnosticSeverity.Information:
        return "info"
    if severity == lsp.DiagnosticSeverity.Hint:
        return "hint"
    return "diagnostic"


if __name__ == "__main__":
    raise SystemExit(main())
