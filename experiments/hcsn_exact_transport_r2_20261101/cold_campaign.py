"""Run every declared workload in independent cold workers, preserving receipts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from . import audit


def run(out, workers):
    if not 1 <= workers <= 4:
        raise ValueError("Cold worker concurrency cap is four")
    out.mkdir(parents=True, exist_ok=False)
    jobs = []
    frozen = json.loads((audit.HERE / "CANDIDATE_FREEZE.json").read_text())
    if frozen["selected_backend"] != "integrated" or frozen["source"] != audit.sources():
        raise ValueError("Cold campaign requires the exact frozen integrated candidate")
    for task in audit.PLAN["tasks"]:
        for batch, condition in audit.PLAN["workloads"]:
            for backward in (False, True):
                for kind in ("dense", "integrated"):
                    name = f"{task}_B{batch}_{condition}_{int(backward)}_{kind}"
                    path = out / (name + ".json")
                    prefix = out / (name + ".worker")
                    command = [sys.executable, "-m", "experiments.hcsn_four_stage_flow_20261031.meter",
                               "--out", str(prefix), "--", sys.executable, "-m",
                               "experiments.hcsn_exact_transport_r2_20261101.cold_start",
                               "--kind", kind, "--task", task, "--batch", str(batch),
                               "--condition", condition, "--out", str(path)]
                    if backward:
                        command.append("--backward")
                    jobs.append(dict(name=name, path=path, prefix=prefix, command=command))

    def execute(job):
        result = subprocess.run(job["command"], capture_output=True, text=True)
        return dict(name=job["name"], command=job["command"], returncode=result.returncode,
                    meter_stdout=result.stdout, meter_stderr=result.stderr)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(execute, jobs))
    audit.write(out / "PROCESS_RECORDS.json", runs)
    rows = []
    for left, right in zip(jobs[::2], jobs[1::2], strict=True):
        if not left["path"].exists() or not right["path"].exists():
            rows.append(dict(name=left["name"], passed=False, reason="Missing failed worker output"))
            continue
        dense, candidate = [json.loads(j["path"].read_text()) for j in (left, right)]
        with np.load(left["path"].with_suffix(".npz")) as a, np.load(right["path"].with_suffix(".npz")) as b:
            error = float(np.max(np.abs(a["logits"] - b["logits"])))
            labels = a["labels"]
            argmax = bool(np.array_equal(a["logits"].argmax(-1)[:, labels >= 0], b["logits"].argmax(-1)[:, labels >= 0]))
        rows.append(dict(task=dense["task"], batch=dense["batch"], condition=dense["condition"],
                         backward=dense["backward"], max_cold_output_error=error,
                         argmax_identical=argmax, input_identical=dense["input_sha256"] == candidate["input_sha256"],
                         passed=error <= audit.PLAN["max_output_absolute_error"] and argmax
                         and dense["input_sha256"] == candidate["input_sha256"],
                         dense=dense, candidate=candidate))
    result = dict(schema="hcsn.exact-addressed-r2.cold-campaign.v1", workers=workers,
                  source_sha256={str(p.relative_to(audit.ROOT)): audit.digest(p) for p in
                                 [Path(__file__), audit.HERE / "cold_start.py"]},
                  source_freeze_sha256=audit.digest(audit.HERE / "CANDIDATE_FREEZE.json"),
                  passed=all(r["returncode"] == 0 for r in runs) and all(r["passed"] for r in rows),
                  process_count=len(runs), rows=rows,
                  cost_note="Use outer campaign receipt only in non-nested CPU totals; per-worker receipts are nested")
    audit.write(out / "SUMMARY.json", result)
    print(json.dumps(dict(passed=result["passed"], process_count=len(runs), cases=len(rows))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    run(args.out, args.workers)
