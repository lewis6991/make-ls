from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from lsprotocol import types as lsp

from .analysis import analyze_document
from .server import create_server

MAKEFILE_FILENAMES = frozenset({"Makefile", "makefile", "GNUmakefile"})
LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class MakeLsArgs(argparse.Namespace):
    command: str | None
    log_file: str | None
    log_level: str
    no_log_file: bool
    paths: list[str]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(
        list(argv) if argv is not None else None,
        namespace=MakeLsArgs(),
    )
    log_file = _resolved_log_file(
        args.log_file,
        command=args.command,
        no_log_file=args.no_log_file,
    )
    try:
        configure_logging(log_file, args.log_level)
    except OSError as error:
        print(f"make-ls: failed to open log file {log_file}: {error}", file=sys.stderr)
        return 2

    if args.command == "check":
        return _run_check(args.paths, stdout=sys.stdout, stderr=sys.stderr)

    logging.getLogger("make_ls").info("starting stdio server")
    create_server().start_io()
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make-ls",
        description="Makefile language server. Run without a subcommand to start stdio LSP.",
    )
    _ = parser.add_argument(
        "--log-file",
        nargs="?",
        metavar="path",
        const="",
        help="Write make-ls LSP logs to a file. Stdio LSP defaults to the XDG state log file.",
    )
    _ = parser.add_argument(
        "--log-level",
        choices=tuple(LOG_LEVELS),
        default="debug",
        help="Log verbosity for the LSP log file.",
    )
    _ = parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable the default stdio LSP log file.",
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


def configure_logging(log_file: Path | None, log_level: str) -> None:
    logger = logging.getLogger("make_ls")
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if log_file is None:
        logger.setLevel(logging.NOTSET)
        return

    # stdio LSP owns stdout, so opt-in debug output has to live in a separate file.
    log_path = log_file.expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVELS[log_level])
    logger.info("logging enabled path=%s level=%s", log_path, log_level)


def _resolved_log_file(
    raw_log_file: str | None,
    *,
    command: str | None,
    no_log_file: bool,
) -> Path | None:
    if no_log_file:
        return None
    if raw_log_file == "":
        return _default_log_file()
    if raw_log_file is not None:
        return Path(raw_log_file)
    if command is None:
        return _default_log_file()
    return None


def _default_log_file() -> Path:
    launch_path = Path.cwd().resolve()
    launch_hash = hashlib.sha1(str(launch_path).encode("utf-8")).hexdigest()[:8]
    raw_state_home = os.environ.get("XDG_STATE_HOME")
    state_home = (
        Path(raw_state_home).expanduser()
        if raw_state_home is not None
        else Path.home() / ".local" / "state"
    )
    return state_home / "make-ls" / f"make-ls-{launch_hash}.log"


if __name__ == "__main__":
    raise SystemExit(main())
