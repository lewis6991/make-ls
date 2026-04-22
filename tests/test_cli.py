from __future__ import annotations

from pathlib import Path

import pytest

from make_ls import __main__ as cli


def test_main_without_subcommand_starts_language_server(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"started": False}

    class FakeServer:
        def start_io(self) -> None:
            state["started"] = True

    monkeypatch.setattr(cli, "create_server", lambda: FakeServer())

    assert cli.main([]) == 0
    assert state["started"] is True


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag_prints_usage(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _ = cli.main([flag])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage: make-ls" in captured.out
    assert "check [paths ...]" in captured.out


def test_check_reports_diagnostics_for_positional_file_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / "defs").write_text("all dep\n", encoding="utf-8")
    _ = (tmp_path / "rules").write_text("also bad\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["check", "defs", "rules"]) == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "defs:1:1: error: Invalid Makefile syntax near `all dep`",
        "rules:1:1: error: Invalid Makefile syntax near `also bad`",
    ]


def test_check_defaults_to_current_directory_and_skips_hidden_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / ".deps").mkdir()
    _ = (tmp_path / ".deps" / "Makefile").write_text("all dep\n", encoding="utf-8")
    _ = (tmp_path / "sub").mkdir()
    _ = (tmp_path / "sub" / "rules.mk").write_text("all:\n\t@echo ok\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["check"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_check_errors_when_no_makefiles_are_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.main(["check"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "make-ls: no Makefiles found"
