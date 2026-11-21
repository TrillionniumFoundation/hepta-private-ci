"""Summarize five sealed attempts without generating data, refitting or selecting models."""
import argparse
from collections import Counter, defaultdict
import csv
import datetime
import json
from pathlib import Path
import statistics
import sys

from .receipts import ARMS, PREFIXES, SEEDS, SUFFIX, costs, digest, finite, normalize, read, registry_evidence


def inspect_stage(stage, attempt, registry, inventory):
    attempt, issues = Path(attempt), []
    admission = read(attempt / "admission.json", inventory, issues) or {}
    cfg, identity = admission.get("config", {}), admission.get("manifest_sha256")
    expected_schema = "hepta.hcsn-" + ("" if stage == "readout" else stage + "-") + "confirmatory.v1"
    if (cfg.get("schema") != expected_schema or cfg.get("seeds") != SEEDS
            or cfg.get("namespace") != PREFIXES[stage] + SUFFIX
            or cfg.get("budget", {}).get("wall_seconds") != (90 if stage == "boundary" else 180)):
        issues.append("admission differs from the prospectively declared stage/seeds/namespace/budget")
    reconstructed = digest(json.dumps(cfg, sort_keys=True, indent=2, allow_nan=False).encode())
    if reconstructed != identity:
        issues.append("admission config cannot reproduce the frozen manifest bytes")
    selection = read(attempt / "selection.json", inventory, issues)
    final = read(attempt / "final.json", inventory, issues)
    for name, phase, receipt in (("selection", "fit", selection), ("final", "final", final)):
        if receipt and (receipt.get("phase") != phase or receipt.get("manifest_sha256") != identity):
            issues.append(f"{name} receipt identity/phase mismatch")
    selection_hash, final_hash = (inventory.get(str(attempt / (name + ".json"))) for name in ("selection", "final"))
    marker = attempt / "FINAL_CONSUMED"
    try:
        raw = marker.read_bytes()
        inventory[str(marker)] = digest(raw)
        if raw.decode() != selection_hash:
            issues.append("FINAL_CONSUMED does not bind current selection")
    except (OSError, UnicodeError) as error:
        issues.append(f"{marker}: {error}")
    rows, grid_issues = normalize(stage, {"seeds": SEEDS, "final": cfg.get("final", -1)}, selection, final)
    issues.extend(grid_issues)
    accounting = costs(attempt, cfg, identity, inventory, issues) if "budget" in cfg else {}
    outer = registry_evidence(registry, stage, cfg, identity, selection_hash, final_hash, inventory, issues) if cfg.get("namespace") else {"admitted": False}
    for row in rows:
        row["admitted"] = outer["admitted"] and not issues and row["cell_valid"]
    decisions = Counter(r["status"] for r in rows if r["phase"] == "fit")
    counts = {phase: {"expected": sum(r["phase"] == phase for r in rows),
                      "valid": sum(r["phase"] == phase and r["cell_valid"] for r in rows),
                      "admitted": sum(r["phase"] == phase and r["admitted"] for r in rows),
                      "statuses": dict(Counter(r["status"] for r in rows if r["phase"] == phase))}
              for phase in ("fit", "final")}
    return {"stage": stage, "attempt": str(attempt), "manifest_sha256": identity, "issues": issues,
            "counts": counts, "fit_decisions_only": dict(decisions), "rows": rows,
            "ledger_cost": accounting, "outer": outer,
            "discovery_cost": cfg.get("discovery_cost", {"assistant_tokens": None, "api_cost": None,
                                "design_wall_seconds": None, "meaning": "not recorded; unknown, not zero"})}


def describe(values):
    return {"mean": statistics.fmean(values), "min": min(values), "max": max(values)} if values else {"mean": None, "min": None, "max": None}


