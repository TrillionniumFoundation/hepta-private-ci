"""Bind one readonly inventory to its unchanged profile-probe parent."""

import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys

from hepta_core_selected_evidence import identity, read_regular, require

ROOT = Path(__file__).resolve().parents[2]
PARENT = "25d940b9b768b9117a020fe350fd134198a2efcf"
PARENT_TREE = "26277e2bebd9e9f5a7cd04869c955dfd2fa7ddd2"
INPUTS_HEAD = "937c7a87099496aabbf59dcc28570a61e4c984b7"
INPUTS_TREE = "0d2e86e3d826f8e1e41c4ce2a4101e91e57542ab"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
INPUTS_REF = "research/ndu-bwrap-inventory-inputs-20261106"
PROPOSAL_REF = "research/ndu-bwrap-inventory-probe-20261106"
CONTRACT = ".github/scripts/hepta_bwrap_inventory_contract.py"
INPUT_PATHS = {CONTRACT, ".github/scripts/hepta_bwrap_inventory_evidence.py"}
EXECUTOR_PATHS = {
    ".github/scripts/hepta_bwrap_inventory.py",
    ".github/workflows/hepta-bwrap-input-inventory.yml",
}
ADDED = INPUT_PATHS | EXECUTOR_PATHS
SCANNER_PATH = ".github/scripts/hepta_core_selected_evidence.py"
SCANNER_BLOB = "f18f5d0ce06cead0817513814da96f129523cf8c"
LIMIT = 4 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 4096
READS = {
    "include_01": "/etc/apparmor.d/tunables/home.d/ubuntu",
    "include_02": "/etc/apparmor.d/tunables/xdg-user-dirs.d/site.local",
}
DIRECTORIES = {
    "/etc/apparmor.d/tunables/home.d",
    "/etc/apparmor.d/tunables/multiarch.d",
    "/etc/apparmor.d/tunables/xdg-user-dirs.d",
}
PATHS = (
    set(READS.values())
    | DIRECTORIES
    | {
        str(parent)
        for name in set(READS.values()) | DIRECTORIES
        for parent in Path(name).parents
    }
    | {
        "/usr",
        "/usr/share",
        "/usr/share/apparmor",
        "/usr/share/apparmor/extra-profiles",
    }
)
SLOTS = {
    "source-before.json",
    "source-after.json",
    "readiness.json",
    "result.json",
    "before.paths.json",
    "after.paths.json",
} | {f"reads/{key}.raw" for key in READS}
STAT_FIELDS = (
    "mode",
    "permissions",
    "uid",
    "gid",
    "device",
    "inode",
    "nlink",
    "size",
    "mtime_ns",
    "ctime_ns",
)


def git(*args):
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    require(result.returncode == 0, "GIT_FAILED")
    return result.stdout


