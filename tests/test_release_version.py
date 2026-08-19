from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read_json_object(path: Path) -> dict[str, object]:
    value = cast('object', json.loads(path.read_text(encoding='utf-8')))
    assert isinstance(value, dict)
    return cast('dict[str, object]', value)


@pytest.mark.parametrize(
    ('release_version', 'vscode_version'),
    [
        ('1.2.3', '1.2.3'),
        ('1.2.4.dev7', '1.2.4-dev.7'),
    ],
)
def test_stamp_updates_json_versions_and_removes_resolved_urls(
    tmp_path: Path,
    release_version: str,
    vscode_version: str,
) -> None:
    project = tmp_path / 'project'
    script_path = project / 'scripts' / 'release_version.py'
    _ = script_path.parent.mkdir(parents=True)
    _ = shutil.copy2(ROOT / 'scripts' / 'release_version.py', script_path)
    _ = (project / 'pyproject.toml').write_text(
        '[project]\nversion = "0.4.0"\n',
        encoding='utf-8',
    )
    package_version_path = project / 'src' / 'make_ls' / '_version.py'
    _ = package_version_path.parent.mkdir(parents=True)
    _ = package_version_path.write_text("__version__ = '0.4.0'\n", encoding='utf-8')
    _ = (project / 'uv.lock').write_text(
        '[[package]]\nname = "make-ls"\nversion = "0.4.0"\n',
        encoding='utf-8',
    )
    vscode = project / 'editors' / 'vscode'
    _ = vscode.mkdir(parents=True)
    package_json_path = vscode / 'package.json'
    _ = package_json_path.write_text(
        '{"name": "make-ls", "version": "0.4.0"}\n',
        encoding='utf-8',
    )
    package_lock_path = vscode / 'package-lock.json'
    _ = package_lock_path.write_text(
        json.dumps(
            {
                'version': '0.4.0',
                'resolved': 'https://example.com/root.tgz',
                'packages': {
                    '': {
                        'version': '0.4.0',
                        'resolved': 'https://example.com/package.tgz',
                    },
                },
                'dependencies': {
                    'example': {'resolved': 'https://example.com/dependency.tgz'},
                },
            },
        ),
        encoding='utf-8',
    )

    result = subprocess.run(
        [sys.executable, str(script_path), 'stamp', release_version],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert _read_json_object(package_json_path) == {
        'name': 'make-ls',
        'version': vscode_version,
    }
    assert _read_json_object(package_lock_path) == {
        'version': vscode_version,
        'packages': {'': {'version': vscode_version}},
        'dependencies': {'example': {}},
    }
