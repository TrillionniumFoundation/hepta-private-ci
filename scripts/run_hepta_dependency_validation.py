#!/usr/bin/env python3
"""Isolated dependency generation and regression evidence, never qualification."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import time
import tomllib

from capture_cargo_deny_diagnostic import capture, identity
from run_hepta_field_maintenance import (
    ARCHIVE_CAP,
    FILE_CAP,
    FILE_COUNT,
    MIB,
    RAW_CAP,
    inventory,
    package,
    safe_name,
    unique_pairs,
)
import hepta_dependency_validation as policy

LOG_CAP = 512 * 1024
JUNIT_CAP = MIB
METADATA_CAP = 8 * MIB
PAYLOAD_CAP = RAW_CAP - 8 * MIB
RECEIPT_CAP, MANIFEST_CAP = MIB, MIB
DELIVERY_CAP = ARCHIVE_CAP + 2 * RECEIPT_CAP + MANIFEST_CAP
UPLOAD_CAP = PAYLOAD_CAP + DELIVERY_CAP
RUN_SECONDS = 45 * 60
INPUTS = (
    *policy.RUNNER_FILES,
    *policy.LOCKS,
    policy.REGRESSION_PATH,
    "codex-rs/Cargo.toml",
    "codex-rs/core-plugins/src/startup_sync.rs",
    "codex-rs/.config/nextest.toml",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/deny.toml",
    "MODULE.bazel",
    "justfile",
    "scripts/run-nextest.py",
    "scripts/just-shell.py",
    "scripts/check-module-bazel-lock.sh",
    ".github/actions/setup-ci/action.yml",
    ".github/actions/prepare-bazel-ci/action.yml",
    ".github/actions/setup-bazel-ci/action.yml",
)


def delivery_usage(output):
    limits = {
        "receipt.json": RECEIPT_CAP,
        "receipt.json.tmp": RECEIPT_CAP,
        "MANIFEST.json": MANIFEST_CAP,
        "maintenance.tar.gz": ARCHIVE_CAP,
    }
    sizes = {}
    for path in output.iterdir():
        if path.name not in limits or path.is_symlink() or not path.is_file():
            raise ValueError("unexpected delivery member")
        sizes[path.name] = path.stat().st_size
        if sizes[path.name] > limits[path.name]:
            raise ValueError("delivery member exceeds its registered byte bound")
    if sum(sizes.values()) > DELIVERY_CAP:
        raise ValueError("combined delivery bytes exceed their bound")
    return sizes


def checkpoint(output, rec, phase, status="in_progress"):
    raw, overflow = policy.receipt_bytes(
        rec, phase, status, datetime.now(timezone.utc).isoformat(), RECEIPT_CAP
    )
    sizes = delivery_usage(output)
    if (
        sum(v for k, v in sizes.items() if k != "receipt.json.tmp") + len(raw)
        > DELIVERY_CAP
    ):
        raise ValueError("atomic receipt write would exceed the delivery budget")
    temporary = output / "receipt.json.tmp"
    try:
        with temporary.open("wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output / "receipt.json")
    finally:
        temporary.unlink(missing_ok=True)
    delivery_usage(output)
    if overflow:
        raise ValueError(
            "receipt overflow was preserved as a compact failure; stop execution"
        )


def reserve(out, additional):
    used = sum(item["bytes"] for item in inventory(out / "payload").values())
    if used + additional > PAYLOAD_CAP:
        raise ValueError("remaining bounded payload capacity is insufficient")


def put_json(out, name, value):
    safe_name(name)
    raw = (json.dumps(value, indent=2) + "\n").encode()
    if len(raw) > FILE_CAP:
        raise ValueError("JSON evidence exceeds its file bound")
    reserve(out, len(raw))
    with (out / "payload" / name).open("xb") as target:
        target.write(raw)


def bounded_read(path, maximum):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"missing, nonregular or oversized evidence: {path.name}")
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("evidence grew beyond its declared bound")
    return raw


def invoke(rec, out, root, label, argv, *, timeout=120, limit=LOG_CAP, check=True):
    if any(attempt["label"] == label for attempt in rec["commands"]):
        raise ValueError(f"command label already recorded: {label}")
    reserve(out, 2 * limit)
    remaining = rec.get("run_deadline_unix", time.time() + timeout) - time.time()
    if remaining <= 0:
        raise TimeoutError("registered execution time budget exhausted")
    attempt = {"label": label, "command": argv, "state": "started"}
    rec["commands"].append(attempt)
    checkpoint(out / "delivery", rec, label + "_started")
    try:
        result = capture(
            argv,
            root,
            out / "payload",
            label,
            timeout=min(timeout, remaining),
            limit=limit,
        )
        attempt.update(result)
        attempt["state"] = "returned"
    except Exception as error:
        attempt["capture_error"] = f"{type(error).__name__}: {error}"[:4096]
        raise
    finally:
        checkpoint(out / "delivery", rec, label + "_finished")
    if check and (result["exit_code"] != 0 or result["timed_out"]):
        raise RuntimeError(
            f"{label} failed: exit={result['exit_code']} timeout={result['timed_out']}"
        )
    return result


def stdout(out, label, result):
    if not result["streams"]["stdout"]["complete"]:
        raise ValueError(f"complete stdout evidence is unavailable for {label}")
    return b"".join(
        (out / "payload" / f"{label}.stdout{part}.log").read_bytes()
        for part in ("", ".tail")
    )


def git(rec, out, root, label, *args):
    result = invoke(rec, out, root, label, ["git", *args], limit=65536)
    return stdout(out, label, result).decode("utf-8")


def phase_environment(mode):
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != policy.BRANCH
    ):
        raise ValueError("only the dedicated dependency-validation push is accepted")
    workflow_sha, baseline = (
        os.environ.get("GITHUB_SHA", ""),
        os.environ.get("BASELINE_SHA", ""),
    )
    if any(
        not re.fullmatch(r"[0-9a-f]{40}", value) for value in (workflow_sha, baseline)
    ):
        raise ValueError(
            "workflow and baseline must be fixed full Git commit identities"
        )
    return {
        "workflow_head": workflow_sha,
        "baseline_head": baseline,
        "source_head": baseline if mode == "baseline" else workflow_sha,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }


def snapshot_locks(root, out, name):
    data = {
        Path(path).name: bounded_read(root / path, FILE_CAP) for path in policy.LOCKS
    }
    reserve(out, sum(map(len, data.values())))
    destination = out / "payload" / name
    destination.mkdir(exist_ok=False)
    for filename, raw in data.items():
        with (destination / filename).open("xb") as target:
            target.write(raw)
    return inventory(destination)


def source_state(rec, out, root, label):
    actual = git(
        rec, out, root, label + "_identity", "rev-parse", "HEAD", "HEAD^{tree}"
    ).splitlines()
    if actual != [rec["source_head"], rec["source_tree"]]:
        raise ValueError("source HEAD or tree changed across phases")
    changed = git(rec, out, root, label + "_diff", "diff", "--name-only", "-z", "HEAD")
    untracked = git(
        rec,
        out,
        root,
        label + "_untracked",
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    paths = sorted(set(filter(None, (changed + untracked).split("\0"))))
    for name in paths:
        safe_name(name)
    for name, value in rec["source_inputs"].items():
        if name not in policy.LOCKS and identity(root / name) != value:
            raise ValueError(f"bound source input changed: {name}")
    policy.changed_scope(paths, rec["mode"])
    return paths


def initialize(root, out, mode):
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    if runner_temp not in out.parents or out == root or root in out.parents:
        raise ValueError("output must be a fresh external RUNNER_TEMP subdirectory")
    out.mkdir(exist_ok=False)
    (out / "payload").mkdir()
    (out / "delivery").mkdir()
    rec = {
        "schema_version": 1,
        "mode": mode,
        "source_head": "unverified",
        "qualification": False,
        "validation_passed": False,
        "dependency_graph_approved": False,
        "graph_review_required": True,
        "commands": [],
        "tests": [],
        "errors": [],
        "claim_scope": "Source commit plus identified effective lock bytes; generated locks are not claimed committed.",
        "platform_scope": "Linux x86_64 engineering validation only; no Windows-native or scientific qualification.",
        "bounds": {
            "file_bytes": FILE_CAP,
            "payload_bytes": PAYLOAD_CAP,
            "tar_bytes": RAW_CAP,
            "archive_bytes": ARCHIVE_CAP,
            "receipt_bytes": RECEIPT_CAP,
            "manifest_bytes": MANIFEST_CAP,
            "delivery_bytes_including_atomic_receipt_temporary": DELIVERY_CAP,
            "uploaded_output_bytes": UPLOAD_CAP,
            "file_count": FILE_COUNT,
            "junit_bytes": JUNIT_CAP,
            "test_log_bytes_per_stream": LOG_CAP,
            "run_seconds": RUN_SECONDS,
        },
        "remaining_gates": [
            "Independent review of every actual dependency delta",
            "Unchanged canonical cargo-deny and native/Bazel/cross-platform CI",
            "Additional YAML data-contract cases identified by the separate migration review",
        ],
    }
    checkpoint(out / "delivery", rec, "initializing")
    try:
        rec.update(phase_environment(mode))
        actual = git(
            rec,
            out,
            root,
            "initial_head_identity",
            "rev-parse",
            "HEAD",
            "HEAD^{tree}",
        ).splitlines()
        if len(actual) != 2 or actual[0] != rec["source_head"]:
            raise ValueError("checkout does not match the fixed identity for this arm")
        rec["source_tree"] = actual[1]
        paths = list(INPUTS)
        workflow = ".github/workflows/hepta-field-dependency-validation.yml"
        if (root / workflow).is_file():
            paths.append(workflow)
        rec["source_inputs"] = {name: identity(root / name) for name in paths}
        rec["runner_inputs"] = {
            name: rec["source_inputs"][name] for name in policy.RUNNER_FILES
        }
        rec["regression"] = policy.regression_contract(
            bounded_read(root / policy.REGRESSION_PATH, 65536),
            os.environ.get("REGRESSION_SHA256", ""),
        )
        rec["nextest_store"] = {
            "junit_path": policy.junit_relative_path(
                tomllib.loads((root / "codex-rs/.config/nextest.toml").read_text()),
                (root / "justfile").read_text(),
            ),
            "upstream": policy.NEXTEST_STORE_SOURCE,
            "config_overrides": "Fixed command supplies no --config-file or --tool-config-file; just selects local.",
        }
        rec["dependencies"] = policy.manifest_contract(
            tomllib.loads((root / "codex-rs/Cargo.toml").read_text()),
            (root / "codex-rs/core-plugins/src/startup_sync.rs").read_text(),
            mode,
        )
        if source_state(rec, out, root, "initial"):
            raise ValueError("input checkout must be clean, including lockfiles")
        rec["locks_before"] = snapshot_locks(root, out, "before")
        rec["ready"] = True
        put_json(
            out,
            "INPUTS.json",
            {
                "source_head": rec["source_head"],
                "source_tree": rec["source_tree"],
                "source_inputs": rec["source_inputs"],
                "regression": rec["regression"],
            },
        )
    except Exception as error:
        rec["errors"].append(f"initialize: {type(error).__name__}: {error}"[:4096])
        checkpoint(out / "delivery", rec, "initialize_failed", "failed")
        raise
    checkpoint(out / "delivery", rec, "ready")


def collect_junit(out, path, label):
    raw = bounded_read(path, JUNIT_CAP)
    reserve(out, len(raw))
    destination = out / "payload" / f"{label}.junit.xml"
    with destination.open("xb") as target:
        target.write(raw)
    return raw, {
        "path": destination.name,
        **identity(destination),
        "mtime_ns": path.stat().st_mtime_ns,
    }


def test_group(rec, out, root, spec):
    relative = policy.junit_relative_path(
        tomllib.loads((root / "codex-rs/.config/nextest.toml").read_text()),
        (root / "justfile").read_text(),
    )
    junit = root / relative
    report = {
        "label": spec["label"],
        "package": spec["package"],
        "passed": False,
        "filters": spec["filters"],
        "junit": None,
        "command_returned": False,
        "workspace_junit_path": relative,
    }
    rec["tests"].append(report)
    try:
        if junit.exists() or junit.is_symlink():
            bounded_read(junit, JUNIT_CAP)
            report["stale_junit_removed"] = identity(junit)
            junit.unlink()
        report["junit_absent_before"] = not junit.exists()
        report["started_unix_ns"] = time.time_ns()
        result = invoke(
            rec,
            out,
            root,
            spec["label"],
            policy.test_command(spec),
            timeout=25 * 60,
            check=False,
        )
        report["command_returned"] = True
        raw, report["junit"] = collect_junit(out, junit, spec["label"])
        report.update(
            policy.junit_result(
                raw, result, spec, rec["regression"], baseline=rec["mode"] == "baseline"
            )
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"[:4096]
        if junit.is_file() and not junit.is_symlink():
            report["uncollected_junit"] = {
                "bytes": junit.stat().st_size,
                "reason": "not accepted as complete bounded JUnit evidence",
            }
    finally:
        report["finished_unix_ns"] = time.time_ns()
        checkpoint(out / "delivery", rec, spec["label"] + "_classified")


def execute(root, out, rec):
    if not rec.get("ready"):
        raise ValueError("initialization did not complete")
    rec["run_deadline_unix"] = time.time() + RUN_SECONDS
    if source_state(rec, out, root, "run_start"):
        raise ValueError("source or locks changed between initialize and execution")
    rec["runtime"] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "environment": {
            key: os.environ.get(key)
            for key in (
                "CARGO_BUILD_JOBS",
                "CARGO_INCREMENTAL",
                "CARGO_PROFILE_DEV_DEBUG",
                "CARGO_PROFILE_TEST_DEBUG",
                "CARGO_TARGET_DIR",
                "CARGO_NET_GIT_FETCH_WITH_CLI",
            )
        },
    }
    for tool in ("rustc", "cargo", "just"):
        invoke(rec, out, root, tool + "_version", [tool, "--version"], limit=65536)
    result = invoke(
        rec,
        out,
        root,
        "nextest_version",
        ["cargo", "nextest", "--version"],
        limit=65536,
    )
    if not re.search(
        rb"\bcargo-nextest 0\.9\.103\b", stdout(out, "nextest_version", result)
    ):
        raise ValueError("nextest is not the pinned 0.9.103 runner")
    invoke(
        rec,
        out,
        root,
        "native_packages",
        [
            "dpkg-query",
            "-W",
            "build-essential",
            "pkg-config",
            "libcap-dev",
            "bubblewrap",
        ],
        limit=65536,
    )
    before = tomllib.loads((out / "payload/before/Cargo.lock").read_text())
    if rec["mode"] == "candidate":
        invoke(rec, out, root, "bazel_version", ["bazel", "--version"], limit=65536)
        for name, wanted in (
            ("zip", "9.1.2"),
            ("zstd", "0.14.3"),
            ("serde_norway", "0.9.42"),
        ):
            current = tomllib.loads((root / policy.LOCKS[0]).read_text())["package"]
            if len([p for p in current if p["name"] == name]) != 1:
                raise ValueError(
                    f"current {name} package selector is absent or ambiguous"
                )
            invoke(
                rec,
                out,
                root / "codex-rs",
                "update_" + name,
                ["cargo", "update", "-p", name, "--precise", wanted],
                timeout=15 * 60,
            )
        delta = policy.lock_delta(
            before, tomllib.loads((root / policy.LOCKS[0]).read_text())
        )
        put_json(out, "PACKAGE_DELTA.json", delta)
        invoke(
            rec,
            out,
            root,
            "bazel_lock_update",
            ["just", "bazel-lock-update"],
            timeout=20 * 60,
        )
        invoke(
            rec,
            out,
            root,
            "bazel_lock_check",
            ["just", "bazel-lock-check"],
            timeout=20 * 60,
        )
        result = invoke(
            rec,
            out,
            root / "codex-rs",
            "cargo_metadata",
            ["cargo", "metadata", "--locked", "--format-version=1"],
            timeout=15 * 60,
            limit=METADATA_CAP,
        )
        metadata = json.loads(
            stdout(out, "cargo_metadata", result), object_pairs_hook=unique_pairs
        )
        if not metadata.get("resolve", {}).get("nodes") or not metadata.get("packages"):
            raise ValueError("actual Cargo resolve graph is missing")
        put_json(out, "CARGO_METADATA.json", metadata)
        for name, version in (
            ("zip", "9.1.2"),
            ("zstd", "0.14.3"),
            ("serde_norway", "0.9.42"),
        ):
            invoke(
                rec,
                out,
                root / "codex-rs",
                "features_" + name,
                [
                    "cargo",
                    "tree",
                    "--locked",
                    "-e",
                    "features",
                    "-i",
                    f"{name}@{version}",
                ],
                timeout=120,
            )
        rec["lock_generation_passed"] = True
    else:
        versions = {p["version"] for p in before["package"] if p["name"] == "zip"}
        if versions != {"2.4.2"}:
            raise ValueError("baseline does not actually resolve zip 2.4.2")
    rec["effective_locks"] = snapshot_locks(root, out, "effective-locks")
    source_state(rec, out, root, "before_tests")
    specs = policy.GROUPS[:1] if rec["mode"] == "baseline" else policy.GROUPS
    for spec in specs:
        test_group(rec, out, root, spec)
        if {Path(p).name: identity(root / p) for p in policy.LOCKS} != rec[
            "effective_locks"
        ]:
            raise ValueError("a test invocation changed its effective input lockfiles")
    rec["validation_passed"] = len(rec["tests"]) == len(specs) and all(
        t["passed"] for t in rec["tests"]
    )


def finalize(root, out, rec, outcome):
    rec.pop("run_deadline_unix", None)
    rec["workflow_execution_step_outcome"] = outcome
    try:
        if rec.get("receipt_overflow"):
            raise ValueError(
                "receipt metadata is incomplete; no further validation commands may run"
            )
        rec["final_locks"] = snapshot_locks(root, out, "final-locks")
        try:
            before = tomllib.loads((out / "payload/before/Cargo.lock").read_text())
            after = tomllib.loads((out / "payload/final-locks/Cargo.lock").read_text())
            put_json(
                out,
                "FINAL_PACKAGE_DELTA.json",
                policy.package_difference(before, after),
            )
        except Exception as error:
            rec["final_package_delta_error"] = f"{type(error).__name__}: {error}"[:4096]
        rec["changed_paths"] = source_state(rec, out, root, "final")
        rec["source_tree_matches_effective_files"] = not rec["changed_paths"]
        if rec.get("effective_locks") != rec["final_locks"]:
            raise ValueError("final lock bytes differ from identified test inputs")
        if outcome != "success" or not rec["validation_passed"]:
            raise ValueError(
                "execution did not finish with the required classified results"
            )
    except Exception as error:
        rec["validation_passed"] = False
        rec["errors"].append(f"finalize: {type(error).__name__}: {error}"[:4096])
    rec["qualification"] = False
    rec["dependency_graph_approved"] = False
    rec["provenance_scope"] = (
        "Post-execution checks, before packaging; delivery/receipt.json records the final packaging outcome."
    )
    put_json(out, "PROVENANCE.json", rec)
    try:
        # Match the frozen package() manifest format before it writes any bytes.
        manifest = {
            "source_head": rec["source_head"],
            "files": {
                "evidence/" + name: meta
                for name, meta in inventory(out / "payload").items()
            },
        }
        if len((json.dumps(manifest, indent=2) + "\n").encode()) > MANIFEST_CAP:
            raise ValueError("delivery manifest would exceed its metadata budget")
        package(out, rec, {"evidence": out / "payload"})
        rec["delivery_after_package_before_final_receipt"] = delivery_usage(
            out / "delivery"
        )
        total = sum(
            item["bytes"] for item in inventory(out / "payload").values()
        ) + sum(delivery_usage(out / "delivery").values())
        if total > UPLOAD_CAP:
            raise ValueError("complete uploaded output exceeds its registered budget")
    except Exception as error:
        rec["validation_passed"] = False
        rec["artifact_collection_error"] = f"{type(error).__name__}: {error}"[:4096]
        rec["raw_payload_retained_for_upload"] = True
    rec["finalized"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "candidate"), required=True)
    parser.add_argument(
        "--phase", choices=("initialize", "run", "finalize"), required=True
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--step-outcome", default="unknown")
    args = parser.parse_args()
    root, out = Path(__file__).resolve().parents[1], args.output_dir.resolve()
    if args.phase == "initialize":
        initialize(root, out, args.mode)
        return 0
    rec = json.loads(
        bounded_read(out / "delivery/receipt.json", RECEIPT_CAP),
        object_pairs_hook=unique_pairs,
    )
    try:
        rec["qualification"] = False
        if rec.get("mode") != args.mode or rec.get("finalized"):
            raise ValueError("invalid mode or already finalized evidence")
        expected = phase_environment(args.mode)
        if any(rec.get(key) != value for key, value in expected.items()):
            raise ValueError("source/workflow/run identity changed across phases")
        if args.phase == "run":
            execute(root, out, rec)
        else:
            finalize(root, out, rec, args.step_outcome)
        checkpoint(out / "delivery", rec, args.phase + "_finished", "completed")
    except Exception as error:
        rec["validation_passed"] = False
        rec["errors"].append(f"{args.phase}: {type(error).__name__}: {error}"[:4096])
        checkpoint(out / "delivery", rec, args.phase + "_failed", "failed")
    return 0 if rec["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