def source_guard():
    require(INPUTS_HEAD and INPUTS_TREE, "UNBOUND_SOURCE")
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "WRONG_PLATFORM"
    )
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "bwrap-inventory"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
        "WRONG_JOB",
    )
    require(
        [
            os.environ.get(name)
            for name in ("PROBE_RUNNER_CLASS", "PROBE_RUNNER_OS", "PROBE_RUNNER_ARCH")
        ]
        == ["github-hosted", "Linux", "X64"],
        "WRONG_RUNNER",
    )
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
        "WRONG_EVENT",
    )
    event = json.loads(read_regular(Path(os.environ["GITHUB_EVENT_PATH"])))[
        "pull_request"
    ]
    require(
        event["base"]["sha"] == INPUTS_HEAD
        and event["base"]["ref"] == INPUTS_REF
        and event["head"]["ref"] == PROPOSAL_REF,
        "WRONG_REFS",
    )
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == REPOSITORY
        and event["head"]["repo"]["fork"] is False,
        "WRONG_REPOSITORY",
    )
    head = git("rev-parse", "HEAD").decode().strip()
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    for child, parent in (
        (head, INPUTS_HEAD),
        (INPUTS_HEAD, PARENT),
    ):
        require(
            git("show", "-s", "--format=%P", child).decode().strip() == parent,
            "PARENT_MISMATCH",
        )
    for commit, tree in (
        (PARENT, PARENT_TREE),
        (INPUTS_HEAD, INPUTS_TREE),
    ):
        require(
            git("show", "-s", "--format=%T", commit).decode().strip() == tree,
            "TREE_MISMATCH",
        )
    require(
        not git(
            "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"
        ),
        "DIRTY_SOURCE",
    )
    require(
        all(
            row[:2] == b"H " for row in git("ls-files", "-v", "-z").split(b"\0") if row
        ),
        "HIDDEN_INDEX_ENTRY",
    )
    for previous, current, added in (
        (PARENT, INPUTS_HEAD, INPUT_PATHS),
        (INPUTS_HEAD, head, EXECUTOR_PATHS),
    ):
        expected = {"A\t" + name for name in added}
        if previous != PARENT:
            expected.add("M\t" + CONTRACT)
        require(
            set(
                git(
                    "diff-tree",
                    "-r",
                    "--no-commit-id",
                    "--name-status",
                    "--no-renames",
                    previous,
                    current,
                )
                .decode()
                .splitlines()
            )
            == expected,
            "STAGE_SCOPE_MISMATCH",
        )
    unbound = read_regular(ROOT / CONTRACT)
    for suffix, value in (("HEAD", INPUTS_HEAD), ("TREE", INPUTS_TREE)):
        key = "INPUTS_" + suffix
        literal = f'{key} = "{value}"'.encode()
        require(unbound.count(literal) == 1, "BINDING_LITERAL")
        unbound = unbound.replace(literal, f"{key} = None".encode())
    require(unbound == git("show", INPUTS_HEAD + ":" + CONTRACT), "BINDING_DELTA")
    rows = git(
        "diff-tree",
        "-r",
        "--no-commit-id",
        "--raw",
        "--no-abbrev",
        "-z",
        "--no-renames",
        PARENT,
        head,
    ).split(b"\0")
    require(rows.pop() == b"" and len(rows) % 2 == 0, "INVALID_DIFF")
    additions = {}
    for offset in range(0, len(rows), 2):
        old_mode, mode, old_blob, blob, status = rows[offset].decode().split()
        name = rows[offset + 1].decode()
        require(
            old_mode == ":000000"
            and mode == "100644"
            and old_blob == "0" * 40
            and status == "A",
            "PRODUCT_CHANGE",
        )
        require(name not in additions, "DUPLICATE_PATH")
        additions[name] = blob
    require(set(additions) == ADDED, "ADDITIONS_MISMATCH")
    count = 0
    for row in git("ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        fields, name = row.split(b"\t", 1)
        mode, expected, stage = fields.decode().split()
        path = ROOT / name.decode()
        require(stage == "0" and mode in {"100644", "100755", "120000"}, "INDEX_MODE")
        require(
            all(
                not parent.is_symlink()
                for parent in path.parents
                if parent != ROOT and ROOT in parent.parents
            ),
            "LINKED_SOURCE_PARENT",
        )
        before = path.lstat()
        if mode == "120000":
            require(stat.S_ISLNK(before.st_mode), "SOURCE_MODE")
            actual = identity(os.fsencode(os.readlink(path)))["git_blob"]
        else:
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == int(mode[-3:], 8),
                "SOURCE_MODE",
            )
            digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                require(
                    (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                    "SOURCE_REPLACED",
                )
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            require(
                (before.st_size, before.st_mtime_ns)
                == (after.st_size, after.st_mtime_ns),
                "SOURCE_CHANGED",
            )
            actual = digest.hexdigest()
        require(actual == expected, "WORKTREE_BLOB_MISMATCH")
        count += 1
    require(
        identity(read_regular(ROOT / SCANNER_PATH))["git_blob"] == SCANNER_BLOB,
        "SCANNER_CHANGED",
    )
    require(os.getuid() != 0 and os.geteuid() == os.getuid(), "PRIVILEGED_CALLER")
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
        "inputs_head": INPUTS_HEAD,
        "inputs_tree": INPUTS_TREE,
        "only_additions": additions,
        "all_tracked_worktree_blobs_verified": count,
        "scanner_blob": SCANNER_BLOB,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner_class": os.environ["PROBE_RUNNER_CLASS"],
        "runner_os": os.environ["PROBE_RUNNER_OS"],
        "runner_arch": os.environ["PROBE_RUNNER_ARCH"],
    }


def private_dir():
    path = Path(os.environ["PROBE_PRIVATE_DIR"])
    require(
        path.is_dir()
        and not path.is_symlink()
        and path.name.startswith("hepta-bwrap-inventory.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "INVALID_PRIVATE_DIR",
    )
    return path
