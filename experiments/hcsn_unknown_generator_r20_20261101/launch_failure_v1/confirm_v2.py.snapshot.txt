"""Powered fresh confirmation with streamed records and bounded cluster-bootstrap memory."""

import argparse
import gzip
import json
import os
import subprocess
import sys
import time

import numpy as np

from .campaign import ROOT, archive, frozen, predictions, public, write
from .world_confirm_v2 import sample


def bootstrap(stats, spec, worlds):
    models, generators = spec.get("confirmation_arms", spec["models"]), next(iter(stats.values())).shape[0]
    controls = ["orbit_first_order"] + list(spec.get("feasible_controls", {}))
    rng = np.random.default_rng(spec["bootstrap_seed"])
    draws = {name:np.zeros((spec["bootstrap_draws"], 4)) for name in models}
    paired = np.zeros((spec["bootstrap_draws"], 2 * len(controls)))
    for start in range(0, spec["bootstrap_draws"], spec["bootstrap_batch"]):
        count = min(spec["bootstrap_batch"], spec["bootstrap_draws"] - start)
        indices = rng.integers(generators, size=(count, generators))
        for name in models:
            s = stats[name]
            totals = np.column_stack([s[:, column][indices].sum(1) for column in range(6)])
            draws[name][start:start + count, 0] = np.divide(totals[:, 3], totals[:, 2], out=np.ones(count), where=totals[:, 2] > 0)
            draws[name][start:start + count, 1] = np.divide(totals[:, 1], totals[:, 0], out=np.ones(count), where=totals[:, 0] > 0)
            draws[name][start:start + count, 2:] = totals[:, 4:6] / worlds
        for column, control in enumerate(controls):
            difference = stats["context_orbit"] - stats[control]
            paired[start:start + count, 2 * column] = difference[:, 4][indices].sum(1) / worlds
            paired[start:start + count, 2 * column + 1] = -difference[:, 5][indices].sum(1) / worlds
    return draws, paired


def worker(panel, spec, calibration):
    output = ROOT / "confirm_v2_01" / panel
    output.mkdir(exist_ok=False)
    models = json.loads(gzip.decompress((ROOT / "prepare_01/MODELS.json.gz").read_bytes()))
    cutoffs = json.loads((ROOT / "prepare_01/OOD.json").read_text())["cutoffs"]
    thresholds = {name:[spec["threshold"]] for name in models}
    policy_thresholds = {}
    for alias, base in spec["feasible_controls"].items():
        threshold = spec["threshold"] if calibration["selected"][base]["calibration_gate_passed"] else spec["fallback_threshold"]
        policy_thresholds[alias] = threshold
        thresholds[base] = sorted(set(thresholds[base] + [threshold]))
    worlds = spec["confirmation_worlds"][panel]
    if worlds % spec["worlds_per_generator"]:
        raise ValueError("Whole generator clusters required")
    generators = worlds // spec["worlds_per_generator"]
    stats = {name:np.zeros((generators, 9)) for name in spec["confirmation_arms"]}
    invalid, rows, archives = dict.fromkeys(stats, 0), [], []
    for generator in range(generators):
        for index in range(spec["worlds_per_generator"]):
            world = sample(panel, generator, index)
            base_values = predictions(world, models, cutoffs, thresholds)
            values = {name:{str(spec["threshold"]):base_values[name][str(spec["threshold"])]} for name in models}
            values.update({alias:{str(policy_thresholds[alias]):base_values[base][str(policy_thresholds[alias])]}
                           for alias, base in spec["feasible_controls"].items()})
            rows.append(dict(phase="r20_powered_confirmation_v2", panel=panel, generator=generator, index=index,
                public=public(world), target=world["target"], price=world["price"], predictions=values))
            for name, candidates in values.items():
                p = next(iter(candidates.values()))
                invalid[name] += p["invalid"]
                if not p["invalid"]:
                    a, f, e = p["accepted"], p["accepted"] and p["fractional"], not p["correct"]
                    stats[name][generator] += [a, a and e, f, f and e, p["payoff"], p["before_brier"],
                        p["true_probability"] <= 0, p["read_index"] is not None, p["payoff"] - p["no_read_payoff"]]
            if len(rows) == spec["archive_worlds"]:
                archives.append(archive(output, "worlds_%03d" % len(archives), rows))
                rows = []
    if rows:
        archives.append(archive(output, "worlds_%03d" % len(archives), rows))
    write(output / "ARCHIVES.json", archives)
    write(output / "CLUSTER_STATS_ARCHIVE.json", archive(output, "CLUSTER_STATS", {name:value.tolist() for name, value in stats.items()}))
    draws, paired = bootstrap(stats, spec, worlds)
    write(output / "BOOTSTRAP_ARCHIVE.json", archive(output, "BOOTSTRAP", dict(
        models={name:value.tolist() for name, value in draws.items()}, paired=paired.tolist(),
        columns=["fractional_risk", "overall_risk", "payoff", "before_brier"],
        paired_columns=["context_minus_" + control + "_" + measure
                        for control in ["orbit_first_order"] + list(spec["feasible_controls"])
                        for measure in ("payoff", "before_brier_improvement")])))
    summary = dict(panel=panel, worlds=worlds, independent_generators=generators, models={}, production_activation=False)
    for name in stats:
        base = spec["feasible_controls"].get(name, name)
        control_calibration = dict(calibration["selected"][base])
        control_calibration["threshold"] = policy_thresholds.get(name, spec["threshold"])
        value = dict(attempts=worlds, invalid=invalid[name], calibration=control_calibration, quality=None)
        if not invalid[name]:
            total = stats[name].sum(0)
            quality = dict(accepted=int(total[0]), errors=int(total[1]), fractional=int(total[2]), fractional_errors=int(total[3]),
                payoff=float(total[4] / worlds), before_brier=float(total[5] / worlds), support_losses=int(total[6]),
                reads=int(total[7]), read_net_effect=float(total[8] / worlds), upper95_fractional=float(np.quantile(draws[name][:, 0], .95)),
                upper95_overall=float(np.quantile(draws[name][:, 1], .95)))
            quality["gate"] = bool(value["calibration"]["calibration_gate_passed"] and not quality["support_losses"]
                and quality["fractional"] >= spec["minimum_fractional_confirmation_answers"]
                and max(quality["upper95_fractional"], quality["upper95_overall"]) <= spec["risk_limit"])
            value["quality"] = quality
        summary["models"][name] = value
    if not invalid["context_orbit"] and not invalid["orbit_first_order"]:
        difference = (stats["context_orbit"] - stats["orbit_first_order"]).mean(0) / spec["worlds_per_generator"]
        summary["paired"] = dict(payoff_difference=float(difference[4]), before_brier_improvement=float(-difference[5]),
            payoff_ci95=np.quantile(paired[:, 0], [.025, .975]).tolist(), before_brier_ci95=np.quantile(paired[:, 1], [.025, .975]).tolist(),
            fixed95_control_calibration_passed=calibration["selected"]["orbit_first_order"]["calibration_gate_passed"],
            model_adoption_claim=False)
    summary["feasible_control_comparisons"] = {}
    for column, alias in enumerate(spec["feasible_controls"], start=1):
        if not invalid["context_orbit"] and not invalid[alias]:
            difference = (stats["context_orbit"] - stats[alias]).mean(0) / spec["worlds_per_generator"]
            summary["feasible_control_comparisons"][alias] = dict(policy_threshold=policy_thresholds[alias],
                payoff_difference=float(difference[4]), payoff_ci95=np.quantile(paired[:, 2 * column], [.025, .975]).tolist(),
                before_brier_improvement=float(-difference[5]), before_brier_ci95=np.quantile(paired[:, 2 * column + 1], [.025, .975]).tolist(),
                model_adoption_claim=False)
    write(output / "SUMMARY.json", summary)


