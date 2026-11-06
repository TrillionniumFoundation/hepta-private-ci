#!/usr/bin/env python3
"""Run the existing from-zero full-limb false-trace mode on exact C4.

Only this component is executed. Its 3300-second local outer cap is fixed before
execution and equals the original shared 55-minute job ceiling, not a separate
per-mode budget. The original 30/900/300/5-second inner limits remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time

COMMIT = "8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE = "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
ROOT = Path("/home/qian-qi/work/chain-joint-20261105-93bfc-current")
BASE = Path("/home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4")
TARGET = Path("/home/qian-qi/work/chain-joint-20261105-93bfc-w1-target-C4")
OUTPUT = BASE / "false-trace-full-limb"
ORIGINAL_RECEIPT_BASE = OUTPUT / "original"
ORIGINAL_RECEIPT = ORIGINAL_RECEIPT_BASE / "w1-full-limb-reuse-v1"



def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if not sys.dont_write_bytecode or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise SystemExit("-B and PYTHONDONTWRITEBYTECODE=1 required")
    if ROOT.resolve() != ROOT or not ROOT.is_dir():
        raise SystemExit("complete canonical source required")
    if OUTPUT.resolve().is_relative_to(ROOT) or TARGET.resolve().is_relative_to(ROOT):
        raise SystemExit("receipts and Cargo target must remain outside source")
    for phase in ("prepare", "checks", "collector"):
        prior = json.loads((BASE / phase / "manifest.json").read_text())
        if (prior.get("commit"), prior.get("tree"), prior.get("passed")) != (COMMIT, TREE, True):
            raise SystemExit("successful exact-C4 " + phase + " receipt required")
    for prior_cost in ("legal-v3", "reused-v3"):
        primary = json.loads((BASE / prior_cost / "manifest.json").read_text())
        if (primary.get("commit"), primary.get("tree")) != (COMMIT, TREE) or not primary.get("completed_utc"):
            raise SystemExit("previous exact-C4 " + prior_cost + " phase must already be terminal")
        if primary.get("source_before") is None or primary.get("source_before") != primary.get("source_after"):
            raise SystemExit("previous source identity must remain complete and unchanged")
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    sys.path.insert(0, str(ROOT / "formal/pon-nakamoto-v1"))
    from bounded_process import ProcessFailure, run_bounded

    env = dict(os.environ)
    env.update(CARGO_BUILD_JOBS="2", RUST_TEST_THREADS="1", CARGO_TERM_COLOR="never",
               PYTHONDONTWRITEBYTECODE="1", CARGO_TARGET_DIR=str(TARGET),
               TRNM_EXPECTED_SOURCE_SHA=COMMIT,
               TRNM_CI_RECEIPT_DIR=str(ORIGINAL_RECEIPT_BASE))
    env.pop("CARGO_INCREMENTAL", None)
    started = time.monotonic()
    deadline = started + 3300
    report = dict(schema="trnm-c4-original-full-limb-false-trace-component-v1",
        commit=COMMIT, tree=TREE, coordinator_sha256=digest(Path(__file__).read_bytes()),
        started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        root=str(ROOT), output=str(OUTPUT), target=str(TARGET),
        original_entry="scripts/ci/run_w1_false_trace_reuse_v1.py --full-limb",
        original_workflow=".github/workflows/pon-w1-work-security.yml",
        original_job="false-trace-reuse", original_shared_job_timeout_seconds=3300,
        local_component_outer_cap_seconds=3300,
        outer_cap_scope="single-mode local component; original 55-minute job also contains default mode and tests/lints",
        original_identity_timeout_seconds=30,
        original_build_timeout_seconds=900, original_native_campaign_timeout_seconds=300,
        original_native_termination_grace_seconds=5,
        runtime_process=dict(pid=os.getpid(), parent_pid=os.getppid(),
            cgroup=Path("/proc/self/cgroup").read_text(),
            start_ticks=Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
        execution_context="local-native-preflight", observations=[], failures=[],
        source_before=None, source_after=None, cargo_configuration_before=None,
        cargo_configuration_after=None, passed=False,
        original_hosted_lane_qualified=False, public_service_measured=False,
        fastest_adversary_qualified=False, work_hardness_accepted=False,
        production_activation=False)

    def save():
        temporary = OUTPUT / "manifest.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        temporary.replace(OUTPUT / "manifest.json")

    def execute(name, command, cap, *, required=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("fixed local component window exhausted")
        timeout = min(float(cap), remaining)
        row = dict(name=name, command=command, command_cap_seconds=cap,
                   effective_timeout_seconds=timeout, exit_code=None,
                   timed_out=False, passed=False)
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        tick = time.monotonic_ns()
        out = err = b""
        try:
            value = run_bounded(command, b"", timeout=timeout, stdout_limit=8*1024*1024,
                                stderr_limit=8*1024*1024, cwd=ROOT, env=env)
            out, err = value.stdout, value.stderr
            row.update(exit_code=value.returncode, passed=value.returncode == 0)
        except ProcessFailure as error:
            out, err = error.stdout, error.stderr
            row.update(exit_code=error.returncode, exchange_error=str(error),
                       timed_out=str(error) == "NATIVE_EXECUTOR_TIMEOUT",
                       stdout_truncated=error.stdout_truncated, stderr_truncated=error.stderr_truncated)
        except (OSError, ValueError) as error:
            row["launch_error"] = str(error)
        row["elapsed_ns"] = time.monotonic_ns() - tick
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row["child_rusage"] = dict(
            scope="waited children; maxrss is cumulative, not a per-command RSS limit",
            user_cpu_seconds_delta=usage_after.ru_utime-usage_before.ru_utime,
            system_cpu_seconds_delta=usage_after.ru_stime-usage_before.ru_stime,
            cumulative_maxrss_kib_before=usage_before.ru_maxrss,
            cumulative_maxrss_kib_after=usage_after.ru_maxrss)
        for channel, raw in (("stdout", out), ("stderr", err)):
            name_on_disk = name + "." + channel
            with (OUTPUT / name_on_disk).open("xb") as stream:
                stream.write(raw)
            row[channel] = dict(path=name_on_disk, bytes=len(raw), sha256=digest(raw))
        report["observations"].append(row)
        if not row["passed"]:
            report["failures"].append(name)
        save()
        print(json.dumps({key: row[key] for key in (
            "name", "exit_code", "timed_out", "passed", "elapsed_ns")}), flush=True)
        if required and not row["passed"]:
            raise ValueError(name + " failed; original raw retained")
        return row

    def source(name):
        execute(name, ["python3", "-B", "scripts/ci/verify_ci_source.py", "--kind", "head",
            "--expected-head", COMMIT, "--output", str(OUTPUT / (name + ".json"))], 600, required=True)
        value = json.loads((OUTPUT / (name + ".json")).read_text())
        if (value.get("tested_commit"), value.get("tested_tree")) != (COMMIT, TREE):
            raise ValueError("exact source commit/tree mismatch")
        return value

    save()
    try:
        execute("candidate-preflight", ["bash", "scripts/project-preflight.sh", "--audit"], 120, required=True)
        report["source_before"] = source("source-before")
        sys.path.insert(0, str(ROOT / "scripts/ci"))
        from run_cross_arch_cost import (build_environment_overrides,
                                        cargo_configuration_snapshot,
                                        require_cargo_configuration)
        report["build_environment_overrides"] = build_environment_overrides(env)
        if report["build_environment_overrides"]:
            raise ValueError("original release compiler/target contract forbids overrides")
        report["cargo_configuration_before"] = cargo_configuration_snapshot(ROOT, env)
        require_cargo_configuration(report["cargo_configuration_before"])
        save()
        execute("original-full-limb-false-trace", ["env", "-u", "CARGO_INCREMENTAL", "python3", "-B",
            "scripts/ci/run_w1_false_trace_reuse_v1.py", "--arch", "x64", "--local", "--full-limb"], 3300)
        if (ORIGINAL_RECEIPT / "manifest.json").is_file():
            raw = (ORIGINAL_RECEIPT / "manifest.json").read_bytes()
            original = json.loads(raw)
            report["original_receipt"] = dict(path=str(ORIGINAL_RECEIPT), manifest_sha256=digest(raw),
                result=original.get("result"), error=original.get("error"),
                reader_record_counts=original.get("reader", {}).get("record_counts"),
                reader_schema=original.get("reader", {}).get("schema"),
                source_before=original.get("source_before"), source_after=original.get("source_after"),
                binary_sha256_before=original.get("binary_sha256_before"),
                binary_sha256_after=original.get("binary_sha256_after"))
            if original.get("result") != "PASS":
                report["failures"].append("original full-limb false-trace receipt failed")
            if original.get("expected_source_commit") != COMMIT:
                report["failures"].append("original full-limb explicit expected-source pin mismatch")
            if (original.get("source_before", {}).get("commit"), original.get("source_before", {}).get("tree")) != (COMMIT, TREE):
                report["failures"].append("original full-limb false-trace source mismatch")
            if original.get("source_before") != original.get("source_after"):
                report["failures"].append("original full-limb false-trace source changed")
            retained = ORIGINAL_RECEIPT / "pon_w1_false_trace_reuse_v1"
            if retained.is_file():
                retained_raw = retained.read_bytes()
                report["retained_binary_sha256"] = digest(retained_raw)
                if (retained_raw[:4] != b"\x7fELF" or report["retained_binary_sha256"] != original.get("binary_sha256_before")
                        or report["retained_binary_sha256"] != original.get("binary_sha256_after")):
                    report["failures"].append("retained original ELF binding mismatch")
            else:
                report["failures"].append("retained original ELF absent")
        else:
            report["failures"].append("original full-limb false-trace receipt absent")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["failures"].append(str(error))
    finally:
        if report["cargo_configuration_before"] is not None:
            try:
                report["cargo_configuration_after"] = cargo_configuration_snapshot(ROOT, env)
                require_cargo_configuration(report["cargo_configuration_after"])
                if report["cargo_configuration_after"] != report["cargo_configuration_before"]:
                    report["failures"].append("Cargo configuration changed during false-trace full-limb phase")
            except (OSError, ValueError) as error:
                report["failures"].append("Cargo configuration after: " + str(error))
        if report["source_before"] is not None:
            try:
                report["source_after"] = source("source-after")
                if report["source_after"] != report["source_before"]:
                    report["failures"].append("source changed during false-trace full-limb phase")
            except (OSError, ValueError, KeyError, TypeError) as error:
                report["failures"].append("source-after: " + str(error))
        report["elapsed_seconds"] = time.monotonic() - started
        report["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["passed"] = not report["failures"] and report["source_before"] is not None and (
            report["source_before"] == report["source_after"])
        save()
        print(json.dumps(dict(passed=report["passed"], failures=report["failures"],
            manifest=str(OUTPUT / "manifest.json"))), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
