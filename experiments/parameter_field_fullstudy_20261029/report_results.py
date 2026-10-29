"""Read-only assembly of completed evidence; never train, score, or tune a gate.

REPORT_INPUTS.json schema hepta.fullstudy.report-inputs.1 requires attempt_id,
raw_root, protocol and amendment={path,bytes,sha256}, and stages A/B/C/W/R. Each stage has
status and runs=[{seed,operation,complete,...}] with exact file descriptors.
A runs also supply bank and paths; B runs supply paths. A/B/C supply endpoint.
Optional A bank_outputs maps each parent stem to four output file descriptors.
C trace/head descriptors are already bound by its COMPLETE artifact inventory.
engineering_preflights holds both actual RESULT descriptors. failed_attempts
contains {receipt,training_microsteps_lower_bound,engineering_microsteps_included:
0,unknown_additional_work:true}. integrity and resource_status are metadata.
Any unfinished/blocked stage returns status only, before importing scientific
loaders or opening efficacy artifacts. Input metadata must never assert a stage
complete before its producer has sealed every registered path.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

PHASES = ("A", "B", "C", "W", "R")
SEEDS = (17, 29, 43)
PLANNED = {"A": 117504, "B": 69120, "C": 57536, "W": 2880, "R": 96768}
SCHEMA = "hepta.fullstudy.report-inputs.1"


def require(test, message):
    if not test:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(descriptor):
    path = Path(descriptor["path"]).resolve()
    require(path.is_file() and path.stat().st_size == descriptor["bytes"] and sha(path) == descriptor["sha256"],
            "Report input bytes differ: " + str(path))
    require(".pending." not in path.name and "FAILED" not in path.name, "Unfinished scientific artifact")
    return path


def read(descriptor):
    path = checked(descriptor)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def relative_descriptor(root, artifact):
    relative = Path(artifact["path"])
    target = (Path(root) / relative).resolve()
    require(not relative.is_absolute() and ".." not in relative.parts and target.is_relative_to(Path(root).resolve()),
            "Unsafe scientific artifact path")
    return {**artifact, "path": str(target)}


def ready_operations(spec):
    """Read metadata-only operation receipts for the entire population first."""
    root = Path(spec["raw_root"]).resolve()
    operations = {}
    for phase in PHASES:
        runs = spec["stages"][phase]["runs"]
        expected = set(SEEDS) if phase in ("A", "B", "R") else {None}
        require(len(runs) == len(expected) and {r["seed"] for r in runs} == expected, "Incomplete operation population")
        for run in runs:
            path = checked(run["operation"])
            require(not path.with_name(path.name.replace(".COMPLETE.json", ".FAILED.json")).exists(), "Failed operation cannot be reported complete")
            op = read(run["operation"])
            require(op.get("complete") is True and op.get("post_execution_storage_check") is True
                    and op.get("attempt_id") == spec["attempt_id"] and op.get("phase") == phase
                    and op.get("seed") == run["seed"] and op.get("scientific_source_bytes_unchanged") is True,
                    "Operation did not complete its registered gates")
            target = relative_descriptor(root, op["scientific_complete"])
            require(checked(target) == checked(run["complete"]) and target["sha256"] == run["complete"]["sha256"],
                    "Operation does not bind supplied scientific completion")
            operations[(phase, run["seed"])] = op
    for phase in ("A", "B", "C"):
        path = checked(spec["stages"][phase]["endpoint"])
        require(path.name == "ENDPOINTS.json" and not (path.parent / "FAILED.json").exists(), "Endpoint publication barrier has not completed")
    return operations


def bank_diagnostics(bank, outputs=None):
    require(bank.get("complete") is True and len(bank["records"]) == 48, "Incomplete A bank")
    counts = Counter()
    for row in bank["records"]:
        branches = row["branches"]
        require(len(branches) == 4 and {b["action"] for b in branches} == set(range(4)), "Incomplete legal action bank")
        identities = [b["first"] for b in sorted(branches, key=lambda x: x["action"])]
        legal = len({x["dynamics"] for x in identities})
        parameter_optimizer = len({(x["components"]["parameters"], x["components"]["optimizer"]) for x in identities})
        counts["parents"] += 1
        counts["parents_with_multiple_complete_legal_hashes"] += legal > 1
        counts["parents_with_multiple_parameter_optimizer_successors"] += parameter_optimizer > 1
        counts["parents_with_hash_diversity_only_in_other_components"] += legal > 1 and parameter_optimizer == 1
        counts["parents_with_distinct_terminal_label_values"] += len(set(row["action_values"])) > 1
        require(row["advantages"][row["baseline"]] == 0 and row["prefix_replay_equal"] is True,
                "Baseline-aligned label or prefix reconstruction differs")
    result = {"seed": bank["seed"], "counts": dict(counts), "calibration": bank["heads"],
              "warning": "Complete-state hashes include incoming gradient presence; a hash difference alone need not change future behavior."}
    if outputs is not None:
        import numpy as np
        expected = {f"schedule-{r['schedule_id']}-{r['prefix']}-step-{r['step']}" for r in bank["records"]}
        require(set(outputs) == expected, "Bank hard-output population differs")
        different = 0
        for group in outputs.values():
            require(len(group) == 4, "Each parent needs all four hard outputs")
            hashes = []
            for item in group:
                with np.load(checked(item), allow_pickle=False) as saved:
                    hashes.append(tuple(saved["output_sha256"].tolist()))
            different += len(set(hashes)) > 1
        result["parents_with_distinct_terminal_hard_outputs"] = different
    else:
        result["parents_with_distinct_terminal_hard_outputs"] = None
    return result


def path_diagnostics(paths, stage):
    """Descriptive mechanism checks, distinct from all prespecified efficacy tests."""
    grouped, rows = {}, []
    for path in paths:
        mode = path.get("method", {"baseline": "ordinary", "field": "field12"}.get(path.get("policy")))
        architecture = path.get("mode")
        group = (path["seed"], path.get("schedule_id", 8000), architecture)
        grouped.setdefault(group, {})[mode] = path
    for group, arms in grouped.items():
        require("ordinary" in arms, "Missing paired ordinary path")
        baseline = arms["ordinary"]["trace"]
        for mode, path in arms.items():
            trace = path["trace"]
            require(len(trace) == len(baseline) == 6, "Incomplete decision trace")
            first = None
            if stage in ("A", "B"):
                first = next((row["transaction"]["end"] for row, ref in zip(trace, baseline, strict=True)
                              if any(row["transaction"]["after"][key] != ref["transaction"]["after"][key]
                                     for key in ("parameters", "optimizer"))), None)
            rows.append({"seed": group[0], "schedule_id": group[1], "architecture": group[2], "method": mode,
                         "overrides": sum(bool(t["choice"]["override"]) for t in trace),
                         "accepted_overrides": sum(bool(t["choice"]["override"] and t["transaction"]["accepted"]) for t in trace),
                         "guard_rejections": sum(not t["transaction"]["accepted"] for t in trace),
                         "fallbacks": dict(Counter(str(t["choice"]["fallback_reason"]) for t in trace if t["choice"].get("fallback_reason"))),
                         "outside_fit_norm": sum(bool(t["choice"].get("outside_fit_norm")) for t in trace),
                         "first_complete_legal_hash_divergence_clock": path.get("first_legal_divergence_clock"),
                         "first_parameter_optimizer_divergence_clock": first,
                         "parameter_optimizer_trace_available": stage in ("A", "B"),
                         "same_baseline_terminal_complete_state": (path["state_sha256"] == arms["ordinary"]["state_sha256"] if stage == "C" else path.get("terminal_reference_tail_state_equal"))})
    return rows


def output_differences(descriptor, records):
    """Compare already-emitted bytes, with no model execution or new inference."""
    import numpy as np
    root = checked(descriptor).parent
    hashes, references = {}, {}
    for row in records:
        with np.load(checked(relative_descriptor(root, row)), allow_pickle=False) as saved:
            pixels, captions, codes = saved["pixels_u8"], saved["captions_utf8"], saved["output_sha256"]
            require(all(hashlib.sha256(p.tobytes() + str(t).encode()).hexdigest() == h
                        for p, t, h in zip(pixels, captions, codes, strict=True)), "Emitted-byte hash differs")
            values = {(tuple(pair), str(condition)): str(code) for pair, condition, code
                      in zip(saved["source_ids"], saved["conditions"], codes, strict=True)}
        require(len(values) == row["rows"], "Repeated output/source condition")
        group = (row["seed"], row.get("architecture"), row["schedule_id"], row["role"])
        hashes[row["id"]] = values
        if row["method"] == "ordinary":
            references[group] = values
    differences = []
    for row in records:
        if row["method"] == "frozen":
            continue
        group = (row["seed"], row.get("architecture"), row["schedule_id"], row["role"])
        value, ref = hashes[row["id"]], references[group]
        require(value.keys() == ref.keys(), "Unpaired output identities")
        differences.append({"id": row["id"], "different_outputs": sum(value[key] != ref[key] for key in value),
                            "total_outputs": len(value), "reference": "same model/architecture/schedule ordinary path"})
    return differences


def microsteps(ledger):
    counts = ledger.get("counts", ledger)
    return sum(value for key, value in counts.items() if key.split(".")[-1] == "scheduled_gradient_microsteps")


def prior_costs(spec):
    """Only explicitly supplied engineering/failure receipts; no efficacy inputs."""
    preflights, failures = [], []
    descriptors = spec.get("engineering_preflights", [])
    require(len({d["sha256"] for d in descriptors}) == len(descriptors), "Duplicate engineering receipt")
    for descriptor in descriptors:
        value = read(descriptor)
        require(value.get("complete") is True and value.get("schema") == "hepta.fullstudy.real-kernel-preflight.1", "Unsealed engineering receipt")
        preflights.append({"kind": "engineering_preflight", "receipt_sha256": descriptor["sha256"],
                          "gradient_microsteps": microsteps(value["costs"]), "ledger": value["costs"], "wall_seconds": value["wall_seconds"]})
    for item in spec.get("failed_attempts", []):
        require(item["engineering_microsteps_included"] == 0 and item["unknown_additional_work"] is True,
                "Failed-attempt cost scope must exclude separately counted engineering work")
        value = read(item["receipt"])
        known = value["known_scheduled_gradient_microsteps_lower_bound"]
        require(value["schema"] == "hepta.fullstudy.infrastructure-failure.1"
                and item["training_microsteps_lower_bound"] == known["attempt01_training_total"], "Failed-attempt training lower bound differs")
        failures.append({**item, "receipt": value})
    lower = sum(row["gradient_microsteps"] for row in preflights) + sum(item["training_microsteps_lower_bound"] for item in failures)
    return {"engineering_receipts": preflights, "failed_attempts": failures,
            "gradient_microsteps_known_lower_bound": lower, "unknown_partial_work": bool(failures),
            "scope": "Only receipt-backed work supplied here; inclusive historical subtotal keys are not added again."}


def development_summary(records):
    cells = defaultdict(list)
    for row in records:
        means = {observer: float(sum(values) / len(values)) for observer, values in row["values"].items()}
        cells[(row["seed"], row["method"], row["role"])].append(means)
    means = {key: {o: sum(row[o] for row in rows) / len(rows) for o in ("reward", "audit")} for key, rows in cells.items()}
    effects = {}
    for left, right in (("ordinary", "frozen"), ("field12", "ordinary"), ("field12", "history6"), ("full_current_state", "field12")):
        for role in ("task", "clean"):
            by_seed = {str(seed): {o: means[(seed, left, role)][o] - means[(seed, right, role)][o] for o in ("reward", "audit")} for seed in SEEDS}
            effects[f"{left}-{right} {role}"] = {"per_seed": by_seed, "point": {o: sum(row[o] for row in by_seed.values()) / 3 for o in ("reward", "audit")}}
    return {"effects": effects, "scope": "Exposed development roles; descriptive means only, no independent efficacy inference or new confidence interval."}


def cost_rows(complete, operations, endpoint, spec):
    rows = []
    for (phase, seed), record in complete.items():
        ledger = record["work" if phase == "C" else "reconstruction_work" if phase == "R" else "costs"]
        rows.append({"kind": "training" if phase in ("A", "B", "C") else "reconstruction" if phase == "R" else "constructed_witness",
                     "phase": phase, "seed": seed, "gradient_microsteps": microsteps(ledger), "ledger": ledger,
                     "wall_seconds": record.get("wall_seconds", ledger.get("wall_seconds")),
                     "cpu_seconds": record.get("cpu_seconds", ledger.get("cpu_seconds")),
                     "process_peak_rss_bytes": operations[(phase, seed)].get("process_peak_rss_bytes")})
    for phase, record in endpoint.items():
        ledger = record["scoring_work" if phase == "C" else "scoring_costs"]
        rows.append({"kind": "endpoint_scoring", "phase": phase, "gradient_microsteps": microsteps(ledger), "ledger": ledger,
                     "wall_seconds": record.get("wall_seconds", ledger.get("wall_seconds")),
                     "cpu_seconds": record.get("cpu_seconds", ledger.get("cpu_seconds")),
                     "process_peak_rss_bytes": record.get("process_peak_rss_bytes")})
    prior = prior_costs(spec)
    require(len(prior["engineering_receipts"]) == 2, "Both executed engineering preflights need their real receipts")
    rows.extend(prior["engineering_receipts"])
    failed = prior["failed_attempts"]
    actual = sum(row["gradient_microsteps"] for row in rows)
    lower = actual + sum(item["training_microsteps_lower_bound"] for item in failed)
    return {"rows": rows, "failed_attempts": failed, "completed_receipt_gradient_microsteps": actual,
            "all_attempts_gradient_microsteps_known_lower_bound": lower, "unknown_partial_work": bool(failed),
            "no_quality_cost_exchange_rate_fitted": True,
            "rule": "Shared training and offline ledgers counted once; per-path analysis costs are descriptive, not added again. Peak RSS is not additive."}


def assemble(spec, input_sha256=None):
    require(spec.get("schema") == SCHEMA and set(spec["stages"]) == set(PHASES), "Unknown report-input schema/population")
    incomplete = {phase: spec["stages"][phase]["status"] for phase in PHASES if spec["stages"][phase]["status"] != "COMPLETE"}
    base = {"schema": "hepta.fullstudy.aggregate-results.1", "attempt_id": spec["attempt_id"], "input_sha256": input_sha256,
            "planned_gradient_microsteps": PLANNED, "resource_status": spec.get("resource_status"),
            "original_1GiB_2GiB_reserve_contract_passed": False,
            "historical_exact_regression_gate": spec.get("integrity", {}).get("historical_exact_regression_gate", "UNRESOLVED"),
            "prior_attempt_costs": prior_costs(spec)}
    if incomplete:
        return {**base, "status": "BLOCKED" if "BLOCKED" in incomplete.values() else "PENDING",
                "incomplete_stages": incomplete, "efficacy_artifacts_opened": False, "five_priority_findings": None,
                "actual_costs": None, "note": "Planned counts are not executed work. No unfinished endpoint outcomes were decoded."}
    operations = ready_operations(spec)
    protocol = read(spec["protocol"])
    require(all(op["scientific_protocol_sha256"] == spec["protocol"]["sha256"] for op in operations.values()), "Scientific protocol ancestry differs")
    complete, banks, mechanisms, endpoint, decoded = {}, [], {}, {}, {}
    for phase in PHASES:
        paths = []
        for run in spec["stages"][phase]["runs"]:
            value = read(run["complete"])
            require(value.get("complete") is True, "Unsealed scientific stage")
            complete[(phase, run["seed"])] = value
            if phase in ("A", "B"):
                value = read(run["paths"])
                require(value.get("complete") is True and value.get("training_complete") is True, "Unsealed paths")
                paths.extend(value["paths"])
            if phase == "A":
                banks.append(bank_diagnostics(read(run["bank"]), run.get("bank_outputs")))
            if phase == "C":
                stage = checked(run["complete"]).parent
                artifacts = {a["path"]: a for a in value["artifacts"]}
                for item in value["paths"]:
                    name = item["checkpoint"]["path"].replace(".pt.gz", ".trace.json.gz")
                    paths.append({**read(relative_descriptor(stage, artifacts[name])), **item})
                mechanisms["C_heads"] = {mode: read(relative_descriptor(stage, artifacts[f"heads/{mode}/HEAD.json"]))["head"] for mode in ("ordinary", "dual")}
        if phase in ("A", "B", "C"):
            require(len(paths) == {"A": 48, "B": 240, "C": 32}[phase], "Training path population differs")
            mechanisms[phase] = path_diagnostics(paths, phase)
    # No Torch/model imports before registered memory admission, even for analysis.
    from .resource_v2 import load_registration, training_slot
    amendment = spec["amendment"]
    registration = load_registration(checked(amendment), amendment["sha256"])
    require(all(op["operational_amendment_sha256"] == amendment["sha256"] for op in operations.values()), "Operation amendment differs")
    analyses, emitted = {}, {}
    with training_slot(spec["raw_root"], registration):
        from . import analysis, architecture_endpoints, endpoints
        for phase in ("A", "B", "C"):
            descriptor = spec["stages"][phase]["endpoint"]
            path = checked(descriptor)
            require(path.name == "ENDPOINTS.json", "Endpoint publication barrier has not completed")
            endpoint[phase] = read(descriptor)
            decoded[phase] = (architecture_endpoints if phase == "C" else endpoints).load_records(path, descriptor["sha256"])
            emitted[phase] = output_differences(descriptor, decoded[phase])
            if phase in ("B", "C"):
                analyses[phase] = analysis.summarize(decoded[phase], phase, protocol)
    development = development_summary(decoded["A"])
    costs = cost_rows(complete, operations, endpoint, spec)
    for phase in PHASES:
        require(sum(r["gradient_microsteps"] for r in costs["rows"] if r.get("phase") == phase and r["kind"] != "endpoint_scoring") == PLANNED[phase],
                "Actual completed gradient inventory differs from frozen design")
    reconstruction = [{key: value[key] for key in ("seed", "terminal_count", "all_original_component_and_receipt_hashes_equal",
                      "all_literal_terminal_restores_equal", "original_scientific_counts_changed", "new_fitting_or_selection",
                      "reconstructed_terminal_bytes_not_originally_archived")} for (phase, unused), value in complete.items() if phase == "R"]
    require(len(reconstruction) == 3 and all(row["terminal_count"] == 192 and row["all_original_component_and_receipt_hashes_equal"]
            and row["all_literal_terminal_restores_equal"] and not row["original_scientific_counts_changed"]
            and not row["new_fitting_or_selection"] and row["reconstructed_terminal_bytes_not_originally_archived"]
            for row in reconstruction), "R completion evidence differs from the fixed reconstruction contract")
    witness = complete[("W", None)]
    findings = [
        {"priority": 1, "topic": "Legal successors and actual activity", "banks": banks, "paths": mechanisms, "terminal_output_differences": emitted,
         "scope": "Hash, parameter/optimizer, and emitted-output diversity are distinct descriptive quantities."},
        {"priority": 2, "topic": "Baseline-aligned terminal labels and calibration", "reconstruction": reconstruction,
         "scope": "Calibration RMSE, attainable gain, and threshold remain per head; dependent calibration states give no uniform certificate. R adds evidence bytes and costs, not samples."},
        {"priority": 3, "topic": "Field/current-state/history information", "B_effects": analyses["B"]["effects"],
         "scope": "12-field versus 54,740-current-state and 114-history fitted heads. No oracle or future RNG exposure; W is constructed off policy."},
        {"priority": 4, "topic": "Independent benefit and measured cost", "development": development, "B_thresholds": analyses["B"]["statistical_thresholds"],
         "scope": "Threshold passage is separate from integrity, activity and cost admission. Fixed taper is the cheap baseline; no fitted retrospective price."},
        {"priority": 5, "topic": "Architecture by controller interaction", "C_effects": analyses["C"]["effects"], "C_thresholds": analyses["C"]["statistical_thresholds"],
         "scope": "Eight paired seeds; only the FPT event-law architecture increment. No complete HJB/NDU or LLM-scale claim."}]
    return {**base, "status": "COMPLETE", "efficacy_artifacts_opened": True, "five_priority_findings": findings,
            "formal_analyses": analyses, "actual_costs": costs, "constructed_witness": witness,
            "integrity": spec.get("integrity", {}), "overall_admission": "NOT_AUTOMATIC: all statistical, integrity, activity, and full-cost conditions remain separate.",
            "negative_results_retained": True}


def render(result):
    lines = ["# Parameter-field / Hepta full-study results", "", "Status: **" + result["status"] + "**.", "",
             "The original 1 GiB storage / 2 GiB reserve contract did not pass. Operational amendments and failed attempts remain part of the record.", ""]
    if result["status"] != "COMPLETE":
        lines += ["No unfinished scientific endpoint outcomes were opened. Planned work is separate from executed work.", "", "```json",
                  json.dumps({k: result[k] for k in ("incomplete_stages", "planned_gradient_microsteps", "resource_status", "prior_attempt_costs")}, indent=2), "```", ""]
        return "\n".join(lines)
    for finding in result["five_priority_findings"]:
        lines += [f"## {finding['priority']}. {finding['topic']}", "", finding["scope"], ""]
    mechanism = result["five_priority_findings"][0]
    lines += ["## Legal successor diagnostics", "", "| Seed | Parents | Multiple legal hashes | Multiple parameter/optimizer successors | Hash diversity only elsewhere | Distinct hard terminal outputs |",
              "|---|---:|---:|---:|---:|---:|"]
    for bank in mechanism["banks"]:
        counts = bank["counts"]
        lines.append("| " + " | ".join(str(x) for x in (bank["seed"], counts["parents"], counts.get("parents_with_multiple_complete_legal_hashes", 0),
                     counts.get("parents_with_multiple_parameter_optimizer_successors", 0), counts.get("parents_with_hash_diversity_only_in_other_components", 0),
                     bank["parents_with_distinct_terminal_hard_outputs"])) + " |")
    lines += ["", "Hash differences in incoming gradients may disappear when the next step clears gradients. Parameter/optimizer changes and emitted outputs are reported separately.", "",
              "| Phase / method | Paths | Overrides | Accepted overrides | Guard rejections | First parameter/optimizer divergence clocks |", "|---|---:|---:|---:|---:|---|"]
    for phase in ("A", "B", "C"):
        groups = defaultdict(list)
        for row in mechanism["paths"][phase]:
            groups[(row["architecture"], row["method"])].append(row)
        for (architecture, method), rows in groups.items():
            clocks = dict(Counter(str(r["first_parameter_optimizer_divergence_clock"]) for r in rows)) if phase != "C" else "not separately stored"
            label = phase + "/" + ((architecture + "+") if architecture else "") + method
            lines.append(f"| {label} | {len(rows)} | {sum(r['overrides'] for r in rows)} | {sum(r['accepted_overrides'] for r in rows)} | {sum(r['guard_rejections'] for r in rows)} | {clocks} |")
    lines += ["", "## Calibration versus attainable action gain", "", "| Model / head | Dimension | Calibration RMSE | Mean attainable gain | RMSE / gain | Threshold |", "|---|---:|---:|---:|---:|---:|"]
    heads = [(str(bank["seed"]) + "/" + name, head) for bank in mechanism["banks"] for name, head in bank["calibration"].items()]
    heads.extend(("C/" + mode, head) for mode, head in mechanism["paths"]["C_heads"].items())
    for name, head in heads:
        d = head["diagnostics"]
        lines.append("| " + " | ".join(str(v) for v in (name, head["dimension"], d["calibration_rmse"], d["mean_attainable_gain"], d["rmse_over_mean_attainable_gain"], head["threshold"])) + " |")
    lines += ["", "Calibration states are dependent; these maxima are empirical screens, not uniform error bounds or confidence guarantees.", ""]
    for phase, summary in result["formal_analyses"].items():
        lines += ["## " + phase + " registered effects", "", summary["scope"], "",
                  "| Effect | Observer | Point | Corrected interval |", "|---|---|---:|---:|"]
        for name, effect in summary["effects"].items():
            for observer in ("reward", "audit"):
                low, high = effect["ci"][observer]
                lines.append(f"| {name} | {observer} | {effect['point'][observer]:.9g} | [{low:.9g}, {high:.9g}] |")
        lines += ["", "Threshold outcomes: `" + json.dumps(summary["statistical_thresholds"], sort_keys=True) + "`.", ""]
    witness = result["constructed_witness"]
    lines += ["## Constructed momentum diagnostic", "", "| Seed | Near-field criterion | Action ranking changed | Best-action set changed |", "|---|---|---|---|"]
    for row in witness["records"]:
        lines.append(f"| {row['seed']} | {row['near_field']} | {row['ranking_changed']} | {row['best_action_set_changed']} |")
    lines += ["", "These constructed states do not establish reachable policy occupancy or independent efficacy.", ""]
    costs = result["actual_costs"]
    lines += ["## Costs and limitations", "", f"Completed receipt-backed gradient work: **{costs['completed_receipt_gradient_microsteps']:,} microsteps**. "
              f"Known lower bound across all attempts: **{costs['all_attempts_gradient_microsteps_known_lower_bound']:,}**. "
              "Unlogged partial work remains unknown; peak RSS is not additive. Full separate ledgers, negative results, mechanism counts, calibration diagnostics, and all fixed-seed effects are preserved in RESULTS.json.", "",
              "Passing statistical thresholds alone does not grant admission or establish a quality-cost Pareto improvement. This experiment does not solve the full HJB/NDU system or establish LLM-scale effects.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    require(sha(args.inputs) == args.expected_sha256, "Report input manifest differs")
    result = assemble(json.loads(Path(args.inputs).read_text()), args.expected_sha256)
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "RESULTS.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (directory / "REPORT.md").write_text(render(result))


if __name__ == "__main__":
    main()
