#!/usr/bin/env python3
"""Reduce retained Hepta development results; never import or run learning code.

Only stdlib is needed. This recomputes descriptive statistics from RESULT.json,
not the separate numerical-generator or checkpoint-restoration audit.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cost(records):
    return {
        key: {"sum": sum(values), "mean": fmean(values), "min": min(values), "max": max(values)}
        for key in ("execution_wall_seconds", "execution_cpu_seconds")
        if (values := [row[key] for row in records])
    } | {"energy_joules": None}


def receipts(result):
    rows = result.get("step_receipts", result.get("update_receipts", []))
    return [row.get("update", row) for row in rows]


def counts(records):
    results = [row["result"] for row in records]
    updates = [update for result in results for update in receipts(result)]
    return {
        "attempts": len(records),
        "gradient_calls": sum(r.get("gradient_calls", r.get("counts", {}).get(
            "gradient_calls_completed", 0)) for r in results),
        "optimizer_calls": sum(r.get("optimizer_calls", r.get("counts", {}).get(
            "optimizer_updates", 0)) for r in results),
        "label_exposures": sum(r.get("total_label_exposures", r.get("unique_supervision_events",
            r.get("counts", {}).get("supervised_events", 0))) for r in results),
        "update_receipts": len(updates),
        "changed_update_receipts": sum(u["selected_digest"] != u["candidate_digest"] for u in updates),
        "no_update_receipts": sum(u["no_update"] for u in updates),
        "final_models_changed": sum(r["initial_model_digest"] != r["final_model_digest"] for r in results),
        "distinct_initial_model_digests": len({r["initial_model_digest"] for r in results}),
        "distinct_final_model_digests": len({r["final_model_digest"] for r in results}),
    }


def replay_slices(result):
    loss = result["probe_losses_initial_mid_final"]
    slices = {
        "stable_phase0_fact_episode": (0, [i for i in range(16) if i % 4 < 2]),
        "obsolete_phase0_procedure_error": (0, [i for i in range(16) if i % 4 >= 2]),
        "current_phase1_all": (1, list(range(16))),
        "current_phase1_stable_fact_episode": (1, [i for i in range(16) if i % 4 < 2]),
        "current_phase1_changed_procedure_error": (1, [i for i in range(16) if i % 4 >= 2]),
        "phase0_fact": (0, list(range(0, 16, 4))),
        "phase0_episode": (0, list(range(1, 16, 4))),
    }
    return {name: [fmean(snapshot[phase][i] for i in indices) for snapshot in loss]
            for name, (phase, indices) in slices.items()}


def analyze(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    records = data["attempt_records"]
    require(all(row["status"] == "completed" for row in records), "Incomplete roster")
    require(len({r["attempt_id"] for r in records}) == len(records), "Duplicate attempt")
    families = defaultdict(list)
    for row in records:
        families[row["family"]].append(row)
        previous = row["result"]["initial_model_digest"]
        for update in receipts(row["result"]):
            require(update["selected_digest"] == previous, "Broken update chain")
            require(update["no_update"] == (previous == update["candidate_digest"]), "NoUpdate mismatch")
            require(not update["native_adoption_qualified"], "Unexpected native claim")
            previous = update["candidate_digest"]
        require(previous == row["result"]["final_model_digest"], "Final model mismatch")
    credit_groups = defaultdict(lambda: defaultdict(list))
    for row in families["credit_axes"]:
        r = row["result"]
        credit_groups[(r["horizon"], r["timing"], r["coverage"])][row["method"]].append(row)
    credit = []
    for (horizon, timing, coverage), groups in sorted(credit_groups.items()):
        methods = {}
        for method, rows in sorted(groups.items()):
            seed_rows = []
            for row in sorted(rows, key=lambda x: x["seed"]):
                evaluation = row["result"]["evaluation_rows"]
                change = fmean(e["final_loss"] - e["initial_loss"] for e in evaluation)
                require(abs(change - row["result"]["mean_evaluation_loss_change"]) < 1e-14, "Credit mean mismatch")
                seed_rows.append({"seed": row["seed"], "loss_change": change,
                                  "initial_loss": fmean(e["initial_loss"] for e in evaluation),
                                  "final_loss": fmean(e["final_loss"] for e in evaluation)})
            methods[method] = {"mean_loss_change": fmean(r["loss_change"] for r in seed_rows),
                               "per_seed": seed_rows, "cost": cost(rows)}
        credit.append({"horizon": horizon, "timing": timing, "coverage": coverage, "methods": methods})
    clocks, replay = {}, {}
    budget_keys = ("gradient_calls", "optimizer_calls", "unique_training_entries",
                   "unique_supervision_events", "total_label_exposures", "replay_presentations",
                   "replay_timesteps", "replay_numeric_payload_bytes")
    clock_keys = ("group_update_slots", "group_updates", "gradient_calls",
                  "optimizer_calls", "training_timesteps")
    for family in ("learning_clocks", "memory_replay"):
        for method in sorted({r["method"] for r in families[family]}):
            rows = sorted((r for r in families[family] if r["method"] == method), key=lambda x: x["seed"])
            if family == "learning_clocks":
                per_seed = [{"seed": row["seed"],
                             **{key: row["result"][key] for key in clock_keys},
                             "phase_loss_by_snapshot": [[fmean(phase) for phase in snapshot]
                                 for snapshot in row["result"]["probe_losses_initial_mid_final"]]}
                            for row in rows]
                curve = [[fmean(r["phase_loss_by_snapshot"][snapshot][phase] for r in per_seed)
                          for phase in range(2)] for snapshot in range(3)]
                clocks[method] = {"per_seed": per_seed, "mean_phase_loss_by_snapshot": curve,
                                  "cost": cost(rows)}
            else:
                per_seed = [{"seed": row["seed"],
                             **{key: row["result"][key] for key in budget_keys},
                             "distinct_replayed_entries": row["result"]["distinct_replayed_entries"],
                             "slices": replay_slices(row["result"])} for row in rows]
                curves = {name: [fmean(r["slices"][name][snapshot] for r in per_seed)
                                 for snapshot in range(3)] for name in per_seed[0]["slices"]}
                replay[method] = {"per_seed": per_seed, "mean_loss_by_slice_snapshot": curves,
                                  "cost": cost(rows)}
    for method, value in replay.items():
        uniform = {r["seed"]: r for r in replay["uniform"]["per_seed"]}
        value["paired_final_difference_vs_uniform"] = {
            name: {"mean": fmean(r["slices"][name][2] - uniform[r["seed"]]["slices"][name][2]
                                 for r in value["per_seed"]), "budget_matched": method != "none"}
            for name in value["mean_loss_by_slice_snapshot"]
        }
    audits, fingerprints = [], {split: defaultdict(set) for split in ("train", "probe")}
    kinds = {split: defaultdict(set) for split in ("train", "probe")}
    for row in families["memory_replay"]:
        r = row["result"]
        if "data_split_audit" not in r:
            continue
        audit = r["data_split_audit"]
        require(digest(audit) == r["data_split_audit_digest"], "Replay audit digest mismatch")
        overlaps = {}
        for key in ("input_message_sha256", "supervised_payload_sha256"):
            train = {x[key] for x in audit["fingerprints"]["train"]}
            probe = {x[key] for x in audit["fingerprints"]["probe"]}
            overlaps[key] = sorted(train & probe)
            require(overlaps[key] == audit["cross_split_overlaps"][key], "Audit overlap mismatch")
        for split, items in audit["fingerprints"].items():
            for item in items:
                for key in ("item_id", "input_message_sha256", "supervised_payload_sha256"):
                    fingerprints[split][key].add(item[key])
                kinds[split][item["kind"]].add(item["input_message_sha256"])
        audits.append({"attempt_id": row["attempt_id"], "seed": row["seed"],
                       "overlap_counts": {k: len(v) for k, v in overlaps.items()}})
    credit_samples = {}
    for split in ("train", "evaluation"):
        manifest = [x for row in families["credit_axes"] for x in row["result"]["data_manifest"][split]]
        credit_samples[split] = {"task_ids": len({x["task_id"] for x in manifest}),
                                "numeric_payloads": len({x["payload_sha256"] for x in manifest})}
    samples = {
        "credit_manifest_counts": credit_samples,
        "clock_unique_streams": len({(row["seed"], row["result"]["data_digest"])
                                    for row in families["learning_clocks"]}),
        "clock_scope": "Stream digests only; raw sample deduplication requires the independent generator audit.",
        "replay_audits_present": len(audits), "replay_audits_missing": len(families["memory_replay"]) - len(audits),
        "replay_per_attempt_audits": audits,
        "replay_counts": {split: {key: len(values) for key, values in fields.items()}
                          for split, fields in fingerprints.items()},
        "replay_unique_inputs_by_kind": {split: {key: len(values) for key, values in fields.items()}
                                         for split, fields in kinds.items()},
        "replay_global_overlap_counts": {
            key: len(fingerprints["train"][key] & fingerprints["probe"][key])
            for key in ("input_message_sha256", "supervised_payload_sha256")
        } if audits else None,
        "scope": "Stored fingerprints checked, not regenerated. Missing audit is unknown, never a pass.",
    }
    return {
        "schema": "hepta.neuroscience-descriptive-reduction.v1",
        "result_sha256": hashlib.sha256(raw).hexdigest(), "source_commit": data["git"]["commit"],
        "plan_digest": data["plan_digest"], "binding_digest": data["binding_digest"],
        "attempts_by_family": dict(Counter(r["family"] for r in records)),
        "development_seeds": sorted({r["seed"] for r in records}),
        "scientific_acceptance": data["scientific_acceptance"], "production_adoption": data["production_adoption"],
        "independent_real_task_count": data["independent_real_task_count"],
        "update_accounting": {family: counts(rows) for family, rows in families.items()} | {"all": counts(records)},
        "credit_strata": credit, "learning_clocks": clocks, "memory_replay": replay,
        "recorded_sample_evidence": samples, "runner_cost": data["cost"], "attempt_cost": cost(records),
        "per_attempt": [{key: row[key] for key in (
            "attempt_id", "family", "method", "seed", "execution_wall_seconds", "execution_cpu_seconds")}
            | {"energy_joules": None} for row in records],
        "limitations": [
            "Descriptive development results; no p values or confirmation claims.",
            "Credit comparisons stay within timing/horizon/coverage; dense labels and objective differ.",
            "Known fixed readout signs are supplied, not learned credit assignment.",
            "Clock group slots do not equal FLOPs or full-gradient cost.",
            "Replay none has fewer labels/updates; synthetic strata are not actual tool failures.",
            "Obsolete phase0 procedure/error targets are not an old-task retention gate.",
            "This reducer does not restore checkpoints, reconstruct generators, or establish owner authentication.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="Retained RESULT.json, read only")
    parser.add_argument("--output", type=Path, help="Create a new JSON file; refuse overwrite")
    args = parser.parse_args()
    rendered = json.dumps(analyze(args.result), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
