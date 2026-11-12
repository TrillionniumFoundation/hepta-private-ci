"""New bounded continuation identity; no initial trajectory or reference replay."""
import argparse
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from qualification.hcsn_currentstate.fixtures import fixture
from qualification.hcsn_currentstate.packets import Ledger, advance, observe, dump, load


ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT/"qualification/hcsn_currentstate/evidence/currentstate-attempt001"
PACKAGE = ROOT/"qualification/hcsn_currentstate_resume"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def values(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, dict):
        return {k: values(v) for k, v in x.items()}
    return x


def write(path, x):
    path.write_text(json.dumps(x, indent=2, allow_nan=False)+"\n")


def guarded(freeze):
    src = {p: digest(ROOT/p) for p in freeze["source_sha256"]}
    inputs = {p: digest(ROOT/p) for p in freeze["input_sha256"]}
    if src != freeze["source_sha256"] or inputs != freeze["input_sha256"]:
        raise RuntimeError("frozen source/input mismatch")
    return {"source_sha256": src, "input_sha256": inputs}


def trajectory(name, out, times):
    out.mkdir(parents=True, exist_ok=False)
    physics, _ = fixture(name)  # unused initial state is never advanced
    raw = (OLD/f"{name}.resume.json").read_bytes()
    state = load(raw, physics)
    if state.time != F(201, 1000) or dump(state, physics) != raw:
        raise RuntimeError("input cold restore failed")
    (out/"INPUT.json").write_bytes(dump(state, physics))
    ledger = Ledger(maximum=100); rows = []
    for t in times:
        prior = dump(state, physics)
        new = advance(state, t, physics, ledger)
        if dump(state, physics) != prior:
            raise RuntimeError("old state mutation")
        state = new
        label = "028" if t == F(7, 25) else "036"
        snapshot = out/f"STATE-{label}.json"
        snapshot.write_bytes(dump(state, physics))
        rows.append({"time": str(t), "observed": values(observe(state, physics, ledger)),
                     "snapshot_name": snapshot.name, "snapshot_sha256": digest(snapshot)})
    result = {"fixture": name, "input_sha256": hashlib.sha256(raw).hexdigest(), "input_direct_bytes_equal": True,
              "rows": rows, "ledger": vars(ledger), "initial_trajectory_advances": 0,
              "reference_evaluations": 0}
    write(out/"TRAJECTORY.json", result)
    return result


def cold(args):
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    freeze = json.loads(Path(args.freeze).read_text()); before = guarded(freeze)
    result = trajectory(args.fixture, Path(args.output), (F(7, 25), F(9, 25)))
    after = guarded(freeze)
    write(Path(args.output)/"GUARD.json", {"before": before, "after": after, "unchanged": before == after})


