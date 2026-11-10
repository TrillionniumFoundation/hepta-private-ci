"""Run a frozen, bounded development plan and retain every subprocess attempt."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import threading
import time
import traceback


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_bytes())
    source = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    journal = (out / "commands.jsonl").open("x")
    lock = threading.Lock()
    source_manifest = {
        str(p.relative_to(source)): digest(p)
        for p in sorted(source.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    (out / "source-manifest.json").write_text(
        json.dumps(source_manifest, sort_keys=True, indent=2) + "\n"
    )
    (out / "locked-plan.json").write_bytes(args.plan.read_bytes())
    reports = []

    def record(row):
        with lock:
            journal.write(json.dumps(row, allow_nan=False) + "\n")
            journal.flush()

    def run(arm, seed, learning_rate):
        name = f"{arm}-s{seed}-lr{learning_rate:g}"
        dispatch = time.monotonic()
        remaining = plan["whole_wall_seconds"] - (dispatch - started)
        if remaining <= 0:
            row = {"name": name, "status": "not_started_whole_budget"}
            record(row)
            return row
        seconds = min(plan["per_fit_wall_seconds"], remaining)
        bootstrap = (
            "import resource,runpy,sys; resource.setrlimit(resource.RLIMIT_AS,"
            f"({plan['address_space_bytes']},{plan['address_space_bytes']})); "
            "script=sys.argv[1];sys.argv=sys.argv[1:];"
            "sys.path.insert(0,str(__import__('pathlib').Path(script).parent));"
            "runpy.run_path(script,run_name='__main__')"
        )
        argv = [
            plan["python"],
            "-B",
            "-c",
            bootstrap,
            str(source / "proposals/localization-v3/train.py"),
            "--prepared",
            plan["prepared"],
            "--manifest-sha256",
            plan["manifest_sha256"],
            "--output",
            str(out / name),
            "--arm",
            arm,
            "--seed",
            str(seed),
            "--learning-rate",
            str(learning_rate),
            "--width",
            str(plan["width"]),
            "--batch-size",
            str(plan["batch_size"]),
            "--min-epochs",
            str(plan["min_epochs"]),
            "--max-epochs",
            str(plan["max_epochs"]),
            "--patience",
            str(plan["patience"]),
            "--memorization-updates",
            str(plan["memorization_updates"]),
            "--wall-seconds",
            str(max(1, seconds - 30)),
            "--rss-bytes",
            str(plan["peak_rss_bytes"]),
            "--s4-repo",
            plan["s4_repo"],
        ]
        if arm == "hcsn":
            argv += [
                "--hcsn-grid-json",
                json.dumps(plan["hcsn_grid"], sort_keys=True),
                "--trace-records",
                str(plan["trace_records"]),
                "--trace-bytes",
                str(plan["trace_bytes"]),
            ]
            if plan["cache_frozen_tables"]:
                argv += ["--cache-frozen-tables"]
        if plan.get("learn_core_adapter", False):
            argv += ["--learn-core-adapter"]
        micro_batch = plan.get("micro_batch_sizes", {}).get(arm)
        if micro_batch is not None:
            argv += ["--micro-batch-size", str(micro_batch)]
        row = {
            "name": name,
            "arm": arm,
            "seed": seed,
            "learning_rate": learning_rate,
            "argv": argv,
            "status": "started",
            "hard_wall_seconds": seconds,
            "dispatch_offset_seconds": dispatch - started,
        }
        record(row)
        env = dict(
            os.environ,
            OMP_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            CUDA_VISIBLE_DEVICES="",
            PYTHONDONTWRITEBYTECODE="1",
            HCSN_PROCESS_STARTED=str(dispatch),
        )
        try:
            with (
                (out / f"{name}.stdout").open("xb") as stdout,
                (out / f"{name}.stderr").open("xb") as stderr,
            ):
                process = subprocess.run(
                    argv,
                    cwd=source,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=seconds,
                    check=False,
                )
            row.update(
                status="completed" if process.returncode == 0 else "failed",
                returncode=process.returncode,
            )
        except subprocess.TimeoutExpired:
            row.update(status="timed_out", returncode=None)
        except Exception:
            row.update(
                status="launch_failed", returncode=None, error=traceback.format_exc()
            )
        row.update(whole_process_wall_seconds=time.monotonic() - dispatch)
        try:
            row.update(
                stdout_sha256=digest(out / f"{name}.stdout"),
                stderr_sha256=digest(out / f"{name}.stderr"),
            )
            result = out / name / "result.json"
            if result.exists():
                row["result_sha256"] = digest(result)
                fit = json.loads(result.read_bytes())
                row.update(
                    fit_status=fit["status"],
                    epochs=len(fit["epochs"]),
                    adequate=fit["training_adequacy_established"],
                    source_unchanged=fit["source_unchanged"],
                    common_weights_unchanged=fit.get("common_weights_unchanged"),
                    selected_development=fit.get("selected_development"),
                    cpu_seconds=fit["cpu_seconds"],
                    peak_rss_bytes=fit["peak_rss_bytes"],
                )
            else:
                row["fit_evidence_missing"] = True
                if row["status"] == "completed":
                    row["status"] = "evidence_failed"
        except Exception:
            row.update(
                status="evidence_failed",
                evidence_error=traceback.format_exc(),
                adequate=False,
            )
        record(row)
        print(
            json.dumps(
                {
                    key: row.get(key)
                    for key in (
                        "name",
                        "status",
                        "epochs",
                        "adequate",
                        "whole_process_wall_seconds",
                    )
                }
            ),
            flush=True,
        )
        return row

    # Same opportunity roster and resource ceilings for every arm. No retry,
    # resumed checkpoint, deleted failure or confirmation label is used.
    tasks = [
        (arm, seed, lr)
        for seed in plan["seeds"]
        for lr in plan["learning_rates"]
        for arm in plan["arms"]
    ]
    with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        futures = [pool.submit(run, *item) for item in tasks]
        for future in as_completed(futures):
            reports.append(future.result())
    final_manifest = {
        str(p.relative_to(source)): digest(p)
        for p in sorted(source.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hcsn-common-core-campaign-v1",
        "plan_sha256": digest(args.plan),
        "status": "completed_attempt_roster",
        "attempts": reports,
        "whole_wall_seconds": time.monotonic() - started,
        "sum_attempt_wall_seconds": sum(
            row.get("whole_process_wall_seconds", 0) for row in reports
        ),
        "children_cpu_seconds": children.ru_utime + children.ru_stime,
        "controller_cpu_seconds": time.process_time(),
        "source_unchanged": source_manifest == final_manifest,
        "training_adequacy_passed_fits": sum(
            row.get("adequate", False) for row in reports
        ),
        "confirmation_access": False,
        "formal_fits_started": 0,
        "scientific_admission": "HOLD",
        "energy_joules": None,
        "cost_context": "one CPU thread per fit; concurrent workers recorded in plan; external host contention uncontrolled",
        "complete_historical_cost_known": False,
        "missing_cost_scope": "historic data preparation, old cloud reservations, controller work before this campaign and physical energy",
    }
    (out / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    journal.close()
    print(
        json.dumps(
            {"completed": len(reports), "wall_seconds": result["whole_wall_seconds"]}
        ),
        flush=True,
    )
    return 0 if result["source_unchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
