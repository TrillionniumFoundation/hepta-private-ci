"""Sequential cold-process execution of two frozen real-sensor study plans.

This launcher uses only the standard library. Child wall time includes Python
and numerical imports, data preparation, all candidate work and artifact writes.
It is an accounting harness, not a model-selection or automatic retry policy.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, record):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_source(root, manifest):
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source manifest must use repository-relative paths")
        if digest(root / relative) != entry["sha256"]:
            raise RuntimeError("frozen source changed: " + str(relative))


def run(
    csv, output, manifest_path, stream_plan, adaptation_plan, *, child_timeout=1200
):
    entry_started = time.perf_counter()
    root = Path(__file__).resolve().parents[2]
    source = json.loads(Path(manifest_path).read_text())
    verify_source(root, source)
    plans = {
        "stream": json.loads(Path(stream_plan).read_text()),
        "adaptation": json.loads(Path(adaptation_plan).read_text()),
    }
    if not 1 <= child_timeout <= 7200:
        raise ValueError("bounded child timeout required")
    tasks = [
        {"study": study, "arm": arm, "seed": seed}
        for study, plan in plans.items()
        for seed in plan["seeds"]
        for arm in plan["arms"]
    ]
    random.Random(76129).shuffle(tasks)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    (out / "logs").mkdir()
    (out / "stream").mkdir()
    (out / "adaptation").mkdir()
    save(out / "SOURCE_MANIFEST.json", source)
    for name, plan in plans.items():
        save(out / (name.upper() + "_PLAN.json"), plan)
    record = {
        "schema": "hcsn-flow-cold-process-ledger-v1",
        "state": "running",
        "source_manifest_sha256": digest(manifest_path),
        "plans_sha256": {
            "stream": digest(stream_plan),
            "adaptation": digest(adaptation_plan),
        },
        "declared_order": tasks,
        "trials": [],
        "concurrent_children": 1,
        "schedule_seed": 76129,
        "child_hard_timeout_seconds": child_timeout,
        "clock_scope": "cold child process start through exit; launcher setup is reported separately",
        "no_automatic_retries": True,
        "executable": sys.executable,
    }
    started = time.perf_counter()
    record["launcher_setup_seconds"] = started - entry_started
    save(out / "LAUNCH.json", record)
    for index, task in enumerate(tasks):
        verify_source(root, source)
        name = f"{task['study']}-{task['arm']}-{task['seed']}"
        destination = out / task["study"] / f"{task['arm']}-{task['seed']}"
        module = "stream_benchmark" if task["study"] == "stream" else "adaptation_study"
        command = [
            sys.executable,
            "-m",
            "qualification.hcsn_scale." + module,
            str(Path(csv).resolve()),
            str(destination),
            "--arm",
            task["arm"],
            "--seed",
            str(task["seed"]),
        ]
        if task["study"] == "stream":
            command.extend(["--plan", str(Path(stream_plan).resolve())])
        environment = dict(
            os.environ,
            PYTHONDONTWRITEBYTECODE="1",
            HCSN_SOURCE_MANIFEST_SHA256=record["source_manifest_sha256"],
        )
        entry = {
            **task,
            "index": index,
            "state": "running",
            "command": command,
            "stdout": "logs/" + name + ".stdout",
            "stderr": "logs/" + name + ".stderr",
        }
        record["active_trial"] = entry
        save(out / "LAUNCH.json", record)
        began = time.perf_counter()
        with (
            (out / entry["stdout"]).open("wb") as stdout,
            (out / entry["stderr"]).open("wb") as stderr,
        ):
            try:
                process = subprocess.run(
                    command,
                    cwd=root,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=child_timeout,
                    check=False,
                )
                entry.update(
                    exit_code=process.returncode,
                    state="completed" if process.returncode == 0 else "failed",
                )
            except subprocess.TimeoutExpired:
                entry.update(exit_code=None, state="timed_out")
        entry["cold_wall_seconds"] = time.perf_counter() - began
        verify_source(root, source)
        report_path = destination / (
            "RESULT.json" if task["study"] == "stream" else "STUDY.json"
        )
        if report_path.exists():
            report = json.loads(report_path.read_text())
            entry.update(
                report_sha256=digest(report_path), reported_state=report.get("state")
            )
            embedded = (
                report.get("plan")
                if task["study"] == "adaptation"
                else json.loads((destination / "PLAN.json").read_text())
            )
            if embedded != plans[task["study"]]:
                entry["state"] = "plan_mismatch"
            if report.get("state") not in ("completed", "wall_budget_exhausted"):
                entry["state"] = "failed"
        else:
            entry["state"] = "missing_report"
        record["trials"].append(entry)
        record.pop("active_trial", None)
        record["elapsed_seconds"] = time.perf_counter() - started
        save(out / "LAUNCH.json", record)
        print(
            json.dumps(
                {
                    k: entry[k]
                    for k in (
                        "index",
                        "study",
                        "arm",
                        "seed",
                        "state",
                        "cold_wall_seconds",
                    )
                }
            ),
            flush=True,
        )
    record["state"] = (
        "completed"
        if all(r["state"] == "completed" for r in record["trials"])
        else "completed_with_failures"
    )
    record["elapsed_seconds"] = time.perf_counter() - started
    save(out / "LAUNCH.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("output")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--stream-plan", required=True)
    parser.add_argument("--adaptation-plan", required=True)
    parser.add_argument("--child-timeout", type=int, default=1200)
    args = parser.parse_args()
    record = run(
        args.csv,
        args.output,
        args.source_manifest,
        args.stream_plan,
        args.adaptation_plan,
        child_timeout=args.child_timeout,
    )
    raise SystemExit(0 if record["state"] == "completed" else 1)


if __name__ == "__main__":
    main()
