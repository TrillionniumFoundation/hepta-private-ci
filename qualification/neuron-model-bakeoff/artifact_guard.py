"""Disposable runtime copies keep SDK compatibility rewrites off frozen artifacts."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from bakeoff import file_hash, require


def snapshot_files(root: Path) -> dict[str, str]:
    inventory = {}
    for path in sorted(root.rglob('*')):
        require(not (path.is_symlink() and path.is_dir()),
                'snapshot directory symlinks are not supported')
        if path.is_dir():
            continue
        require(path.is_file() and path.resolve(strict=True).is_relative_to(root.parent.parent),
                f'absent/escaped snapshot file: {path}')
        inventory[path.relative_to(root).as_posix()] = file_hash(path)
    require(bool(inventory), 'snapshot files absent')
    return inventory


class SnapshotGuard:
    """Hash all files, copy rather than hardlink, and reject any runtime drift."""

    def __init__(self, source: Path):
        self.source = source
        self.original = snapshot_files(source)
        self.digest = hashlib.sha256(json.dumps(
            self.original, sort_keys=True, separators=(',', ':'),
        ).encode()).hexdigest()
        self.temp = None

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hepta-frozen-model-')
        self.path = (Path(self.temp.name) / self.source.parent.parent.name /
                     'snapshots' / self.source.name)
        try:
            # Never hardlink: some SDK versions overwrite in place.
            shutil.copytree(self.source, self.path, symlinks=False)
            self.verify('after copy')
        except BaseException:
            self.temp.cleanup()
            raise
        return self

    def verify(self, stage: str) -> None:
        for scope, root in (('frozen source', self.source), ('runtime copy', self.path)):
            actual = snapshot_files(root)
            changes = sorted(name for name in set(actual) | set(self.original)
                             if actual.get(name) != self.original.get(name))
            require(not changes, f'{stage}: {scope} artifact drift: {changes}')

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.verify('before publishing observations')
        finally:
            self.temp.cleanup()
