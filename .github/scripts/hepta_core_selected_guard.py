"""Bind selected Core qualification to one unchanged product tree and native host."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from hepta_core_selected_evidence import identity
from hepta_core_selected_evidence import require

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads(
    (Path(__file__).parent / "hepta-core-selected-spec.json").read_bytes()
)


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def source_guard():
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "NOT_NATIVE_LINUX"
    )
    require(os.environ.get("GITHUB_ACTIONS") == "true", "NOT_GITHUB_ACTIONS")
    require(
        [
            os.environ.get(name)
            for name in ("PROBE_RUNNER_CLASS", "PROBE_RUNNER_OS", "PROBE_RUNNER_ARCH")
        ]
        == ["github-hosted", "Linux", "X64"],
        "WRONG_RUNNER",
    )
    require(os.environ.get("GITHUB_JOB") == "core-selected", "WRONG_JOB")
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request", "WRONG_EVENT")
    require(
        os.environ.get("GITHUB_REPOSITORY") == SPEC["repository"], "WRONG_REPOSITORY"
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
    require(SPEC["inputs_head"] and SPEC["inputs_tree"], "INPUTS_PARENT_NOT_BOUND")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())[
        "pull_request"
    ]
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == SPEC["repository"]
        and event["head"]["repo"]["fork"] is False,
        "WRONG_SOURCE_REPOSITORY",
    )
    require(
        event["base"]["sha"] == SPEC["inputs_head"]
        and event["base"]["ref"] == SPEC["inputs_ref"],
        "BASE_MOVED",
    )
    require(event["head"]["ref"] == SPEC["proposal_ref"], "WRONG_PROPOSAL_BRANCH")
    head = git("rev-parse", "HEAD").decode().strip()
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    require(
        git("show", "-s", "--format=%P", "HEAD").decode().strip()
        == SPEC["inputs_head"],
        "PARENT_MISMATCH",
    )
    require(
        git("show", "-s", "--format=%P", SPEC["inputs_head"]).decode().strip()
        == SPEC["base_head"],
        "INPUTS_PARENT_MISMATCH",
    )
    require(
        git("show", "-s", "--format=%T", SPEC["inputs_head"]).decode().strip()
        == SPEC["inputs_tree"],
        "INPUTS_TREE_MISMATCH",
    )
    specification_path = ".github/scripts/hepta-core-selected-spec.json"
    require(
        json.loads(git("show", SPEC["inputs_head"] + ":" + specification_path))
        == dict(SPEC, inputs_head=None, inputs_tree=None),
        "INPUTS_SPEC_CHANGED",
    )
    changed = (
        git("diff", "--name-only", "--no-renames", SPEC["inputs_head"], "HEAD")
        .decode()
        .splitlines()
    )
    require(
        set(changed)
        == (set(SPEC["added_paths"]) - set(SPEC["inputs_paths"]))
        | {specification_path},
        "INPUTS_CHANGED",
    )
    require(
        git("show", "-s", "--format=%T", SPEC["base_head"]).decode().strip()
        == SPEC["base_tree"],
        "BASE_TREE_MISMATCH",
    )
    require(
        not git("status", "--porcelain=v1", "--untracked-files=all"), "DIRTY_SOURCE"
    )
    require(
        all(row[:1] == b"H" for row in git("ls-files", "-v").splitlines()),
        "HIDDEN_INDEX_ENTRY",
    )
    rows = git(
        "diff-tree",
        "-r",
        "--no-commit-id",
        "--raw",
        "--no-abbrev",
        "-z",
        "--no-renames",
        SPEC["base_head"],
        "HEAD",
    ).split(b"\0")
    require(rows.pop() == b"" and len(rows) % 2 == 0, "INVALID_DIFF")
    additions = {}
    for offset in range(0, len(rows), 2):
        mode0, mode1, old, new, status = rows[offset].decode().split()
        name = rows[offset + 1].decode()
        require(
            mode0 == ":000000"
            and mode1 == "100644"
            and old == "0" * 40
            and status == "A",
            "PRODUCT_CHANGE",
        )
        require(name not in additions, "DUPLICATE_DIFF_PATH")
        path = ROOT / name
        require(path.is_file() and not path.is_symlink(), "INVALID_ADDITION")
        require(
            identity(path.read_bytes())["git_blob"] == new, "WORKTREE_BLOB_MISMATCH"
        )
        additions[name] = new
    require(set(additions) == set(SPEC["added_paths"]), "ADDITION_SCOPE_MISMATCH")
    for name, blob in SPEC["baseline_blobs"].items():
        require(
            identity((ROOT / name).read_bytes())["git_blob"] == blob, "PIN_MISMATCH"
        )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "product_parent": SPEC["base_head"],
        "product_tree": SPEC["base_tree"],
        "inputs_head": SPEC["inputs_head"],
        "inputs_tree": SPEC["inputs_tree"],
        "only_additions": additions,
        "baseline_blobs": SPEC["baseline_blobs"],
        "runner_class": os.environ["PROBE_RUNNER_CLASS"],
        "runner_os": os.environ["PROBE_RUNNER_OS"],
        "runner_arch": os.environ["PROBE_RUNNER_ARCH"],
        "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"),
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
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
