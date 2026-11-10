"""Five-arm controlled SQLite experiment; real tools, fixture authority only."""

import argparse
import gzip
import hashlib
import json
import platform
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

from models import Model, gradient_check
from sqlite_destination import BudgetExhausted, Destination


OPTIONS = ("inspect", "ensure", "stop")
ARMS = ("B0_workflow", "B1_macro", "B2_flat", "B3_head", "B4_gru")


def encode(destination):
    view, last = destination.view, destination.last
    return [int(view is not None), int(bool(view and view["complete"])),
            int(bool(view and view["staged"])), int(last == "ensure"),
            int(last == "inspect"), int(last == "stage"), int(last == "apply"),
            view["matched"] / len(destination.task["goals"]) if view else 0,
            min(destination.failed_reads, 2) / 2, 1]


def macro(destination):
    if destination.failed_reads >= 2:
        return "stop"
    if destination.last in ("ensure", "apply") or destination.view is None:
        return "inspect"
    return "stop" if destination.view["complete"] else "ensure"


def primitive(destination):
    if destination.last == "stage":
        return "apply"
    option = macro(destination)
    if option == "ensure":
        return "apply" if destination.view["staged"] else "stage"
    return option


def tasks(split):
    output = []
    schemas = (0, 1) if split == "train" else (2, 3)
    destinations = ("train-a", "train-b") if split == "train" else ("confirm-c", "confirm-d")
    lengths = (1, 2) if split == "train" else (3, 4)
    faults = ("normal", "prestaged", "already_partial", "lost_reply", "opaque_after_apply")
    for schema in schemas:
        for destination in destinations:
            for length in lengths:
                for fault in faults:
                    for replicate in range(2):
                        identity = f"{split}/{destination}/schema-{schema}/keys-{length}/{fault}/{replicate}"
                        goals = [hashlib.sha256(f"{identity}:{i}".encode()).hexdigest() for i in range(length)]
                        output.append({"id": identity, "destination": destination, "schema": schema,
                                       "composition": length, "fault": fault, "goals": goals})
    return output


def episode(task, arm, model, directory, keep_trace):
    directory.mkdir(parents=True)
    destination = Destination(directory / "destination.db", task)
    features, actions, decisions, claimed, inference_ns = [], [], [], False, 0
    inference_cpu_ns = 0
    state = np.zeros(model.hidden) if arm == "B4_gru" else None
    try:
        for _ in range(2 * destination.budget):
            features.append(encode(destination))
            before = time.perf_counter_ns()
            cpu_before = time.process_time_ns()
            if arm in ("B3_head", "B4_gru"):
                choice, state = model.choose(features[-1], state)
                action = OPTIONS[choice]
            elif arm == "B1_macro":
                action = macro(destination)
            else:
                action = primitive(destination)
            inference_ns += time.perf_counter_ns() - before
            inference_cpu_ns += time.process_time_ns() - cpu_before
            decisions.append(action)
            if keep_trace:
                actions.append(OPTIONS.index(action))
            if action == "stop":
                current = destination.inspect()
                claimed = bool(current and current["complete"])
                break
            getattr(destination, action)()
    except BudgetExhausted:
        pass
    score = destination.score(claimed)
    score.update(task_id=task["id"], arm=arm, destination=task["destination"],
                 schema=task["schema"], composition=task["composition"], fault=task["fault"],
                 policy_decisions=len(decisions), inference_ns=inference_ns,
                 inference_cpu_ns=inference_cpu_ns, private_state_bytes=state.nbytes if state is not None else 0,
                 events=destination.events, decisions=decisions)
    score["policy_visible_features"] = features
    return score, (features[:len(actions)], actions)


def arrays(traces):
    length = max(len(x) for x, _ in traces)
    x = np.zeros((len(traces), length, 10))
    y = np.zeros((len(traces), length, 3))
    mask = np.zeros((len(traces), length))
    for i, (features, actions) in enumerate(traces):
        x[i, :len(features)] = features
        y[i, :len(actions)] = np.eye(3)[actions]
        mask[i, :len(actions)] = 1
    return x, y, mask


