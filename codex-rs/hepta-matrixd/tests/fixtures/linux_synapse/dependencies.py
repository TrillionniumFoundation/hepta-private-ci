"""Exact offline Cargo input custody, including bounded internal file links."""

import os
from pathlib import Path, PurePosixPath
import stat

from .files import copy_file, describe, physical, relative


SEED_SCHEMA = "hepta.synapse.linux.seed.v2"
CACHE_BOOKKEEPING = {
    ".package-cache", ".package-cache-mutate", ".global-cache",
    ".global-cache-journal", ".global-cache-wal", ".global-cache-shm",
}


def regular_link_target(seed, link, seen=()):
    """Resolve file-link chains without traversing directory links or the root."""
    if link in seen or len(seen) >= 40:
        raise ValueError("Cyclic or excessive dependency link chain")
    target = os.readlink(link)
    if (not target or PurePosixPath(target).is_absolute() or target.endswith("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        raise ValueError("Dependency link must name a relative regular file")
    # Preserve dot components: file/. is ENOTDIR, not the regular file.
    parts = target.split("/")
    current = link.parent
    for index, part in enumerate(parts):
        if part in {"", "."}:
            pass
        elif part == "..":
            if current == seed:
                raise ValueError("Dependency link escapes its seed root")
            current = current.parent
        else:
            current /= part
        metadata = current.lstat()
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("Dependency link traverses a nonphysical directory")
        elif stat.S_ISLNK(metadata.st_mode):
            return regular_link_target(seed, current, (*seen, link))
    if (not current.is_relative_to(seed) or current == seed
            or current.relative_to(seed).parts[0] not in {"registry", "git"}
            or not stat.S_ISREG(current.lstat().st_mode)):
        raise ValueError("Dependency link target is not an in-root registry/git file")
    return current


def dependency_inventory(seed):
    """Keep regular files and exact links; never use the general evidence walker."""
    seed = physical(seed)
    if not seed.is_dir():
        raise ValueError("Expected a physical Cargo seed directory")
    entries = {}
    for path in sorted(seed.rglob("*")):
        name = relative(path.relative_to(seed).as_posix())
        metadata = path.lstat()
        first = Path(name).parts[0]
        if first not in {"registry", "git", *CACHE_BOOKKEEPING}:
            raise ValueError("Offline seed permits only registry/git and known Cargo bookkeeping; no credentials/config/bin")
        if first in CACHE_BOOKKEEPING:
            if name != first or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Cargo bookkeeping must be a regular root file")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            target = regular_link_target(seed, path)
            entries[name] = {
                "kind": "symlink", "target": os.readlink(path),
                "resolved": target.relative_to(seed).as_posix(),
                "resolved_file": {**describe(target), "mode": stat.S_IMODE(target.stat().st_mode)},
            }
        elif stat.S_ISREG(metadata.st_mode):
            entries[name] = {"kind": "regular", **describe(path),
                             "mode": stat.S_IMODE(metadata.st_mode)}
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("Special entry in offline dependency seed")
    return entries


def copy_seed(seed, destination, expected):
    seed, destination = physical(seed), physical(destination)
    before = dependency_inventory(seed)
    if before != expected or not before:
        raise ValueError("Complete offline dependency seed differs from its frozen ledger")
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    # Files first: no destination link can redirect a regular-file creation or chmod.
    for name, item in before.items():
        if item["kind"] == "regular":
            copy_file(seed / name, destination / name, executable=bool(item["mode"] & 0o111))
            os.chmod(destination / name, item["mode"])
    for name, item in before.items():
        if item["kind"] == "symlink":
            target = physical(destination / name)
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            target.symlink_to(item["target"])
    if dependency_inventory(destination) != before or dependency_inventory(seed) != before:
        raise ValueError("Dependency seed copy failed complete write/readback verification")
    return before
