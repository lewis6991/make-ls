from __future__ import annotations

import io
import json
import logging
import re
from typing import TYPE_CHECKING, cast, override

import pytest

from make_ls import __main__ as cli

if TYPE_CHECKING:
    from pathlib import Path

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def expect_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast('dict[str, object]', value)


def expect_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast('list[object]', value)


def test_main_without_subcommand_starts_language_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {'started': False}
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))

    class FakeServer:
        def start_io(self) -> None:
            state['started'] = True

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main([]) == 0
    finally:
        cli.configure_logging(None, 'debug')

    assert state['started'] is True


def test_main_uses_default_xdg_log_file_for_stdio_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_home = tmp_path / 'state'
    workspace = tmp_path / 'workspace-dir'
    _ = workspace.mkdir()
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    monkeypatch.chdir(workspace)

    class FakeServer:
        def start_io(self) -> None:
            logging.getLogger('make_ls.server').info('fake server started')

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main([]) == 0
    finally:
        cli.configure_logging(None, 'debug')

    log_files = list((state_home / 'make-ls').glob('*.log'))
    assert len(log_files) == 1
    log_path = log_files[0]
    assert log_path.stem.startswith('make-ls-')
    assert len(log_path.stem) == len('make-ls-') + 8
    assert all(
        character in '0123456789abcdef' for character in log_path.stem.removeprefix('make-ls-')
    )
    assert log_path.exists()
    log_text = log_path.read_text(encoding='utf-8')
    assert 'starting stdio server' in log_text
    assert 'fake server started' in log_text


def test_main_reuses_default_xdg_log_file_for_same_stdio_launch_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_home = tmp_path / 'state'
    workspace = tmp_path / 'workspace-dir'
    _ = workspace.mkdir()
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    monkeypatch.chdir(workspace)

    class FakeServer:
        def start_io(self) -> None:
            logging.getLogger('make_ls.server').info('fake server started')

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main([]) == 0
        cli.configure_logging(None, 'debug')
        assert cli.main([]) == 0
    finally:
        cli.configure_logging(None, 'debug')

    log_files = sorted((state_home / 'make-ls').glob('*.log'))
    assert len(log_files) == 1
    log_path = log_files[0]
    assert log_path.stem.startswith('make-ls-')
    assert len(log_path.stem) == len('make-ls-') + 8
    assert all(
        character in '0123456789abcdef' for character in log_path.stem.removeprefix('make-ls-')
    )
    log_text = log_path.read_text(encoding='utf-8')
    assert log_text.count('starting stdio server') == 2


def test_main_writes_logs_when_log_file_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / 'make-ls.log'
    state = {'started': False}

    class FakeServer:
        def start_io(self) -> None:
            state['started'] = True
            logging.getLogger('make_ls.server').info('fake server started')

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main(['--log-file', str(log_path), '--log-level', 'info']) == 0
    finally:
        cli.configure_logging(None, 'debug')

    assert state['started'] is True
    log_text = log_path.read_text(encoding='utf-8')
    assert 'logging enabled path=' in log_text
    assert 'starting stdio server' in log_text
    assert 'fake server started' in log_text


def test_main_uses_default_xdg_log_file_when_log_file_has_no_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_home = tmp_path / 'state'
    workspace = tmp_path / 'workspace-dir'
    _ = workspace.mkdir()
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    monkeypatch.chdir(workspace)

    class FakeServer:
        def start_io(self) -> None:
            logging.getLogger('make_ls.server').info('fake server started')

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main(['--log-file', '--log-level', 'info']) == 0
    finally:
        cli.configure_logging(None, 'debug')

    log_files = list((state_home / 'make-ls').glob('*.log'))
    assert len(log_files) == 1
    log_path = log_files[0]
    assert log_path.exists()
    log_text = log_path.read_text(encoding='utf-8')
    assert f'path={log_path}' in log_text
    assert 'fake server started' in log_text


def test_main_can_disable_default_stdio_log_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_home = tmp_path / 'state'
    workspace = tmp_path / 'workspace-dir'
    _ = workspace.mkdir()
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    monkeypatch.chdir(workspace)

    class FakeServer:
        def start_io(self) -> None:
            logging.getLogger('make_ls.server').info('fake server started')

    monkeypatch.setattr(cli, 'create_server', lambda: FakeServer())

    try:
        assert cli.main(['--no-log-file']) == 0
    finally:
        cli.configure_logging(None, 'debug')

    assert list((state_home / 'make-ls').glob('*.log')) == []