def compressed_jsonl(path, rows):
    with path.open("wb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as stream:
            for row in rows:
                stream.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())


def summarize(rows):
    results = {}
    for arm in ARMS:
        records = [row for row in rows if row["arm"] == arm]
        results[arm] = {"episodes": len(records), "actual_complete": sum(row["complete"] for row in records),
                        "reported_success": sum(row["claimed_success"] for row in records),
                        "unknown": sum(row["unknown"] for row in records),
                        "false_success": sum(row["claimed_success"] and not row["complete"] for row in records),
                        "duplicate_effects": sum(row["duplicate_effects"] for row in records),
                        "partial_effect": sum(row["partial"] and not row["complete"] for row in records),
                        "right_censored": sum(row["right_censored"] for row in records),
                        "missing_goal_labels": sum(not row["goal_label_available"] for row in records)}
        for metric in ("primitive_calls", "readback_queries", "independent_oracle_queries", "write_transactions", "inference_ns", "inference_cpu_ns", "setup_ns", "duration_ns"):
            values = [row[metric] for row in records]
            results[arm][metric] = {"sum": sum(values), "mean": float(np.mean(values)),
                                    "median": float(np.median(values)), "p95": float(np.quantile(values, .95))}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--training-repeats", type=int, default=8)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    train, confirmation = tasks("train"), tasks("confirm")
    source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
    frozen = {"schema_version": 1, "base_source_pin": "ae8a08059df73ccb875f4f541f76ad01080ba74b",
              "provenance": "controlled_local_sqlite_research_fixture", "product_final_use_lane": False,
              "production_authority": False, "independent_external_acceptance": False,
              "source_files_sha256": source, "train_tasks": train, "confirmation_tasks": confirmation,
              "training_seeds": list(range(700, 700 + args.training_repeats)), "epochs": 220,
              "allowed_primitives": ["inspect", "stage", "apply", "stop"], "options": list(OPTIONS),
              "stop_semantics": "suggestion followed by fresh destination read; cannot self-certify success",
              "matching": "same destination setup, goals, faults, primitive budget, observer and allowed primitives",
              "baselines_training_access": "same training trajectories available; no confirmation-driven tuning",
              "confirmation_split": {"destination_instances_disjoint": True, "physical_sql_schemas_disjoint": True,
                                     "composition_lengths_disjoint": True, "destination_families_disjoint": False},
              "criterion": "no reduction in actual completion or increase in false/duplicate effects; strict mean primitive-call improvement over every strong baseline; full training/data acquisition cost must also be paid",
              "statistics": "descriptive paired per-training-seed results only; episodes are not independent fits; no post-selection significance claim"}
    (out / "FROZEN_MANIFEST.json").write_text(json.dumps(frozen, indent=2) + "\n")
    (out / "manifest-frozen-before-training.txt").write_text(str(time.time_ns()) + "\n")
    gradient = gradient_check()
    train_rows, traces, rows, fits = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="act2-sqlite-learning-") as scratch, zipfile.ZipFile(
        out / "destination-databases.zip", "w", zipfile.ZIP_DEFLATED
    ) as custody:
        scratch = Path(scratch)
        collection_started = time.perf_counter_ns()
        for i, task in enumerate(train):
            row, trace = episode(task, "B1_macro", None, scratch / f"train-{i}", True)
            before = time.perf_counter_ns()
            member = f"training/{i}.db"
            custody.write(scratch / f"train-{i}/destination.db", member)
            row.update(database_archive_member=member, custody_ns=time.perf_counter_ns() - before)
            train_rows.append(row)
            traces.append(trace)
        collection_ns = time.perf_counter_ns() - collection_started
        x, y, mask = arrays(traces)
        for seed in frozen["training_seeds"]:
            models = {}
            for arm, kind in (("B3_head", "head"), ("B4_gru", "gru")):
                model = Model(kind, seed)
                before = time.perf_counter_ns()
                cpu_before = time.process_time_ns()
                losses = model.fit(x, y, mask)
                elapsed = time.perf_counter_ns() - before
                cpu_elapsed = time.process_time_ns() - cpu_before
                weights = out / f"{arm}-seed-{seed}.npz"
                np.savez(weights, **model.p)
                fits.append({"seed": seed, "arm": arm, "optimizer_steps": len(losses),
                             "train_ns": elapsed, "losses": losses, "weight_bytes": weights.stat().st_size,
                             "train_cpu_ns": cpu_elapsed,
                             "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
                             "train_trajectory_sha256": hashlib.sha256(x.tobytes() + y.tobytes() + mask.tobytes()).hexdigest()})
                models[arm] = model
            # Confirmation is opened only after both models are frozen for this seed.
            for arm in ARMS:
                for i, task in enumerate(confirmation):
                    row, _ = episode(task, arm, models.get(arm), scratch / f"{seed}-{arm}-{i}", False)
                    before = time.perf_counter_ns()
                    member = f"confirmation/{seed}/{arm}/{i}.db"
                    custody.write(scratch / f"{seed}-{arm}-{i}/destination.db", member)
                    row.update(database_archive_member=member, custody_ns=time.perf_counter_ns() - before)
                    row["training_seed"] = seed
                    rows.append(row)
            print(json.dumps({"seed": seed, "completed_episodes": len(rows)}), flush=True)
    compressed_jsonl(out / "training-trajectories.jsonl.gz", train_rows)
    compressed_jsonl(out / "confirmation-trajectories.jsonl.gz", rows)
    compressed_jsonl(out / "optimizer-records.jsonl.gz", fits)
    summary = summarize(rows)
    by_seed = {str(seed): summarize([row for row in rows if row["training_seed"] == seed]) for seed in frozen["training_seeds"]}
    primitive_frontier = {}
    for arm in ("B3_head", "B4_gru"):
        candidate = summary[arm]
        primitive_frontier[arm] = all(candidate["actual_complete"] >= summary[baseline]["actual_complete"] and
                                      candidate["reported_success"] >= summary[baseline]["reported_success"] and
                                      candidate["primitive_calls"]["mean"] < summary[baseline]["primitive_calls"]["mean"]
                                      for baseline in ARMS[:3]) and not candidate["false_success"] and not candidate["duplicate_effects"]
    result = {"schema_version": 1, "status": "CONTROLLED_RESEARCH_COMPLETED", "promotion": False,
              "fixed_skill_library_retained": True, "source_files_sha256": source,
              "training_collection_ns": collection_ns, "training_collection_calls": sum(row["primitive_calls"] for row in train_rows),
              "training_trajectories": len(train_rows), "independent_training_repeats": args.training_repeats,
              "fits": len(fits), "optimizer_steps_per_fit": 220, "gradient_checks": gradient,
              "training_cost_ns": {arm: sum(fit["train_ns"] for fit in fits if fit["arm"] == arm) for arm in ARMS[3:]},
              "training_cpu_cost_ns": {arm: sum(fit["train_cpu_ns"] for fit in fits if fit["arm"] == arm) for arm in ARMS[3:]},
              "summary": summary, "by_training_seed": by_seed, "primitive_frontier_criterion": primitive_frontier,
              "process_work_ns": time.perf_counter_ns() - started,
              "environment": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
              "holds": ["controlled SQLite fixture is not product FinalUse integration", "destination-family holdout absent", "production authority and independent field acceptance absent", "no learned-hierarchy promotion from this bounded research run"]}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "SHA256SUMS.json").write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "primitive_frontier_criterion": primitive_frontier, "promotion": False}), flush=True)


if __name__ == "__main__":
    main()
