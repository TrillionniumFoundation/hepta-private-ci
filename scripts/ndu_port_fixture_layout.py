"""Bind fixture permissions to producer bytes and restore only a new private copy."""

import os
from pathlib import Path
import shutil
import stat

from ndu_port_candidate_common import HEX256
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import relative_path


SCHEMA = "hepta.ci.fixture-layout.v1"
MANIFEST = "fixture-layout.json"


def validate_layout(layout):
    if (
        not isinstance(layout, dict)
        or set(layout) != {"schema", "root_mode", "directories", "files"}
        or layout["schema"] != SCHEMA
    ):
        raise ValueError("Invalid fixture layout schema")
    directories, files = layout["directories"], layout["files"]
    if not isinstance(directories, dict) or not isinstance(files, dict):
        raise ValueError("Fixture layout must bind complete directory and file sets")
    if set(directories) & set(files):
        raise ValueError("A fixture path cannot be both a directory and a file")
    for name in (*directories, *files):
        if relative_path(name) == ".":
            raise ValueError("Fixture children cannot be the root path")
        if any(
            parent.as_posix() not in directories
            for parent in Path(name).parents
            if parent.as_posix() != "."
        ):
            raise ValueError("Fixture layout omits a parent directory")
    modes = [(layout["root_mode"], 0o700)]
    modes.extend((mode, 0o700) for mode in directories.values())
    for entry in files.values():
        if not isinstance(entry, dict) or set(entry) != {"bytes", "sha256", "mode"}:
            raise ValueError("Invalid fixture file identity")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ValueError("Invalid fixture file size")
        if not isinstance(entry["sha256"], str) or not HEX256.fullmatch(
            entry["sha256"]
        ):
            raise ValueError("Invalid fixture file hash")
        modes.append((entry["mode"], 0o600))
    for mode, owner in modes:
        if type(mode) is not int or mode < 0 or mode & ~0o777 or mode & owner != owner:
            raise ValueError(
                "Fixture modes must be ordinary and writable by their owner"
            )
    return layout


def snapshot_layout(root):
    root = Path(root)
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("Fixture root must be a plain directory")
    layout = {
        "schema": SCHEMA,
        "root_mode": stat.S_IMODE(root_stat.st_mode),
        "directories": {},
        "files": {},
    }

    def visit(directory):
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for child in children:
            path = Path(child.path)
            name = relative_path(path.relative_to(root).as_posix())
            information = path.lstat()
            mode = stat.S_IMODE(information.st_mode)
            if stat.S_ISDIR(information.st_mode):
                layout["directories"][name] = mode
                visit(path)
            elif stat.S_ISREG(information.st_mode) and information.st_nlink == 1:
                layout["files"][name] = {
                    "bytes": information.st_size,
                    "sha256": checksum(path),
                    "mode": mode,
                }
            else:
                raise ValueError(
                    "Fixture members must be plain directories or single-link regular files"
                )

    visit(root)
    return validate_layout(layout)


def file_identities(layout):
    return {
        name: {"bytes": entry["bytes"], "sha256": entry["sha256"]}
        for name, entry in layout["files"].items()
    }


def restore_copy(source, destination, layout):
    validate_layout(layout)
    transported = snapshot_layout(source)
    if set(transported["directories"]) != set(layout["directories"]) or file_identities(
        transported
    ) != file_identities(layout):
        raise ValueError(
            "Old database directory set, file set or bytes differ from the producer"
        )
    destination.mkdir(mode=0o700, exist_ok=False)
    for name in sorted(layout["directories"], key=lambda name: (name.count("/"), name)):
        (destination / name).mkdir(mode=0o700)
    for name, entry in layout["files"].items():
        target = destination / name
        shutil.copyfile(source / name, target, follow_symlinks=False)
        target.chmod(entry["mode"], follow_symlinks=False)
    for name in sorted(
        layout["directories"], key=lambda name: (-name.count("/"), name)
    ):
        (destination / name).chmod(layout["directories"][name])
    destination.chmod(layout["root_mode"])
    if snapshot_layout(destination) != layout:
        raise ValueError(
            "Restored fixture differs in membership, bytes or original permissions"
        )
    if snapshot_layout(source) != transported:
        raise ValueError("Fixture copy changed the preserved transport source")
    return transported
