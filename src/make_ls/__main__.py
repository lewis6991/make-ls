"""CLI entrypoints for stdio LSP mode and the `make-ls check` batch checker.

Running `make-ls` starts the stdio server. `make-ls check [paths ...]` reuses
the same analyzer for batch diagnostics and emits text or JSON output over the
discovered Makefiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TextIO

from lsprotocol import types as lsp

from .analysis import analyze_document
from .server import create_server

if TYPE_CHECKING:
    from collections.abc import Sequence

MAKEFILE_FILENAMES = frozenset({'Makefile', 'makefile', 'GNUmakefile'})
LOG_LEVELS = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
}
CHECK_CONTEXT_TAB_WIDTH = 4
ANSI_RESET = '\x1b[0m'
ANSI_BOLD = '\x1b[1m'
ANSI_DIM = '\x1b[2m'
ANSI_RED = '\x1b[31m'
ANSI_YELLOW = '\x1b[33m'
ANSI_BLUE = '\x1b[34m'
ANSI_CYAN = '\x1b[36m'


class CheckedFile(NamedTuple):
    path: Path
    source_lines: list[str]
    diagnostics: tuple[lsp.Diagnostic, ...]


class DiagnosticStyle(NamedTuple):
    name: str
    sarif_level: str
    ansi_code: str


DIAGNOSTIC_STYLES: dict[int, DiagnosticStyle] = {
    int(lsp.DiagnosticSeverity.Error): DiagnosticStyle('error', 'error', ANSI_RED),
    int(lsp.DiagnosticSeverity.Warning): DiagnosticStyle('warning', 'warning', ANSI_YELLOW),
    int(lsp.DiagnosticSeverity.Information): DiagnosticStyle('info', 'note', ANSI_BLUE),
    int(lsp.DiagnosticSeverity.Hint): DiagnosticStyle('hint', 'note', ANSI_CYAN),
}
DEFAULT_DIAGNOSTIC_STYLE = DiagnosticStyle('diagnostic', 'note', ANSI_BOLD)


class MakeLsArgs(argparse.Namespace):
    command: str | None
    check_format: str | None
    log_file: str | None
    log_level: str
    no_log_file: bool
    paths: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.command = None
        self.check_format = None
        self.log_file = None
        self.log_level = 'debug'
        self.no_log_file = False
        self.paths = []


def main(argv: Sequence[str] | None = None) -> int:
    """Run either the stdio server or the batch checker from one flat CLI."""
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
        print(f'make-ls: failed to open log file {log_file}: {error}', file=sys.stderr)
        return 2

    if args.command == 'check':
        return _run_check(
            args.paths,
            stdout=sys.stdout,
            stderr=sys.stderr,
            output_format=args.check_format or 'text',
        )

    logging.getLogger('make_ls').info('starting stdio server')
    create_server().start_io()
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='make-ls',
        description='Makefile language server. Run without a subcommand to start stdio LSP.',
    )
    _ = parser.add_argument(
        '--log-file',
        nargs='?',
        metavar='path',
        const='',
        help='Write make-ls LSP logs to a file. Stdio LSP defaults to the XDG state log file.',
    )
    _ = parser.add_argument(
        '--log-level',
        choices=tuple(LOG_LEVELS),
        default='debug',
        help='Log verbosity for the LSP log file.',
    )
    _ = parser.add_argument(
        '--no-log-file',
        action='store_true',
        help='Disable the default stdio LSP log file.',
    )
    subparsers = parser.add_subparsers(dest='command', metavar='check [paths ...]')
    check_parser = subparsers.add_parser(
        'check',
        help='Run make-ls diagnostics over files or directories.',
    )
    _ = check_parser.add_argument(
        'paths',
        nargs='*',
        help='Files or directories to check. Defaults to the current directory.',
    )
    _ = check_parser.add_argument(
        '--format',
        dest='check_format',
        choices=('text', 'json'),
        default='text',
        help='Check output format.',
    )
    return parser


def _run_check(
    raw_paths: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    output_format: str,
) -> int:
    """Analyze discovered Makefiles and emit text or JSON diagnostics."""
    files = _check_files(raw_paths, stderr=stderr)
    if files is None:
        return 2
    if not files:
        print('make-ls: no Makefiles found', file=stderr)
        return 2

    checked_files: list[CheckedFile] = []
    diagnostics_found = False
    for path in files:
        try:
            source = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as error:
            print(f'make-ls: failed to read {path}: {error}', file=stderr)
            return 2

        analyzed = analyze_document(path.resolve().as_uri(), None, source)
        checked_file = CheckedFile(
            path=path,
            source_lines=source.splitlines(),
            diagnostics=analyzed.diagnostics,
        )
        checked_files.append(checked_file)
        if checked_file.diagnostics:
            diagnostics_found = True

    if output_format == 'json':
        json.dump(_sarif_log(checked_files), stdout, indent=2)
        print(file=stdout)
        return 1 if diagnostics_found else 0

    use_color = _check_uses_color(stdout)
    rendered_diagnostics = [
        _format_diagnostic(
            checked_file.path,
            diagnostic,
            source_lines=checked_file.source_lines,
            color=use_color,
        )
        for checked_file in checked_files
        for diagnostic in checked_file.diagnostics
    ]
    if rendered_diagnostics:
        print('\n\n'.join(rendered_diagnostics), file=stdout)

    return 1 if diagnostics_found else 0


def _check_files(
    raw_paths: Sequence[str],
    *,
    stderr: TextIO,
) -> list[Path] | None:
    paths = [Path(raw_path) for raw_path in raw_paths] if raw_paths else [Path()]
    files: list[Path] = []
    seen: set[Path] = set()

    for path in paths:
        if not path.exists():
            print(f'make-ls: path not found: {path}', file=stderr)
            return None

        if path.is_file():
            _append_unique_path(files, seen, path)
            continue

        if not path.is_dir():
            print(f'make-ls: unsupported path: {path}', file=stderr)
            return None

        for candidate in _discover_makefiles(path):
            _append_unique_path(files, seen, candidate)

    return files


def _discover_makefiles(root: Path) -> list[Path]:
    discovered: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith('.'))
        discovered.extend(
            Path(directory, filename)
            for filename in sorted(filenames)
            if _is_makefile_name(filename)
        )

    return discovered


def _is_makefile_name(name: str) -> bool:
    return name in MAKEFILE_FILENAMES or name.endswith('.mk')


def _append_unique_path(files: list[Path], seen: set[Path], path: Path) -> None:
    resolved_path = path.resolve()
    if resolved_path in seen:
        return

    files.append(path)
    seen.add(resolved_path)


def _format_diagnostic(
    path: Path,
    diagnostic: lsp.Diagnostic,
    *,
    source_lines: list[str],
    color: bool,
) -> str:
    start = diagnostic.range.start
    style = _diagnostic_style(diagnostic.severity)
    message = _single_line_message(diagnostic.message)
    location = f'{_display_path(path)}:{start.line + 1}:{start.character + 1}'
    header = (
        f'{_styled(location, ANSI_BOLD, enabled=color)}: '
        f'{_styled(style.name, style.ansi_code, enabled=color)}: '
        f'{message}'
    )
    context = _format_diagnostic_context(
        source_lines,
        diagnostic,
        color_code=style.ansi_code,
        color=color,
    )
    if context is None:
        return header
    return f'{header}\n{context}'


def _display_path(path: Path) -> str:
    resolved_path = path.resolve()
    current_directory = Path.cwd().resolve()
    try:
        return str(resolved_path.relative_to(current_directory))
    except ValueError:
        return str(path)


def _diagnostic_style(severity: lsp.DiagnosticSeverity | int | None) -> DiagnosticStyle:
    if severity is None:
        return DEFAULT_DIAGNOSTIC_STYLE
    return DIAGNOSTIC_STYLES.get(int(severity), DEFAULT_DIAGNOSTIC_STYLE)


def _sarif_log(
    checked_files: list[CheckedFile],
) -> dict[str, object]:
    rules: dict[str, dict[str, object]] = {}
    results: list[dict[str, object]] = []
    for checked_file in checked_files:
        artifact_uri = checked_file.path.resolve().as_uri()
        for diagnostic in checked_file.diagnostics:
            rule_id = _sarif_rule_id(diagnostic)
            if rule_id is not None and rule_id not in rules:
                rules[rule_id] = {
                    'id': rule_id,
                    'shortDescription': {'text': _diagnostic_summary(diagnostic.message)},
                }

            results.append(
                _sarif_result(
                    diagnostic,
                    artifact_uri=artifact_uri,
                    rule_id=rule_id,
                    source_lines=checked_file.source_lines,
                )
            )

    driver: dict[str, object] = {'name': 'make-ls'}
    if rules:
        driver['rules'] = list(rules.values())

    return {
        '$schema': 'https://json.schemastore.org/sarif-2.1.0.json',
        'version': '2.1.0',
        'runs': [
            {
                'tool': {'driver': driver},
                'columnKind': 'unicodeCodePoints',
                'results': results,
            }
        ],
    }


def _sarif_result(
    diagnostic: lsp.Diagnostic,
    *,
    artifact_uri: str,
    rule_id: str | None,
    source_lines: list[str],
) -> dict[str, object]:
    start = diagnostic.range.start
    region: dict[str, object] = {
        'startLine': start.line + 1,
        'startColumn': start.character + 1,
    }
    if 0 <= start.line < len(source_lines):
        region['snippet'] = {'text': source_lines[start.line]}

    result: dict[str, object] = {
        'level': _diagnostic_style(diagnostic.severity).sarif_level,
        'message': {'text': _single_line_message(diagnostic.message)},
        'locations': [
            {
                'physicalLocation': {
                    'artifactLocation': {'uri': artifact_uri},
                    'region': region,
                }
            }
        ],
    }
    if rule_id is not None:
        result['ruleId'] = rule_id
    return result


def _sarif_rule_id(diagnostic: lsp.Diagnostic) -> str | None:
    if diagnostic.code is not None:
        return str(diagnostic.code)

    message = diagnostic.message
    if message.startswith('Invalid Makefile syntax'):
        return 'make-syntax'
    if message.startswith('Invalid shell syntax in recipe'):
        return 'shell-syntax'
    if message.startswith('Invalid variable reference in assignment'):
        return 'invalid-variable-reference'
    return None


def _diagnostic_summary(message: str) -> str:
    prefix, separator, _rest = message.partition(': `')
    if separator != '':
        return prefix
    return message


def _single_line_message(message: str) -> str:
    return ' '.join(message.splitlines())


def _format_diagnostic_context(
    source_lines: list[str],
    diagnostic: lsp.Diagnostic,
    *,
    color_code: str,
    color: bool,
) -> str | None:
    start = diagnostic.range.start
    if start.line < 0 or start.line >= len(source_lines):
        return None

    raw_line = source_lines[start.line]
    line_number = start.line + 1
    gutter_width = len(str(line_number))
    display_line = raw_line.expandtabs(CHECK_CONTEXT_TAB_WIDTH)
    marker_start = _display_column(raw_line, start.character)
    marker_end_character = (
        diagnostic.range.end.character if diagnostic.range.end.line == start.line else len(raw_line)
    )
    marker_end = _display_column(raw_line, marker_end_character)
    marker_width = max(1, marker_end - marker_start)
    marker = (' ' * marker_start) + ('^' * marker_width)
    line_prefix = _styled(f'{line_number:>{gutter_width}} | ', ANSI_DIM, enabled=color)
    marker_prefix = _styled(f'{" " * gutter_width} | ', ANSI_DIM, enabled=color)
    marker_text = _styled(marker, color_code, enabled=color)
    return f'{line_prefix}{display_line}\n{marker_prefix}{marker_text}'


def _display_column(text: str, character: int) -> int:
    clamped_character = max(0, min(character, len(text)))
    # LSP columns are character-based, so expand tabs before drawing carets.
    return len(text[:clamped_character].expandtabs(CHECK_CONTEXT_TAB_WIDTH))


def _check_uses_color(stream: TextIO) -> bool:
    force_color = os.environ.get('FORCE_COLOR')
    if force_color not in {None, '', '0'}:
        return True
    if os.environ.get('NO_COLOR') is not None:
        return False
    isatty = getattr(stream, 'isatty', None)
    if isatty is None or not isatty():
        return False
    return os.environ.get('TERM', '') != 'dumb'


def _styled(text: str, *codes: str, enabled: bool) -> str:
    if not enabled or not codes:
        return text
    return ''.join(codes) + text + ANSI_RESET


def configure_logging(log_file: Path | None, log_level: str) -> None:
    logger = logging.getLogger('make_ls')
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
    handler = logging.FileHandler(log_path, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVELS[log_level])
    logger.info('logging enabled path=%s level=%s', log_path, log_level)


def _resolved_log_file(
    raw_log_file: str | None,
    *,
    command: str | None,
    no_log_file: bool,
) -> Path | None:
    if no_log_file:
        return None
    if raw_log_file == '':
        return _default_log_file()
    if raw_log_file is not None:
        return Path(raw_log_file)
    if command is None:
        return _default_log_file()
    return None


def _default_log_file() -> Path:
    launch_path = Path.cwd().resolve()
    launch_hash = hashlib.sha1(str(launch_path).encode('utf-8')).hexdigest()[:8]
    raw_state_home = os.environ.get('XDG_STATE_HOME')
    state_home = (
        Path(raw_state_home).expanduser()
        if raw_state_home is not None
        else Path.home() / '.local' / 'state'
    )
    return state_home / 'make-ls' / f'make-ls-{launch_hash}.log'


if __name__ == '__main__':
    raise SystemExit(main())
