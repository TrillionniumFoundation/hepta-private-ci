"""Single bounded execution after source freeze, retaining every observed array."""
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

from .fixtures import fixture, FINE, COARSE, RESUME
from .packets import Ledger, advance, observe, dump, load, canonical
from .reference import Reference
from .negative_control import counterexample


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_roster(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted((root/"qualification/hcsn_currentstate").glob("*.py"))} | {
        "qualification/hcsn_currentstate/PLAN.json": sha(root/"qualification/hcsn_currentstate/PLAN.json"),
        "qualification/hcsn_currentstate/SPEC.md": sha(root/"qualification/hcsn_currentstate/SPEC.md")}


def serializable(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, dict):
        return {k: serializable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [serializable(v) for v in x]
    return x


def cold(args):
    resource.setrlimit(resource.RLIMIT_CPU, (25, 26))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    physics, _ = fixture(args.fixture)
    raw = Path(args.snapshot).read_bytes(); state = load(raw, physics)
    ledger = Ledger()
    out = {"restored_snapshot_exact": dump(state, physics) == raw, "start_time": str(state.time), "rows": []}
    for t in (F(7, 25), F(9, 25)):
        state = advance(state, t, physics, ledger)
        out["rows"].append({"time": str(t), "observed": serializable(observe(state, physics, ledger))})
    out["final_snapshot_sha256"] = hashlib.sha256(dump(state, physics)).hexdigest()
    out["cost"] = vars(ledger)
    Path(args.output).write_text(json.dumps(out, indent=2, allow_nan=False)+"\n")


def rejection_controls(raw, physics):
    results = []
    def reject(name, callback):
        try:
            callback()
        except (ValueError, TypeError, KeyError):
            results.append({"name": name, "rejected": True})
        else:
            results.append({"name": name, "rejected": False})
    b = json.loads(raw)
    def changed(name, edit):
        x = json.loads(raw); edit(x["state"])
        x["sha256"] = hashlib.sha256(canonical(x["state"])).hexdigest()
        reject(name, lambda: load(canonical(x), physics))
    reject("checksum", lambda: load(raw.replace(b'"sha256":"', b'"sha256":"0', 1), physics))
    changed("missing_phase_law", lambda s: s.pop("pending"))
    changed("wrong_physics", lambda s: s.update(physics_id="0"*64))
    changed("unknown_operator", lambda s: s.update(operator="unknown"))
    changed("nonfinite_active", lambda s: s["active"]["hex"].__setitem__(0, "nan"))
    changed("negative_probability", lambda s: s["active"]["hex"].__setitem__(0, "-0x1p-2"))
    changed("noncanonical_time", lambda s: s.update(time=[402, 2000]))
    changed("out_of_domain_time", lambda s: s.update(time=[1, 1]))
    changed("packet_cap", lambda s: s.update(pending=s["pending"]*129))
    changed("packet_unknown_kind", lambda s: s["pending"][0].update(kind="totals"))
    changed("packet_float_target", lambda s: s["pending"][0].update(target=float(s["pending"][0]["target"])))
    changed("packet_bool_target", lambda s: s["pending"][0].update(target=True))
    changed("packet_float_origin", lambda s: s["pending"][0].update(origin=float(s["pending"][0]["origin"])))
    return results


def run(args):
    root = Path(__file__).resolve().parents[2]; out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_before = source_roster(root)
    freeze = json.loads(Path(args.freeze).read_text())
    if source_before != freeze["source_sha256"]:
        raise RuntimeError("source differs from pre-execution frozen roster")
    start = time.monotonic(); cpu = time.process_time()
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    rows = []; costs = {}; max_abs = {}; max_relative = {}; cold_count = 0
    max_order_delta = {}; ineligible = 0; eligible_count = 0
    negative = [counterexample(dps) for dps in (80, 120)]
    (out/"NEGATIVE_CONTROL.json").write_text(json.dumps(negative, indent=2)+"\n")
    for name in ("mixed", "rare"):
        physics, initial = fixture(name); fine = initial; ledger = Ledger()
        initial_bytes = dump(initial, physics); baseline = None; saved_resume = None
        snapshots = {}; fine_obs = {}
        for t in FINE:
            old_bytes = dump(fine, physics)
            new = advance(fine, t, physics, ledger)
            if dump(fine, physics) != old_bytes:
                raise RuntimeError("advance mutated old state")
            fine = new; observation = observe(fine, physics, ledger)
            fine_obs[t] = observation
            physical_total = fine.active.sum((1, 2))+fine.upper.sum(1)+observation["R"].sum(1)
            if baseline is None:
                baseline = physical_total
            mass_error = float(np.max(np.abs(physical_total-baseline)))
            row = {"fixture": name, "time": str(t), "observed": serializable(observation),
                   "channel_conservation_error": mass_error, "packets": len(fine.pending),
                   "packet_max_dimension": max((len(p.output) for p in fine.pending if hasattr(p, "output")), default=0)}
            rows.append(row)
            if t == RESUME:
                saved_resume = dump(fine, physics)
                (out/f"{name}.resume.json").write_bytes(saved_resume)
        fine_final = dump(fine, physics); (out/f"{name}.final.json").write_bytes(fine_final)
        if dump(initial, physics) != initial_bytes:
            raise RuntimeError("initial changed")
        coarse = initial; coarse_ledger = Ledger()
        for t in COARSE:
            coarse = advance(coarse, t, physics, coarse_ledger)
        coarse_obs = observe(coarse, physics, coarse_ledger)
        schedule = {k: float(np.max(np.abs(coarse_obs[k]-fine_obs[FINE[-1]][k]))) for k in coarse_obs}
        references = [Reference(name, n) for n in (32, 64)]
        for row in [r for r in rows if r["fixture"] == name]:
            t = F(row["time"]); r32, r64 = (r.at(t) for r in references)
            row["reference32"] = serializable(r32); row["reference64"] = serializable(r64)
            row["error"] = {}
            for k in r64:
                obs = np.array(row["observed"][k]); ref = r64[k]
                errors = np.abs(obs-ref); eligible = np.abs(ref) >= 1e-12
                ineligible += int(np.count_nonzero(~eligible)); eligible_count += int(np.count_nonzero(eligible))
                relative = np.divide(errors, np.abs(ref), out=np.full_like(errors, np.nan), where=eligible)
                row["error"][k] = {"absolute": errors.tolist(), "relative_eligible": np.where(eligible, relative, None).tolist(),
                                     "reference_order_delta": np.abs(r32[k]-ref).tolist()}
                max_abs[k] = max(max_abs.get(k, 0.), float(np.max(errors)))
                max_order_delta[k] = max(max_order_delta.get(k, 0.), float(np.max(np.abs(r32[k]-ref))))
                if np.any(eligible):
                    max_relative[k] = max(max_relative.get(k, 0.), float(np.nanmax(relative)))
        rejects = rejection_controls(saved_resume, physics)
        if not all(r["rejected"] for r in rejects):
            raise RuntimeError("snapshot reject control failed")
        # The subprocess imports only frozen current-stage source and starts at the
        # retained .201 state. It does not construct/replay the initial trajectory.
        childout = out/f"{name}.cold.json"
        command = [sys.executable, "-m", "qualification.hcsn_currentstate.audit", "--cold", "--fixture", name,
                   "--snapshot", str(out/f"{name}.resume.json"), "--output", str(childout)]
        child = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=30,
                               env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
        cold_count += 1
        (out/f"{name}.cold.stdout").write_text(child.stdout); (out/f"{name}.cold.stderr").write_text(child.stderr)
        if child.returncode:
            raise RuntimeError(f"cold child exit {child.returncode}: {child.stderr}")
        cold_result = json.loads(childout.read_text())
        cold_errors = {k: 0. for k in fine_obs[FINE[-1]]}
        for r in cold_result["rows"]:
            t = F(r["time"])
            for k in cold_errors:
                cold_errors[k] = max(cold_errors[k], float(np.max(np.abs(np.array(r["observed"][k])-fine_obs[t][k]))))
        if not cold_result["restored_snapshot_exact"] or cold_result["final_snapshot_sha256"] != hashlib.sha256(fine_final).hexdigest():
            raise RuntimeError("cold state bitwise recovery failed")
        costs[name] = {"fine": vars(ledger), "coarse": vars(coarse_ledger), "cold": cold_result["cost"],
                       "reference": [{"order": r.order, "expm_calls": r.expm_calls, "gl_nodes": r.quad_nodes} for r in references],
                       "schedule_errors": schedule, "cold_errors": cold_errors, "reject_controls": rejects,
                       "cold_final_bytes_exact": True}
    source_after = source_roster(root)
    if source_before != source_after:
        raise RuntimeError("executing source changed")
    if sum(r["expm_calls"] for c in costs.values() for r in c["reference"]) > 100000:
        raise RuntimeError("global reference cap")
    if sum(r["gl_nodes"] for c in costs.values() for r in c["reference"]) > 10000:
        raise RuntimeError("global reference GL cap")
    if sum(c[mode]["expm_calls"] for c in costs.values() for mode in ("fine", "coarse", "cold")) > 4000:
        raise RuntimeError("global candidate cap")
    raw_rows = json.dumps(rows, indent=2, allow_nan=False)+"\n"
    (out/"ROWS.json").write_text(raw_rows)
    wall = time.monotonic()-start
    summary = {"identity": freeze["identity"], "source_freeze_commit": freeze["source_commit"],
               "source_sha256_before": source_before, "source_sha256_after": source_after,
               "rows": len(rows), "fixtures": 2, "channels": 3, "cold_subprocesses": cold_count,
               "max_abs": max_abs, "max_relative_eligible_diagnostic": max_relative,
               "max_reference_order_delta": max_order_delta,
               "eligible_scalar_rows": eligible_count, "ineligible_relative_scalar_rows": ineligible,
               "cost": costs, "wall_seconds": wall, "parent_cpu_seconds": time.process_time()-cpu,
               "child_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
               "max_rss_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "numerical_roundoff_certified": False, "old_kernels": 0, "old_refs": 0, "training": 0, "torch": 0,
               "admission": "HOLD_NO_GO", "all_closed": False}
    summary["finite_control_absolute_checks_passed"] = all(v <= 2e-11 for v in max_abs.values())
    summary["reference_order_check_passed"] = all(v <= 2e-11 for v in max_order_delta.values())
    summary["schedule_check_passed"] = all(v <= 2e-11 for c in costs.values() for v in c["schedule_errors"].values())
    summary["conservation_check_passed"] = all(r["channel_conservation_error"] <= 2e-11 for r in rows)
    summary["artifacts"] = {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(out.iterdir()) if p.is_file()}
    (out/"SUMMARY.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k: summary[k] for k in ("identity", "rows", "max_abs", "finite_control_absolute_checks_passed", "wall_seconds", "parent_cpu_seconds", "admission")}))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--freeze"); parser.add_argument("--cold", action="store_true")
    parser.add_argument("--fixture"); parser.add_argument("--snapshot")
    args = parser.parse_args()
    cold(args) if args.cold else run(args)


if __name__ == "__main__":
    main()
