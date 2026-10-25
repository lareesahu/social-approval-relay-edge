#!/usr/bin/env python3
"""Pull the rendered post designs into this service's image at BUILD time.

The relay serves /media/<file> from <repo>/media. The designs live in the PRIVATE repo
lareesahu/social-approval-relay (they are unreleased marketing material, so they must not be
published to a public repo to make Render's free-plan "public repository only" rule happy).
This script runs in the Render build, clones that private repo with GH_TOKEN, copies the media
across, and deletes the clone - the images end up inside the built service image, never in a
public git history.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

PRIVATE = 'github.com/lareesahu/social-approval-relay.git'
EXTS = {'.jpg', '.jpeg', '.png', '.mp4', '.webm'}


def main() -> int:
    token = os.environ.get('GH_TOKEN', '').strip()
    if not token:
        print('WARNING: GH_TOKEN absent - building without media', flush=True)
        return 0
    root = pathlib.Path.cwd()
    dest = root / 'media'
    dest.mkdir(exist_ok=True)
    clone = root / '_src'
    if clone.exists():
        shutil.rmtree(clone, ignore_errors=True)
    subprocess.check_call(['git', 'clone', '--depth', '1', '--quiet',
                           f'https://x-access-token:{token}@{PRIVATE}', str(clone)])
    src = clone / 'media'
    n = 0
    if src.is_dir():
        for f in src.iterdir():
            if f.is_file() and f.suffix.lower() in EXTS:
                shutil.copy2(f, dest / f.name)
                n += 1
    shutil.rmtree(clone, ignore_errors=True)
    print(f'media files copied: {n}', flush=True)
    if n == 0:
        print('ERROR: no media copied', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
