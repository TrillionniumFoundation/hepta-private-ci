"""Hash every tracked worktree object against the complete fixed Git roster."""

import hashlib
import os
from pathlib import PurePosixPath
import re
import stat

from sha256_asm_lock_guards import require


def roster(root, git, tree):
    raw = git(root, "ls-tree", "-r", "-z", "-l", tree)
    records = raw.split(b"\0")
    require(records[-1] == b"", "INCOMPLETE_TRACKED_ROSTER")
    result = {}
    for record in records[:-1]:
        header, tab, raw_path = record.partition(b"\t")
        fields = header.split()
        require(tab == b"\t" and len(fields) == 4, "INVALID_TRACKED_ENTRY")
        mode, kind, digest, size = [value.decode("ascii") for value in fields]
        path = raw_path.decode("utf-8")
        parts = PurePosixPath(path).parts
        require(
            path not in result
            and parts
            and all(p not in (".", "..") for p in parts)
            and not path.startswith("/")
            and "/".join(parts) == path,
            "UNSAFE_OR_DUPLICATE_TRACKED_PATH",
        )
        require(
            mode in ("100644", "100755", "120000")
            and kind == "blob"
            and re.fullmatch(r"[0-9a-f]{40}", digest)
            and size.isdecimal(),
            "UNSUPPORTED_TRACKED_OBJECT",
        )
        result[path] = {"mode": mode, "git_blob": digest, "bytes": int(size)}
    return result


def stable(stat_value):
    return (
        stat_value.st_dev,
        stat_value.st_ino,
        stat_value.st_mode,
        stat_value.st_nlink,
        stat_value.st_size,
        stat_value.st_mtime_ns,
        stat_value.st_ctime_ns,
    )


def verify_object(root_fd, path, expected):
    directory = os.dup(root_fd)
    try:
        parts = PurePosixPath(path).parts
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        before = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        require(
            before.st_nlink == 1 and before.st_size == expected["bytes"],
            "TRACKED_OBJECT_SIZE_OR_LINKS_CHANGED",
        )
        digest = hashlib.sha1(b"blob " + str(expected["bytes"]).encode() + b"\0")
        if expected["mode"] == "120000":
            require(stat.S_ISLNK(before.st_mode), "TRACKED_SYMLINK_TYPE_CHANGED")
            raw = os.fsencode(os.readlink(parts[-1], dir_fd=directory))
            require(len(raw) == expected["bytes"], "TRACKED_SYMLINK_SIZE_CHANGED")
            digest.update(raw)
        else:
            permissions = 0o755 if expected["mode"] == "100755" else 0o644
            require(
                stat.S_ISREG(before.st_mode)
                and stat.S_IMODE(before.st_mode) == permissions,
                "TRACKED_REGULAR_MODE_CHANGED",
            )
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory
            )
            with os.fdopen(descriptor, "rb") as stream:
                require(
                    stable(os.fstat(stream.fileno())) == stable(before),
                    "TRACKED_OBJECT_REPLACED_BEFORE_READ",
                )
                count = 0
                while True:
                    data = stream.read(min(1024 * 1024, expected["bytes"] - count + 1))
                    if not data:
                        break
                    count += len(data)
                    require(
                        count <= expected["bytes"], "TRACKED_OBJECT_GREW_DURING_READ"
                    )
                    digest.update(data)
                require(
                    count == expected["bytes"]
                    and stable(os.fstat(stream.fileno())) == stable(before),
                    "TRACKED_OBJECT_CHANGED_DURING_READ",
                )
        require(
            stable(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False))
            == stable(before),
            "TRACKED_OBJECT_REPLACED_AFTER_READ",
        )
        require(
            digest.hexdigest() == expected["git_blob"], "TRACKED_WORKTREE_BLOB_MISMATCH"
        )
    finally:
        os.close(directory)


def verify_worktree(root, git, base_tree, head_tree, additions, overrides=None):
    base, head = roster(root, git, base_tree), roster(root, git, head_tree)
    require(
        not (set(base) & additions) and set(head) == set(base) | additions,
        "TRACKED_WORKTREE_ROSTER_CHANGED",
    )
    require(
        all(head[path] == item for path, item in base.items()),
        "ORIGINAL_TRACKED_TREE_CHANGED",
    )
    expected = dict(head)
    overrides = overrides or {}
    require(
        not overrides
        or set(overrides)
        == {
            "codex-rs/hepta-contracts/Cargo.toml",
            "codex-rs/Cargo.lock",
            "MODULE.bazel.lock",
        },
        "UNEXPECTED_WORKTREE_OVERRIDE_SET",
    )
    for path, item in overrides.items():
        require(
            path in base
            and set(item) == {"mode", "git_blob", "bytes"}
            and item["mode"] == base[path]["mode"] == "100644"
            and re.fullmatch(r"[0-9a-f]{40}", item["git_blob"])
            and type(item["bytes"]) is int
            and item["bytes"] >= 0,
            "INVALID_WORKTREE_OVERRIDE",
        )
        expected[path] = item
    inventory = hashlib.sha256()
    total = 0
    modes = {}
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for path, item in sorted(expected.items()):
            verify_object(root_fd, path, item)
            inventory.update(
                (
                    item["mode"]
                    + " "
                    + item["git_blob"]
                    + " "
                    + str(item["bytes"])
                    + "\t"
                    + path
                    + "\0"
                ).encode()
            )
            total += item["bytes"]
            modes[item["mode"]] = modes.get(item["mode"], 0) + 1
    finally:
        os.close(root_fd)
    return {
        "base_tree": base_tree,
        "head_tree": head_tree,
        "base_leaves": len(base),
        "checked_worktree_leaves": len(expected),
        "checked_bytes": total,
        "mode_counts": modes,
        "worktree_inventory_sha256": inventory.hexdigest(),
        "exact_validated_output_overrides": overrides,
        "all_tracked_objects_rehashed": True,
        "symlink_targets_hashed_without_following": True,
        "stat_cache_not_used_as_byte_evidence": True,
    }
