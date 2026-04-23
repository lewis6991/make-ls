from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from typing import Literal, cast

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / 'pyproject.toml'
PACKAGE_VERSION_PATH = ROOT / 'src' / 'make_ls' / '_version.py'
UV_LOCK_PATH = ROOT / 'uv.lock'

_PYPROJECT_VERSION_PATTERN = re.compile(r'(?m)^(version\s*=\s*)"[^"]+"$')
_MODULE_VERSION_PATTERN = re.compile(r"""(?m)^__version__ = ['"][^'"]+['"]$""")
_UV_LOCK_VERSION_PATTERN = re.compile(
    r'(?m)(^\[\[package\]\]\nname = "make-ls"\nversion\s*=\s*)"[^"]+"$'
)
_STABLE_VERSION_PATTERN = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
_DEV_VERSION_PATTERN = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\.dev([1-9]\d*)$')


class ReleaseVersionArgs(argparse.Namespace):
    command: Literal['compute', 'stamp']
    channel: Literal['stable', 'nightly']
    run_number: int
    version: str

    def __init__(self) -> None:
        super().__init__()
        self.command = 'compute'
        self.channel = 'stable'
        self.run_number = 0
        self.version = ''


def main() -> int:
    parser = argparse.ArgumentParser(description='Compute and stamp release versions.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    compute_parser = subparsers.add_parser('compute', help='Compute the release version.')
    _ = compute_parser.add_argument('--channel', choices=('stable', 'nightly'), required=True)
    _ = compute_parser.add_argument('--run-number', type=int, default=0)

    stamp_parser = subparsers.add_parser('stamp', help='Stamp files with a release version.')
    _ = stamp_parser.add_argument('version')

    args = cast('ReleaseVersionArgs', parser.parse_args())

    if args.command == 'compute':
        version = compute_release_version(
            base_version=read_project_version(),
            channel=args.channel,
            run_number=args.run_number,
        )
        print(version)
        return 0

    stamp_version(args.version)
    return 0


def read_project_version() -> str:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding='utf-8'))
    project_object = pyproject.get('project')
    if not isinstance(project_object, dict):
        raise TypeError('project must be a table')

    project = cast('dict[str, object]', project_object)
    version = project.get('version')
    if not isinstance(version, str):
        raise TypeError('project.version must be a string')
    _ = _parse_stable_version(version)
    return version


def compute_release_version(base_version: str, channel: str, run_number: int) -> str:
    major, minor, patch = _parse_stable_version(base_version)
    if channel == 'stable':
        return f'{major}.{minor}.{patch}'
    if run_number <= 0:
        raise ValueError('nightly builds require a positive run number')

    # Nightlies should sort before the next stable release while still producing
    # valid Python package versions for wheels and sdists.
    return f'{major}.{minor}.{patch + 1}.dev{run_number}'


def stamp_version(version: str) -> None:
    _validate_release_version(version)
    _replace_pattern(PYPROJECT_PATH, _PYPROJECT_VERSION_PATTERN, rf'\1"{version}"')
    _replace_pattern(PACKAGE_VERSION_PATH, _MODULE_VERSION_PATTERN, f"__version__ = '{version}'")
    _replace_pattern(UV_LOCK_PATH, _UV_LOCK_VERSION_PATTERN, rf'\1"{version}"')


def _parse_stable_version(version: str) -> tuple[int, int, int]:
    match = _STABLE_VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f'invalid stable version: {version}')
    major_text, minor_text, patch_text = match.groups()
    return int(major_text), int(minor_text), int(patch_text)


def _validate_release_version(version: str) -> None:
    if _STABLE_VERSION_PATTERN.fullmatch(version) is not None:
        return
    if _DEV_VERSION_PATTERN.fullmatch(version) is not None:
        return
    raise ValueError(f'invalid release version: {version}')


def _replace_pattern(path: Path, pattern: re.Pattern[str], replacement: str) -> None:
    text = path.read_text(encoding='utf-8')
    updated_text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ValueError(f'could not update version in {path}')
    _ = path.write_text(updated_text, encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
