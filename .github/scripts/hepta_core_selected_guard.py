"""Bind original Core qualification to the same reviewed profile source chain."""

import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys

from hepta_bwrap_profile_contract import BASELINE_BLOBS
from hepta_bwrap_profile_contract import CHECK_PATHS
from hepta_bwrap_profile_contract import CHECKS_HEAD
from hepta_bwrap_profile_contract import CHECKS_REF
from hepta_bwrap_profile_contract import CHECKS_TREE
from hepta_bwrap_profile_contract import CONTRACT
from hepta_bwrap_profile_contract import DECLARED_PATHS
from hepta_bwrap_profile_contract import EXECUTOR_PATHS
from hepta_bwrap_profile_contract import INPUT_PATHS
from hepta_bwrap_profile_contract import INPUTS_HEAD
from hepta_bwrap_profile_contract import INPUTS_TREE
from hepta_bwrap_profile_contract import PARENT
from hepta_bwrap_profile_contract import PARENT_TREE
from hepta_bwrap_profile_contract import PROFILE_PACKAGE
from hepta_bwrap_profile_contract import PROFILE_SHA
from hepta_bwrap_profile_contract import PROPOSAL_REF
from hepta_bwrap_profile_contract import REPOSITORY
from hepta_bwrap_profile_contract import ROOT
from hepta_bwrap_profile_contract import SCANNER_BLOB
from hepta_bwrap_profile_contract import SCANNER_PATH
from hepta_bwrap_profile_contract import git
from hepta_core_selected_evidence import identity
from hepta_core_selected_evidence import read_regular
from hepta_core_selected_evidence import require

SPEC = json.loads(
    (Path(__file__).parent / "hepta-core-selected-spec.json").read_bytes()
)


def source_guard():
    require(
        INPUTS_HEAD and INPUTS_TREE and CHECKS_HEAD and CHECKS_TREE, "UNBOUND_SOURCE"
    )
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "WRONG_PLATFORM"
    )
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "bwrap-profile"
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
    require(
        not any(
            os.environ.get(name)
            for name in (
                "RUSTC_WRAPPER",
                "RUSTC_WORKSPACE_WRAPPER",
                "RUSTFLAGS",
                "RUSTDOCFLAGS",
                "CARGO_ENCODED_RUSTFLAGS",
                "CARGO_BUILD_TARGET",
                "CARGO_BUILD_RUSTFLAGS",
                "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER",
            )
        ),
        "BUILD_OVERRIDE_PRESENT",
    )
    require(
        not any(name.startswith("NEXTEST_") for name in os.environ),
        "NEXTEST_OVERRIDE_PRESENT",
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
        not git("status", "--porcelain=v1", "--untracked-files=all"),
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
        expected = {
            ("M\t" if name in BASELINE_BLOBS else "A\t") + name for name in added
        }
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
            mode == "100644"
            and (
                name in BASELINE_BLOBS
                and old_mode == ":100644"
                and old_blob == BASELINE_BLOBS[name]
                and status == "M"
                or name not in BASELINE_BLOBS
                and old_mode == ":000000"
                and old_blob == "0" * 40
                and status == "A"
            ),
            "PRODUCT_CHANGE",
        )
        require(name not in additions, "DUPLICATE_PATH")
        additions[name] = blob
    require(set(additions) == DECLARED_PATHS, "DECLARED_SCOPE_MISMATCH")
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
        identity(read_regular(ROOT / PROFILE_PACKAGE))["sha256"]
        == "90b02aa006eea7702cd4e851343e469e41365dda42145a3cb035de1d6c773b8c",
        "VENDOR_PACKAGE_CHANGED",
    )
    require(
        SPEC["repository"] == REPOSITORY
        and SPEC["base_head"] == PARENT
        and SPEC["base_tree"] == PARENT_TREE
        and SPEC["source_contract"] == CONTRACT,
        "CORE_SOURCE_CONTRACT_MISMATCH",
    )
    for name, blob in SPEC["baseline_blobs"].items():
        require(
            identity((ROOT / name).read_bytes())["git_blob"] == blob, "PIN_MISMATCH"
        )
    return {
        "head": head,
        "job": os.environ["GITHUB_JOB"],
        "core_baseline_blobs": SPEC["baseline_blobs"],
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
        "inputs_head": INPUTS_HEAD,
        "inputs_tree": INPUTS_TREE,
        "checks_head": CHECKS_HEAD,
        "checks_tree": CHECKS_TREE,
        "declared_source_changes": additions,
        "all_tracked_worktree_blobs_verified": count,
        "scanner_blob": SCANNER_BLOB,
        "profile_sha256": PROFILE_SHA,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner_class": os.environ["PROBE_RUNNER_CLASS"],
        "runner_os": os.environ["PROBE_RUNNER_OS"],
        "runner_arch": os.environ["PROBE_RUNNER_ARCH"],
    }


def private_dir():
    path = Path(os.environ["PROBE_PRIVATE_DIR"])
    require(
        path.is_dir() and not path.is_symlink() and not path.is_junction(),
        "INVALID_PRIVATE_DIR",
    )
    require(
        path.name.startswith("hepta-core-selected.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "PRIVATE_DIR_OUTSIDE_RUNNER",
    )
    return path
