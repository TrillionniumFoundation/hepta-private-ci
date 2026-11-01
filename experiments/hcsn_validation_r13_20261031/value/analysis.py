"""All four factorials, stronger controls and complete task/actor cost reporting."""

import json
from pathlib import Path

import numpy as np

from .run import BASE, inherited, sha, write


def summarize(out):
    out = Path(out)
    paths = sorted(out.glob("*/*/RESULT.json"))
    rows = [json.loads(p.read_text()) for p in paths]
    protocol = json.loads((BASE/"PROTOCOL.json").read_text())
    expected = len(protocol["families"])*len(protocol["seeds"])*len(protocol["fresh"])
    if len(rows) != expected:
        raise ValueError("Incomplete fixed confirmation matrix")
    groups = {}
    for family in protocol["families"]:
        for name in rows[0]["policies"]:
            selected = [r["policies"][name] for r in rows if r["family"] == family]
            mean = lambda key: float(np.mean([s["exact"][key] for s in selected]))
            count = sum(len(s["actual_paired"]["returns"]) for s in selected)
            metric = lambda path: [get(s["metrics"], path) for s in selected]
            calibration = {head: {k: nullable_mean(metric(("calibration", "qpi", "occupancy", head, k)))
                           for k in ("rmse", "bias", "sign_accuracy")} for head in ("all", "READ", "SKIP")}
            groups[family+"/"+name] = dict(return_mean=mean("return"), oracle_gap=mean("gap"),
                correctness=float(np.mean([s["correctness"] for s in selected])), reads=mean("expected_reads"),
                skips=mean("expected_skips"), below_initial_stop=sum(s["below_initial_stop"] for s in selected),
                cases=len(selected), paired_trajectories=count,
                actor_cpu_ms_per_trajectory=1000*sum(s["actual_paired"]["actor_cpu"] for s in selected)/count,
                actor_wall_ms_per_trajectory=1000*sum(s["actual_paired"]["actor_wall"] for s in selected)/count,
                qpi_calibration=calibration,
                pairwise_rank=nullable_mean(metric(("qpi_pairwise_rank_accuracy_occupancy",))),
                qpi_improvement_regret=nullable_mean(metric(("qpi_one_step_improvement_regret_mean",))))
    factorials = {}
    for controller in ("qpi_selected", "matched_qstar"):
        for suffix in ("", "_tailstop"):
            fits = {}
            for seed in protocol["seeds"]:
                def mean(family, name):
                    return float(np.mean([r["policies"][name+suffix]["exact"]["return"]
                         for r in rows if r["family"] == family and r["seed"] == seed]))
                a, b = mean("ordinary", "lightweight"), mean("ordinary", controller)
                c, d = mean("analytic", "lightweight"), mean("analytic", controller)
                fits[str(seed)] = dict(A=a, B=b, C=c, D=d, **{"B-A":b-a, "D-C":d-c,
                    "C-A":c-a, "D-B":d-b, "interaction":d-c-b+a})
            factorials[controller+suffix] = dict(by_seed=fits, descriptive={k: dict(
                mean=float(np.mean([f[k] for f in fits.values()])),
                minimum_seed_mean=min(f[k] for f in fits.values()), maximum_seed_mean=max(f[k] for f in fits.values()))
                for k in next(iter(fits.values()))})
    checks = [c for r in rows for c in r["forced_checks"]]
    pair_checks = [c for r in rows for c in r["trajectory_dominance"]]
    result = dict(schema="hcsn.r13.value.results.v1", cases=len(rows), groups=groups, factorials=factorials,
        source_freeze_sha256=sha(BASE/"SOURCE_FREEZE.json"), input_results={str(p.relative_to(out)):sha(p) for p in paths},
        engineering=dict(histories=sum(r["histories"] for r in rows), paired_dominance_checks=len(pair_checks),
            forced_groups=len(checks), conditional_complete_worlds=sum(c["complete_worlds"] for c in checks),
            forced_max_errors={k:max(c["errors"][k] for c in checks) for k in ("mass", "qpi", "complete_fee", "state")},
            exact_max_error=max(v for r in rows for d in r["exact_dominance"].values() for v in d["errors"].values()),
            trajectory_max_error=max(v for c in pair_checks for v in c["errors"].values())),
        inherited_r12_training_receipt=json.loads((inherited.BASE/"TRAINING_01_PROCESS.json").read_text()),
        caveats=protocol["statistical_unit"], energy_joules=None,
        process_cost_note="Fresh child outer receipt is written by supervise after child exit. Actor costs are nested. Inherited training is prior work, not new R13 training.")
    write(out/"SUMMARY.json", result)
    lines = ["# R13 public-state SKIP-tail confirmation", "", protocol["statistical_unit"], "",
        "All original and transformed controllers are retained. Critic scores are unchanged; calibration uses each executed policy's actual Qpi.", "",
        "| Core / controller | Return | Correctness | READ | SKIP | Below initial STOP | Actor CPU ms |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name, row in groups.items():
        lines.append(f"| {name} | {row['return_mean']:.9f} | {row['correctness']:.6f} | {row['reads']:.6f} | {row['skips']:.6f} | {row['below_initial_stop']}/{row['cases']} | {row['actor_cpu_ms_per_trajectory']:.6f} |")
    lines += ["", "## Every factorial effect", "", "| Value policy | Effect | Mean | Min / max of three fit means |", "|---|---|---:|---|"]
    for name, value in factorials.items():
        for key, row in value["descriptive"].items():
            lines.append(f"| {name} | {key} | {row['mean']:+.9f} | [{row['minimum_seed_mean']:+.9f}, {row['maximum_seed_mean']:+.9f}] |")
    lines += ["", "These ranges are descriptive, not confidence intervals. Compare guarded matched-Qstar as well as Qpi, and retain CPU and residual STOP failures.", "",
              "The complete child-process receipt includes all state enumeration, actual execution, extra wrapper calls, evidence I/O and startup/exit. It must not be added to its nested actor times. Device energy remains unmeasured."]
    (out/"REPORT.md").write_text("\n".join(lines)+"\n")
    return result


def get(value, path):
    for key in path:
        value = value[key]
    return value


def nullable_mean(values):
    return None if all(v is None for v in values) else float(np.mean([v for v in values if v is not None]))
