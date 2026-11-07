"""Bind the read-only ACL observer to its unchanged failed setup parent."""

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
PARENT = "e94d91a717c8731d2ce0ad9973fcef593b0c8df4"
PARENT_TREE = "9dd4d0cd95eb93e12db27dc65c880674decccccf"
INPUTS_HEAD = "74979765695a1048b13f7c9bca0c922cbee97308"
INPUTS_TREE = "d19cb6f300d55510c58cd1b0268bd9553c10a321"
CHECKS_HEAD = None
CHECKS_TREE = None
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
INPUTS_REF = "research/ndu-bwrap-acl-inputs-20261107"
CHECKS_REF = "research/ndu-bwrap-acl-checks-20261107"
PROPOSAL_REF = "research/ndu-bwrap-acl-probe-20261107"
CONTRACT = ".github/scripts/hepta_bwrap_acl_contract.py"
HELPER = ".github/scripts/hepta_bwrap_acl_inventory.py"
HELPER_SHA = "04f6004476acb370210dd892bed58fd34778724b3c9d255d2b020d23e930d8dc"
INPUT_PATHS = {CONTRACT, HELPER}
CHECK_PATHS = {
    ".github/scripts/hepta_bwrap_acl_checks.py",
    ".github/scripts/hepta_bwrap_acl_evidence.py",
}
EXECUTOR_PATHS = {
    ".github/scripts/hepta_bwrap_acl.py",
    ".github/workflows/hepta-bwrap-acl-inventory.yml",
}
ADDED = INPUT_PATHS | CHECK_PATHS | EXECUTOR_PATHS
SCANNER_PATH = ".github/scripts/hepta_core_selected_evidence.py"
SCANNER_BLOB = "f18f5d0ce06cead0817513814da96f129523cf8c"
RUNTIME_PATH = ".github/scripts/hepta_bwrap_share_checks.py"
RUNTIME_BLOB = "fe68e992b2c3187b4e112445f0e131e97d01734e"
LIMIT = 4 * 1024 * 1024
SLOTS = {
    "source-before.json",
    "source-after.json",
    "readiness.json",
    "result.json",
    "acl-runtime.before.json",
    "acl-runtime.after.json",
    "logs/acl_inventory.stdout.log",
    "logs/acl_inventory.stderr.log",
}


def expected_argv():
    raw = read_regular(ROOT / HELPER)
    require(identity(raw)["sha256"] == HELPER_SHA, "HELPER_CHANGED")
    return [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/python3.12",
        "-I",
        "-S",
        "-c",
        raw.decode(),
    ]


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
    require(
        INPUTS_HEAD and INPUTS_TREE and CHECKS_HEAD and CHECKS_TREE, "UNBOUND_SOURCE"
    )
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "WRONG_PLATFORM"
    )
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "bwrap-acl-inventory"
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
        event["base"]["sha"] == CHECKS_HEAD
        and event["base"]["ref"] == CHECKS_REF
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
        (head, CHECKS_HEAD),
        (CHECKS_HEAD, INPUTS_HEAD),
        (INPUTS_HEAD, PARENT),
    ):
        require(
            git("show", "-s", "--format=%P", child).decode().strip() == parent,
            "PARENT_MISMATCH",
        )
    for commit, tree in (
        (PARENT, PARENT_TREE),
        (INPUTS_HEAD, INPUTS_TREE),
        (CHECKS_HEAD, CHECKS_TREE),
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
        (INPUTS_HEAD, CHECKS_HEAD, CHECK_PATHS),
        (CHECKS_HEAD, head, EXECUTOR_PATHS),
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
    for prefix, commit, tree, expected_commit in (
        ("CHECKS", CHECKS_HEAD, CHECKS_TREE, CHECKS_HEAD),
        ("INPUTS", INPUTS_HEAD, INPUTS_TREE, INPUTS_HEAD),
    ):
        for suffix, value in (("HEAD", commit), ("TREE", tree)):
            key = prefix + "_" + suffix
            literal = f'{key} = "{value}"'.encode()
            require(unbound.count(literal) == 1, "BINDING_LITERAL")
            unbound = unbound.replace(literal, f"{key} = None".encode())
        require(
            unbound == git("show", expected_commit + ":" + CONTRACT), "BINDING_DELTA"
        )
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
    require(
        identity(read_regular(ROOT / RUNTIME_PATH))["git_blob"] == RUNTIME_BLOB,
        "RUNTIME_CAPTURE_CHANGED",
    )
    require(os.getuid() != 0 and os.geteuid() == os.getuid(), "PRIVILEGED_CALLER")
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
        "inputs_head": INPUTS_HEAD,
        "inputs_tree": INPUTS_TREE,
        "checks_head": CHECKS_HEAD,
        "checks_tree": CHECKS_TREE,
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
        and path.name.startswith("hepta-bwrap-acl.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "INVALID_PRIVATE_DIR",
    )
    return path