def run(spec, calibration):
    output = ROOT / "confirm_v2_01"
    output.mkdir(exist_ok=False)
    processes, receipts = [], {}
    for panel in spec["confirmation_worlds"]:
        log = (output / (panel + "_STDOUT.txt")).open("x")
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", panel], stdout=log, stderr=subprocess.STDOUT)
        log.close()
        processes.append((panel, process))
    for panel, process in processes:
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        receipts[panel] = dict(exit_code=process.returncode, child_cpu_seconds=usage.ru_utime + usage.ru_stime, max_rss_kib=usage.ru_maxrss)
    write(output / "WORKER_RECEIPTS.json", receipts)
    if any(value["exit_code"] for value in receipts.values()):
        write(output / "FAILED.json", dict(complete_confirmation=False, original_r20_holdouts_opened=False))
        return 1
    panels = {panel:json.loads((output / panel / "SUMMARY.json").read_text()) for panel in receipts}
    def passed(panel):
        quality = panels[panel]["models"]["context_orbit"]["quality"]
        return quality is not None and quality["gate"]
    write(output / "SUMMARY.json", dict(panels=panels, original_r20_holdouts_opened=False,
        known_failure_repair_gate=passed("reverse") and passed("lag2"), label_transport_gate=passed("relabeled_lag2"),
        untouched_structural_shift_gate=passed("lag2_skip"), all_blockers_closed=False, production_activation=False))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("confirm", "reverse", "lag2", "relabeled_lag2", "lag2_skip"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    frozen("CALIBRATION_V2_SOURCE_FREEZE.json", "CALIBRATION_V2_SOURCE_PUBLICATION.json")
    frozen("POSTCALIBRATION_V2_FREEZE.json", "CALIBRATION_V2_PUBLICATION.json")
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    calibration = json.loads((ROOT / "calibration_v2_01/CALIBRATION.json").read_text())
    if not calibration["selected"]["context_orbit"]["calibration_gate_passed"]:
        raise ValueError("Primary calibration prerequisite failed; do not open fresh confirmation")
    if args.worker:
        worker(args.worker, spec, calibration)
        return
    if args.child:
        raise SystemExit(run(spec, calibration))
    start = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--child"])
    _, status, usage = os.wait4(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(status)
    worker_cpu = sum(x["child_cpu_seconds"] for x in json.loads((ROOT / "confirm_v2_01/WORKER_RECEIPTS.json").read_text()).values())
    total_cpu = usage.ru_utime + usage.ru_stime
    write(ROOT / "CONFIRM_V2_PROCESS_RECEIPT.json", dict(exit_code=process.returncode, child_cpu_seconds=total_cpu,
        parallel_worker_cpu_sum=worker_cpu, wall_seconds=time.perf_counter() - start, max_process_rss_kib=usage.ru_maxrss,
        concurrent_family_peak_rss_kib=None,
        accounting_sanity_total_at_least_workers=total_cpu + 1e-6 >= worker_cpu,
        scope="Outerwait4 fullcoordinator and5waitedpanel descendants; allattempts/raw/bootstrap/IOincluded. Workercosts includedonce; development/audits separate."))
    if total_cpu + 1e-6 < worker_cpu:
        raise RuntimeError("Process-family CPU accounting lost panel costs")
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
