"""Read-only reconciliation of an existing neuroscience run; never trains.

Usage: python review_recovery.py --repo REPO --run RUN --output REPORT
Restores retained final checkpoints, reconstructs input data and schedules, and
uses forward inference only to validate final probe losses. No optimizer runs.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True)
parser.add_argument("--run", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--source", default="f7f78c88289999ced04bbedd9b4790b9729d972d")
args = parser.parse_args()
repo, run, output = (Path(p).resolve() for p in (args.repo, args.run, args.output))
if output.exists() or run == output or run in output.parents:
    raise ValueError("report must be a new path outside the original run")
sys.path.insert(0, str(repo))
from qualification.cell_common_foundations.credit import Model, copy_episode, forward, make_model
from qualification.cell_common_foundations.credit_axes import credit_axes_data
from qualification.cell_common_foundations.learning_clocks import LearningClock
from qualification.cell_common_foundations.memory_replay import ReplayPool, KINDS, make_item
from qualification.cell_common_foundations.protocol import canonical_digest
from qualification.cell_common_foundations.run_neuroscience import inspect_run


def deny_training(*arguments, **keywords):
    raise RuntimeError("this read-only review refuses gradient or optimizer execution")


for module_name in ("credit", "learning_clocks", "memory_replay"):
    module = sys.modules["qualification.cell_common_foundations." + module_name]
    for name in ("gradient", "propose"):
        setattr(module, name, deny_training)


checks = Counter()
issues, limitations = [], []


def check(category, condition, context=""):
    checks[category] += 1
    if not bool(condition):
        issues.append({"category": category, "context": context})


def fingerprints(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


before = fingerprints(run)
inspection = inspect_run(run)
plan = json.loads((run / "PLAN.json").read_text())
report = json.loads((run / "RESULT.json").read_text())
check("run_reconciliation", inspection["execution_complete"])
check("derived_report", canonical_digest(inspection) == canonical_digest({k: report[k] for k in inspection}))
check("source_commit", plan["git"]["commit"] == args.source)
check("clean_source_at_run", plan["git"]["status"] == "")
check("source_unchanged", inspection["source_unchanged"] is True)
head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
check("review_source_commit", head == args.source, head)
for relative, item in plan["source"]["files"].items():
    committed = subprocess.check_output(["git", "-C", str(repo), "show", f"{args.source}:{relative}"])
    check("source_bytes", hashlib.sha256(committed).hexdigest() == item["sha256"], relative)
    check("loaded_source_bytes", (repo / relative).read_bytes() == committed, relative)

rows = [r["result"] for r in inspection["attempt_records"]]
by_family = defaultdict(list)
for row in rows:
    by_family[row["family"]].append(row)
    check("completed_records", row["status"] == "completed", row["attempt_id"])
    updates = (row["step_receipts"] if row["family"] == "credit_axes" else
               [r["update"] for r in row["update_receipts"]] if row["family"] == "learning_clocks" else
               row["update_receipts"])
    previous = row["initial_model_digest"]
    check("initial_model", previous == make_model(row["seed"]).digest, row["attempt_id"])
    for index, receipt in enumerate(updates):
        label = f"{row['attempt_id']}:{index}"
        check("receipt_chain", receipt["selected_digest"] == previous, label)
        check("receipt_no_update", receipt["no_update"] == (receipt["selected_digest"] == receipt["candidate_digest"]), label)
        check("receipt_bounds", 0 <= receipt["global_relative_norm"] <= 0.0025 + 1e-12 and
              all(0 <= x <= 0.005 + 1e-12 for x in receipt["layer_relative_norms"].values()), label)
        check("no_adoption", receipt["native_adoption_qualified"] is False, label)
        previous = receipt["candidate_digest"]
    check("final_model_chain", previous == row["final_model_digest"], row["attempt_id"])

credit_groups, credit_data = defaultdict(list), {}
for row in by_family["credit_axes"]:
    label = row["attempt_id"]
    credit_groups[row["comparison_id"]].append(row)
    count = row["counts"]
    check("credit_update_counts", count["optimizer_updates"] == len(row["step_receipts"]) == row["updates"], label)
    check("credit_observations", count["training_observations"] == row["updates"] * row["horizon"], label)
    supervised = row["updates"] * (row["horizon"] if row["timing"] == "dense" else 1)
    check("credit_supervision", count["supervised_events"] == supervised, label)
    check("credit_training_ids", [r["task_id"] for r in row["training_rows"]] ==
          [r["task_id"] for r in row["step_receipts"]] ==
          [r["task_id"] for r in row["data_manifest"]["train"]], label)
    check("credit_training_models", [r["model_digest"] for r in row["training_rows"]] ==
          [r["selected_digest"] for r in row["step_receipts"]], label)
    check("credit_eval_ids", [r["task_id"] for r in row["evaluation_rows"]] ==
          [r["task_id"] for r in row["data_manifest"]["evaluation"]], label)
    check("credit_split_disjoint", not ({r["task_id"] for r in row["training_rows"]} &
          {r["task_id"] for r in row["evaluation_rows"]}), label)
    pair = (row["seed"], row["horizon"])
    if pair not in credit_data:
        credit_data[pair] = {
            name: credit_axes_data(row["seed"], row["horizon"], name, row["updates"])
            for name in ("train", "evaluation")
        }
    raw = credit_data[pair]
    expected_manifest = {name: value[1] for name, value in raw.items()}
    check("credit_data_reconstruction", row["data_manifest"] == expected_manifest and
          row["data_digest"] == canonical_digest(expected_manifest), label)
    raw_hashes = {name: {canonical_digest({"inputs": x.tolist(), "messages": m.tolist()})
                        for _, x, _, m in value[0]} for name, value in raw.items()}
    check("credit_raw_split_disjoint", not (raw_hashes["train"] & raw_hashes["evaluation"]), label)
    check("credit_changed_count", count["changed_updates"] == sum(not r["no_update"] for r in row["step_receipts"]), label)
    change = np.mean([r["final_loss"] - r["initial_loss"] for r in row["evaluation_rows"]])
    check("credit_mean", change == row["mean_evaluation_loss_change"], label)
    if row["method"] == "zero_feedback":
        check("zero_feedback", row["initial_model_digest"] == row["final_model_digest"] and
              count["changed_updates"] == 0, label)
for group, values in credit_groups.items():
    check("credit_pairing", len(values) == 7 and len({r["method"] for r in values}) == 7 and
          len({r["data_digest"] for r in values}) == 1 and
          len({r["supervision_digest"] for r in values}) == 1 and
          len({r["initial_model_digest"] for r in values}) == 1, group)

clock_review, clock_by_seed = [], defaultdict(dict)
for row in by_family["learning_clocks"]:
    label = row["attempt_id"]
    clock_by_seed[row["seed"]][row["method"]] = row
    model, restored = LearningClock.restore(row["final_checkpoint"])
    check("clock_restore", restored.checkpoint(model) == row["final_checkpoint"], label)
    check("clock_model_restore", model.digest == row["final_model_digest"], label)
    ticks, cursor, updates, last = row["steps"], 0, [0] * 7, [0] * 7
    receipts = row["update_receipts"]
    for tick, receipt in enumerate(receipts, 1):
        due = [i for i, p in enumerate(row["periods"]) if tick % p == 0]
        if row["method"] == "uniform_all":
            due = list(range(7))
        elif row["method"] == "budget_round_robin":
            due = [(cursor + i) % 7 for i in range(len(due))]
            cursor = (cursor + len(due)) % 7
        check("clock_schedule", receipt["groups"] == due and receipt["tick"] == tick, f"{label}:{tick}")
        check("clock_buffer_samples", receipt["buffered_samples"] == [tick - last[i] for i in due], f"{label}:{tick}")
        check("clock_buffer_sources", receipt["first_model_digests"] ==
              [receipts[last[i]]["update"]["selected_digest"] for i in due], f"{label}:{tick}")
        check("clock_current_source", receipt["current_model_digest"] == receipt["update"]["selected_digest"], f"{label}:{tick}")
        for i in due:
            last[i] = tick
            updates[i] += 1
    pending = [ticks - t for t in last]
    p = row["final_checkpoint"]["payload"]
    check("clock_final_counts", updates == row["group_updates"] == p["group_updates"] and
          sum(updates) == row["group_update_slots"] and pending == row["pending_counts"] == p["counts"], label)
    check("clock_final_cursor", cursor == p["cursor"], label)
    check("clock_count_budget", row["optimizer_calls"] == row["gradient_calls"] ==
          row["unique_supervision_events"] == len(receipts) == ticks and row["training_timesteps"] == ticks * 8, label)
    expected_first = [None if t == ticks else receipts[t]["update"]["selected_digest"] for t in last]
    check("clock_pending_sources", p["first_source"] == expected_first, label)
    rng = np.random.default_rng(row["seed"] + 900)
    stream = [copy_episode(rng, 8) for _ in range(ticks)]
    probe = [copy_episode(rng, 8) for _ in range(8)]
    check("clock_data", canonical_digest([[a.tolist() for a in e] for e in stream]) == row["data_digest"], label)
    final_losses = [[float(0.5 * np.sum(f[:, None] * (forward(model, x, m)[1] - phase * y) ** 2))
                     for x, y, f, m in probe] for phase in (1, -1)]
    check("clock_final_probe", np.allclose(final_losses, row["probe_losses_initial_mid_final"][-1], rtol=0, atol=1e-15), label)
    clock_review.append({"attempt_id": label, "method": row["method"], "seed": row["seed"],
                         "group_update_slots": sum(updates), "group_updates": updates,
                         "pending_counts": pending, "checkpoint_roundtrip": True})
clock_budget_pairs = []
for seed, values in clock_by_seed.items():
    lineage, rr = values["lineage"], values["budget_round_robin"]
    same = [len(r["groups"]) for r in lineage["update_receipts"]] == [len(r["groups"]) for r in rr["update_receipts"]]
    check("clock_paired_slots", same, str(seed))
    check("clock_paired_data", len({r["data_digest"] for r in values.values()}) == 1, str(seed))
    clock_budget_pairs.append({"seed": seed, "per_tick_budget_equal": same,
                               "lineage_slots": lineage["group_update_slots"],
                               "round_robin_slots": rr["group_update_slots"],
                               "uniform_slots": values["uniform_all"]["group_update_slots"]})

replay_review, replay_by_seed = [], defaultdict(list)
unverifiable_priority_steps = []
for row in by_family["memory_replay"]:
    label = row["attempt_id"]
    replay_by_seed[row["seed"]].append(row)
    p = row["final_checkpoint"]["payload"]
    restored = ReplayPool.restore(row["final_checkpoint"], p["scope"], p["versions"])
    check("replay_restore", restored.checkpoint() == row["final_checkpoint"], label)
    model = Model(**row["final_model"])
    check("replay_model_restore", model.digest == row["final_model_digest"], label)
    stream = [make_item(row["seed"] + 800, i, phase) for phase in (0, 1) for i in range(16)]
    data = {e.item_id: e for e in stream}
    check("replay_data", canonical_digest([e.payload() for e in stream]) == row["data_digest"], label)
    state, versions, selection_index = [], dict.fromkeys(KINDS, "v1"), 0
    rng, priorities = np.random.default_rng(row["seed"]), {e["item_id"]: e["priority"] for e in p["items"]}
    selected_ids, steps, payload_bytes = [], 0, 0
    for position, entry in enumerate(stream):
        if versions[entry.source] != entry.version:
            versions[entry.source] = entry.version
            state = [e for e in state if versions[e.source] == e.version]
        state = (state + [entry])[-p["capacity"]:]
        if position < row["warmup"]:
            continue
        selection = row["replay_selections"][selection_index]
        selection_index += 1
        ids = selection["ids"]
        allowed = {e.item_id: e for e in state}
        check("replay_temporal_admission", selection["position"] == position and len(ids) == len(set(ids)) and
              all(i in allowed for i in ids), f"{label}:{position}")
        check("replay_source_admission", all(allowed[i].split == "train" and allowed[i].scope == p["scope"]
              and versions[allowed[i].source] == allowed[i].version for i in ids), f"{label}:{position}")
        policy = row["method"]
        kind = "error" if policy == "error_prioritized" else policy
        candidates = [e for e in state if policy == "uniform" or e.kind == kind]
        exact = True
        if policy == "none":
            candidates = []
        if policy == "error_prioritized":
            exact = all(e.item_id in priorities for e in candidates)
            if exact:
                candidates.sort(key=lambda e: (-priorities[e.item_id], e.item_id))
            else:
                unverifiable_priority_steps.append({"attempt_id": label, "position": position})
        else:
            candidates = [candidates[i] for i in rng.permutation(len(candidates))]
        expected, consumed = [], 0
        for e in candidates:
            n = len(e.episode[0])
            if len(expected) < row["entry_budget"] and consumed + n <= row["timestep_budget"]:
                expected.append(e.item_id)
                consumed += n
        if exact:
            check("replay_choice_reconstruction", ids == expected, f"{label}:{position}")
        else:
            check("replay_priority_subset", all(allowed[i].kind == "error" for i in ids), f"{label}:{position}")
        actual_steps = sum(len(data[i].episode[0]) for i in ids)
        actual_bytes = sum(a.nbytes for i in ids for a in data[i].arrays())
        check("replay_selection_counts", selection["entry_presentations"] == len(ids) and
              selection["timesteps"] == actual_steps and selection["numeric_payload_bytes"] == actual_bytes and
              len(ids) <= row["entry_budget"] and actual_steps <= row["timestep_budget"], f"{label}:{position}")
        selected_ids.extend(ids)
        steps += actual_steps
        payload_bytes += actual_bytes
    check("replay_final_pool", [e.item_id for e in state] == [e["item_id"] for e in p["items"]] and versions == p["versions"], label)
    check("replay_final_rng", canonical_digest(rng.bit_generator.state) == canonical_digest(p["rng"]), label)
    check("replay_counters", len(selected_ids) == row["replay_presentations"] == p["presentations"] and
          steps == row["replay_timesteps"] == p["timesteps"] and
          payload_bytes == row["replay_numeric_payload_bytes"] == p["numeric_payload_bytes"] and
          sorted(set(selected_ids)) == p["distinct"] and len(set(selected_ids)) == row["distinct_replayed_entries"] and
          selection_index == len(row["replay_selections"]) == p["calls"] == row["steps"], label)
    check("replay_label_count", len(stream) + len(selected_ids) == row["total_label_exposures"] ==
          row["gradient_calls"] == row["optimizer_calls"] == len(row["update_receipts"]), label)
    check("replay_unique_labels", len(stream) == row["unique_training_entries"] == row["unique_supervision_events"], label)
    probes = [[make_item(row["seed"] + 1800, i, phase, "holdout") for i in range(16)] for phase in (0, 1)]
    check("replay_probe_ids", [[e.item_id for e in group] for group in probes] == row["probe_ids"], label)
    check("replay_probe_kinds", [[e.kind for e in group] for group in probes] == row["probe_kinds"], label)
    check("replay_obsolete_workflow", [[phase == 0 and e.kind in ("procedure", "error")
                                        for e in group] for phase, group in enumerate(probes)] ==
          row["probe_obsolete_workflow"], label)
    check("replay_split_disjoint", not ({e.item_id for group in probes for e in group} & set(selected_ids)), label)
    audit = row["data_split_audit"]
    expected_fingerprints = {}
    for split, values in (("train", stream), ("probe", [e for group in probes for e in group])):
        expected_fingerprints[split] = []
        for e in values:
            x, y, feedback, messages = e.arrays()
            expected_fingerprints[split].append({
                "item_id": e.item_id, "kind": e.kind,
                "input_message_sha256": canonical_digest({"inputs": x.tolist(), "messages": messages.tolist()}),
                "supervised_payload_sha256": canonical_digest([a.tolist() for a in (x, y, feedback, messages)]),
            })
    check("replay_raw_fingerprints", expected_fingerprints == audit["fingerprints"], label)
    overlaps = {key: sorted({e[key] for e in expected_fingerprints["train"]} &
                            {e[key] for e in expected_fingerprints["probe"]})
                for key in ("input_message_sha256", "supervised_payload_sha256")}
    check("replay_raw_split_disjoint", overlaps == audit["cross_split_overlaps"] and not any(overlaps.values()), label)
    unique = {split: {kind: len({e["input_message_sha256"] for e in values if e["kind"] == kind})
                      for kind in KINDS} for split, values in expected_fingerprints.items()}
    check("replay_payload_diversity", unique == audit["unique_input_payloads_by_kind"] and
          all(count == 8 for counts in unique.values() for count in counts.values()), label)
    check("replay_audit_digest", audit["passed"] is True and canonical_digest(audit) == row["data_split_audit_digest"], label)
    final_losses = [[float(0.5 * np.sum(e.arrays()[2][:, None] *
                    (forward(model, e.arrays()[0], e.arrays()[3])[1] - e.arrays()[1]) ** 2))
                    for e in group] for group in probes]
    check("replay_final_probe", np.allclose(final_losses, row["probe_losses_initial_mid_final"][-1], rtol=0, atol=1e-15), label)
    replay_review.append({"attempt_id": label, "seed": row["seed"], "method": row["method"],
                          "replay_presentations": len(selected_ids), "distinct_entries": len(set(selected_ids)),
                          "replay_timesteps": steps, "numeric_payload_bytes": payload_bytes,
                          "label_exposures": row["total_label_exposures"], "checkpoint_roundtrip": True})
for seed, values in replay_by_seed.items():
    replay = [r for r in values if r["method"] != "none"]
    check("replay_paired_data", len(values) == 7 and len({r["data_digest"] for r in values}) == 1 and
          len({canonical_digest(r["probe_ids"]) for r in values}) == 1, str(seed))
    for k in ("replay_presentations", "replay_timesteps", "replay_numeric_payload_bytes", "total_label_exposures"):
        check("replay_paired_budget", len({r[k] for r in replay}) == 1, f"{seed}:{k}")

limitations.extend([
    "Checksums and model digests establish consistency, not independent owner authentication.",
    "Credit-axis final tensor bytes are not retained; receipt chains and paired records were checked without reconstructing optimizer trajectories.",
    "Clock midpoint checkpoint only retains its digest; midpoint cold restore cannot be independently reconstructed from retained bytes. All nine final checkpoints were restored.",
    "Replay intermediate model/pool snapshots are not retained; all 21 final model/pool states were restored and final losses re-evaluated by forward inference only.",
    "Error-prioritized choices before the new error-source version arrives lack retained priorities for subsequently evicted v1 items. Admissibility and budgets were checked; exact priority ordering for those steps remains unknown.",
    "No gradient, optimizer, training, full panel rerun or external task execution was performed by this review.",
])
after = fingerprints(run)
check("original_run_unmodified", before == after)
summary = {
    "schema": "hepta.neuroscience-recovery-review.v1",
    "status": "CONSISTENCY_CHECKS_PASSED_WITH_LIMITS" if not issues else "INCONSISTENCIES_FOUND",
    "source_commit": args.source, "run_binding_digest": plan["binding_digest"],
    "training_guard": "gradient_and_propose_replaced_with_rejecting_functions_for_this_review_process",
    "review_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "retained_file_count": len(before), "retained_files_digest": canonical_digest(before),
    "original_run_unmodified": before == after,
    "attempt_counts": {k: len(v) for k, v in by_family.items()},
    "checks_by_category": dict(sorted(checks.items())), "total_checks": sum(checks.values()),
    "inconsistencies": issues, "limitations": limitations,
    "clock_attempts": clock_review, "clock_budget_pairs": clock_budget_pairs,
    "replay_attempts": replay_review,
    "unverifiable_early_priority_steps": unverifiable_priority_steps,
    "scientific_acceptance": "HOLD", "production_adoption": "not_granted",
}
with output.open("x", encoding="utf-8") as stream:
    json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
print(json.dumps({k: summary[k] for k in ("status", "attempt_counts", "total_checks", "inconsistencies", "original_run_unmodified")}, indent=2))
print("unverifiable_early_priority_steps", len(unverifiable_priority_steps))
