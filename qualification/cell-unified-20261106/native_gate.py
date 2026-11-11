#!/usr/bin/env python3
"""Qualify one clean commit without hiding failures or mutating the source."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


PACKAGES = (
    "codex-hepta-neuron",
    "codex-hepta-plasticity",
    "codex-hepta-agentd",
    "codex-hepta-infer-core",
    "codex-hepta-infer-worker-host",
)


def identity(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source):
        raise ValueError("Evidence must not mutate the checkout under qualification")
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ)
    environment["HEPTA_JOINT_TRAINED_EVIDENCE_DIR"] = str(output / "trained-agentd")
    stages = []

    def git(*values):
        return subprocess.check_output(["git", *values], cwd=source, text=True).strip()

    def source_identity():
        return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                "status": git("status", "--porcelain=v1", "--untracked-files=all")}

    before = source_identity()
    if before["commit"] != args.commit or before["status"]:
        raise ValueError("Expected one clean fixed source commit")
    run = {"schema": "hepta.cell-unified.native-gate.v1", "source_before": before,
           "started_at_utc": datetime.now(timezone.utc).isoformat(), "stages": stages,
           "packages": list(PACKAGES), "prepare_only": args.prepare_only,
           "environment": {key: environment.get(key) for key in (
               "CARGO_TARGET_DIR", "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG",
               "CARGO_INCREMENTAL", "CARGO_BUILD_JOBS", "RUSTUP_TOOLCHAIN")},
           "historical_preparation_cost_included": False,
           "energy_joules": None, "billed_usd": None, "network_bytes": None,
           "unknown_cost_is_zero": False, "qualification_complete": False}

    def stage(name, command):
        row = {"name": name, "command": command, "state": "running"}
        stages.append(row)
        save(output / "STATUS.json", run)
        print(json.dumps(row), flush=True)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        with (output / (name + ".stdout")).open("xb") as stdout:
            with (output / (name + ".stderr")).open("xb") as stderr:
                process = subprocess.run(command, cwd=source / "codex-rs", env=environment,
                                         stdout=stdout, stderr=stderr, check=False)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(exit_code=process.returncode, state="passed" if process.returncode == 0 else "failed",
                   wall_seconds=time.monotonic() - started,
                   cpu_user_seconds=after.ru_utime - usage.ru_utime,
                   cpu_system_seconds=after.ru_stime - usage.ru_stime,
                   largest_child_rss_bytes_cumulative=after.ru_maxrss * 1024,
                   disk_free_bytes=shutil.disk_usage(output).free,
                   stdout=identity(output / (name + ".stdout")),
                   stderr=identity(output / (name + ".stderr")))
        save(output / "STATUS.json", run)
        print(json.dumps(row), flush=True)
        return process.returncode

    packages = [value for package in PACKAGES for value in ("-p", package)]
    code = 1
    try:
        code = stage("strict-clippy", ["cargo", "clippy", "--locked", "--tests", *packages,
                                       "--", "-D", "warnings"])
        if code:
            return code
        code = stage("helpers", [sys.executable, str(source / "scripts/hepta_cell_test_helpers.py"),
                                  "--package", "codex-hepta-infer-worker-host",
                                  "--output-dir", str(output / "helpers")])
        if code:
            return code
        manifest = json.loads((output / "helpers/manifest.json").read_text())
        helper_env = json.loads((output / "helpers/env.json").read_text())
        if not manifest["complete"] or manifest["source_sha"] != args.commit:
            raise ValueError("Missing same-source compiler metadata")
        environment.update(helper_env)
        if args.prepare_only:
            return 0
        candidates = {source / "codex-rs/target/nextest/local/junit.xml"}
        if environment.get("CARGO_TARGET_DIR"):
            candidates.add(Path(environment["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml")
        for index, path in enumerate(sorted(candidates)):
            if path.exists():
                shutil.copy2(path, output / f"prior-junit-{index}.xml")
                path.unlink()
        test_started_ns = time.time_ns()
        code = stage("scoped-tests", ["just", "test", "--locked", *packages,
                                       "--retries", "0", "--test-threads", "4"])
        fresh = [p for p in candidates if p.is_file() and p.stat().st_mtime_ns >= test_started_ns]
        if len(fresh) != 1:
            raise ValueError("Expected exactly one fresh JUnit result")
        shutil.copy2(fresh[0], output / "junit.xml")
        root = ET.parse(fresh[0]).getroot()
        tests = list(root.iter("testcase"))
        failed = [{"suite": test.get("classname"), "name": test.get("name"),
                   "details": "\n".join((child.text or "") for child in test
                                         if child.tag in ("failure", "error"))}
                  for test in tests if test.find("failure") is not None or test.find("error") is not None]
        run["junit"] = {**identity(output / "junit.xml"), "testcases": len(tests),
                        "failed": failed, "skipped": sum(t.find("skipped") is not None for t in tests)}
        run["runner_summary_lines"] = [
            line for suffix in ("stdout", "stderr")
            for line in (output / ("scoped-tests." + suffix)).read_text().splitlines()
            if "Summary" in line or "Skipped" in line or "tests run:" in line]
        if not tests or failed:
            code = code or 1
        for binary, item in manifest["artifacts"].items():
            if identity(Path(item["executable"])) != {"sha256": item["sha256"], "bytes": item["bytes"]}:
                raise ValueError("Compiler artifact changed during tests: " + binary)
        run["qualification_complete"] = code == 0
        return code
    except BaseException as error:
        run["error"] = {"type": type(error).__name__, "message": str(error)}
        code = code or 1
        raise
    finally:
        run["source_after"] = source_identity()
        run["source_unchanged"] = before == run["source_after"]
        run["qualification_complete"] &= run["source_unchanged"]
        if not run["source_unchanged"]:
            code = code or 1
        run["exit_code"] = code
        run["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        run["measured_stage_cpu_seconds"] = sum(
            row.get("cpu_user_seconds", 0) + row.get("cpu_system_seconds", 0) for row in stages)
        run["measured_stage_wall_seconds"] = sum(row.get("wall_seconds", 0) for row in stages)
        save(output / "STATUS.json", run)
        print(json.dumps({"complete": run["qualification_complete"], "exit_code": code,
                          "output": str(output)}), flush=True)
        if not run["source_unchanged"]:
            raise RuntimeError("Source identity changed during qualification")


if __name__ == "__main__":
    raise SystemExit(main())
