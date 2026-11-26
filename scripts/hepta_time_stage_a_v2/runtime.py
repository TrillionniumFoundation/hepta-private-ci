"""New-scope adapter for the unchanged pinned process and source owner.

Only Scope, its observations and source_snapshot/require_tree are reused.
No old preparation, resolver, registration, control or main entry is called.
"""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time

import run_chrono_hooks_cli_lock_scope_v1 as original
from . import contract as c

require = original.require
sha256 = original.digest
json_value = original.json_value


def now():
    return datetime.now(timezone.utc).isoformat()


def git_hash(kind, raw):
    return hashlib.sha1(
        kind.encode("ascii") + b" " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def relative(value):
    require(
        type(value) is str and value and "\0" not in value and "\\" not in value,
        "invalid relative path",
    )
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in ("", ".", "..", ".git") for part in path.parts),
        "unsafe relative path: " + value,
    )
    return value


def stable_read(path, limit=c.MAX_FILE):
    """Read a regular file without following any existing path symlink."""
    path = Path(path).absolute()
    for parent in reversed(path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode), "non-directory path ancestor")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_size <= limit,
            "unexpected regular-file identity or size",
        )
        chunks = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            require(total <= limit, "file exceeded its declared bound")
        after = os.fstat(descriptor)
        names = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        require(
            all(getattr(before, name) == getattr(after, name) for name in names),
            "file changed during read",
        )
        require(path.lstat().st_ino == after.st_ino, "file path changed during read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def leaf_pin(raw, mode):
    return {
        "bytes": len(raw),
        "sha256": sha256(raw),
        "git_blob": git_hash("blob", raw),
        "mode": mode,
    }


def put_raw(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"bytes": len(raw), "sha256": sha256(raw)}


def put(path, value):
    return put_raw(
        path,
        (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
            "utf-8"
        ),
    )


def read_json(path):
    return json_value(stable_read(path, 16 * 1024 * 1024)[0])


class Context:
    def __init__(self, root, evidence, phase, start, cap):
        self.root, self.evidence = root, evidence
        self.scope = original.Scope(root, evidence.parent, phase, start, cap)

    def remaining(self):
        value = self.scope.deadline - time.monotonic()
        require(math.isfinite(value) and value > 0, "absolute phase deadline expired")
        return value

    def check_time(self):
        self.remaining()

    def command(self, label, argv, cap):
        stdout, _ = self.scope.run(label, argv, self.root, cap)
        row = self.scope.commands[-1]
        require(row["elapsed_seconds"] <= cap, "actual command exceeded its phase cap")
        self.check_time()
        raw, _ = stable_read(stdout)
        require(
            sha256(raw) == row["files"][stdout.name]["sha256"],
            "retained original stdout changed",
        )
        return row, raw

    def git(self, *args):
        return self.scope.read_git(self.root, *args)

    def snapshot(self, tree, permitted=frozenset()):
        observed = original.source_snapshot(self.scope, self.root, tree)
        require(
            16000 < len(observed) <= c.MAX_TREE_FILES
            and sum(row["bytes"] for row in observed.values()) <= c.MAX_TREE_BYTES,
            "complete source exceeds its fixed count or byte bounds",
        )
        for name, row in observed.items():
            relative(name)
            require(row["bytes"] <= c.MAX_FILE, "source leaf exceeds its byte bound")
            if row["mode"] == "120000":
                require(
                    name == "codex-rs/vendor/bubblewrap/LICENSE",
                    "unreviewed source symlink",
                )
            for parent in (self.root / name).parents:
                require(
                    stat.S_ISDIR(parent.lstat().st_mode),
                    "source path has a symlink ancestor",
                )
            require(
                name in permitted or row["git_blob"] == row["expected_git_blob"],
                "physical source differs from its Git tree",
            )
        if not permitted:
            original.require_tree(observed, "Stage A physical source")
        self.check_time()
        return {
            name: {key: row[key] for key in ("mode", "bytes", "sha256", "git_blob")}
            for name, row in observed.items()
        }

    def load_original(self, relative_path, module_name):
        raw, _ = stable_read(self.root / relative_path)
        require(
            sha256(raw) == c.ORIGINAL_HELPERS[relative_path],
            "original execution or collection owner changed",
        )
        spec = importlib.util.spec_from_file_location(
            module_name, self.root / relative_path
        )
        require(
            spec is not None and spec.loader is not None, "original module unavailable"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def commit_identity(self, sha):
        require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "invalid commit SHA")
        raw = self.git("cat-file", "commit", sha)
        require(git_hash("commit", raw) == sha, "raw commit does not match object name")
        headers = raw.split(b"\n\n", 1)[0].decode("utf-8").splitlines()
        trees = [line[5:] for line in headers if line.startswith("tree ")]
        require(len(trees) == 1, "commit has no unique tree")
        return {
            "head": sha,
            "tree": trees[0],
            "parents": [line[7:] for line in headers if line.startswith("parent ")],
        }, raw

    def assert_clean(self):
        require(
            not self.git("status", "--porcelain=v1", "--untracked-files=all"),
            "working tree is not clean",
        )
        require(
            not self.git("diff", "--cached", "--name-only", "HEAD"),
            "index differs from HEAD",
        )
        require(
            all(
                row.startswith(b"H ")
                for row in self.git("ls-files", "-v", "-z").split(b"\0")
                if row
            ),
            "index hides source through assume-unchanged or skip-worktree",
        )
