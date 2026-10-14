"""R10 read-only verification of stages, paid monitors, frozen gates and outputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(source: Path, runs: Path, out: Path) -> dict:
    sys.path.insert(0, str(source.resolve()))
    import torch
    from run import sources, specs, name_for, evaluation_panels, gaussian_rule, dump, PROTOCOL_COMMIT
    from refine import (
        WidePolicy,
        rule,
        make_problem,
        evaluate,
        qualifies,
        schedule_stages,
        FIT_CAP,
        SWITCH_AT,
        TARGET,
    )
    import reference

    wall_zero, cpu_zero = time.perf_counter(), time.process_time()
    out.mkdir(parents=True, exist_ok=False)
    plan = json.loads((runs / "PLAN.json").read_text())
    complete = json.loads((runs / "COMPLETE.json").read_text())
    require(plan["source"] == sources(), "source mismatch")
    require(plan["protocol_commit"] == PROTOCOL_COMMIT, "protocol mismatch")
    require(complete["plan_sha256"] == digest((runs / "PLAN.json").read_bytes()), "plan hash mismatch")
    require(plan["cases"] == specs(), "case specification mismatch")
    require([row["name"] for row in complete["census"]] == [name_for(case) for case in specs()], "incomplete census")
    require(complete["completed"] == 96 and complete["failed"] == 0, "execution failures")
    require((plan["fit_cap"], plan["switch_at"]) == (FIT_CAP, SWITCH_AT), "budget changed")
    require(plan["law_sha256"] == digest((runs / "LAWS.npz").read_bytes()), "law hash mismatch")

    with np.load(runs / "LAWS.npz", allow_pickle=False) as stored:
        for name, order in (("gl3", 3), ("gl5", 5)):
            states, weights = gaussian_rule(order)
            np.testing.assert_array_equal(stored[name + "_states"], states)
            np.testing.assert_array_equal(stored[name + "_weights"], weights)
        for name in ("cc5", "cc9"):
            states, weights = rule(name)
            np.testing.assert_array_equal(stored[name + "_states"], states)
            np.testing.assert_array_equal(stored[name + "_weights"], weights)

    gate_laws = {name: rule(name) for name in ("cc5", "cc9")}
    rows: list[dict] = []
    monitor_rows: list[dict] = []
    initial_groups: dict[tuple[int, int], list[str]] = {}
    totals = dict(
        runs=0,
        monitors=0,
        switches=0,
        panels=0,
        scalar_entries=0,
        max_replay_error=0.0,
        independent_action_checks=0,
        independent_action_max_error=0.0,
    )

    # Cache repeated monitor candidates shared by paired conditions.
    gate_cache: dict[tuple[int, str, str], float] = {}

    for index, entry in enumerate(complete["census"]):
        require(entry["case"] == plan["cases"][index], "case order mismatch")
        require(entry["status"] == "completed", "failed case")
        folder = runs / entry["name"]
        report_bytes = (folder / "REPORT.json").read_bytes()
        require(entry["report_sha256"] == digest(report_bytes), "report hash mismatch")
        report = json.loads(report_bytes)
        child = json.loads((folder / "PLAN.json").read_text())
        require(report["case"] == entry["case"] == child["case"], "identity mismatch")
        require(report["plan_sha256"] == digest((folder / "PLAN.json").read_bytes()), "child plan mismatch")
        require(report["source"] == child["source"] == plan["source"], "child source mismatch")
        require(child["protocol_commit"] == PROTOCOL_COMMIT, "child protocol mismatch")
        require((child["fit_cap"], child["switch_at"]) == (FIT_CAP, SWITCH_AT), "child budget mismatch")

        info = json.loads((folder / "FIT.json").read_text())
        seal = json.loads((folder / "FIT_SEAL.json").read_text())
        require(info == report["fit"], "fit/report mismatch")
        require(seal["fit_sha256"] == digest((folder / "FIT.json").read_bytes()), "fit seal mismatch")
        require(seal["monitors_sha256"] == digest((folder / "MONITOR_CHECKPOINTS.npz").read_bytes()), "monitor seal mismatch")
        require(seal["switches_sha256"] == digest((folder / "SWITCH_WEIGHTS.npz").read_bytes()), "switch seal mismatch")

        case = entry["case"]
        policy = WidePolicy(case["width"], case["seed"])
        with np.load(folder / "INITIAL.npz", allow_pickle=False) as data:
            initial = data["theta"].copy()
        with np.load(folder / "WEIGHTS.npz", allow_pickle=False) as data:
            theta = data["theta"].copy()
        with np.load(folder / "MONITOR_CHECKPOINTS.npz", allow_pickle=False) as data:
            monitors = data["theta"].copy()
        with np.load(folder / "SWITCH_WEIGHTS.npz", allow_pickle=False) as data:
            switches = data["theta"].copy()

        np.testing.assert_array_equal(initial, policy.initial)
        require(theta.size == report["parameters"] == 50 + 7 * case["width"], "parameter count mismatch")
        require(report["initial_sha256"] == digest(initial.astype("<f8", copy=False).tobytes()), "initial hash mismatch")
        require(report["weights_sha256"] == seal["weights_sha256"] == digest(theta.astype("<f8", copy=False).tobytes()), "weight hash mismatch")
        require(report["changed"] == (not np.array_equal(initial, theta)), "changed flag mismatch")

        expected_stages = schedule_stages(case["schedule"])
        require([stage["name"] for stage in info["stages"]] == [name for name, _ in expected_stages], "stage identity mismatch")
        require(len(switches) == (1 if case["schedule"] == "stage_gl3_gl5" else 0), "switch count mismatch")
        for stage_index, stage in enumerate(info["stages"]):
            require(stage["start_wall"] <= stage["end_wall"] <= info["fit_wall"] + 1e-9, "stage timing mismatch")
            if stage_index:
                switch_hash = digest(switches[stage_index - 1].astype("<f8", copy=False).tobytes())
                require(stage["start_sha256"] == switch_hash, "stage switch start mismatch")
                require(info["stages"][stage_index - 1]["end_sha256"] == switch_hash, "stage switch end mismatch")
        require(info["counts"]["stage_restarts"] == len(switches), "restart count mismatch")
        require(info["counts"]["full_hessians"] == 0, "dense Hessian fallback")
        require(info["fit_wall"] >= FIT_CAP, "fit budget not consumed")
        require(info["terminal_wall"] > 0 and info["terminal_cpu"] > 0, "unmetered terminal gate")
        require(info["total_wall"] >= info["fit_wall"] + info["terminal_wall"] - 1e-9, "total wall mismatch")

        require(len(monitors) == len(info["monitor_checks"]), "monitor census mismatch")
        if case["monitor"] == "terminal_only":
            require(len(monitors) == 0 and info["monitor_wall"] == 0 and info["monitor_cpu"] == 0, "terminal-only monitored")
        else:
            require(len(monitors) > 0, "frequent monitor missing")
        skipped = 0
        previous_end = -1.0
        for monitor_index, (candidate, row) in enumerate(zip(monitors, info["monitor_checks"])):
            require(row["index"] == monitor_index and row["start_wall"] >= previous_end and row["end_wall"] >= row["start_wall"], "monitor timing mismatch")
            previous_end = row["end_wall"]
            costs = {}
            for name in ("cc5", "cc9"):
                key = (case["width"], digest(candidate.astype("<f8", copy=False).tobytes()), name)
                if key not in gate_cache:
                    states, weights = gate_laws[name]
                    roots = evaluate(policy, torch.tensor(candidate), make_problem(), states, chunk=256)
                    gate_cache[key] = float(weights @ roots.mean(1))
                costs[name] = gate_cache[key]
            require(np.isclose(costs["cc5"], row["cc5"], rtol=1e-12, atol=1e-13), "monitor coarse mismatch")
            if row["cc9"] is None:
                require(row["cc5"] > TARGET, "invalid fine skip")
                skipped += 1
                good = False
            else:
                require(np.isclose(costs["cc9"], row["cc9"], rtol=1e-12, atol=1e-13), "monitor fine mismatch")
                good = qualifies(costs["cc5"], costs["cc9"])
            require(row["predicate"] == good, "monitor predicate mismatch")
            monitor_rows.append(dict(
                run=entry["name"],
                **row,
                recomputed_cc5=costs["cc5"],
                recomputed_cc9=costs["cc9"],
            ))
        require(info["counts"]["monitor_skipped_fine"] == skipped, "monitor skip count mismatch")
        require(info["counts"]["monitor_coarse_calls"] == len(monitors), "monitor coarse count mismatch")
        require(info["counts"]["monitor_fine_calls"] == len(monitors) - skipped, "monitor fine count mismatch")
        require(np.isclose(info["monitor_wall"], sum(row["end_wall"] - row["start_wall"] for row in info["monitor_checks"]), rtol=1e-12, atol=1e-9), "monitor wall mismatch")

        terminal_costs = {}
        for name in ("cc5", "cc9"):
            states, weights = gate_laws[name]
            roots = evaluate(policy, torch.tensor(theta), make_problem(), states, chunk=256)
            terminal_costs[name] = float(weights @ roots.mean(1))
        require(np.isclose(terminal_costs["cc5"], info["terminal_cc5"], rtol=1e-12, atol=1e-13), "terminal CC5 mismatch")
        require(np.isclose(terminal_costs["cc9"], info["terminal_cc9"], rtol=1e-12, atol=1e-13), "terminal CC9 mismatch")
        require(info["final_qualification"] == qualifies(terminal_costs["cc5"], terminal_costs["cc9"]), "false final qualification")
        require(info["stages"][-1]["end_sha256"] == digest(theta.astype("<f8", copy=False).tobytes()), "final stage weight mismatch")

        require(report["predictions_sha256"] == digest((folder / "PREDICTIONS.npz").read_bytes()), "prediction hash mismatch")
        with np.load(folder / "PREDICTIONS.npz", allow_pickle=False) as raw:
            for name, states, weights, problem in evaluation_panels():
                values = evaluate(policy, torch.tensor(theta), problem, states, chunk=256)
                error = float(np.max(np.abs(values - raw[name])))
                require(error <= 1e-13, "prediction replay mismatch")
                require(np.isclose(float(weights @ values.mean(1)), report["costs"][name], rtol=1e-12, atol=1e-13), "cost mismatch")
                totals["max_replay_error"] = max(totals["max_replay_error"], error)
                totals["panels"] += 1
                totals["scalar_entries"] += values.size

        # Independent action-coordinate implementation on one fresh QMC state and two regimes.
        qmc_states = next(states for name, states, _, _ in evaluation_panels() if name == "qmc0")[:1]
        with torch.no_grad():
            values, levels, _, _, _ = policy.tree(torch.tensor(theta), make_problem(), qmc_states)
        for regime in range(2):
            actions = np.concatenate([
                level["u"][regime * 2**depth:(regime + 1) * 2**depth].numpy().reshape(-1)
                for depth, level in enumerate(levels)
            ])
            problem = make_problem()
            tree = reference.build(problem, qmc_states[0], regime)
            independent = reference.evaluate(actions, problem, tree, False)[0]
            error = abs(independent - float(values[regime]))
            require(error <= 1e-12, "independent action mismatch")
            totals["independent_action_checks"] += 1
            totals["independent_action_max_error"] = max(totals["independent_action_max_error"], error)

        initial_groups.setdefault((case["width"], case["seed"]), []).append(report["initial_sha256"])
        rows.append(dict(
            name=entry["name"],
            **case,
            parameters=theta.size,
            qualified=info["final_qualification"],
            terminal_cc5=info["terminal_cc5"],
            terminal_cc9=info["terminal_cc9"],
            fit_wall=info["fit_wall"],
            fit_cpu=info["fit_cpu"],
            monitor_wall=info["monitor_wall"],
            monitor_cpu=info["monitor_cpu"],
            terminal_wall=info["terminal_wall"],
            terminal_cpu=info["terminal_cpu"],
            updates=info["counts"]["updates"],
            hvp=info["counts"]["hvp"],
            graphs=info["counts"]["graphs"],
            fit_peak_rss=info["fit_peak_rss"],
            cc17=report["costs"]["cc17"],
            gl9=report["costs"]["gl9"],
            qmc_mean=float(np.mean([report["costs"][f"qmc{i}"] for i in range(4)])),
            scale=report["costs"]["scale"],
            dynamics=report["costs"]["dynamics"],
            horizon4=report["costs"]["horizon4"],
            child_wall=entry["child_wall"],
            child_cpu=entry["child_cpu"],
        ))
        totals["runs"] += 1
        totals["monitors"] += len(monitors)
        totals["switches"] += len(switches)
        print(json.dumps(dict(verified=totals["runs"], name=entry["name"], qualified=info["final_qualification"])), flush=True)

    for hashes in initial_groups.values():
        require(len(hashes) == 16 and len(set(hashes)) == 1, "factorial initial mismatch")

    with open(out / "SCORES.csv", "x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    if monitor_rows:
        with open(out / "MONITORS.csv", "x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(monitor_rows[0]))
            writer.writeheader(); writer.writerows(monitor_rows)
    receipt = dict(
        **totals,
        initial_groups=len(initial_groups),
        wall=time.perf_counter()-wall_zero,
        cpu=time.process_time()-cpu_zero,
        production_authorized=False,
        timing_externally_authenticated=False,
    )
    dump(out / "AUDIT.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.runs, args.out), sort_keys=True), flush=True)
