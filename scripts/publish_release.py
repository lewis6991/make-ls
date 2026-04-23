"""Create or update GitHub releases and upload built artifacts."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Sequence


class PublishReleaseArgs(argparse.Namespace):
    assets_dir: Path
    create_release: bool
    release_channel: Literal['stable', 'nightly']
    release_tag: str
    release_version: str

    def __init__(self) -> None:
        super().__init__()
        self.assets_dir = Path()
        self.create_release = False
        self.release_channel = 'stable'
        self.release_tag = ''
        self.release_version = ''


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Create or update a GitHub release and upload built artifacts.'
    )
    _ = parser.add_argument('--assets-dir', type=Path, required=True)
    _ = parser.add_argument('--release-channel', choices=('stable', 'nightly'), required=True)
    _ = parser.add_argument('--release-tag', required=True)
    _ = parser.add_argument('--release-version', required=True)
    _ = parser.add_argument('--create-release', action='store_true')
    args = cast('PublishReleaseArgs', parser.parse_args(argv))

    if args.create_release:
        create_or_update_release(
            release_channel=args.release_channel,
            release_tag=args.release_tag,
            release_version=args.release_version,
        )

    if not args.assets_dir.is_dir():
        raise ValueError(f'assets directory does not exist: {args.assets_dir}')

    assets = sorted(str(path) for path in args.assets_dir.rglob('*') if path.is_file())
    if not assets:
        raise ValueError(f'no release assets found in {args.assets_dir}')

    _ = run(['gh', 'release', 'upload', args.release_tag, *assets, '--clobber'])
    return 0


def create_or_update_release(
    *,
    release_channel: str,
    release_tag: str,
    release_version: str,
) -> None:
    prerelease = release_channel != 'stable'
    release_commit = run(['git', 'rev-parse', 'HEAD'], capture_output=True).stdout.strip()

    # Nightly runs reuse a rolling tag, so the workflow force-moves it first.
    _ = run(['git', 'tag', '-f', release_tag, release_commit])
    _ = run(['git', 'push', 'origin', f'refs/tags/{release_tag}', '--force'])

    release_args = ['--title', f'make-ls {release_version}']
    if prerelease:
        release_args.append('--prerelease')

    if run(['gh', 'release', 'view', release_tag], check=False).returncode == 0:
        _ = run(['gh', 'release', 'edit', release_tag, *release_args])
        return

    create_args = ['gh', 'release', 'create', release_tag, *release_args, '--generate-notes']
    if prerelease:
        create_args.append('--latest=false')
    _ = run(create_args)


def run(
    command: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=check,
        capture_output=capture_output,
        text=True,
    )


if __name__ == '__main__':
    raise SystemExit(main())