def bind_allocation(stages, allocation, allocation_sha, protocol_sha):
    issues = []
    try:
        if allocation["seeds"] != SEEDS or set(allocation["stages"]) != set(ARMS):
            raise ValueError("allocation does not match the frozen five-stage three-seed grid")
        for stage in stages:
            record = stage["outer"].get("record", {})
            spec = allocation["stages"][stage["stage"]]
            if (record.get("plan_sha256") != allocation_sha or record.get("source_git_sha") != allocation["source_git_sha"]
                    or record.get("namespace") != spec["namespace"]
                    or record.get("source_files", {}).get("qualification/hcsn_sixwork/CONFIRMATORY_PLAN.md") != protocol_sha):
                raise ValueError(f"{stage['stage']}: wrong allocation/protocol/source binding or missing registry")
    except (KeyError, TypeError, ValueError) as error:
        issues.append(str(error))
    if issues:
        for stage in stages:
            for row in stage["rows"]:
                row["admitted"] = False
            for phase in ("fit", "final"):
                stage["counts"][phase]["admitted"] = 0
    return issues


def complete_grid(rows, issues):
    return (not issues and len(rows) == 630 and sum(r["phase"] == "fit" for r in rows) == 213
            and sum(r["phase"] == "final" for r in rows) == 417 and all(r["admitted"] for r in rows))


def comparisons(rows):
    """Only the contrasts and tolerance specified before final data consumption."""
    by_key = {(r["stage"], r["task"], r["split"], r["seed"], r["method"]): r
              for r in rows if r["phase"] == "final"}
    definitions = [("H1", "feature", "same_generator", "ordinary_tanh", "lower", False),
                   ("H1_diagnostic", "feature", "same_generator", "drop_value_risk", "lower", False),
                   ("H2", "boundary", "howard_qvi", "lookup_gate_bp", "higher", False),
                   ("H2_reference", "boundary", "howard_qvi", "never_reset", "higher", False),
                   ("H2_reference", "boundary", "lookup_gate_bp", "never_reset", "higher", False)]
    for stage, baseline in (("readout", "local_bp"), ("joint", "joint_bp")):
        definitions += [("H3", stage, method, baseline, "lower", True) for method in ARMS[stage] if method != baseline]
    result = []
    for hypothesis, stage, left, right, direction, screen in definitions:
        conditions = sorted({(r["task"], r["split"]) for r in rows if r["stage"] == stage and r["phase"] == "final"})
        for task, split in conditions:
            paired = []
            for seed in SEEDS:
                a, b = (by_key[(stage, task, split, seed, m)] for m in (left, right))
                valid = a["cell_valid"] and b["cell_valid"] and a["data_signature"] == b["data_signature"]
                admitted = valid and a["admitted"] and b["admitted"]
                difference = a["value"] - b["value"] if valid else None
                tau = a["tau"] if screen else None
                if screen and (not finite(tau) or a["incumbent_dev"] != b["incumbent_dev"]):
                    admitted = False
                paired.append({"seed": seed, "left_value": a["value"], "right_value": b["value"],
                               "difference": difference, "cell_pair_valid": valid, "admitted": admitted,
                               "left_status": a["status"], "right_status": b["status"], "tau": tau,
                               "within_tolerance": difference <= tau if admitted and screen else None,
                               "left_standalone_lower_bound": a["standalone_wall_lower_bound"],
                               "right_standalone_lower_bound": b["standalone_wall_lower_bound"],
                               "left_adaptation_seconds": a["adaptation_wall_seconds"],
                               "right_adaptation_seconds": b["adaptation_wall_seconds"]})
            accepted = [p["difference"] for p in paired if p["admitted"]]
            complete = len(accepted) == len(SEEDS)
            result.append({"hypothesis": hypothesis, "stage": stage, "task": task, "split": split,
                           "left": left, "right": right, "difference_is": "left minus right", "benefit_direction": direction,
                           "paired": paired, "n_admitted_seeds": len(accepted), "expected_seeds": len(SEEDS),
                           "difference_summary": describe(accepted),
                           "all_three_benefit": all(x < 0 if direction == "lower" else x > 0 for x in accepted) if complete else None,
                           "quality_tolerance_screen": ("meets" if all(p["within_tolerance"] for p in paired) else "does_not_meet")
                               if screen and complete else ("incomplete" if screen else None)})
    return result