def run(args):
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    freeze = json.loads(Path(args.freeze).read_text()); before = guarded(freeze)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 21))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    wall = time.monotonic(); cpu = time.process_time()
    original = json.loads((OLD/"ROWS.json").read_text())
    all_rows = []; costs = {}; comparisons = {}; maximum = {}; relative_maximum = {}; eligible = 0; nulls = 0
    for name in ("mixed", "rare"):
        fine = trajectory(name, out/name/"warm", (F(7, 25), F(9, 25)))
        coarse = trajectory(name, out/name/"coarse", (F(9, 25),))
        target = out/name/"cold"
        cmd = [sys.executable, "-m", "qualification.hcsn_currentstate_resume.run_saved", "--cold", "--fixture", name,
               "--freeze", str(Path(args.freeze).resolve()), "--output", str(target)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=12,
                           env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
        (out/name/"COLD.stdout").write_text(p.stdout); (out/name/"COLD.stderr").write_text(p.stderr)
        if p.returncode:
            raise RuntimeError(f"cold child exit {p.returncode}: {p.stderr}")
        cold_result = json.loads((target/"TRAJECTORY.json").read_text())
        cold_guard = json.loads((target/"GUARD.json").read_text())
        if not cold_guard["unchanged"]:
            raise RuntimeError("cold guard changed")
        direct = {}
        for label in ("INPUT", "STATE-028", "STATE-036"):
            a = out/name/"warm"/(label+".json"); b = target/(label+".json")
            direct[label] = {"byte_equal": a.read_bytes() == b.read_bytes(), "warm_sha256": digest(a), "cold_sha256": digest(b)}
            if not direct[label]["byte_equal"]:
                raise RuntimeError("cold fullraw direct comparison failed")
        fine_last = fine["rows"][-1]["observed"]; coarse_last = coarse["rows"][-1]["observed"]
        schedule = {k: float(np.max(np.abs(np.array(fine_last[k])-np.array(coarse_last[k])))) for k in fine_last}
        comparisons[name] = {"direct_cold_fullraw": direct, "fine_coarse_max_abs": schedule,
                              "fine_coarse_full_vectors_retained": True,
                              "new_warm_final_matches_retained_original_warm_bytes":
                                  (out/name/"warm/STATE-036.json").read_bytes() == (OLD/f"{name}.final.json").read_bytes()}
        costs[name] = {"warm": fine["ledger"], "coarse": coarse["ledger"], "cold": cold_result["ledger"]}
        for mode, result in (("warm", fine), ("coarse", coarse), ("cold", cold_result)):
            for row in result["rows"]:
                old = next(r for r in original if r["fixture"] == name and r["time"] == row["time"])
                row = dict(row, fixture=name, mode=mode, retained_reference64=old["reference64"],
                           retained_warm_observed=old["observed"], error={})
                for key in old["reference64"]:
                    obs = np.array(row["observed"][key]); ref = np.array(old["reference64"][key])
                    delta = np.abs(obs-ref); mask = np.abs(ref) >= 1e-12
                    rel = np.divide(delta, np.abs(ref), out=np.full_like(delta, np.nan), where=mask)
                    row["error"][key] = {"absolute": delta.tolist(), "relative_eligible": np.where(mask, rel, None).tolist()}
                    maximum[key] = max(maximum.get(key, 0.), float(np.max(delta)))
                    if np.any(mask):
                        relative_maximum[key] = max(relative_maximum.get(key, 0.), float(np.nanmax(rel)))
                    eligible += int(np.count_nonzero(mask)); nulls += int(np.count_nonzero(~mask))
                all_rows.append(row)
    after = guarded(freeze)
    if before != after:
        raise RuntimeError("source/input changed")
    write(out/"ROWS.json", all_rows)
    summary = {"identity": freeze["identity"], "source_freeze_commit": freeze["source_commit"],
               "before": before, "after": after, "unchanged": True, "cost": costs, "comparisons": comparisons,
               "rows": len(all_rows), "eligible_scalar_rows": eligible, "ineligible_relative_scalar_rows": nulls,
               "max_abs_against_retained_reference": maximum, "max_relative_eligible_diagnostic": relative_maximum,
               "reference_evaluations": 0, "initial_trajectory_advances": 0, "old72_kernel_replays": 0,
               "torch": 0, "training": 0, "wall_seconds": time.monotonic()-wall,
               "parent_CPU_seconds": time.process_time()-cpu,
               "children_CPU_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
               "parent_ru_maxrss_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "children_ru_maxrss_platform_field_KiB": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
               "parent_setup_before_timer_excluded": True, "combined_peak_RSS_not_measured": True,
               "finite_absolute_check_passed": all(v <= 2e-11 for v in maximum.values()),
               "schedule_fullraw_check_passed": all(v <= 2e-11 for c in comparisons.values() for v in c["fine_coarse_max_abs"].values()),
               "admission": "HOLD_NO_GO", "all_closed": False}
    summary["artifacts"] = {str(p.relative_to(out)): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(out.rglob("*")) if p.is_file()}
    write(out/"SUMMARY.json", summary)
    print(json.dumps({k: summary[k] for k in ("identity", "rows", "eligible_scalar_rows", "ineligible_relative_scalar_rows", "max_abs_against_retained_reference", "finite_absolute_check_passed", "schedule_fullraw_check_passed", "wall_seconds", "admission")}))


def main():
    p = argparse.ArgumentParser(); p.add_argument("--output", required=True); p.add_argument("--freeze", required=True)
    p.add_argument("--cold", action="store_true"); p.add_argument("--fixture"); args = p.parse_args()
    cold(args) if args.cold else run(args)


if __name__ == "__main__":
    main()