@pytest.mark.parametrize('flag', ['-h', '--help'])
def test_help_flag_prints_usage(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _ = cli.main([flag])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert 'usage: make-ls' in captured.out
    assert 'check [paths ...]' in captured.out


def test_check_reports_diagnostics_for_positional_file_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / 'defs').write_text('all dep\n', encoding='utf-8')
    _ = (tmp_path / 'rules').write_text('also bad\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert cli.main(['check', 'defs', 'rules']) == 1

    captured = capsys.readouterr()
    assert captured.err == ''
    assert captured.out == (
        'defs:1:1: error: Invalid Makefile syntax: `all dep`\n'
        '1 | all dep\n'
        '  | ^^^^^^^\n'
        '\n'
        'rules:1:1: error: Invalid Makefile syntax: `also bad`\n'
        '1 | also bad\n'
        '  | ^^^^^^^^\n'
    )


def test_check_reports_unresolved_prerequisite_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / 'Makefile').write_text('all: dep\n\t@echo done\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert cli.main(['check', 'Makefile']) == 1

    captured = capsys.readouterr()
    assert captured.err == ''
    assert captured.out == (
        'Makefile:1:6: warning: Unresolved prerequisite: `dep`\n1 | all: dep\n  |      ^^^\n'
    )


def test_check_uses_color_for_tty_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = (tmp_path / 'Makefile').write_text('all dep\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setenv('TERM', 'xterm-256color')

    class TtyStringIO(io.StringIO):
        @override
        def isatty(self) -> bool:
            return True

    stdout = TtyStringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, 'stdout', stdout)
    monkeypatch.setattr(cli.sys, 'stderr', stderr)

    assert cli.main(['check', 'Makefile']) == 1
    plain_output = ANSI_ESCAPE_RE.sub('', stdout.getvalue())
    assert '\x1b[' in stdout.getvalue()
    assert plain_output == (
        'Makefile:1:1: error: Invalid Makefile syntax: `all dep`\n1 | all dep\n  | ^^^^^^^\n'
    )


def test_check_can_emit_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / 'Makefile').write_text('all: dep\n\t@echo done\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert cli.main(['check', '--format', 'json', 'Makefile']) == 1

    captured = capsys.readouterr()
    assert captured.err == ''
    sarif = expect_dict(cast('object', json.loads(captured.out)))
    assert sarif['version'] == '2.1.0'

    runs = expect_list(sarif['runs'])
    run = expect_dict(runs[0])
    assert run['columnKind'] == 'unicodeCodePoints'

    tool = expect_dict(run['tool'])
    driver = expect_dict(tool['driver'])
    assert driver['name'] == 'make-ls'

    results = expect_list(run['results'])
    result = expect_dict(results[0])
    assert result['ruleId'] == 'unresolved-prerequisite'
    assert result['level'] == 'warning'
    message = expect_dict(result['message'])
    assert message['text'] == 'Unresolved prerequisite: `dep`'

    locations = expect_list(result['locations'])
    location = expect_dict(locations[0])
    physical_location = expect_dict(location['physicalLocation'])
    artifact_location = expect_dict(physical_location['artifactLocation'])
    region = expect_dict(physical_location['region'])

    assert artifact_location['uri'] == (tmp_path / 'Makefile').resolve().as_uri()
    assert region == {
        'startLine': 1,
        'startColumn': 6,
        'snippet': {'text': 'all: dep'},
    }


def test_check_defaults_to_current_directory_and_skips_hidden_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / '.deps').mkdir()
    _ = (tmp_path / '.deps' / 'Makefile').write_text('all dep\n', encoding='utf-8')
    _ = (tmp_path / 'sub').mkdir()
    _ = (tmp_path / 'sub' / 'rules.mk').write_text('all:\n\t@echo ok\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert cli.main(['check']) == 0

    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ''


def test_check_errors_when_no_makefiles_are_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(['check']) == 2

    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err.strip() == 'make-ls: no Makefiles found'