def process_totals(stages):
    measured, freezes, setup, unknown = [], [], {}, []
    for item in stages:
        outer = item["outer"]
        for name in ("fit", "final", "freeze"):
            process = (outer.get("phases", {}).get(name) or {}).get("process") or {}
            value = process.get("wall_seconds")
            if finite(value):
                (freezes if name == "freeze" else measured).append(value)
            else:
                unknown.append(f"{item['stage']}/{name}")
        registration = outer.get("registration", {})
        if registration.get("plan_sha256"):
            setup[registration["plan_sha256"]] = registration.get("setup_wall_seconds")
    return {"observed_fit_final_child_seconds": sum(measured), "expected_fit_final_ceiling_seconds": 810,
            "complete_fit_final_child_seconds": sum(measured) if not [x for x in unknown if not x.endswith("/freeze")] else None,
            "observed_freeze_child_seconds_separate": sum(freezes), "registration_setup_seconds_by_plan": setup,
            "unknown_process_phases": unknown, "program_design_cost": "unknown; cannot be treated as zero",
            "scope": "sum each complete fit/final subprocess once; ledger snapshots and per-arm lower bounds are not added"}


def number(value):
    return f"{value:.7g}" if finite(value) else "—"


def markdown(report):
    text = ["# Prospective HCSN mechanism campaign: descriptive evidence", "",
            f"Allocation SHA-256: `{report['allocation_plan_sha256']}`. Protocol SHA-256: `{report['protocol_sha256']}`. "
            f"Analysis tool SHA-256: `{report['tool_sha256']}`.", "",
            "All contrasts follow the predeclared plan. Seeds, rather than windows, are the independent reporting units. "
            "No p-values, pooled cross-task MSE or large-model superiority claim is produced.", "",
            f"Expected grid: 213 fit method-cases and 417 final method-cells. Complete campaign: **{report['complete']}**.", "",
            "## Admission and decisions", "", "| Study | Fit valid/admitted/expected | Final valid/admitted/expected | Fit decisions | Issues |",
            "|---|---:|---:|---|---:|"]
    for item in report["stages"]:
        count = item["counts"]
        fmt = lambda phase: "/".join(str(count[phase][k]) for k in ("valid", "admitted", "expected"))
        text.append(f"| {item['stage']} | {fmt('fit')} | {fmt('final')} | {json.dumps(item['fit_decisions_only'], sort_keys=True)} | {len(item['issues'])} |")
    text += ["", "NoUpdate counts are fit decisions, counted once even when the selected incumbent has two final clock scores. "
             "UNAVAILABLE and failed cells remain in the expected denominator, but never become completed-method observations.", "",
             "## Every final seed metric", "", f"Seed order: {SEEDS}. Full fit/final rows and failure details are in seed_metrics.csv and report.json.", "",
             "| Study | Task | Split | Method | Seed metrics | Admitted mean [min, max] | Admitted/3 |", "|---|---|---|---|---|---|---:|"]
    grouped = defaultdict(list)
    for row in report["rows"]:
        if row["phase"] == "final":
            grouped[(row["stage"], row["task"], row["split"], row["method"])].append(row)
    for key, group in sorted(grouped.items()):
        group.sort(key=lambda x: SEEDS.index(x["seed"]))
        values = [x["value"] for x in group if x["admitted"]]
        stats = describe(values)
        seeds = "; ".join(number(x["value"]) + ("" if x["admitted"] else f" ({x['status']}; unadmitted)") for x in group)
        interval = f"{number(stats['mean'])} [{number(stats['min'])}, {number(stats['max'])}]"
        text.append("| " + " | ".join((*key, seeds, interval, str(len(values)))) + " |")
    text += ["", "## Predeclared paired differences", "", "Differences are left minus right. H1/H3 prefer smaller MSE; H2 prefers higher full expected return. "
             "H3 tolerance is max(1e-6, 0.01 × incumbent development MSE), separately for each seed. An all-three pattern is descriptive.", "",
             "| Hypothesis | Task | Split | Left − right | Paired seed differences | Admitted/3 | H3 screen |", "|---|---|---|---|---|---:|---|"]
    for item in report["contrasts"]:
        values = "; ".join(number(p["difference"]) + (f" (τ={number(p['tau'])})" if p["tau"] is not None else "") for p in item["paired"])
        text.append(f"| {item['hypothesis']} ({item['stage']}) | {item['task']} | {item['split']} | {item['left']} − {item['right']} | {values} | {item['n_admitted_seeds']} | {item['quality_tolerance_screen'] or '—'} |")
    text += ["", "## Measured cost and failures", "", "```json", json.dumps(report["process_cost"], indent=2), "```", "",
             "Per-arm standalone lower bounds include declared common setup; actual shared work is charged once. "
             "Unknown program design, assistant tokens, API charges and missing process intervals prevent a complete adaptation-time claim. "
             "The boundary experiment uses known dynamics; its stochastic-gate clock differs from hard instantaneous intervention. "
             "The architecture experiment covers one small parameter band, not multimodal foundation-model scaling.", ""]
    for item in report["stages"]:
        text.append(f"### {item['stage']} unresolved issues")
        text.append("")
        text += ["- " + x.replace("\n", " ") for x in item["issues"]] or ["None reported by this read-only evidence audit."]
        text.append("")
    text += ["## Allocation issues", ""]
    text += ["- " + issue for issue in report["allocation_issues"]] or ["None."]
    return "\n".join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in ARMS:
        parser.add_argument("--" + stage, required=True, type=Path, help="explicit sealed attempt directory")
    parser.add_argument("--registry", type=Path, help="original registry or complete relocated registry copy")
    parser.add_argument("--plan", required=True, type=Path, help="exact registered allocation JSON, not protocol prose")
    parser.add_argument("--protocol", required=True, type=Path, help="frozen CONFIRMATORY_PLAN.md")
    parser.add_argument("--output", required=True, type=Path, help="new report directory; existing directories rejected")
    args = parser.parse_args()
    inventory, allocation_issues = {}, []
    allocation = read(args.plan, inventory, allocation_issues)
    protocol_sha = digest(args.protocol.read_bytes())
    inventory[str(args.protocol)] = protocol_sha
    stages = [inspect_stage(stage, getattr(args, stage), args.registry, inventory) for stage in ARMS]
    allocation_issues.extend(bind_allocation(stages, allocation, inventory.get(str(args.plan)), protocol_sha))
    rows = [row for stage in stages for row in stage["rows"]]
    tool_hash = digest(Path(__file__).read_bytes() + Path(__file__).with_name("receipts.py").read_bytes())
    report = {"schema": "hepta.hcsn-descriptive-report.v1", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "allocation_plan_sha256": inventory.get(str(args.plan)), "protocol_sha256": protocol_sha,
              "allocation_issues": allocation_issues, "tool_sha256": tool_hash, "python": sys.version,
              "complete": complete_grid(rows, allocation_issues), "stages": stages, "rows": rows,
              "contrasts": comparisons(rows), "process_cost": process_totals(stages), "input_sha256": inventory}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (args.output / "report.md").write_text(markdown(report))
    fields = sorted({key for row in rows for key in row})
    with (args.output / "seed_metrics.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)
    print(json.dumps({"complete": report["complete"], "rows": len(rows), "report": str(args.output / "report.md")}))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
