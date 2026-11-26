"""Inactive SQLx four-lock/two-fixture-graph engineering generation owner.

Presence of this file is not execution authorization. An independent Root
baseline acceptance, exact source roster and a newly admitted budget are
required before the original subprocess owner is imported.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import sys
import time
import tomllib

REPO = "TrillionniumFoundation/hepta-private-ci"
SPEC_PATH = "scripts/hepta_sqlx_temporal_lock_inputs_v1.json"
RUNNER_PATH = "scripts/run_sqlx_temporal_lock_scope_v1.py"
CONTRACT_PATH = "scripts/hepta_sqlx_temporal_lock_contract_v1.py"
WORKFLOW_PATH = ".github/workflows/hepta-sqlx-temporal-lock-candidate-v1.yml"
CONTROL_PATH = "scripts/test_hepta_sqlx_temporal_lock_contract_v1.py"
CONTROL_CAP_SECONDS = 5
SYNTHETIC_CONTROLS = (
    "test_main_sqlx_chrono_removal_is_allowed",
    "test_independent_fixture_subset_is_allowed",
    "test_equivalent_dependency_version_spelling_is_allowed",
    "test_registry_version_drift_is_refused",
    "test_registry_checksum_drift_is_refused",
    "test_non_sqlx_dependency_change_is_refused",
    "test_sqlx_non_chrono_removal_is_refused",
    "test_foreign_fixture_identity_is_refused",
    "test_foreign_fixture_dependency_edge_is_refused",
    "test_duplicate_package_identity_is_refused",
    "test_ambiguous_dependency_identity_is_refused",
    "test_absent_dependency_identity_is_refused",
)
RUNTIME_PATH = "scripts/run_chrono_hooks_cli_lock_scope_v1.py"
RUNTIME_SHA = "9f7611b839ebe6518260e40cae81344169e7037a8551b1be00a2f20f28513ac2"
GRAPH_PATH = "scripts/hepta_chrono_hooks_cli_lock_contract_v1.py"
GRAPH_SHA = "97cce2b16b9cabef581f97a3b2aa9bc8b87da507ab7c1cfed4b998489145d90c"
OWNER_SHA = "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba"
TARGET = "aarch64-unknown-linux-gnu"
DEFAULT = "qualification/sqlx_temporal_default_v1"
COMPATIBILITY = "qualification/sqlx_temporal_explicit_chrono_v1"
MAIN_LOCKS = frozenset(("codex-rs/Cargo.lock", "MODULE.bazel.lock"))
FIXTURE_LOCKS = frozenset((DEFAULT + "/Cargo.lock", COMPATIBILITY + "/Cargo.lock"))
LOCKS = MAIN_LOCKS | FIXTURE_LOCKS
SOURCE_CEILINGS = {
    "checkout_seconds": 120,
    "tool_preparation_seconds": 180,
    "generation_seconds": 900,
    "whole_job_seconds": 1320,
}
STDOUT_CAP_BYTES = 64 * 1024 * 1024
EVIDENCE_ACCEPTANCE_CAP_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 4 * 1024 * 1024 * 1024
BAZEL_ASSET = {
    "id": 619248138,
    "name": "bazel-9.3.0-linux-x86_64",
    "url": "https://github.com/bazelbuild/bazel/releases/download/9.3.0/bazel-9.3.0-linux-x86_64",
    "bytes": 77023347,
    "sha256": "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8",
    "release_json_sha256": "d0bd5b73346d1ebedf9ab28a37a180ce3bad2954f1718a396c931c23ca57d348",
}
FIXTURE_SOURCES = frozenset(
    (
        DEFAULT + "/Cargo.toml",
        DEFAULT + "/scalar_public.rs",
        DEFAULT + "/chrono_default_refusal.rs",
        COMPATIBILITY + "/Cargo.toml",
        COMPATIBILITY + "/chrono_explicit.rs",
    )
)
REQUIRED_SOURCE_PATHS = (
    MAIN_LOCKS
    | FIXTURE_SOURCES
    | {
        RUNNER_PATH,
        CONTRACT_PATH,
        CONTROL_PATH,
        WORKFLOW_PATH,
        RUNTIME_PATH,
        GRAPH_PATH,
        "scripts/hepta_ci_exec.py",
        "justfile",
        "scripts/just-shell.py",
        ".bazelrc",
        ".bazelversion",
        ".gitattributes",
        "MODULE.bazel",
        "codex-rs/Cargo.toml",
        "codex-rs/deny.toml",
        "codex-rs/rust-toolchain.toml",
    }
)
ALLOWED_SOURCE_DELTA_PATHS = FIXTURE_SOURCES | {
    RUNNER_PATH,
    CONTRACT_PATH,
    CONTROL_PATH,
    WORKFLOW_PATH,
    SPEC_PATH,
    "qualification/sqlx_temporal_baseline_acceptance_v1.json",
    "qualification/SQLX_TEMPORAL_OWNER_DESIGN.md",
    "qualification/SQLX_TEMPORAL_LOCK_GENERATION_DESIGN.md",
    "codex-rs/Cargo.toml",
    "codex-rs/state/src/lib.rs",
    "codex-rs/hepta-operations/src/lib.rs",
    "codex-rs/state/src/sqlx_temporal_contract_tests.rs",
    "codex-rs/state/SQLX_TEMPORAL_MIGRATION.md",
    "scripts/run_sqlx_temporal_contract_v1.py",
    "scripts/hepta_sqlx_temporal_contract_inputs_v1.json",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_value(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

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


def raw_hash(path):
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": value.hexdigest()}


def tool_file(path):
    resolved = path.resolve(strict=True)
    require(
        resolved.is_file() and os.access(resolved, os.X_OK),
        "tool is not an executable file",
    )
    return {"path": str(path), "resolved_path": str(resolved), **raw_hash(resolved)}


def original_rc_only(source):
    for path in (
        Path("/etc/bazel.bazelrc"),
        Path.home() / ".bazelrc",
        source / "user.bazelrc",
    ):
        require(
            not path.exists() and not path.is_symlink(),
            "unreviewed Bazel rc exists: " + str(path),
        )


def parse_lock(path):
    value = tomllib.loads(path.read_text())
    require(value.get("package"), "actual Cargo lock is empty")
    return value


def read_regular_data(path, maximum):
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    )
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum,
            "data file is not regular or exceeds its byte bound",
        )
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= maximum, "data file grew above its byte bound")
        after, current = os.fstat(descriptor), path.lstat()
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        require(
            size == before.st_size
            and all(
                getattr(before, key) == getattr(after, key) == getattr(current, key)
                for key in fields
            ),
            "data source changed during descriptor read",
        )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def load_module(path, expected_sha, name):
    require(path.is_file() and not path.is_symlink(), "module is not a regular source")
    require(raw_hash(path)["sha256"] == expected_sha, "pinned source module changed")
    module_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def admitted_input(source):
    """No repository module import or child command precedes this gate."""
    path = source / SPEC_PATH
    require(path.is_file() and not path.is_symlink(), "input is not a regular source")
    spec = json_value(read_regular_data(path, 8 * 1024 * 1024))
    require(
        spec["schema"] == "hepta.sqlx-temporal-lock-approved-inputs.v1"
        and spec["activated"] is True
        and spec["blockers"] == [],
        "SQLx generation is inactive; an empty proposal is not an admitted run",
    )
    require(
        spec["source_ceilings_seconds"] == SOURCE_CEILINGS, "source ceilings changed"
    )
    budget = spec["budget"]
    require(
        isinstance(budget, dict)
        and budget.keys() == SOURCE_CEILINGS.keys()
        and all(
            type(budget[key]) is int and 30 <= budget[key] <= ceiling
            for key, ceiling in SOURCE_CEILINGS.items()
        )
        and budget["whole_job_seconds"]
        >= sum(
            budget[key]
            for key in (
                "checkout_seconds",
                "tool_preparation_seconds",
                "generation_seconds",
            )
        ),
        "new engineering budget is absent, inconsistent or above reviewed ceilings",
    )
    require(
        spec["old_E1_E6_budget_used"] == 0
        and spec["maximum_generation_attempts"] == 1
        and spec["source_baseline_2fd_reuse_permitted"] is False,
        "old acceptance or old resolver allowance cannot authorize this scope",
    )
    baseline = spec["accepted_baseline"]
    require(
        re.fullmatch(r"[0-9a-f]{40}", baseline["head"] or "")
        and re.fullmatch(r"[0-9a-f]{40}", baseline["tree"] or "")
        and re.fullmatch(r"[0-9a-f]{64}", baseline["root_graph_sha256"] or "")
        and set(baseline["locks"]) == MAIN_LOCKS,
        "actual accepted source, two locks or graph are not bound",
    )
    for row in baseline["locks"].values():
        require(
            isinstance(row, dict)
            and type(row["bytes"]) is int
            and row["bytes"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"] or ""),
            "accepted original lock identity is missing",
        )
    generation = baseline["original_generation"]
    require(
        re.fullmatch(r"[0-9a-f]{40}", generation["head"] or "")
        and generation["run_attempt"] == 1
        and all(
            str(generation[key] or "").isdigit() for key in ("run_id", "artifact_id")
        )
        and re.fullmatch(r"[0-9a-f]{64}", generation["artifact_sha256"] or "")
        and generation["terminal_status"] == "success",
        "baseline has no original successful generation identity",
    )
    accepted_path = baseline["root_acceptance"]["path"]
    require(
        accepted_path == "qualification/sqlx_temporal_baseline_acceptance_v1.json",
        "baseline acceptance path changed",
    )
    raw = read_regular_data(source / accepted_path, 8 * 1024 * 1024)
    require(
        digest(raw) == baseline["root_acceptance"]["sha256"],
        "independent Root baseline acceptance is not the reviewed exact source",
    )
    acceptance = json_value(raw)
    require(
        acceptance["schema"] == "hepta-sqlx-temporal-baseline-acceptance-v1"
        and acceptance["accepted"] is True
        and acceptance["reviewer"] == "root"
        and acceptance["baseline"]
        == {k: v for k, v in baseline.items() if k != "root_acceptance"}
        and acceptance["budget"] == budget
        and acceptance["old_E1_E6_budget_used"] == 0,
        "Root did not accept this actual baseline and this new budget",
    )
    require(
        spec["synthetic_contract_controls"] == list(SYNTHETIC_CONTROLS)
        and spec["synthetic_contract_cap_seconds"] == CONTROL_CAP_SECONDS,
        "frozen synthetic control roster or shared-scope five-second ceiling changed",
    )
    require(spec["bazel_asset"] == BAZEL_ASSET, "official Bazel asset differs")
    return spec


def load_spec(scope):
    spec = admitted_input(scope.source)
    baseline = spec["accepted_baseline"]
    require(
        os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["LOCK_PR_AUTHOR"] == "ProfHepta"
        and os.environ["LOCK_PR_DRAFT"] == "true"
        and os.environ["LOCK_HEAD_REPO"] == REPO
        and os.environ["LOCK_EVENT_ACTION"] == "opened"
        and os.environ["LOCK_HEAD_BRANCH"] == spec["branch"],
        "not the first opening of the exact owned SQLx Draft",
    )
    head = os.environ["LOCK_EXPECTED_HEAD"]
    require(re.fullmatch(r"[0-9a-f]{40}", head), "event head is absent")
    job_start = json_value((scope.evidence / "job-start.json").read_bytes())
    require(
        job_start["head"] == head
        and job_start["run_id"] == os.environ["GITHUB_RUN_ID"]
        and job_start["run_attempt"] == "1"
        and job_start["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and job_start["checkout_elapsed_seconds"] <= spec["budget"]["checkout_seconds"],
        "job, original boot or checkout allowance differs",
    )
    require(
        scope.read_git(scope.source, "rev-parse", "HEAD").decode().strip() == head,
        "checkout is not the exact event head",
    )
    source_git = scope.source / ".git"
    require(
        source_git.is_dir() and not source_git.is_symlink(), "Git metadata is not owned"
    )
    shallow_path = source_git / "shallow"
    require(
        shallow_path.is_file() and not shallow_path.is_symlink(),
        "depth-two boundary is absent",
    )
    shallow = shallow_path.read_bytes()
    require(
        shallow == (baseline["head"] + "\n").encode(),
        "source depth-two parent boundary differs",
    )
    commit = scope.read_git(scope.source, "cat-file", "-p", head)
    headers = commit.split(b"\n\n", 1)[0].decode().splitlines()
    require(
        [row[7:] for row in headers if row.startswith("parent ")] == [baseline["head"]]
        and scope.read_git(scope.source, "rev-parse", baseline["head"] + "^{tree}")
        .decode()
        .strip()
        == baseline["tree"],
        "candidate has a different sole parent or accepted parent tree",
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
        "source is dirty, sparse or has an assumed-unchanged tracked input",
    )
    changed = set(
        scope.read_git(
            scope.source, "diff", "--name-only", "-z", baseline["head"], head
        )
        .decode()
        .strip("\0")
        .split("\0")
    )
    require(
        changed == set(spec["source_delta_paths"])
        and changed <= ALLOWED_SOURCE_DELTA_PATHS
        and "codex-rs/Cargo.toml" in changed,
        "unreviewed or incomplete combined source delta",
    )
    parent_cargo = scope.read_git(
        scope.source, "show", baseline["head"] + ":codex-rs/Cargo.toml"
    )
    marker = b'sqlx = { version = "0.9.1", default-features = false, features = [\n    "chrono",\n'
    replacement = (
        b'sqlx = { version = "0.9.1", default-features = false, features = [\n'
    )
    require(
        parent_cargo.count(marker) == 1
        and parent_cargo.replace(marker, replacement, 1)
        == (scope.source / "codex-rs/Cargo.toml").read_bytes(),
        "main Cargo source delta is not exactly removal of the shared SQLx Chrono feature",
    )
    for rel in MAIN_LOCKS:
        parent_lock = scope.read_git(scope.source, "show", baseline["head"] + ":" + rel)
        require(
            {"bytes": len(parent_lock), "sha256": digest(parent_lock)}
            == baseline["locks"][rel]
            and raw_hash(scope.source / rel) == baseline["locks"][rel],
            "baseline locks are not the actual accepted parent bytes",
        )
    require(
        all(
            not (scope.source / rel).exists() and not (scope.source / rel).is_symlink()
            for rel in FIXTURE_LOCKS
        ),
        "fixture lock must be absent before its one genuine generation",
    )
    rows = spec["reviewed_sources"]
    required = (
        REQUIRED_SOURCE_PATHS
        | {baseline["root_acceptance"]["path"]}
        | changed - {SPEC_PATH}
    )
    require(
        rows
        and len({row["path"] for row in rows}) == len(rows)
        and required <= {row["path"] for row in rows},
        "complete actual source/patch/policy roster is not pinned",
    )
    for row in rows:
        rel = Path(row["path"])
        require(
            not rel.is_absolute()
            and ".." not in rel.parts
            and row["mode"] in ("100644", "100755")
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"] or ""),
            "invalid source registration",
        )
        path = scope.source / rel
        require(
            path.is_file()
            and not path.is_symlink()
            and bool(path.stat().st_mode & 0o111) == (row["mode"] == "100755")
            and raw_hash(path)["sha256"] == row["sha256"],
            "reviewed source changed: " + str(rel),
        )
    require(
        (scope.source / ".bazelversion").read_text().strip() == "9.3.0"
        and tomllib.loads((scope.source / "codex-rs/rust-toolchain.toml").read_text())[
            "toolchain"
        ]["channel"]
        == "1.96.0",
        "actual Bazel or Rust selection differs",
    )
    return spec, {
        "head": head,
        "tree": next(row[5:] for row in headers if row.startswith("tree ")),
        "parent": baseline["head"],
        "parent_tree": baseline["tree"],
        "spec_sha256": digest((scope.source / SPEC_PATH).read_bytes()),
        "shallow_sha256": digest(shallow),
    }


def source_pin(spec, path):
    rows = [row for row in spec["reviewed_sources"] if row["path"] == path]
    require(len(rows) == 1, "module has no unique source pin")
    return rows[0]["sha256"]


def prepare_start(scope):
    spec, identity = load_spec(scope)
    original_rc_only(scope.source)
    put(
        scope.evidence / "tool-start.json",
        {
            "schema": "hepta.sqlx-temporal-lock-tool-start.v1",
            "monotonic_seconds": scope.start,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "source": identity,
            "spec_sha256": identity["spec_sha256"],
            "scope_cap_seconds": spec["budget"]["tool_preparation_seconds"],
            "installation_logs": "Complete original GitHub job logs for the pinned Rust and just action steps",
            "old_host_tool_budget_reset": False,
        },
    )
    return {"status": "TOOL_PREPARATION_STARTED_ONLY", "source": identity}


def prepare_finish(scope):
    spec, identity = load_spec(scope)
    begin = json_value((scope.evidence / "tool-start.json").read_bytes())
    require(
        begin["boot_id"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and begin["source"] == identity,
        "tool preparation source/host changed",
    )
    outcomes = json_value(os.environ["LOCK_TOOL_STEPS"])
    require(
        all(
            outcomes.get(name, {}).get("outcome") == "success"
            for name in ("rust", "just")
        ),
        "an original tool installation step did not succeed",
    )
    scope.remaining()
    original_rc_only(scope.source)
    tools_dir = scope.stage / "tools"
    tools_dir.mkdir(exist_ok=False)
    asset = spec["bazel_asset"]
    require(
        asset == BAZEL_ASSET,
        "official Linux Bazel asset is not the reviewed exact release",
    )
    binary = tools_dir / "bazel-9.3.0-linux-x86_64"
    scope.run(
        "download-bazel-once",
        [
            "curl",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--tlsv1.2",
            "--location",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            str(max(1, int(min(50, scope.remaining()) - 1))),
            "--output",
            str(binary),
            asset["url"],
        ],
        scope.source,
        50,
    )
    actual = raw_hash(binary)
    require(
        actual == {"bytes": asset["bytes"], "sha256": asset["sha256"]},
        "official Bazel payload mismatch",
    )
    with binary.open("rb") as stream:
        header = stream.read(20)
    require(
        header[:6] == b"\x7fELF\x02\x01"
        and int.from_bytes(header[18:20], "little") == 62,
        "downloaded tool is not the expected Linux x86-64 executable",
    )
    binary.chmod(0o700)
    tools = {
        "bazel": tool_file(binary),
        "cargo_launcher": tool_file(Path(shutil.which("cargo") or "")),
        "rustup": tool_file(Path(shutil.which("rustup") or "")),
        "just": tool_file(Path(shutil.which("just") or "")),
        "python": tool_file(Path(sys.executable)),
        "shell": tool_file(Path("/bin/sh")),
        "git": tool_file(Path(shutil.which("git") or "")),
    }
    for name in ("cargo", "rustc"):
        out, _ = scope.run(
            "locate-" + name,
            [tools["rustup"]["path"], "which", "--toolchain", "1.96.0", name],
            scope.source,
            5,
        )
        lines = out.read_text().splitlines()
        require(
            len(lines) == 1 and Path(lines[0]).is_absolute(),
            "ambiguous installed Rust tool",
        )
        tools[name] = tool_file(Path(lines[0]))
    versions = {}
    for name, argv, expected in (
        ("cargo", [tools["cargo"]["path"], "--version"], "cargo 1.96.0 "),
        ("rustc", [tools["rustc"]["path"], "--version"], "rustc 1.96.0 "),
        ("just", [tools["just"]["path"], "--version"], "just 1.51.0"),
        (
            "bazel",
            [
                str(binary),
                "--batch",
                "--output_base=" + str(scope.stage / "bazel-version-only"),
                "version",
                "--gnu_format",
            ],
            "bazel 9.3.0",
        ),
    ):
        out, err = scope.run("version-" + name, argv, scope.source, 8)
        lines = out.read_text().splitlines()
        correct = (
            expected in lines
            if name in ("just", "bazel")
            else any(line.startswith(expected) for line in lines)
        )
        require(correct, "actual tool version differs: " + name)
        versions[name] = {"stdout": out.name, "stderr": err.name}
    require(
        not scope.read_git(
            scope.source, "status", "--porcelain=v1", "--untracked-files=all"
        ),
        "tool preparation changed the original checkout",
    )
    require(time.monotonic() <= scope.deadline, "tool preparation cap exceeded")
    result = {
        "status": "TOOLS_PREPARED_ONLY",
        "source": identity,
        "actual_tools": tools,
        "versions": versions,
        "official_bazel_asset": asset,
        "tool_installation_steps": outcomes,
        "path_environment": os.environ["PATH"],
        "full_preparation_cpu_seconds": None,
        "cpu_reason": "Rust/just action processes belong to earlier CI steps; only this process/children CPU is available",
        "old_host_tool_attempts_preserved_separately": True,
        "resolver_not_started": True,
    }
    put(scope.evidence / "tool-preparation.json", result)
    return result


def retain_lock_set(scope, work, destination, paths):
    """Preserve relative paths: three Cargo.lock files must never overwrite."""
    destination.mkdir(exist_ok=False)
    result = {}
    for relative in sorted(paths):
        scope.remaining(reserve=2)
        origin = work / relative
        require(
            origin.is_file() and not origin.is_symlink(), "lock is not a regular file"
        )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = read_regular_data(origin, 32 * 1024 * 1024)
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        result[relative] = {"bytes": len(raw), "sha256": digest(raw)}
    return result


def create_work_copy(scope, runtime, identity, tools):
    work = scope.stage / "work"
    environment = {
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    scope.run(
        "init-isolated-copy",
        [
            tools["git"]["path"],
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "init",
            "--quiet",
            "--template=",
            "--object-format=sha1",
            str(work),
        ],
        scope.stage,
        5,
        environment,
    )
    source_objects = scope.source / ".git/objects"
    require(
        source_objects.is_dir() and not source_objects.is_symlink(),
        "source objects are not local",
    )
    shared_objects = (str(source_objects) + "\n").encode()
    shallow = (scope.source / ".git/shallow").read_bytes()
    require(
        digest(shallow) == identity["shallow_sha256"], "source depth boundary changed"
    )
    for path, raw in (
        (work / ".git/objects/info/alternates", shared_objects),
        (work / ".git/shallow", shallow),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    config = (work / ".git/config").read_bytes()
    routing = {"shallow": shallow, "alternates": shared_objects, "config": config}
    put(
        scope.evidence / "isolated-git-metadata.json",
        {
            "source_object_directory": str(source_objects),
            "shared_read_only_objects": True,
            "source_history_depth": 2,
            "exact_parent_tree_verified": True,
            "second_source_network_request": False,
            "routing_sha256": {key: digest(value) for key, value in routing.items()},
        },
    )
    scope.run(
        "checkout-local-copy",
        [
            tools["git"]["path"],
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-C",
            str(work),
            "checkout",
            "--quiet",
            "--detach",
            identity["head"],
        ],
        scope.stage,
        15,
        environment,
    )
    require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"]
        and not scope.read_git(
            work, "status", "--porcelain=v1", "--untracked-files=all"
        ),
        "isolated work did not start at the clean exact source",
    )
    return work, routing


def check_untracked_outputs(scope, work):
    output_links, fixture_locks = [], set()
    allowed_links = {"bazel-out", "bazel-bin", "bazel-testlogs", "bazel-" + work.name}
    for ignored in (False, True):
        flags = ["ls-files", "--others", "--exclude-standard", "-z"]
        if ignored:
            flags.insert(2, "--ignored")
        for encoded in scope.read_git(work, *flags).split(b"\0"):
            if not encoded:
                continue
            name = encoded.decode()
            path = work / name
            if name in FIXTURE_LOCKS:
                require(
                    path.is_file()
                    and not path.is_symlink()
                    and name not in fixture_locks,
                    "fixture lock is repeated or nonregular",
                )
                fixture_locks.add(name)
                continue
            require(
                ignored
                and name in allowed_links
                and path.is_symlink()
                and path.resolve().is_relative_to(
                    (scope.stage / "bazel-output").resolve()
                ),
                "unexpected untracked or ignored work input: " + name,
            )
            output_links.append({"path": name, "target": os.readlink(path)})
    require(
        fixture_locks == FIXTURE_LOCKS,
        "two generated fixture locks were not both observed",
    )
    return {"fixture_locks": sorted(fixture_locks), "bazel_links": output_links}


def check_lock_contract_controls(scope, spec, work, tools, environment):
    stdout, stderr = scope.run(
        "sqlx-lock-data-controls-once",
        [
            tools["python"]["path"],
            "-m",
            "unittest",
            "-v",
            "test_hepta_sqlx_temporal_lock_contract_v1",
        ],
        work / "scripts",
        CONTROL_CAP_SECONDS,
        environment,
    )
    command = scope.commands[-1]
    elapsed_seconds = command.get("elapsed_seconds")
    require(
        command.get("label") == "sqlx-lock-data-controls-once"
        and type(elapsed_seconds) in (int, float)
        and 0 <= elapsed_seconds <= CONTROL_CAP_SECONDS,
        "actual frozen synthetic control command identity or elapsed time differs",
    )
    names = spec["synthetic_contract_controls"]
    lines = stderr.read_text().splitlines()
    expected = {
        f"{name} (test_hepta_sqlx_temporal_lock_contract_v1.SqlxLockContractTests.{name}) ... ok"
        for name in names
    }
    observed = [line for line in lines if line.startswith("test_")]
    require(
        len(observed) == len(expected) == len(SYNTHETIC_CONTROLS)
        and set(observed) == expected
        and sum(bool(re.fullmatch(r"Ran 12 tests in [0-9.]+s", line)) for line in lines)
        == 1
        and lines[-1] == "OK",
        "actual frozen synthetic lock controls are incomplete or failed",
    )
    receipt = {
        "status": "TWELVE_SYNTHETIC_LOCK_DATA_CONTROLS_PASSED",
        "names": names,
        "execution_count": 1,
        "source_kind": "minimal synthetic TOML locks",
        "source_checksum_literals_are_not_registry_evidence": True,
        "scope_cap_seconds": CONTROL_CAP_SECONDS,
        "actual_command_label": command["label"],
        "actual_elapsed_seconds": elapsed_seconds,
        "included_in_original_generation_deadline": True,
        "stdout": raw_hash(stdout),
        "stderr": raw_hash(stderr),
        "application_native_tests": 0,
        "old_E1_E6_executions": 0,
        "resolver_or_native_qualification": False,
    }
    put(scope.evidence / "synthetic-lock-controls.json", receipt)
    return receipt


def generate(scope, state, runtime):
    spec, identity = load_spec(scope)
    put(
        scope.evidence / "generation-attempt.START.json",
        {
            "source": identity,
            "attempt": 1,
            "budget": spec["budget"],
            "monotonic_seconds": scope.start,
            "retry_permitted": False,
        },
    )
    prepared = json_value((scope.evidence / "tool-preparation.json").read_bytes())
    terminal = json_value((scope.evidence / "prepare-finish.RESULT.json").read_bytes())
    require(
        prepared["status"] == "TOOLS_PREPARED_ONLY"
        and prepared["source"] == identity
        and terminal["status"] == "TOOLS_PREPARED_ONLY"
        and terminal["elapsed_seconds"] <= spec["budget"]["tool_preparation_seconds"]
        and terminal["actual_tools"] == prepared["actual_tools"],
        "exact-source tool preparation has no original successful terminal",
    )
    tools = prepared["actual_tools"]
    require(os.environ["PATH"] == prepared["path_environment"], "prepared PATH changed")
    for tool in tools.values():
        require(tool_file(Path(tool["path"])) == tool, "prepared tool changed")
    original_rc_only(scope.source)
    before = runtime.source_snapshot(scope, scope.source, identity["tree"])
    runtime.require_tree(before, "original checkout")
    put(scope.evidence / "source-before.json", before)
    state.update({"source": identity, "before": before})
    # Record the owned path before copy creation so partial failures remain collectable.
    state["work"] = scope.stage / "work"
    work, routing = create_work_copy(scope, runtime, identity, tools)
    initial = runtime.source_snapshot(scope, work, identity["tree"])
    require(initial == before, "copy is not the complete identical source")
    put(scope.evidence / "copy-before.json", initial)
    original_rc_only(work)
    contract = load_module(
        work / CONTRACT_PATH,
        source_pin(spec, CONTRACT_PATH),
        "sqlx_generation_data_contract",
    )
    graph_contract = load_module(
        work / GRAPH_PATH, GRAPH_SHA, "accepted_chrono_graph_normalizer"
    )
    contract.check_fixture_declarations()
    baseline_lock = parse_lock(work / "codex-rs/Cargo.lock")
    runtime.lock_targets(baseline_lock)
    module_before = (work / "MODULE.bazel.lock").read_bytes()
    require(
        {path: raw_hash(work / path) for path in MAIN_LOCKS}
        == spec["accepted_baseline"]["locks"],
        "copy is not based on the actual accepted main locks",
    )
    retained_originals = retain_lock_set(
        scope, work, scope.evidence / "original-locks", MAIN_LOCKS
    )
    bin_dir = scope.stage / "bin"
    bin_dir.mkdir(exist_ok=False)
    wrapper = bin_dir / "bazel"
    wrapper_text = (
        "#!/bin/sh\nexec "
        + shlex.quote(tools["bazel"]["path"])
        + " --batch "
        + shlex.quote("--output_base=" + str(scope.stage / "bazel-output"))
        + ' "$@"\n'
    )
    with wrapper.open("x") as stream:
        stream.write(wrapper_text)
    wrapper.chmod(0o700)
    put(
        scope.evidence / "bazel-wrapper.json",
        {"path": str(wrapper), "content": wrapper_text, **raw_hash(wrapper)},
    )
    cargo_home = scope.stage / "cargo-home-main-and-fixtures"
    bazel_cargo_home = scope.stage / "cargo-home-bazel"
    cargo_home.mkdir(mode=0o700, exist_ok=False)
    bazel_cargo_home.mkdir(mode=0o700, exist_ok=False)
    require(
        not list(cargo_home.iterdir()) and not list(bazel_cargo_home.iterdir()),
        "resolver cache must start empty",
    )
    environment = {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "CARGO_HOME": str(cargo_home),
        "CARGO_TARGET_DIR": str(scope.stage / "cargo-target-main"),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cargo = [tools["cargo_launcher"]["path"], "+1.96.0"]
    cwd = work / "codex-rs"
    manifest = str(cwd / "Cargo.toml")
    put(
        scope.evidence / "cache-boundary.json",
        {
            "main_and_fixtures": str(cargo_home),
            "bazel_separate": str(bazel_cargo_home),
            "both_initially_empty": True,
            "fixture_network_permitted": False,
            "fixture_lock_copying_permitted": False,
            "root_locked_metadata_seeds_cache": True,
        },
    )
    control_receipt = check_lock_contract_controls(
        scope, spec, work, tools, environment
    )
    scope.run(
        "main-workspace-update-once",
        cargo + ["update", "--workspace", "--manifest-path", manifest],
        cwd,
        120,
        environment,
    )
    lock_after = parse_lock(work / "codex-rs/Cargo.lock")
    runtime.lock_targets(lock_after)
    main_relation = contract.lock_relation(baseline_lock, lock_after)
    put(scope.evidence / "main-cargo-lock-relation.json", main_relation)
    cargo_hash = raw_hash(work / "codex-rs/Cargo.lock")
    metadata_path, _ = scope.run(
        "main-locked-all-features-graph-once",
        cargo
        + [
            "metadata",
            "--manifest-path",
            manifest,
            "--locked",
            "--all-features",
            "--format-version",
            "1",
        ],
        cwd,
        240,
        environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash,
        "locked graph changed Cargo lock",
    )
    metadata = json_value(metadata_path.read_bytes())
    graph = graph_contract.normalize_graph(metadata, work, lock_after)
    require(
        graph["workspace_member_manifests"] == spec["workspace_member_manifests"],
        "accepted actual workspace membership changed",
    )
    resolved = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    for package in metadata["packages"]:
        if package["name"] in contract.SQLX_FAMILY:
            require(
                package["version"] == "0.9.1"
                and "chrono" not in resolved[package["id"]]["features"],
                "main SQLx graph still enables Chrono codecs",
            )
    graph.update(
        {
            "accepted_baseline_root_graph_sha256": spec["accepted_baseline"][
                "root_graph_sha256"
            ],
            "full_original_metadata_file": metadata_path.name,
            "requires_root_complete_graph_review": True,
            "default_or_runtime_features_claimed": False,
            "qualification": False,
        }
    )
    put(scope.evidence / "main-actual-graph.json", graph)
    roster = contract.consumer_targets(metadata)
    put(scope.evidence / "consumer-full-target-roster.json", roster)
    roster_sha = digest(contract.canonical(roster))
    # Bazel uses its own initially empty Cargo cache; it cannot seed an unobserved
    # registry version into the two offline fixture solves.
    bazel_environment = {**environment, "CARGO_HOME": str(bazel_cargo_home)}
    scope.run(
        "main-bazel-lock-update-once",
        [tools["just"]["path"], "bazel-lock-update"],
        work,
        120,
        bazel_environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash,
        "Bazel changed observed main Cargo lock",
    )
    module_hash = raw_hash(work / "MODULE.bazel.lock")
    bazel_relation = contract.bazel_relation(
        module_before, (work / "MODULE.bazel.lock").read_bytes()
    )
    put(scope.evidence / "main-bazel-lock-relation.json", bazel_relation)
    scope.run(
        "main-bazel-error-mode-once",
        [str(wrapper), "mod", "deps", "--lockfile_mode=error"],
        work,
        20,
        bazel_environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash
        and raw_hash(work / "MODULE.bazel.lock") == module_hash,
        "Bazel error-mode changed a main lock",
    )
    fixture_results = {}
    for label, relative, fixture_name, compatibility in contract.FIXTURES:
        fixture = work / relative
        fixture_lock = fixture / "Cargo.lock"
        require(
            not fixture_lock.exists() and not fixture_lock.is_symlink(),
            "fixture lock already exists",
        )
        fixture_environment = {
            **environment,
            "CARGO_NET_OFFLINE": "true",
            "CARGO_TARGET_DIR": str(scope.stage / ("cargo-target-" + label)),
        }
        fixture_manifest = str(fixture / "Cargo.toml")
        scope.run(
            label + "-lock-generate-offline-once",
            cargo
            + ["generate-lockfile", "--manifest-path", fixture_manifest, "--offline"],
            cwd,
            60,
            fixture_environment,
        )
        observed_lock = parse_lock(fixture_lock)
        relation = contract.lock_relation(baseline_lock, observed_lock, fixture_name)
        put(scope.evidence / (label + "-lock-relation.json"), relation)
        fixture_hash = raw_hash(fixture_lock)
        fixture_metadata_path, _ = scope.run(
            label + "-locked-filtered-graph-offline-once",
            cargo
            + [
                "metadata",
                "--manifest-path",
                fixture_manifest,
                "--locked",
                "--offline",
                "--filter-platform",
                TARGET,
                "--format-version",
                "1",
            ],
            cwd,
            90,
            fixture_environment,
        )
        require(
            raw_hash(fixture_lock) == fixture_hash,
            "fixture locked metadata changed its lock",
        )
        normalized, observation = contract.fixture_observation(
            json_value(fixture_metadata_path.read_bytes()),
            observed_lock,
            fixture_name,
            compatibility,
        )
        normalized_receipt = put(
            scope.evidence / (label + "-normalized-graph.json"), normalized
        )
        observation.update(
            {
                "lock": fixture_hash,
                "full_original_metadata_file": fixture_metadata_path.name,
                "normalized_graph_file": normalized_receipt,
                "target": TARGET,
                "generation_attempts": 1,
                "locked_metadata_attempts": 1,
                "network_access_by_fixture_cargo": False,
            }
        )
        put(scope.evidence / (label + "-graph-observation.json"), observation)
        fixture_results[label] = observation
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash
        and raw_hash(work / "MODULE.bazel.lock") == module_hash,
        "isolated fixture generation changed a main lock",
    )
    require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"]
        and (work / ".git/shallow").read_bytes() == routing["shallow"]
        and (work / ".git/objects/info/alternates").read_bytes()
        == routing["alternates"]
        and (work / ".git/config").read_bytes() == routing["config"]
        and not scope.read_git(work, "diff", "--cached", "--name-only")
        and all(
            row.startswith(b"H ")
            for row in scope.read_git(work, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "generator changed source identity, Git routing, index or index flags",
    )
    for tool in tools.values():
        require(
            tool_file(Path(tool["path"])) == tool, "generator changed a prepared tool"
        )
    require(wrapper.read_text() == wrapper_text, "scoped Bazel wrapper changed")
    after = runtime.source_snapshot(scope, work, identity["tree"])
    changed = [path for path in before if before[path] != after[path]]
    require(set(changed) <= MAIN_LOCKS, "generation changed tracked non-lock source")
    outputs = check_untracked_outputs(scope, work)
    put(scope.evidence / "owned-untracked-output-readback.json", outputs)
    put(scope.evidence / "copy-after.json", after)
    retained_candidates = retain_lock_set(
        scope, work, scope.evidence / "candidate-locks", LOCKS
    )
    scope.run(
        "main-lock-complete-binary-diff",
        [
            tools["git"]["path"],
            "-C",
            str(work),
            "diff",
            "--binary",
            "--",
            *sorted(MAIN_LOCKS),
        ],
        work,
        10,
    )
    return {
        "status": "GENERATED_FOUR_LOCK_CANDIDATE_REQUIRES_ROOT_REVIEW",
        "source": identity,
        "original_locks": retained_originals,
        "lock_postimages": retained_candidates,
        "fixture_graphs": fixture_results,
        "consumer_full_target_roster_sha256": roster_sha,
        "changed_tracked_paths": sorted(changed),
        "new_fixture_lock_paths": sorted(FIXTURE_LOCKS),
        "synthetic_lock_contract_control_count": len(control_receipt["names"]),
        "synthetic_controls_executions": control_receipt["execution_count"],
        "synthetic_controls_are_not_native_12_plus_3": True,
        "original_generation_attempts": 1,
        "main_workspace_update_attempts": 1,
        "fixture_generate_attempts": {label: 1 for label in fixture_results},
        "main_bazel_update_attempts": 1,
        "retry_attempts": 0,
        "main_all_feature_graph": graph,
        "accepted_fixture_graphs": None,
        "root_lock_acceptance": None,
        "unapproved_registry_version_or_checksum_drift": False,
        "bazel_crate_fact_requires_independent_root_review": True,
        "native_12_plus_3_execution_count": 0,
        "native_compatibility_qualification": False,
        "advisory_qualification": False,
        "adoption_or_use_evidence": False,
        "production_activation": False,
        "old_E1_E6_budget_used": 0,
        "generation_diagnostics_and_failed_attempts_included_in_elapsed_cost": True,
        "original_upload_step_duration_requires_root_readback": True,
        "complete_adopted_update_cost_accepted": False,
    }


def retain_failed_locks(scope, work, record):
    # Use the original absolute cutoff, including its existing receipt reserve.
    # A caught one-shot SIGALRM must not leave this collection unarmed.
    cutoff = scope.deadline - 1.5

    def remaining():
        left = cutoff - time.monotonic()
        if left <= 0:
            raise TimeoutError("failed-lock retention has no original scope allowance")
        return left

    signal.setitimer(signal.ITIMER_REAL, remaining())
    partial = scope.evidence / "failed-partial-locks"
    partial.mkdir(exist_ok=False)
    available = (
        EVIDENCE_ACCEPTANCE_CAP_BYTES - scope.storage_observation()["evidence_bytes"]
    )
    require(available >= 0, "failed-lock evidence acceptance allowance is exhausted")
    record.update(
        cutoff_monotonic_seconds=cutoff,
        chunk_bytes=64 * 1024,
        available_bytes_at_start=available,
    )
    for path in sorted(LOCKS):
        remaining()
        candidate = work / path
        try:
            source_fd = os.open(
                candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            )
        except FileNotFoundError:
            record["files"].append({"path": path, "status": "ABSENT"})
            continue
        try:
            before = os.fstat(source_fd)
            require(
                stat.S_ISREG(before.st_mode) and before.st_size <= available,
                "failed lock is not a regular file within retained evidence allowance: "
                + path,
            )
            copied, checksum = 0, hashlib.sha256()
            target = partial / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb", buffering=0) as output:
                while True:
                    remaining()
                    chunk = os.read(
                        source_fd, min(64 * 1024, before.st_size - copied + 1)
                    )
                    remaining()
                    if not chunk:
                        break
                    require(
                        copied + len(chunk) <= before.st_size,
                        "failed lock grew during retention: " + path,
                    )
                    offset = 0
                    while offset < len(chunk):
                        remaining()
                        written = output.write(memoryview(chunk)[offset:])
                        remaining()
                        require(
                            written is not None and written > 0,
                            "failed-lock write made no progress",
                        )
                        offset += written
                    copied += len(chunk)
                    checksum.update(chunk)
            after, current = os.fstat(source_fd), candidate.lstat()
            key = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            require(
                copied == before.st_size and key(before) == key(after) == key(current),
                "failed lock changed during retention: " + path,
            )
            remaining()
            available -= copied
            record["files"].append(
                {
                    "path": path,
                    "status": "RETAINED_FAILED_EVIDENCE",
                    "bytes": copied,
                    "sha256": checksum.hexdigest(),
                }
            )
        finally:
            os.close(source_fd)
    remaining()
    record["status"] = "COLLECTION_FINISHED"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare-start", "prepare-finish", "generate"))
    args = parser.parse_args()
    source = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    stage = Path(os.environ["LOCK_STAGE"]).resolve(strict=True)
    require(
        source not in stage.parents and stage not in source.parents and stage != source,
        "scope must live outside the original checkout",
    )
    require(
        os.name == "posix" and sys.platform == "linux",
        "Linux process ownership required",
    )
    job_start = json_value((stage / "evidence/job-start.json").read_bytes())
    spec = admitted_input(source)
    phase_start = time.monotonic()
    if args.mode == "prepare-finish":
        phase_start = json_value((stage / "evidence/tool-start.json").read_bytes())[
            "monotonic_seconds"
        ]
    phase_key = (
        "generation_seconds" if args.mode == "generate" else "tool_preparation_seconds"
    )
    cap = spec["budget"][phase_key]
    whole_deadline = (
        job_start["monotonic_seconds"] + spec["budget"]["whole_job_seconds"]
    )
    require(
        time.monotonic() < min(phase_start + cap, whole_deadline) - 2,
        "original allowance already expired",
    )
    # Importing this source only constructs its original helper definitions.
    # Its Chrono admission, generation and main functions are never invoked.
    runtime = load_module(
        source / RUNTIME_PATH, RUNTIME_SHA, "pinned_original_lock_scope_helpers"
    )
    scope = runtime.Scope(source, stage, args.mode, phase_start, cap)
    scope.deadline = min(scope.deadline, whole_deadline)
    state, result = (
        {},
        {
            "status": "FAIL",
            "mode": args.mode,
            "cap_seconds": cap,
            "budget": spec["budget"],
            "old_E1_E6_budget_used": 0,
            "effective_absolute_deadline": scope.deadline,
            "remote_writes": 0,
            "prior_generation_scopes_reopened": False,
            "error": None,
        },
    )

    def elapsed(signum, frame):
        raise TimeoutError("original SQLx engineering scope deadline reached")

    previous = signal.signal(signal.SIGALRM, elapsed)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.01, scope.deadline - time.monotonic() - 1.5)
    )
    try:
        if args.mode == "prepare-start":
            result.update(prepare_start(scope))
        elif args.mode == "prepare-finish":
            result.update(prepare_finish(scope))
        else:
            result.update(generate(scope, state, runtime))
    except Exception as error:
        result.update(status="FAIL", error=f"{type(error).__name__}: {error}")
    finally:
        if args.mode == "generate":
            try:
                if "before" in state:
                    after = runtime.source_snapshot(
                        scope, source, state["source"]["tree"]
                    )
                    put(scope.evidence / "source-after.json", after)
                    require(after == state["before"], "original checkout changed")
                    require(
                        scope.read_git(source, "rev-parse", "HEAD").decode().strip()
                        == state["source"]["head"]
                        and digest((source / ".git/shallow").read_bytes())
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
                        "original checkout identity, status or index flags changed",
                    )
                    result["original_checkout_unchanged"] = True
                else:
                    result["original_checkout_unchanged"] = None
            except Exception as error:
                result.update(
                    status="FAIL",
                    final_readback_error=f"{type(error).__name__}: {error}",
                )
            # This collection has its own rearmed alarm with the same absolute
            # original cutoff. A failed source check cannot suppress it.
            try:
                if "work" in state and result["status"] == "FAIL":
                    retention = {
                        "status": "INCOMPLETE",
                        "files": [],
                        "accepted_candidate": False,
                    }
                    result["failed_partial_lock_retention"] = retention
                    retain_failed_locks(scope, state["work"], retention)
            except Exception as error:
                result.update(
                    status="FAIL",
                    partial_lock_readback_error=f"{type(error).__name__}: {error}",
                )
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        result.update(scope.receipt())
        result["storage_final"] = scope.storage_observation()
        result["storage_limits"] = {
            "original_owner_stdout_cap_bytes": STDOUT_CAP_BYTES,
            "evidence_acceptance_cap_bytes": EVIDENCE_ACCEPTANCE_CAP_BYTES,
            "minimum_disk_headroom_bytes": MIN_FREE_BYTES,
            "stderr_has_real_time_byte_limit": False,
            "oversize_failed_originals_are_not_deleted_or_reclassified": True,
            "tool_generated_files_have_no_new_per_file_rlimit": True,
        }
        if (
            result["storage_final"]["evidence_bytes"] > EVIDENCE_ACCEPTANCE_CAP_BYTES
            or result["storage_final"]["free_bytes"] < MIN_FREE_BYTES
        ):
            result.update(status="FAIL", storage_acceptance_failed=True)
        result["whole_job_elapsed_seconds_so_far"] = (
            time.monotonic() - job_start["monotonic_seconds"]
        )
        if result["elapsed_seconds"] > cap or time.monotonic() > whole_deadline:
            result.update(status="FAIL", original_budget_exceeded=True)
        result["full_job_or_tool_preparation_cpu_is_not_zero_if_unavailable"] = True
        result["full_job_cpu_seconds"] = None
        result["final_artifact_transfer_elapsed_seconds"] = None
        result["final_artifact_transfer_reason"] = (
            "Read original upload step and complete job duration before Root cost acceptance"
        )
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
        directory = Path(os.environ["LOCK_STAGE"]) / "evidence"
        failure = {
            "status": "FAIL_BOOTSTRAP",
            "error": f"{type(error).__name__}: {error}",
            "automatic_retry": False,
            "resolver_candidate_qualified": False,
            "old_E1_E6_budget_used": 0,
        }
        put(directory / (sys.argv[1] + ".BOOTSTRAP_FAILURE.json"), failure)
        print(json.dumps(failure))
        raise SystemExit(1)
