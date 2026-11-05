"""Native MSVC qualification of the isolated setup-handle candidate.

Two new mechanism controls and the unchanged original seven are separate groups.
This does not claim the original 156-case Windows scope or full blocking CI.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import traceback

BASE = "a3182a76970c26aaa8b7b3530671db09ecb4d317"
BASE_TREE = "84e495dbc15e1e6487a844bf67a1ffad408632e9"
BRANCH = "diagnostics/4853-setup-handles-a318-20261105-v7"
DRIVER = ".github/scripts/windows_setup_handle_diagnostic.py"
WORKFLOW = ".github/workflows/hepta-windows-setup-handle-diagnostic.yml"
PRODUCT_TREE = "d3ca4e259af7cdd51c946587ee86579a37d85d92"
PRODUCT_FILES = {
    ".github/fixtures/windows-current-ci-scope.json": {
        "post_blob": "555fa229c2f366d3615a166e7e960db116640af8",
        "pre_blob": "381e2e01900f4d74d7f0b1456a21042b2e948bf3",
    },
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs": {
        "post_blob": "2534bc6740958ba8e031086e31f257786c2f0ad9",
        "pre_blob": "1d9340c6db26d6d10c1b3edecb1c9fecc908ef1d",
    },
    "codex-rs/windows-sandbox-rs/src/elevated_impl.rs": {
        "post_blob": "7dcfa0c3268af5720c27fe283a351db9de0f2e30",
        "pre_blob": "a8cc511dfd6f876e94da04f7413f0a26d42d4e18",
    },
    "codex-rs/windows-sandbox-rs/src/lib.rs": {
        "post_blob": "0679586eabdf4d9a91cf4b560ea35b8815215438",
        "pre_blob": "401bfd8cf6ebc0f3c625e1b461cb8580ddcddf2a",
    },
    "codex-rs/windows-sandbox-rs/src/setup.rs": {
        "post_blob": "d8aeb27fa84b30b7fe4fcf6d1136058d8a7b7914",
        "pre_blob": "890755d01ca24f5ede1960582eacb9714633a0db",
    },
    "codex-rs/windows-sandbox-rs/src/setup_process.rs": {
        "post_blob": "d595c8de841ea4d252d97ec658cf67ce99611c16",
        "pre_blob": None,
    },
    "codex-rs/windows-sandbox-rs/src/setup_process_tests.rs": {
        "post_blob": "180a3bfa287ba9ed863d22059bc6de7d1c968c07",
        "pre_blob": None,
    },
    "codex-rs/windows-sandbox-rs/src/setup_process_tests_support.rs": {
        "post_blob": "50bc4554d7a343241864be7d7fefad3ebb59c5a8",
        "pre_blob": None,
    },
    "codex-rs/windows-sandbox-rs/tests/helper_manifest.rs": {
        "post_blob": "ee46d664d9abd0f085958d1cb333baa155aceb5b",
        "pre_blob": "346155207c2c726eca0d0e4d761f530b45bbf64e",
    },
}
ORIGINAL_INPUTS = {
    ".github/scripts/test_windows_current_ci.py": "37b431d0fa3aa41b8cd12fe99fe8dccf3db5f171",
    ".github/scripts/windows_current_ci.py": "161ed1149c8ffb5f2bb2a8272f555f8b91d729fe",
    "codex-rs/.config/nextest.toml": "572b624bd4a9b55b5a360f4051efade5c2ec75b5",
    "codex-rs/Cargo.lock": "b7e710988d6a3377a7e0a1dc68aef49c68dda36e",
    "codex-rs/Cargo.toml": "7e2ec509988e11cdf92130e385ffdf409bbcc15d",
    "codex-rs/rust-toolchain.toml": "917d2492264a35bc9c0feaef41878d8825870866",
    "codex-rs/rustfmt.toml": "f9686f9732d3d48311c41c4fd06b40781928b8ec",
    "codex-rs/windows-sandbox-rs/Cargo.toml": "aa41ed5f08608c0275785b2f5e27ec5db08f50dd",
    "codex-rs/windows-sandbox-rs/build.rs": "6ba79e6c75deb87067ced02e824eaf7faf79346d",
    "codex-rs/windows-sandbox-rs/src/token_tests.rs": "25cf2a9b066aacda4e5e7e92dc933159b46574d5",
    "codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs": "1c06624f04400b15221708fa7e39e5ae76480d18",
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/format.py": "d4eabe70b68605933240e9129245f7f4cccbde5d",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
}
LINT_FLAGS = [
    "--deny=clippy::correctness",
    "--deny=clippy::await_holding_invalid_type",
    "--deny=clippy::await_holding_lock",
    "--deny=clippy::disallowed_methods",
    "--deny=clippy::expect_used",
    "--warn=clippy::identity_op",
    "--warn=clippy::manual_clamp",
    "--warn=clippy::manual_filter",
    "--warn=clippy::manual_find",
    "--warn=clippy::manual_flatten",
    "--warn=clippy::manual_map",
    "--warn=clippy::manual_memcpy",
    "--warn=clippy::manual_non_exhaustive",
    "--warn=clippy::manual_ok_or",
    "--warn=clippy::manual_range_contains",
    "--warn=clippy::manual_retain",
    "--warn=clippy::manual_strip",
    "--warn=clippy::manual_try_fold",
    "--warn=clippy::manual_unwrap_or",
    "--warn=clippy::needless_borrow",
    "--warn=clippy::needless_borrowed_reference",
    "--warn=clippy::needless_collect",
    "--warn=clippy::needless_late_init",
    "--warn=clippy::needless_option_as_deref",
    "--warn=clippy::needless_question_mark",
    "--warn=clippy::needless_update",
    "--warn=clippy::redundant_clone",
    "--warn=clippy::redundant_closure",
    "--warn=clippy::redundant_closure_for_method_calls",
    "--warn=clippy::redundant_static_lifetimes",
    "--warn=clippy::trivially_copy_pass_by_ref",
    "--warn=clippy::uninlined_format_args",
    "--warn=clippy::unnecessary_filter_map",
    "--warn=clippy::unnecessary_lazy_evaluations",
    "--warn=clippy::unnecessary_sort_by",
    "--warn=clippy::unnecessary_to_owned",
    "--deny=clippy::unwrap_used",
]
OLD_GROUP_SHA = "16ef660ff6f45aa9d14886864a95791909a8f7e9b7a9c4b14e487345de6e0c0a"
SOURCE = Path(__file__).resolve().parents[2]
STARTED = time.monotonic()
REPORT = {
    "schema": "hepta.windows-setup-handle-diagnostic.v1",
    "base_head": BASE,
    "base_tree": BASE_TREE,
    "product_tree": PRODUCT_TREE,
    "qualified_original156": False,
    "qualified_full_blocking_ci": False,
    "groups": [],
    "status": "PREPARING",
    "original_group_cases": 7,
    "new_mechanism_cases": 2,
    "test_retries": 0,
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def save(output, name, value):
    (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def git(*args, input_bytes=None):
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
    ):
        require(name not in os.environ, "unexpected Git environment override: " + name)
    input_args = {} if input_bytes is None else {"input": input_bytes}
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", *args],
        cwd=SOURCE,
        **input_args,
    )


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "cannot load original module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_source_identity(output, phase, expected_head):
    config = {}
    for key in (
        "core.autocrlf",
        "core.eol",
        "core.filemode",
        "core.symlinks",
        "core.ignorestat",
        "core.trustctime",
        "core.checkstat",
        "core.ignorecase",
        "diff.autoRefreshIndex",
    ):
        try:
            config[key] = {
                "present": True,
                "values": git("config", "--get-all", key).decode().splitlines(),
            }
        except subprocess.CalledProcessError as error:
            config[key] = {"present": False, "exit_code": error.returncode}
    result = {
        "expected_head": expected_head,
        "expected_tree": git("rev-parse", expected_head + "^{tree}").decode().strip(),
        "git_version": git("--version").decode().strip(),
        "git_optional_locks": os.environ.get("GIT_OPTIONAL_LOCKS"),
        "shared_git_override": {"core.fsmonitor": "false"},
        "config": config,
        "files": [],
        "qualification": "Observation only; the original first nonempty status still rejects.",
    }
    paths, rows, snapshots = [], [], []

    def signature(value):
        return [
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        ]

    def safe_parents(name):
        parts = name.split("/")
        require(
            parts
            and all(
                part not in ("", ".", "..") and "\\" not in part and ":" not in part
                for part in parts
            ),
            "unsafe tracked path",
        )
        parent = SOURCE
        for part in parts[:-1]:
            parent /= part
            value = parent.lstat()
            require(
                stat.S_ISDIR(value.st_mode)
                and not (getattr(value, "st_file_attributes", 0) & 0x400),
                "tracked parent is not an ordinary directory",
            )

    for entry in git("ls-tree", "-rz", expected_head).split(b"\0"):
        if not entry:
            continue
        header, name_raw = entry.split(b"\t", 1)
        mode, kind, expected = header.decode().split()
        name = name_raw.decode("utf-8")
        row = {
            "path": name,
            "expected_mode": mode,
            "expected_git_blob": expected,
        }
        result["files"].append(row)
        try:
            require(
                kind == "blob" and mode in ("100644", "100755", "120000"),
                "unexpected tracked object",
            )
            safe_parents(name)
            path = SOURCE / name
            before = path.lstat()
            is_link = stat.S_ISLNK(before.st_mode)
            require(
                is_link
                or (
                    stat.S_ISREG(before.st_mode)
                    and not (getattr(before, "st_file_attributes", 0) & 0x400)
                ),
                "tracked leaf is not a regular file or symlink",
            )
            data = os.fsencode(os.readlink(path)) if is_link else path.read_bytes()
            after = path.lstat()
            row.update(
                {
                    "physical_symlink": is_link,
                    "physical_type_matches_original_rule": not is_link
                    or mode == "120000",
                    "before": signature(before),
                    "after_python_read": signature(after),
                    "stable_python_read": signature(before) == signature(after),
                    "bytes": len(data),
                    "sha256": sha(data),
                    "python_git_blob": blob(data),
                    "python_matches_head": blob(data) == expected,
                }
            )
            safe_parents(name)
            require(
                row["stable_python_read"], "tracked file changed during Python read"
            )
            if is_link:
                # hash-object opens paths normally. Hash only this captured link
                # target string, never the symlink's referenced file contents.
                snapshot = output / (
                    "source-"
                    + phase
                    + "-symlink-target-"
                    + str(len(snapshots))
                    + ".bin"
                )
                with snapshot.open("xb") as stream:
                    stream.write(data)
                snapshots.append(
                    {"path": snapshot.name, "bytes": len(data), "sha256": sha(data)}
                )
                hash_path = snapshot
            else:
                hash_path = path
            # Git's --stdin-paths accepts C-quoted names. Octal-quote every
            # encoded byte so quotes, newlines and non-ASCII paths stay one item.
            encoded = os.fsencode(str(hash_path))
            paths.append(
                b'"'
                + b"".join(("\\%03o" % value).encode("ascii") for value in encoded)
                + b'"\n'
            )
            rows.append(row)
        except (OSError, RuntimeError) as error:
            row["error"] = repr(error)

    input_bytes = b"".join(paths)
    input_name = "source-" + phase + "-hash-object.stdin"
    output_name = "source-" + phase + "-hash-object.stdout"
    (output / input_name).write_bytes(input_bytes)
    argv = ["hash-object", "--no-filters", "--stdin-paths"]
    try:
        hashed = git(*argv, input_bytes=input_bytes)
        exit_code = 0
    except subprocess.CalledProcessError as error:
        hashed = error.output
        exit_code = error.returncode
    (output / output_name).write_bytes(hashed)
    hashes = hashed.decode("ascii", errors="replace").splitlines()
    valid_hashes = (
        exit_code == 0
        and len(hashes) == len(rows)
        and all(re.fullmatch(r"[0-9a-f]{40}", value) for value in hashes)
    )
    for index, row in enumerate(rows):
        if valid_hashes:
            row["git_hash_object"] = hashes[index]
            row["git_matches_python"] = hashes[index] == row["python_git_blob"]
            row["git_matches_head"] = hashes[index] == row["expected_git_blob"]
        try:
            safe_parents(row["path"])
            current = signature((SOURCE / row["path"]).lstat())
            row["after_git_read"] = current
            row["stable_through_git_read"] = current == row["after_python_read"]
        except (OSError, RuntimeError) as error:
            row["after_git_error"] = repr(error)
    actual_head_after = git("rev-parse", "HEAD").decode().strip()
    result.update(
        {
            "actual_head_after": actual_head_after,
            "head_unchanged": actual_head_after == expected_head,
            "hash_object": {
                "git_arguments": argv,
                "exit_code": exit_code,
                "input": {
                    "path": input_name,
                    "bytes": len(input_bytes),
                    "sha256": sha(input_bytes),
                },
                "output": {
                    "path": output_name,
                    "bytes": len(hashed),
                    "sha256": sha(hashed),
                },
                "submitted_files": len(rows),
                "valid_complete_output": valid_hashes,
                "symlink_target_snapshots": snapshots,
            },
            "tracked_count": len(result["files"]),
            "raw_identity_matches_all_tracked": len(result["files"]) == 10811
            and len(rows) == 10811
            and valid_hashes
            and actual_head_after == expected_head
            and all(
                row.get("physical_type_matches_original_rule")
                and row.get("python_matches_head")
                and row.get("git_matches_python")
                and row.get("git_matches_head")
                and row.get("stable_through_git_read")
                for row in result["files"]
            ),
        }
    )
    name = "source-" + phase + "-dirty-physical-inventory.json"
    save(output, name, result)
    return {
        "path": name,
        "sha256": sha((output / name).read_bytes()),
        "raw_identity_matches_all_tracked": result["raw_identity_matches_all_tracked"],
    }


def current_source(expected, output, phase):
    head = git("rev-parse", "HEAD").decode().strip()
    require(head == expected, "source head differs from exact event head")
    status_args = ["status", "--porcelain=v1", "--untracked-files=all"]
    status = git(*status_args)
    if status:
        # Preserve the rejection evidence without reading untracked file contents
        # or changing the worktree, index, checkout configuration or clean gate.
        observation = {"phase": phase, "head": head, "files": []}
        REPORT.setdefault("source_guard_observations", []).append(observation)
        diff_args = [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "--full-index",
            "--no-renames",
            "--no-color",
        ]
        for suffix, arguments in {
            "porcelain.txt": status_args,
            "status.txt": ["status", "--long", "--untracked-files=all"],
            "index-before-diffs.txt": ["ls-files", "--stage", "--debug", "-z"],
            "head.diff": [*diff_args, "HEAD", "--"],
            "index.diff": [*diff_args, "--cached", "HEAD", "--"],
            "worktree.diff": [*diff_args, "--"],
            "porcelain-after-diffs.txt": status_args,
            "index-after-diffs.txt": ["ls-files", "--stage", "--debug", "-z"],
        }.items():
            data = status if suffix == "porcelain.txt" else git(*arguments)
            name = "source-" + phase + "-dirty-" + suffix
            (output / name).write_bytes(data)
            observation["files"].append(
                {
                    "path": name,
                    "git_arguments": arguments,
                    "bytes": len(data),
                    "sha256": sha(data),
                }
            )
        try:
            observation["physical_inventory"] = capture_source_identity(
                output, phase, head
            )
        except Exception as error:
            observation["physical_inventory_error"] = repr(error)
    require(not status, "source is not clean")
    product = git("show", "-s", "--format=%P", "HEAD").decode().strip()
    require(
        re.fullmatch(r"[0-9a-f]{40}", product) is not None,
        "diagnostic must have one product parent",
    )
    require(
        git("show", "-s", "--format=%P", product).decode().strip() == BASE,
        "product parent differs",
    )
    require(
        git("rev-parse", BASE + "^{tree}").decode().strip() == BASE_TREE,
        "base tree differs",
    )
    require(
        git("rev-parse", product + "^{tree}").decode().strip() == PRODUCT_TREE,
        "product tree differs",
    )
    diagnostic_changes = (
        git("diff-tree", "--no-commit-id", "--name-status", "-r", product, head)
        .decode()
        .splitlines()
    )
    require(
        sorted(diagnostic_changes) == sorted(["A\t" + DRIVER, "A\t" + WORKFLOW]),
        "diagnostic changes product source",
    )
    product_changes = (
        git("diff-tree", "--no-commit-id", "--name-status", "-r", BASE, product)
        .decode()
        .splitlines()
    )
    expected_changes = [
        ("A" if row["pre_blob"] is None else "M") + "\t" + name
        for name, row in PRODUCT_FILES.items()
    ]
    require(
        sorted(product_changes) == sorted(expected_changes),
        "product path set differs from reviewed nine",
    )
    inventory = []
    for row in git("ls-tree", "-rz", "HEAD").split(b"\0"):
        if not row:
            continue
        header, path_raw = row.split(b"\t", 1)
        mode, kind, object_id = header.decode().split()
        name = path_raw.decode("utf-8")
        require(
            kind == "blob" and mode in ("100644", "100755", "120000"),
            "unexpected tracked object",
        )
        path = SOURCE / name
        require(path.exists() or path.is_symlink(), "missing tracked path: " + name)
        physical_symlink = path.is_symlink()
        data = os.fsencode(os.readlink(path)) if physical_symlink else path.read_bytes()
        require(
            not physical_symlink or mode == "120000",
            "unexpected physical source redirection",
        )
        require(blob(data) == object_id, "physical source differs: " + name)
        inventory.append(
            {
                "path": name,
                "mode": mode,
                "git_blob": object_id,
                "bytes": len(data),
                "sha256": sha(data),
                "physical_symlink": physical_symlink,
            }
        )
    require(
        len(inventory) == 10811,
        "full candidate10809 plus two diagnostic paths required",
    )
    index = {row["path"]: row for row in inventory}
    for name, value in PRODUCT_FILES.items():
        require(
            index[name]["git_blob"] == value["post_blob"]
            and index[name]["mode"] == "100644",
            "product postimage differs: " + name,
        )
    for name, value in ORIGINAL_INPUTS.items():
        require(
            index[name]["git_blob"] == value,
            "original immutable input differs: " + name,
        )
    config = {
        name: git("config", "--get", name).decode().strip()
        for name in ("core.autocrlf", "core.eol")
    }
    require(
        config == {"core.autocrlf": "false", "core.eol": "lf"},
        "source checkout must use LF",
    )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "product_commit": product,
        "product_tree": PRODUCT_TREE,
        "base": BASE,
        "clean": True,
        "tracked_paths": len(inventory),
        "inventory": inventory,
    }


def run(output, name, argv, cwd=None, env=None):
    log = output / (name + ".log")
    began = time.monotonic()
    with log.open("xb") as stream:
        process = subprocess.run(
            argv,
            cwd=cwd or SOURCE / "codex-rs",
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    record = {
        "command": argv,
        "cwd": str(cwd or SOURCE / "codex-rs"),
        "exit_code": process.returncode,
        "elapsed_seconds": time.monotonic() - began,
        "log": str(log),
        "log_sha256": sha(log.read_bytes()),
    }
    save(output, name + ".json", record)
    REPORT.setdefault("stages", []).append(record)
    save(output, "receipt.json", REPORT)
    return record


def no_delta(output, label):
    changes = git("status", "--porcelain=v1", "--untracked-files=all")
    if changes:
        diff = git("diff", "--binary", "--full-index", "HEAD")
        (output / (label + "-source-diff.patch")).write_bytes(diff)
        post = output / (label + "-postimages")
        post.mkdir()
        for raw in git(
            "ls-files", "--modified", "--others", "--exclude-standard", "-z"
        ).split(b"\0"):
            if not raw:
                continue
            name = os.fsdecode(raw)
            source = SOURCE / name
            if source.is_file() and not source.is_symlink():
                target = post / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        save(
            output,
            label + "-source-change.json",
            {"status": changes.decode(), "diff_sha256": sha(diff)},
        )
        raise RuntimeError(
            label + " changed source; retained for review before any later phase"
        )


def catalog(output, groups):
    metadata_file = output / "cargo-metadata.json"
    with (
        metadata_file.open("xb") as stream,
        (output / "cargo-metadata.stderr.log").open("xb") as err,
    ):
        result = subprocess.run(
            ["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"],
            cwd=SOURCE / "codex-rs",
            stdout=stream,
            stderr=err,
            check=False,
        )
    require(result.returncode == 0, "original scoped metadata prerequisite failed")
    wrapper = load_module("original_nextest", SOURCE / "scripts/run-nextest.py")
    expression = " | ".join("(" + group["filter"] + ")" for group in groups)
    require(
        wrapper.use_scoped_metadata(
            ["--locked", "-p", "codex-windows-sandbox", "--lib", "-E", expression],
            SOURCE / "codex-rs",
        ),
        "original wrapper requires a different metadata strategy",
    )
    command = [
        "cargo",
        "nextest",
        "list",
        "--locked",
        "-p",
        "codex-windows-sandbox",
        "--lib",
        "--cargo-profile",
        "dev-small",
        "--cargo-metadata",
        str(metadata_file),
        "--message-format",
        "json",
        "-E",
        expression,
    ]
    path = output / "catalog.json"
    with path.open("xb") as stream, (output / "catalog.stderr.log").open("xb") as err:
        result = subprocess.run(
            command, cwd=SOURCE / "codex-rs", stdout=stream, stderr=err, check=False
        )
    require(
        result.returncode == 0, "native catalog compilation failed; zero tests executed"
    )
    value = json.loads(path.read_bytes())
    selected = []
    for suite in value["rust-suites"].values():
        for name, case in suite["testcases"].items():
            if case["filter-match"]["status"] == "matches":
                require(case["ignored"] is False, "required case was ignored")
                selected.append(name)
    required = [name for group in groups for name in group["requiredTests"]]
    require(
        sorted(selected) == sorted(required)
        and len(selected) == len(set(selected)) == 9,
        "catalog must contain exactly original seven plus new two",
    )
    receipt = {
        "command": command,
        "catalog_sha256": sha(path.read_bytes()),
        "metadata_sha256": sha(metadata_file.read_bytes()),
        "selected_tests": sorted(selected),
        "original_cases": 7,
        "new_mechanism_cases": 2,
        "test_bodies_executed": 0,
    }
    save(output, "catalog-receipt.json", receipt)
    return receipt


def helper_snapshot(helpers):
    result = []
    for item in helpers["artifacts"]:
        a, b = Path(item["source"]).read_bytes(), Path(item["testSibling"]).read_bytes()
        require(
            a == b and sha(a) == item["sha256"] and len(a) == item["bytes"],
            "real helper changed",
        )
        result.append(item)
    require(len(result) == 2, "both real setup and command helpers required")
    return result


def witnesses(log):
    rows = re.findall(
        r"setup-handle (baseline|candidate) native report: (\{[^\r\n]+\})", log
    )
    require(len(rows) == 4, "two complete controls must expose four native reports")
    pairs = {}
    for role, raw in rows:
        record = json.loads(raw)
        nonce = record["nonce"]
        require(
            record["pid"] > 0 and role not in pairs.setdefault(nonce, {}),
            "ambiguous native witness",
        )
        pairs[nonce][role] = record
    require(
        len(pairs) == 2
        and all(set(p) == {"baseline", "candidate"} for p in pairs.values()),
        "witness identity pairs",
    )
    for pair in pairs.values():
        baseline = pair["baseline"]["observation"]
        candidate = pair["candidate"]["observation"]
        require(
            baseline["event_set"] and baseline["write_ok"],
            "baseline did not prove propagation",
        )
        # These numeric-handle observations can target reused child handle slots.
        # The passing exact control proves the same parent's event remained unset
        # and the same pipe reached EOF while the candidate was still alive.
        require(
            candidate["std_handles"][0] != 0
            and len(set(candidate["std_handles"])) == 1,
            "candidate standard handles differ",
        )
        require(
            candidate["std_types"] == [2, 2, 2]
            and candidate["stdin_eof"]
            and candidate["stdout_write_ok"],
            "candidate NUL contract is incomplete",
        )
    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(
        sys.flags.optimize == 0
        and os.name == "nt"
        and os.environ.get("RUNNER_OS") == "Windows",
        "requires actual Windows without optimized Python",
    )
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "push"
        and os.environ.get("GITHUB_REF") == event["ref"] == "refs/heads/" + BRANCH,
        "requires the unique diagnostic branch push",
    )
    require(
        event["head_commit"]["id"]
        == os.environ.get("GITHUB_SHA")
        == args.expected_head,
        "event head differs from reviewed candidate",
    )
    require(
        event["repository"]["full_name"] == "TrillionniumFoundation/hepta-private-ci",
        "external repository source is unsupported",
    )
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = args.output.resolve()
    require(
        output.is_relative_to(runner_temp)
        and output != runner_temp
        and not output.is_relative_to(SOURCE),
        "evidence must be in a new private runner temporary directory",
    )
    output.mkdir(exist_ok=False)
    REPORT.update(
        {
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "source_head": args.expected_head,
            "source_root": str(SOURCE),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "original_workflow_budget_seconds": 3900,
        }
    )
    try:
        before = current_source(args.expected_head, output, "before")
        save(output, "source-before.json", before)
        REPORT["source_before_sha256"] = sha(
            (output / "source-before.json").read_bytes()
        )
        expected_env = {
            "RUSTUP_TOOLCHAIN": "1.96.0",
            "CARGO_BUILD_JOBS": "1",
            "CARGO_INCREMENTAL": "0",
            "CARGO_PROFILE_DEV_DEBUG": "0",
            "CARGO_PROFILE_TEST_DEBUG": "0",
            "CARGO_TERM_COLOR": "never",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
        require(
            all(os.environ.get(k) == v for k, v in expected_env.items()),
            "original native environment differs",
        )
        REPORT["workflow_environment"] = expected_env
        versions = {}
        for name, argv in {
            "rustc": ["rustc", "--version", "--verbose"],
            "cargo": ["cargo", "--version"],
            "just": ["just", "--version"],
            "nextest": ["cargo", "nextest", "--version"],
            "uv": ["uv", "--version"],
        }.items():
            value = run(output, "version-" + name, argv)
            require(value["exit_code"] == 0, name + " version failed")
            versions[name] = Path(value["log"]).read_text().strip()
        require(
            versions["rustc"].startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in versions["rustc"],
            "wrong native compiler",
        )
        require(
            versions["cargo"].startswith("cargo 1.96.0 ")
            and versions["just"] == "just 1.51.0",
            "wrong original Cargo/just",
        )
        require(
            re.match(r"^cargo-nextest 0\.9\.103(?:\s|$)", versions["nextest"])
            is not None,
            "wrong original nextest",
        )
        require(
            versions["uv"].startswith("uv 0.13.7 "),
            "wrong pinned owning formatter frontend",
        )
        REPORT["versions"] = versions
        target = runner_temp / "hepta-4853-setup-handles-target"
        target.mkdir(exist_ok=False)
        os.environ["CARGO_TARGET_DIR"] = str(target)
        case_temp = runner_temp / "hepta-4853-setup-handles-case-temp"
        case_temp.mkdir(exist_ok=False)
        os.environ["TEMP"] = os.environ["TMP"] = str(case_temp.resolve(strict=True))
        REPORT["target"] = str(target)
        REPORT["physical_case_temp"] = os.environ["TEMP"]
        # This is the same original profile that `just test` sets for every run.
        os.environ["NEXTEST_PROFILE"] = "local"
        for label, argv in [
            ("owning-format", ["just", "fmt", "--base", BASE]),
            (
                "required-fix",
                [
                    "just",
                    "fix",
                    "--locked",
                    "--profile",
                    "dev-small",
                    "-p",
                    "codex-windows-sandbox",
                ],
            ),
            (
                "scoped-original-lints",
                [
                    "just",
                    "clippy",
                    "--locked",
                    "--profile",
                    "dev-small",
                    "-p",
                    "codex-windows-sandbox",
                    "--message-format",
                    "json",
                    "--",
                    *LINT_FLAGS,
                ],
            ),
        ]:
            stage = run(output, label, argv)
            no_delta(output, label)
            require(stage["exit_code"] == 0, label + " failed; no later phase entered")
        original = load_module(
            "original_windows_current", SOURCE / ".github/scripts/windows_current_ci.py"
        )
        scope = json.loads(
            (SOURCE / ".github/fixtures/windows-current-ci-scope.json").read_bytes()
        )
        old = next(g for g in scope["groups"] if g["id"] == "sandbox-original-failures")
        controls = next(
            g for g in scope["groups"] if g["id"] == "setup-handle-inheritance-controls"
        )
        require(
            sha(json.dumps(old, sort_keys=True, separators=(",", ":")).encode())
            == OLD_GROUP_SHA,
            "original seven group changed",
        )
        require(
            old["expectedTestCount"] == 7 and controls["expectedTestCount"] == 2,
            "group scope differs",
        )
        helpers = original.prepare_sandbox_helpers(SOURCE, output)
        require(
            helpers["passed"],
            "real native helper prerequisite failed; tests not entered",
        )
        REPORT["helpers_before"] = helper_snapshot(helpers)
        REPORT["catalog"] = catalog(output, [controls, old])
        for group in (controls, old):
            command = [
                "just",
                "test",
                "--locked",
                "-p",
                group["package"],
                "--lib",
                "--cargo-profile",
                "dev-small",
                "-E",
                group["filter"],
                "--test-threads",
                "1",
                "--no-tests",
                "fail",
                "--retries",
                "0",
                "--success-output",
                "immediate",
            ]
            executed = run(output, group["id"], command)
            text = Path(executed["log"]).read_text(encoding="utf-8", errors="strict")
            assessed = original.assess(group, executed["exit_code"], text)
            assessed["execution"] = executed
            REPORT["groups"].append(assessed)
            save(output, "groups.json", REPORT["groups"])
            if group is controls and assessed["passed"]:
                REPORT["mechanism_witnesses"] = witnesses(text)
            require(
                executed["exit_code"] >= 0 and assessed["selectionMatches"],
                "incomplete native selection/custody; later group not entered",
            )
            # A fully observed ordinary FAIL/LEAK remains a failure, while the other
            # complete group still runs. No timeout, retry or assertion is changed.
        REPORT["helpers_after"] = helper_snapshot(helpers)
        after = current_source(args.expected_head, output, "after")
        save(output, "source-after.json", after)
        require(before == after, "source changed during native execution")
        REPORT.update(
            {
                "execution_complete": True,
                "source_unchanged": True,
                "source_after_sha256": sha((output / "source-after.json").read_bytes()),
                "status": "PASS_TWO_CONTROLS_AND_ORIGINAL_SEVEN"
                if all(g["passed"] for g in REPORT["groups"])
                else "FAIL_TWO_CONTROLS_AND_ORIGINAL_SEVEN",
            }
        )
    except BaseException as error:
        REPORT.update(
            {"status": "DIAGNOSTIC_INCOMPLETE_OR_FAILED", "error": repr(error)}
        )
        traceback.print_exc()
    finally:
        REPORT["elapsed_seconds"] = time.monotonic() - STARTED
        save(output, "receipt.json", REPORT)
        records = [
            {
                "path": p.relative_to(output).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha(p.read_bytes()),
            }
            for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "artifact-manifest.json"
        ]
        save(
            output,
            "artifact-manifest.json",
            {
                "head": args.expected_head,
                "product_tree": PRODUCT_TREE,
                "files": records,
            },
        )
        print(json.dumps(REPORT, sort_keys=True), flush=True)
    return 0 if REPORT["status"] == "PASS_TWO_CONTROLS_AND_ORIGINAL_SEVEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
