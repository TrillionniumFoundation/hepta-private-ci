"""Bind the dedicated diagnostic to one reviewed source and disposable runner."""

import json
import os
from pathlib import Path
import subprocess
import sys

from hepta_rotation_evidence import identity
from hepta_rotation_evidence import require

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((Path(__file__).parent / "hepta-rotation-spec.json").read_bytes())


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def runner_guard(env, platform):
    require(
        platform == "win32" and env.get("GITHUB_ACTIONS") == "true", "NOT_NATIVE_GHA"
    )
    require(
        [
            env.get(name)
            for name in ("PROBE_RUNNER_CLASS", "PROBE_RUNNER_OS", "PROBE_RUNNER_ARCH")
        ]
        == ["github-hosted", "Windows", "X64"],
        "WRONG_RUNNER",
    )
    require(env.get("GITHUB_JOB") == "rotation-probe", "WRONG_JOB")
    require(env.get("GITHUB_EVENT_NAME") == "pull_request", "WRONG_EVENT")
    require(env.get("GITHUB_REPOSITORY") == SPEC["repository"], "WRONG_REPOSITORY")
    require(
        not env.get("RUSTC_WRAPPER") and not env.get("RUSTC_WORKSPACE_WRAPPER"),
        "BUILD_WRAPPER_PRESENT",
    )
    require(
        not env.get("CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUNNER"),
        "TARGET_RUNNER_PRESENT",
    )


def source_guard():
    runner_guard(os.environ, sys.platform)
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
    specification_path = ".github/scripts/hepta-rotation-spec.json"
    expected_before = dict(SPEC, inputs_head=None, inputs_tree=None)
    require(
        json.loads(git("show", SPEC["inputs_head"] + ":" + specification_path))
        == expected_before,
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
    for index in range(0, len(rows), 2):
        mode0, mode1, old, new, status = rows[index].decode().split()
        name = rows[index + 1].decode()
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
    require(
        identity((ROOT / SPEC["probe_path"]).read_bytes())["sha256"]
        == SPEC["probe_sha256"],
        "PROBE_MISMATCH",
    )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": SPEC["base_head"],
        "parent_tree": SPEC["base_tree"],
        "reviewed_inputs_head": SPEC["inputs_head"],
        "reviewed_inputs_tree": SPEC["inputs_tree"],
        "only_additions": additions,
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
        path.name.startswith("hepta-rotation.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "PRIVATE_DIR_OUTSIDE_RUNNER",
    )
    return path
