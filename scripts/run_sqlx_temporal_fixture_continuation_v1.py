"""Complete only the two unfinished SQLx fixture locks and graphs.

Inactive until a separate Root admission, exact combined source pins and
workflow activation agree. Original successful main stages are never called.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import time
import tomllib

SPEC_PATH = "scripts/hepta_sqlx_temporal_fixture_continuation_inputs_v1.json"
RUNNER_PATH = "scripts/run_sqlx_temporal_fixture_continuation_v1.py"
DATA_PATH = "scripts/hepta_sqlx_temporal_fixture_continuation_contract_v1.py"
DATA_SHA = "e236e6bb5d871c7716b26d40e7c0f53096a9c7b16f7566606c0c8b01325b79a4"
WORKFLOW_PATH = ".github/workflows/hepta-sqlx-temporal-fixture-continuation-v1.yml"
TEST_PATH = "qa/b4-no-bypass/test_sqlx_temporal_fixture_continuation_v1.py"
REUSE_PATH = "qualification/sqlx_temporal_partial_main_reuse_acceptance_v1.json"
REUSE_SHA = "cf3e3d8c41332737d013699ded3c334411a9dfdcea02d222e75cf87b696d9e1f"
ADMISSION_PATH = "qualification/sqlx_temporal_fixture_continuation_admission_v1.json"
PEER_PATH = "scripts/hepta_chrono_hooks_cli_native_inputs_v2.json"
RUNTIME_PATH = "scripts/run_chrono_hooks_cli_lock_scope_v1.py"
RUNTIME_SHA = "9f7611b839ebe6518260e40cae81344169e7037a8551b1be00a2f20f28513ac2"
HELPER_PATH = "scripts/run_sqlx_temporal_lock_scope_v1.py"
HELPER_SHA = "bda2c49e04f2277f0c39cab922d901ba9018281c32e7bae7d1f874aa2721ea6a"
CONTRACT_PATH = "scripts/hepta_sqlx_temporal_lock_contract_v1.py"
CONTRACT_SHA = "b65a3e60a2efc8d2716aad48e97fb70768d920f9df9e8f3e582461a4b35c9043"
EXECUTOR_PATH = "scripts/hepta_ci_exec.py"
EXECUTOR_SHA = "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba"
FROZEN_RUST = {
    "cargo": {
        "bytes": 42865872,
        "sha256": "f30f9fd1b1d0b8fd10dc33219eb4cd4bec3543f40e434ac71f5a03fd0359063f",
    },
    "rustc": {
        "bytes": 646032,
        "sha256": "ba4b837efb6612dfa8d941c5a72b8a50d1d03a0f36216743b173949aa8d9eb75",
    },
}
REQUIRED = {
    RUNNER_PATH,
    DATA_PATH,
    WORKFLOW_PATH,
    TEST_PATH,
    REUSE_PATH,
    ADMISSION_PATH,
    RUNTIME_PATH,
    HELPER_PATH,
    CONTRACT_PATH,
    EXECUTOR_PATH,
    "AGENTS.md",
    "scripts/run_chrono_hooks_cli_native_controls_v2.py",
    ".github/workflows/hepta-chrono-hooks-cli-native-controls-v2.yml",
    "codex-rs/Cargo.lock",
    "MODULE.bazel.lock",
    "qualification/sqlx_temporal_default_v1/Cargo.toml",
    "qualification/sqlx_temporal_default_v1/scalar_public.rs",
    "qualification/sqlx_temporal_default_v1/chrono_default_refusal.rs",
    "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.toml",
    "qualification/sqlx_temporal_explicit_chrono_v1/chrono_explicit.rs",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(path, limit=8 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= limit,
            "input is nonregular or exceeds its bound",
        )
        raw = stream.read(limit + 1)
        after, current = os.fstat(stream.fileno()), path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        len(raw) == before.st_size <= limit
        and all(
            getattr(before, key) == getattr(after, key) == getattr(current, key)
            for key in fields
        ),
        "input changed during descriptor read",
    )
    return raw


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def put(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"file": path.name, "bytes": len(raw), "sha256": digest(raw)}


def module(path, expected, name):
    require(
        digest(read_regular(path)) == expected, "pinned helper changed: " + str(path)
    )
    description = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(description)
    description.loader.exec_module(value)
    return value


def admitted(source):
    """Only stdlib and raw data are touched before the explicit admission gate."""
    spec = strict_json(read_regular(source / SPEC_PATH))
    require(
        spec["schema"] == "hepta.sqlx-temporal-fixture-continuation-inputs.v1"
        and spec["activated"] is True
        and spec["activation_blockers"] == [],
        "fixture continuation is inactive",
    )
    raw = read_regular(source / REUSE_PATH)
    require(
        len(raw) == 16175 and digest(raw) == REUSE_SHA,
        "Root partial reuse receipt changed",
    )
    review = strict_json(raw)
    approval_raw = read_regular(source / ADMISSION_PATH)
    approval = strict_json(approval_raw)
    require(
        approval["schema"] == "root-sqlx-fixture-continuation-admission-v1"
        and approval["accepted"] is True
        and approval["reviewer"] == "root"
        and approval["execution_authorization"] is True
        and approval["budget"] == spec["budget"]
        and approval["branch"] == spec["branch"]
        and approval["parent"] == spec["parent"]
        and approval["source_delta_paths"] == spec["source_delta_paths"]
        and approval["reuse_acceptance_sha256"] == REUSE_SHA
        and approval["old_E1_E6_budget_used"] == 0
        and approval["repeat_successful_original_stages"] is False
        and approval["maximum_continuation_attempts"] == 1,
        "separate Root continuation execution admission is absent",
    )
    data = module(source / DATA_PATH, DATA_SHA, "sqlx_fixture_continuation_data")
    data.validate_reuse(review)
    remaining = data.validate_budget(spec["budget"], spec["original_spent_seconds"])
    require(
        spec["parent"] == data.PARENT
        and spec["parent_tree"] == data.PARENT_TREE
        and spec["source_ceilings_seconds"] == data.CEILINGS
        and spec["maximum_continuation_attempts"] == 1
        and spec["command_caps_seconds"] == list(data.COMMAND_CAPS)
        and spec["old_E1_E6_budget_used"] == 0
        and spec["peer_spec_byte_pin_exception"] == PEER_PATH
        and spec["source_delta_paths"] == sorted(set(spec["source_delta_paths"]))
        and isinstance(spec["branch"], str)
        and spec["branch"]
        and spec["actual_head"] is None
        and spec["actual_tree"] is None,
        "continuation source identity or immutable budget contract changed",
    )
    require(
        approval["controls"]["accepted"] is True
        and approval["controls"]["execution_count"] == 1
        and data.finite_number(approval["controls"]["elapsed_seconds"])
        and 0 <= approval["controls"]["elapsed_seconds"] <= 5
        and approval["controls"]["names"] == spec["new_data_controls"]
        and re.fullmatch(
            r"[0-9a-f]{64}", approval["controls"]["original_receipt_sha256"] or ""
        ),
        "new pure-data control admission lacks its original accepted receipt",
    )
    data.validate_peer(strict_json(read_regular(source / PEER_PATH)), spec)
    return spec, review, data, remaining


def git_tree(scope, root, revision):
    result = {}
    for row in scope.read_git(root, "ls-tree", "-r", "-z", revision).split(b"\0"):
        if not row:
            continue
        header, path = row.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        name = path.decode()
        require(
            kind == "blob"
            and mode in ("100644", "100755", "120000")
            and name not in result,
            "unsupported or duplicate tree entry",
        )
        result[name] = {"mode": mode, "git_blob": blob}
    require(result, "empty Git tree")
    return result


def bound_source(scope, spec, data, helper):
    require(
        os.environ["GITHUB_REPOSITORY"] == data.REPO
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["LOCK_PR_AUTHOR"] == "ProfHepta"
        and os.environ["LOCK_PR_DRAFT"] == "true"
        and os.environ["LOCK_HEAD_REPO"] == data.REPO
        and os.environ["LOCK_EVENT_ACTION"] == "opened"
        and os.environ["LOCK_HEAD_BRANCH"] == spec["branch"],
        "not the original owned Draft opening",
    )
    head = os.environ["LOCK_EXPECTED_HEAD"]
    require(re.fullmatch(r"[0-9a-f]{40}", head), "missing event head")
    begin = strict_json(read_regular(scope.evidence / "job-start.json"))
    require(
        begin["head"] == head
        and begin["run_id"] == os.environ["GITHUB_RUN_ID"]
        and begin["run_attempt"] == "1"
        and begin["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and data.finite_number(begin["checkout_elapsed_seconds"])
        and 0
        <= begin["checkout_elapsed_seconds"]
        <= spec["budget"]["checkout_seconds"],
        "job identity, boot or checkout allowance differs",
    )
    require(
        scope.read_git(scope.source, "rev-parse", "HEAD").decode().strip() == head,
        "checkout is not the exact event head",
    )
    git = scope.source / ".git"
    require(git.is_dir() and not git.is_symlink(), "Git metadata is not owned")
    shallow = read_regular(git / "shallow", 1024)
    require(
        shallow == (data.PARENT + "\n").encode(),
        "checkout must contain exactly this source and the b4fa parent",
    )
    headers = (
        scope.read_git(scope.source, "cat-file", "-p", head)
        .split(b"\n\n", 1)[0]
        .decode()
        .splitlines()
    )
    require(
        [line[7:] for line in headers if line.startswith("parent ")] == [data.PARENT],
        "combined candidate has a different sole parent",
    )
    tree = next(line[5:] for line in headers if line.startswith("tree "))
    require(
        scope.read_git(scope.source, "rev-parse", data.PARENT + "^{tree}")
        .decode()
        .strip()
        == data.PARENT_TREE,
        "original parent tree differs",
    )
    require(
        not scope.read_git(
            scope.source, "status", "--porcelain=v1", "--untracked-files=all"
        )
        and all(
            row.startswith(b"H ")
            for row in scope.read_git(scope.source, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "source is dirty, sparse or assumed unchanged",
    )
    parent = git_tree(scope, scope.source, data.PARENT)
    current = git_tree(scope, scope.source, head)
    changed = sorted(
        path
        for path in parent.keys() | current.keys()
        if parent.get(path) != current.get(path)
    )
    require(changed == spec["source_delta_paths"], "complete publication delta differs")
    require(
        parent["codex-rs/Cargo.lock"]
        == {"mode": "100644", "git_blob": data.RELATION_BASELINE["git_blob"]},
        "original d301 relation baseline blob differs",
    )
    relation_raw = scope.read_git(
        scope.source, "show", data.PARENT + ":codex-rs/Cargo.lock"
    )
    require(
        data.pin(relation_raw)
        == {key: data.RELATION_BASELINE[key] for key in ("bytes", "sha256")},
        "original d301 relation baseline bytes differ",
    )
    manifest_review = data.validate_manifest_equivalence(parent, current)
    put(scope.evidence / (scope.phase + "-manifest-equivalence.json"), manifest_review)
    for path, expected in data.MAIN_LOCKS.items():
        require(
            data.pin(read_regular(scope.source / path)) == expected,
            "source does not carry the accepted main lock: " + path,
        )
    for _, relative in data.FIXTURES:
        path = scope.source / relative / "Cargo.lock"
        require(
            not path.exists() and not path.is_symlink(),
            "fixture lock already exists before the continuation",
        )
    rows = spec["reviewed_sources"]
    mapped = {row["path"]: row for row in rows}
    required = REQUIRED | set(data.resolution_inputs(current)) | set(changed)
    required -= {SPEC_PATH, PEER_PATH}
    require(
        rows
        and len(mapped) == len(rows)
        and required <= mapped.keys()
        and SPEC_PATH not in mapped
        and PEER_PATH not in mapped,
        "reviewed source pins are incomplete or form a cross-spec hash cycle",
    )
    for path, row in mapped.items():
        rel = Path(path)
        require(
            not rel.is_absolute()
            and ".." not in rel.parts
            and current[path]["mode"] == row["mode"]
            and row["mode"] in ("100644", "100755"),
            "source registration path or mode differs",
        )
        actual = scope.source / rel
        require(
            bool(actual.stat().st_mode & 0o111) == (row["mode"] == "100755")
            and data.pin(read_regular(actual, 32 * 1024 * 1024))
            == {key: row[key] for key in ("bytes", "sha256")},
            "reviewed source bytes changed: " + path,
        )
    for path, expected in (
        (RUNTIME_PATH, RUNTIME_SHA),
        (HELPER_PATH, HELPER_SHA),
        (CONTRACT_PATH, CONTRACT_SHA),
        (EXECUTOR_PATH, EXECUTOR_SHA),
        (DATA_PATH, DATA_SHA),
    ):
        require(mapped[path]["sha256"] == expected, "helper registration changed")
    require(
        tomllib.loads(
            read_regular(scope.source / "codex-rs/rust-toolchain.toml").decode()
        )["toolchain"]["channel"]
        == "1.96.0",
        "Rust toolchain changed",
    )
    return {
        "head": head,
        "tree": tree,
        "parent": data.PARENT,
        "parent_tree": data.PARENT_TREE,
        "shallow_sha256": digest(shallow),
        "spec_sha256": digest(read_regular(scope.source / SPEC_PATH)),
        "reuse_acceptance_sha256": REUSE_SHA,
        "admission_sha256": digest(read_regular(scope.source / ADMISSION_PATH)),
    }, relation_raw


def prepare_start(scope, spec, data, helper):
    identity, _ = bound_source(scope, spec, data, helper)
    put(
        scope.evidence / "tool-start.json",
        {
            "source": identity,
            "monotonic_seconds": scope.start,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        },
    )
    return {"status": "TOOL_PREPARATION_STARTED_ONLY", "source": identity}


def prepare_finish(scope, spec, data, helper):
    identity, _ = bound_source(scope, spec, data, helper)
    begin = strict_json(read_regular(scope.evidence / "tool-start.json"))
    require(
        begin["source"] == identity
        and begin["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "tool preparation source or boot changed",
    )
    outcomes = strict_json(os.environ["LOCK_TOOL_STEPS"])
    require(
        outcomes.get("rust", {}).get("outcome") == "success",
        "original Rust installation failed",
    )
    tools = {
        "cargo_launcher": helper.tool_file(Path(shutil.which("cargo") or "")),
        "rustup": helper.tool_file(Path(shutil.which("rustup") or "")),
        "git": helper.tool_file(Path(shutil.which("git") or "")),
        "python": helper.tool_file(Path(sys.executable)),
        "shell": helper.tool_file(Path("/bin/sh")),
    }
    versions = {}
    for name in ("cargo", "rustc"):
        out, _ = scope.run(
            "locate-" + name,
            [tools["rustup"]["path"], "which", "--toolchain", "1.96.0", name],
            scope.source,
            5,
        )
        lines = out.read_text().splitlines()
        require(len(lines) == 1 and Path(lines[0]).is_absolute(), "ambiguous Rust tool")
        tools[name] = helper.tool_file(Path(lines[0]))
        require(
            {key: tools[name][key] for key in ("bytes", "sha256")} == FROZEN_RUST[name],
            "original pinned Rust executable changed: " + name,
        )
        out, err = scope.run(
            "version-" + name, [tools[name]["path"], "--version"], scope.source, 5
        )
        require(
            scope.commands[-1]["elapsed_seconds"] <= 5
            and any(
                line.startswith(name + " 1.96.0 ")
                for line in out.read_text().splitlines()
            ),
            "actual Rust version or five-second cap differs",
        )
        versions[name] = {
            "stdout": out.name,
            "stderr": err.name,
            "elapsed_seconds": scope.commands[-1]["elapsed_seconds"],
        }
    result = {
        "status": "TOOLS_PREPARED_ONLY",
        "source": identity,
        "actual_tools": tools,
        "versions": versions,
        "tool_steps": outcomes,
        "path_environment": os.environ["PATH"],
        "full_preparation_cpu_seconds": None,
    }
    put(scope.evidence / "tool-preparation.json", result)
    return result


def complete(scope, spec, review, data, helper, runtime, state):
    identity, relation_raw = bound_source(scope, spec, data, helper)
    state["source"] = identity
    prepared = strict_json(read_regular(scope.evidence / "tool-preparation.json"))
    terminal = strict_json(read_regular(scope.evidence / "prepare-finish.RESULT.json"))
    require(
        prepared["status"] == terminal["status"] == "TOOLS_PREPARED_ONLY"
        and prepared["source"] == terminal["source"] == identity
        and terminal["elapsed_seconds"] <= spec["budget"]["tool_preparation_seconds"]
        and prepared["actual_tools"] == terminal["actual_tools"],
        "original exact-source tool preparation did not succeed",
    )
    tools = prepared["actual_tools"]
    require(prepared["path_environment"] == os.environ["PATH"], "prepared PATH changed")
    for value in tools.values():
        require(
            helper.tool_file(Path(value["path"])) == value,
            "prepared executable changed",
        )
    before = runtime.source_snapshot(scope, scope.source, identity["tree"])
    runtime.require_tree(before, "original source")
    state["before"] = before
    put(scope.evidence / "source-before.json", before)
    state["work"] = scope.stage / "work"
    work, routing = helper.create_work_copy(scope, runtime, identity, tools)
    copied = runtime.source_snapshot(scope, work, identity["tree"])
    require(copied == before, "isolated source copy differs")
    put(scope.evidence / "copy-before.json", copied)
    contract = module(
        work / CONTRACT_PATH, CONTRACT_SHA, "original_fixture_lock_contract"
    )
    contract.check_fixture_declarations()
    baseline = tomllib.loads(relation_raw.decode())
    seed = read_regular(work / "codex-rs/Cargo.lock")
    runtime.lock_targets(tomllib.loads(seed.decode()))
    original_main = {
        path: data.pin(read_regular(work / path)) for path in data.MAIN_LOCKS
    }
    require(original_main == data.MAIN_LOCKS, "copied main locks changed")
    cache = scope.stage / "cargo-home-continuation"
    cache.mkdir(mode=0o700)
    require(not list(cache.iterdir()), "continuation cache did not start empty")
    environment = {
        "CARGO_HOME": str(cache),
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "CARGO_TARGET_DIR": str(scope.stage / "cargo-target-cache-only"),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "CARGO_NET_RETRY": "0",
        "CARGO_NET_OFFLINE": "false",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cargo = [tools["cargo_launcher"]["path"], "+1.96.0"]
    plan = data.command_plan(cargo, work)
    put(
        scope.evidence / "exact-unfinished-command-plan.json",
        {
            "commands": [
                {"label": name, "argv": argv, "cap_seconds": cap}
                for name, argv, cap in plan
            ],
            "original_successful_stages_replayed": False,
            "seed_is_original_bc8_main_lock": True,
            "relation_edge_ceiling_is_original_d301_lock": True,
            "fresh_cache_requires_one_locked_fetch": True,
        },
    )
    state["cache_fetch_attempts"] += 1
    scope.run(*plan[0][:2], work / "codex-rs", plan[0][2], environment)
    require(
        {path: data.pin(read_regular(work / path)) for path in data.MAIN_LOCKS}
        == original_main,
        "locked cache recovery changed a main lock",
    )
    fixture_results = {}
    for index, (label, relative, name, compatibility) in enumerate(contract.FIXTURES):
        fixture = work / relative
        lock = fixture / "Cargo.lock"
        state["fixture_seed_attempts"][label] += 1
        seed_receipt = data.copy_seed(
            seed, lock, data.MAIN_LOCKS["codex-rs/Cargo.lock"]
        )
        require(
            lock.stat().st_ino != (work / "codex-rs/Cargo.lock").stat().st_ino,
            "fixture seed shares the main lock inode",
        )
        put(scope.evidence / (label + "-seed.json"), seed_receipt)
        fixture_environment = {
            **environment,
            "CARGO_NET_OFFLINE": "true",
            "CARGO_TARGET_DIR": str(scope.stage / ("cargo-target-" + label)),
        }
        update, metadata = plan[1 + index * 2 : 3 + index * 2]
        state["fixture_update_attempts"][label] += 1
        scope.run(*update[:2], work / "codex-rs", update[2], fixture_environment)
        observed = tomllib.loads(read_regular(lock).decode())
        relation = contract.lock_relation(baseline, observed, name)
        put(scope.evidence / (label + "-lock-relation.json"), relation)
        lock_pin = data.pin(read_regular(lock))
        state["fixture_metadata_attempts"][label] += 1
        output, _ = scope.run(
            *metadata[:2], work / "codex-rs", metadata[2], fixture_environment
        )
        require(
            data.pin(read_regular(lock)) == lock_pin,
            "locked metadata rewrote fixture lock",
        )
        metadata_raw = read_regular(output, 64 * 1024 * 1024)
        normalized, observation = contract.fixture_observation(
            strict_json(metadata_raw), observed, name, compatibility
        )
        normalized_file = put(
            scope.evidence / (label + "-normalized-graph.json"), normalized
        )
        observation.update(
            lock=lock_pin,
            normalized_graph_file=normalized_file,
            original_metadata={"file": output.name, **data.pin(metadata_raw)},
            target=data.TARGET,
            seed=seed_receipt,
            qualification=False,
        )
        put(scope.evidence / (label + "-graph-observation.json"), observation)
        fixture_results[label] = observation
    require(
        {path: data.pin(read_regular(work / path)) for path in data.MAIN_LOCKS}
        == original_main,
        "fixture completion changed a main lock",
    )
    require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"]
        and read_regular(work / ".git/shallow") == routing["shallow"]
        and read_regular(work / ".git/objects/info/alternates") == routing["alternates"]
        and read_regular(work / ".git/config") == routing["config"]
        and not scope.read_git(work, "diff", "--cached", "--name-only")
        and all(
            row.startswith(b"H ")
            for row in scope.read_git(work, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "isolated source identity, index or routing changed",
    )
    after = runtime.source_snapshot(scope, work, identity["tree"])
    require(after == before, "fixture continuation changed tracked source")
    put(scope.evidence / "copy-after.json", after)
    outputs = helper.check_untracked_outputs(scope, work)
    require(
        outputs["bazel_links"] == [], "continuation created unexpected Bazel output"
    )
    put(scope.evidence / "owned-untracked-output-readback.json", outputs)
    locks = helper.retain_lock_set(
        scope, work, scope.evidence / "candidate-locks", helper.LOCKS
    )
    for label, relative in data.FIXTURES:
        require(
            locks[relative + "/Cargo.lock"] == fixture_results[label]["lock"],
            "retained fixture lock differs from its observed graph: " + label,
        )
    for value in tools.values():
        require(
            helper.tool_file(Path(value["path"])) == value,
            "continuation changed a tool",
        )
    executed = data.validate_completed_commands(scope.commands, plan, cargo)
    return {
        "status": "FIXTURE_LOCK_CANDIDATES_REQUIRES_ROOT_REVIEW",
        "source": identity,
        "lock_postimages": locks,
        "fixture_graphs": fixture_results,
        "actual_cargo_commands": executed,
        "cargo_command_prefix": cargo,
        "original_main_metadata": review["main_metadata"],
        "original_successful_commands": review["successful_original_commands"],
        "original_failed_origin": review["origin"],
        "original_generation_stays_failed": True,
        "main_update_executions": 0,
        "main_metadata_executions": 0,
        "bazel_executions": 0,
        "original_twelve_controls_executions": 0,
        "native_12_plus_3_executions": 0,
        "retry_attempts": 0,
        "root_four_lock_acceptance": None,
        "accepted_fixture_graphs": None,
        "native_qualification": False,
        "advisory_qualification": False,
        "science_qualification": False,
        "adoption_or_use_qualification": False,
    }


def readback(scope, spec, data):
    steps = strict_json(os.environ["LOCK_ALL_STEPS"])
    require(
        all(
            steps.get(name, {}).get("outcome") == "success"
            for name in ("job_scope", "checkout", "begin", "rust", "tools", "complete")
        ),
        "an original workflow step failed",
    )
    raw = read_regular(scope.evidence / "complete.RESULT.json", 8 * 1024 * 1024)
    result = strict_json(raw)
    require(
        result["status"] == "FIXTURE_LOCK_CANDIDATES_REQUIRES_ROOT_REVIEW"
        and result["source"]["head"] == os.environ["LOCK_EXPECTED_HEAD"]
        and result["source"]["parent"] == data.PARENT
        and result["source"]["spec_sha256"]
        == digest(read_regular(scope.source / SPEC_PATH))
        and result["original_checkout_unchanged"] is True
        and result["original_generation_stays_failed"] is True
        and result["elapsed_seconds"] <= spec["budget"]["generation_seconds"]
        and result["retry_attempts"] == 0,
        "fixture continuation lacks its exact successful original terminal",
    )
    require(
        set(result["lock_postimages"])
        == set(data.MAIN_LOCKS)
        | {relative + "/Cargo.lock" for _, relative in data.FIXTURES}
        and set(result["fixture_graphs"]) == {"default", "compatibility"},
        "four candidate locks or two observed fixture graphs are missing",
    )
    for path, expected in result["lock_postimages"].items():
        require(
            data.pin(read_regular(scope.evidence / "candidate-locks" / path))
            == expected,
            "retained candidate lock changed",
        )
    for path in data.MAIN_LOCKS:
        require(
            result["lock_postimages"][path] == data.MAIN_LOCKS[path],
            "retained main reuse bytes changed",
        )
    for label, relative in data.FIXTURES:
        require(
            result["lock_postimages"][relative + "/Cargo.lock"]
            == result["fixture_graphs"][label]["lock"],
            "retained fixture lock differs from its observed graph: " + label,
        )
    for graph in result["fixture_graphs"].values():
        for key in ("normalized_graph_file", "original_metadata"):
            row = graph[key]
            require(
                Path(row["file"]).name == row["file"],
                "artifact filename leaves evidence",
            )
            require(
                data.pin(read_regular(scope.evidence / row["file"], 64 * 1024 * 1024))
                == {name: row[name] for name in ("bytes", "sha256")},
                "retained fixture graph changed",
            )
    require(
        result["cache_fetch_attempts"] == 1
        and all(
            result[key] == {"default": 1, "compatibility": 1}
            for key in (
                "fixture_seed_attempts",
                "fixture_update_attempts",
                "fixture_metadata_attempts",
            )
        )
        and all(
            result[key] == 0
            for key in (
                "main_update_executions",
                "main_metadata_executions",
                "bazel_executions",
                "original_twelve_controls_executions",
                "native_12_plus_3_executions",
            )
        ),
        "completed or forbidden stage counts differ",
    )
    data.validate_completed_commands(
        result["commands"],
        data.command_plan(result["cargo_command_prefix"], scope.stage / "work"),
        result["cargo_command_prefix"],
    )
    return {
        "status": "FIXTURE_LOCK_CANDIDATES_REQUIRES_ROOT_REVIEW",
        "complete_result": data.pin(raw),
        "steps": steps,
        "full_original_job_and_upload_cost_still_required": True,
        "root_four_lock_acceptance": None,
        "native_qualification": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("prepare-start", "prepare-finish", "complete", "readback")
    )
    args = parser.parse_args()
    started = time.monotonic()
    source = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    stage = Path(os.environ["LOCK_STAGE"]).resolve(strict=True)
    require(
        os.name == "posix"
        and sys.platform == "linux"
        and source != stage
        and source not in stage.parents
        and stage not in source.parents,
        "owned Linux scope must be outside checkout",
    )
    spec, review, data, remaining = admitted(source)
    job = strict_json(read_regular(stage / "evidence/job-start.json"))
    require(
        data.finite_number(job["monotonic_seconds"])
        and 0 <= job["monotonic_seconds"] <= started,
        "job start monotonic clock is invalid",
    )
    whole_deadline = job["monotonic_seconds"] + spec["budget"]["whole_job_seconds"]
    if args.mode == "prepare-finish":
        started = strict_json(read_regular(stage / "evidence/tool-start.json"))[
            "monotonic_seconds"
        ]
    key = (
        "generation_seconds" if args.mode == "complete" else "tool_preparation_seconds"
    )
    cap = 30 if args.mode == "readback" else spec["budget"][key]
    deadline = min(
        started + cap, whole_deadline - (120 if args.mode != "readback" else 1)
    )
    require(
        time.monotonic() < deadline - 2, "remaining original allowance is exhausted"
    )
    runtime = module(source / RUNTIME_PATH, RUNTIME_SHA, "original_lock_process_scope")
    helper = module(source / HELPER_PATH, HELPER_SHA, "original_sqlx_data_helpers")
    scope = runtime.Scope(source, stage, args.mode, started, cap)
    scope.deadline = deadline
    state = {
        "cache_fetch_attempts": 0,
        "fixture_seed_attempts": {"default": 0, "compatibility": 0},
        "fixture_update_attempts": {"default": 0, "compatibility": 0},
        "fixture_metadata_attempts": {"default": 0, "compatibility": 0},
    }
    result = {
        "status": "FAIL",
        "mode": args.mode,
        "error": None,
        "budget": spec["budget"],
        "original_spent_seconds": data.SPENT,
        "remaining_original_seconds": remaining,
        "old_E1_E6_budget_used": 0,
        "effective_absolute_deadline": deadline,
        "remote_writes": 0,
        "new_tests_or_native_executions": 0,
        "original_queue_seconds": 4120,
        "original_readback_seconds_nested_inside_old_job": 79.133119422,
    }
    put(
        scope.evidence / (args.mode + ".START.json"),
        {
            "source_head": os.environ["LOCK_EXPECTED_HEAD"],
            "phase_start": started,
            "absolute_deadline": deadline,
            "automatic_retry": False,
        },
    )

    def expired(signum, frame):
        raise TimeoutError("original remaining SQLx continuation allowance exhausted")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic() - 1.5))
    try:
        if args.mode == "prepare-start":
            result.update(prepare_start(scope, spec, data, helper))
        elif args.mode == "prepare-finish":
            result.update(prepare_finish(scope, spec, data, helper))
        elif args.mode == "complete":
            result.update(complete(scope, spec, review, data, helper, runtime, state))
        else:
            result.update(readback(scope, spec, data))
    except Exception as error:
        result.update(status="FAIL", error=type(error).__name__ + ": " + str(error))
    finally:
        if args.mode == "complete":
            try:
                if "before" in state:
                    after = runtime.source_snapshot(
                        scope, source, state["source"]["tree"]
                    )
                    put(scope.evidence / "source-after.json", after)
                    require(after == state["before"], "original checkout bytes changed")
                    require(
                        scope.read_git(source, "rev-parse", "HEAD").decode().strip()
                        == state["source"]["head"]
                        and digest(read_regular(source / ".git/shallow"))
                        == state["source"]["shallow_sha256"]
                        and not scope.read_git(
                            source, "status", "--porcelain=v1", "--untracked-files=all"
                        )
                        and all(
                            row.startswith(b"H ")
                            for row in scope.read_git(
                                source, "ls-files", "-v", "-z"
                            ).split(b"\0")
                            if row
                        ),
                        "original checkout identity or status changed",
                    )
                    result["original_checkout_unchanged"] = True
            except Exception as error:
                result.update(status="FAIL", final_readback_error=str(error))
            try:
                if "work" in state and result["status"] == "FAIL":
                    retention = {
                        "status": "INCOMPLETE",
                        "files": [],
                        "accepted_candidate": False,
                    }
                    result["failed_partial_lock_retention"] = retention
                    helper.retain_failed_locks(scope, state["work"], retention)
            except Exception as error:
                result.update(status="FAIL", partial_lock_readback_error=str(error))
            result.update(
                {
                    key: state[key]
                    for key in (
                        "cache_fetch_attempts",
                        "fixture_seed_attempts",
                        "fixture_update_attempts",
                        "fixture_metadata_attempts",
                    )
                }
            )
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        result.update(scope.receipt())
        result["storage_final"] = scope.storage_observation()
        result["whole_job_elapsed_seconds_so_far"] = (
            time.monotonic() - job["monotonic_seconds"]
        )
        result["cumulative_whole_job_seconds_so_far"] = (
            data.SPENT["whole_job_seconds"] + result["whole_job_elapsed_seconds_so_far"]
        )
        if args.mode == "complete":
            result["cumulative_generation_seconds"] = (
                data.SPENT["generation_seconds"] + result["elapsed_seconds"]
            )
        result["full_job_cpu_seconds"] = None
        result["final_upload_seconds"] = None
        if (
            result["elapsed_seconds"] > cap
            or time.monotonic() > whole_deadline
            or result["storage_final"]["evidence_bytes"] > 512 * 1024 * 1024
            or result["storage_final"]["free_bytes"] < 4 * 1024 * 1024 * 1024
        ):
            result.update(status="FAIL", budget_or_storage_acceptance_failed=True)
        put(scope.evidence / (args.mode + ".RESULT.json"), result)
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in ("status", "mode", "elapsed_seconds", "error")
                }
            )
        )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        failure = {
            "status": "FAIL_BOOTSTRAP",
            "error": type(error).__name__ + ": " + str(error),
            "automatic_retry": False,
            "old_E1_E6_budget_used": 0,
            "native_qualification": False,
        }
        put(
            Path(os.environ["LOCK_STAGE"])
            / "evidence"
            / (sys.argv[1] + ".BOOTSTRAP_FAILURE.json"),
            failure,
        )
        print(json.dumps(failure))
        raise SystemExit(1)
