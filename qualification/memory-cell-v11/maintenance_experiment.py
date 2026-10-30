"""Preregistered persistent-replay experiment on controlled random-key features.

This isolates update interference; it is not a natural-language benchmark or a
claim of compression.  Corrections and revocations require verified clean fits.
Calibration views and held views use different frozen perturbation streams.
"""

import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
import torch

from maintenance import SQLiteReplayStore
from models import FeatureMemory, digest_state, fit, load, predict, save


PROTOCOL = dict(
    schema="hepta.memory.v11.maintenance-protocol.v1", seeds=[1009, 2017, 3023],
    arms={"no_replay": 0, "persistent_buffer16": 16, "persistent_buffer32": 32, "full_active_rebuild": 0},
    feature_dimension=32, hidden=64, output_bits=12, initial_independent_records=32,
    derived_records=2, insert_cycles=4, inserts_per_cycle=8, corrections=8,
    init_steps=600, online_steps=80, rebuild_steps=900, batch_size=16,
    learning_rate=0.01, query_noise=0.02, unknown_queries=16,
    correction_indices=list(range(4, 12)), correction_xor_mask=[5, 3, 9], revocation_indices=[0, 2],
    calibration_thresholds=[0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99, 0.999, 0.9999],
    calibration_rule="maximize correct known accepts subject to zero wrong-known and zero unknown accepts; else reject all",
    phases=["initial", "insert-1", "insert-2", "insert-3", "insert-4", "correct", "revoke"],
    cpu_threads=2, source_authority="synthetic frozen records; no live owner admission claimed",
    model="two-layer GELU MLP on fixed random continuous features; bit logits",
    features="independent normalized random key vectors; shared canonical/calibration/held identities",
    held_scope="unseen perturbations of observed keys; no new-entity or language-generalization claim",
    rebuild_control="full_active_rebuild resets and trains on every current row after every insert; higher cost reported",
    correction_and_revocation="all arms reset model and optimizer; current sources only; rebuild cost separate",
    replay_scope="bounded persistent bottom-k hot buffer; complete SQLite evidence archive remains unbounded",
    restart_after="insert-2: close/reopen SQLite and load actual model plus optimizer checkpoint",
    metrics="unconditional and prior-correct-conditioned unchanged retention; new/corrected exactness; calibrated held coverage/risk",
    selection="no hyperparameter or source selection from held results; all four arms retained including negative outcomes",
)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def bits(value):
    return [(int(number) >> bit) & 1 for number in value for bit in range(4)]


def source_record(key, index, value, *, version=1, parents=()):
    body = dict(key=key, type="semantic", version=version, query=f"controlled-key:{key}",
                feature_index=index, value=[int(v) for v in value], target_text=json.dumps([int(v) for v in value]),
                parent_keys=list(parents))
    body["source_ids"] = [hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()]
    return body


def corpus(seed):
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((66, PROTOCOL["feature_dimension"])).astype(np.float32)
    features /= np.linalg.norm(features, axis=1, keepdims=True)
    values = rng.integers(0, 16, size=(64, 3))
    base = [source_record(f"key-{i:03d}", i, value) for i, value in enumerate(values)]
    derived = [source_record(f"derived-{i}", 64 + i, values[2*i] ^ values[2*i+1],
                             parents=(base[2*i]["key"], base[2*i+1]["key"])) for i in range(2)]
    views = {}
    for offset, name in ((70001, "calibration"), (90001, "held")):
        view_rng = np.random.default_rng(seed + offset)
        view = features + view_rng.normal(0, PROTOCOL["query_noise"], features.shape).astype(np.float32)
        view /= np.linalg.norm(view, axis=1, keepdims=True)
        unknown = view_rng.standard_normal((PROTOCOL["unknown_queries"], features.shape[1])).astype(np.float32)
        unknown /= np.linalg.norm(unknown, axis=1, keepdims=True)
        views[name] = (view, unknown)
    return features, base, derived, views


def current_rows(store):
    rows, cursor = [], 0
    while page := store.active_page(after_id=cursor, limit=128):
        rows.extend(page)
        cursor = page[-1]["record_id"]
    return rows


def model_predictions(model, features, rows):
    raw = predict(model, features[[r["feature_index"] for r in rows]])
    truth = np.asarray([bits(r["value"]) for r in rows], dtype=np.int8)
    exact = np.all((raw > 0) == truth, axis=1)
    probabilities = 1 / (1 + np.exp(-np.clip(np.abs(raw), 0, 60)))
    return raw, exact, probabilities.min(axis=1)


def evaluate(model, features, views, rows, before, changed):
    _, canonical, _ = model_predictions(model, features, rows)
    raw_held, held, held_confidence = model_predictions(model, views["held"][0], rows)
    _, cal_correct, cal_confidence = model_predictions(model, views["calibration"][0], rows)
    unknown_raw = predict(model, views["calibration"][1])
    unknown_confidence = (1 / (1 + np.exp(-np.clip(np.abs(unknown_raw), 0, 60)))).min(axis=1)
    threshold, maximum = None, -1
    for value in PROTOCOL["calibration_thresholds"]:
        accepted = cal_confidence >= value
        if not np.any(accepted & ~cal_correct) and not np.any(unknown_confidence >= value):
            correct = int(np.sum(accepted & cal_correct))
            if correct > maximum:
                maximum, threshold = correct, value
    accepted = held_confidence >= threshold if threshold is not None else np.zeros(len(rows), dtype=bool)
    held_unknown = predict(model, views["held"][1])
    held_unknown_confidence = (1 / (1 + np.exp(-np.clip(np.abs(held_unknown), 0, 60)))).min(axis=1)
    keys = [r["key"] for r in rows]
    unchanged = [i for i, key in enumerate(keys) if key in before and key not in changed]
    prior_correct = [i for i in unchanged if before[keys[i]]]
    changed_indices = [i for i, key in enumerate(keys) if key in changed]
    ratio = lambda total, count: total / count if count else None
    report = dict(active_count=len(rows), canonical_correct=int(canonical.sum()), held_correct=int(held.sum()),
                  canonical_accuracy=float(canonical.mean()), held_accuracy=float(held.mean()),
                  unchanged_count=len(unchanged), unchanged_correct=int(held[unchanged].sum()),
                  unchanged_retention=ratio(int(held[unchanged].sum()), len(unchanged)),
                  prior_correct_unchanged_count=len(prior_correct), retained_prior_correct=int(held[prior_correct].sum()),
                  prior_correct_conditioned_retention=ratio(int(held[prior_correct].sum()), len(prior_correct)),
                  changed_count=len(changed_indices), changed_correct=int(held[changed_indices].sum()),
                  changed_accuracy=ratio(int(held[changed_indices].sum()), len(changed_indices)),
                  threshold_from_calibration=threshold, held_known_accepted=int(accepted.sum()),
                  held_known_wrong_accepted=int(np.sum(accepted & ~held)),
                  held_known_coverage=float(accepted.mean()),
                  held_unknown_accepted=int(np.sum(held_unknown_confidence >= threshold)) if threshold is not None else 0,
                  held_unknown_count=len(held_unknown_confidence),
                  held_selective_error=ratio(int(np.sum(accepted & ~held)), int(accepted.sum())))
    predictions = [dict(key=r["key"], version=r["version"], target=bits(r["value"]),
                        held_prediction=(raw_held[i] > 0).astype(int).tolist(),
                        canonical_correct=bool(canonical[i]), held_correct=bool(held[i]),
                        confidence=float(held_confidence[i]), accepted=bool(accepted[i])) for i, r in enumerate(rows)]
    return report, predictions


def fit_batch(model, optimizer, rows, features, *, seed, phase_index, steps, label):
    data = features[[r["feature_index"] for r in rows]]
    target = np.asarray([bits(r["value"]) for r in rows], dtype=np.float32)
    schedule = np.random.default_rng(seed + 10000 * phase_index).integers(
        len(rows), size=(steps, PROTOCOL["batch_size"]), dtype=np.int64)
    before_states = len(optimizer.state)
    receipt = fit(model, data, target, [("binary", 4)] * 3, schedule,
                  lr=PROTOCOL["learning_rate"], optimizer=optimizer,
                  source_ids=[r["source_ids"][0] for r in rows], label=label,
                  deadline=time.perf_counter() + 120)
    receipt.update(optimizer_state_entries_before_fit=before_states, optimizer_state_entries_after_fit=len(optimizer.state))
    return receipt, schedule


def run_arm(root, arm, seed, features, base, derived, views):
    root.mkdir()
    config = dict(replay_capacity=PROTOCOL["arms"][arm], pending_capacity=128, max_batch_size=128, seed=seed)
    store = SQLiteReplayStore(root / "replay.sqlite", **config)
    model = FeatureMemory("mlp", PROTOCOL["feature_dimension"], 12, seed=seed, hidden=PROTOCOL["hidden"])
    optimizer = torch.optim.Adam(model.parameters(), lr=PROTOCOL["learning_rate"])
    clean_identity = digest_state({k: p for k, p in model.named_parameters() if p.requires_grad})
    prior_checkpoint, phases, source_map, expected = None, [], {}, {}
    total_fit, total_rebuild, total_evaluation = 0.0, 0.0, 0.0
    for phase_index, phase in enumerate(PROTOCOL["phases"]):
        phase_root = root / phase
        phase_root.mkdir()
        old_rows = current_rows(store)
        before = {}
        if old_rows:
            _, old_correct, _ = model_predictions(model, views["held"][0], old_rows)
            before = {r["key"]: bool(correct) for r, correct in zip(old_rows, old_correct, strict=True)}
        changed, revoked, guards = set(), [], []
        maintenance_started = time.perf_counter()
        if phase == "initial":
            incoming = base[:32] + derived
        elif phase.startswith("insert-"):
            cycle = int(phase.rsplit("-", 1)[1])
            incoming = base[32 + (cycle - 1) * 8:32 + cycle * 8]
        elif phase == "correct":
            incoming = [source_record(base[i]["key"], i, np.asarray(base[i]["value"]) ^ PROTOCOL["correction_xor_mask"], version=2)
                        for i in PROTOCOL["correction_indices"]]
        else:
            incoming = []
            for index in PROTOCOL["revocation_indices"]:
                row = base[index]
                store.revoke_source(row["source_ids"][0])
                store.delete_key(row["key"], "semantic")
                revoked.append(row["key"])
            for key in revoked + [r["key"] for r in derived]:
                expected.pop(key)
                guard = dict(key=key, denied=store.current(key, "semantic") is None, model_calls=0)
                if not guard["denied"]:
                    raise AssertionError("revoked or derived record remained current")
                guards.append(guard)
        for row in incoming:
            parent_ids = [source_map[key] for key in row["parent_keys"]]
            source_map[row["key"]] = store.append(row, parent_ids=parent_ids)
            expected[row["key"]] = row
            changed.add(row["key"])
        parent_was_valid = store.checkpoint_is_valid(prior_checkpoint) if prior_checkpoint else None
        clean_rebuild = phase in ("correct", "revoke") or (arm == "full_active_rebuild" and phase != "initial")
        if phase in ("correct", "revoke") and parent_was_valid:
            raise AssertionError("changed training dependency did not invalidate the parent")
        if phase == "revoke":
            store.close()
            store = SQLiteReplayStore(root / "replay.sqlite", **config)
            if store.checkpoint_is_valid(prior_checkpoint):
                raise AssertionError("restart revived the withdrawn checkpoint")
            batch = store.claim_rebuild_page(limit=128)
        else:
            replay_count = 0 if phase == "initial" or clean_rebuild else PROTOCOL["arms"][arm]
            batch = store.claim_batch(new_count=len(incoming), replay_count=replay_count)
        if batch is None:
            raise AssertionError("maintenance phase produced no training batch")
        if clean_rebuild:
            all_current = current_rows(store)
            batch = replace(batch, records=tuple(all_current), replay_ids=tuple(
                r["record_id"] for r in all_current if r["record_id"] not in batch.pending_ids))
            model = FeatureMemory("mlp", PROTOCOL["feature_dimension"], 12, seed=seed, hidden=PROTOCOL["hidden"])
            optimizer = torch.optim.Adam(model.parameters(), lr=PROTOCOL["learning_rate"])
            identity = digest_state({k: p for k, p in model.named_parameters() if p.requires_grad})
            if identity != clean_identity:
                raise AssertionError("clean rebuild was not reset to the declared initialization")
            parent = None
        else:
            parent = prior_checkpoint
            shadow = copy.deepcopy(model)
            shadow_optimizer = torch.optim.Adam(shadow.parameters(), lr=PROTOCOL["learning_rate"])
            shadow_optimizer.load_state_dict(copy.deepcopy(optimizer.state_dict()))
            model, optimizer = shadow, shadow_optimizer
        acquisition_seconds = time.perf_counter() - maintenance_started
        steps = PROTOCOL["init_steps"] if phase == "initial" else PROTOCOL["rebuild_steps"] if clean_rebuild else PROTOCOL["online_steps"]
        receipt, schedule = fit_batch(model, optimizer, list(batch.records), features,
                                      seed=seed, phase_index=phase_index, steps=steps, label=f"{arm}:{phase}")
        total_fit += receipt["wall_seconds"]
        if clean_rebuild:
            total_rebuild += receipt["wall_seconds"]
        np.save(phase_root / "schedule.npy", schedule, allow_pickle=False)
        checkpoint = phase_root / "checkpoint"
        save(model, checkpoint, metadata=dict(seed=seed, arm=arm, phase=phase,
             feature_matrix_sha256=hashlib.sha256(features.tobytes()).hexdigest(),
             source_ids=receipt["source_ids"], fit_initial_sha256=receipt["initial_parameter_sha256"],
             fit_final_sha256=receipt["final_parameter_sha256"], clean_rebuild=clean_rebuild,
             parent_checkpoint=parent, training_rows=len(batch.records)))
        torch.save(optimizer.state_dict(), checkpoint / "optimizer.pt")
        checkpoint_id = f"{arm}:{seed}:{phase}"
        committed = store.commit_training(batch, checkpoint_id, checkpoint, parent_checkpoint=parent)
        prior_checkpoint = checkpoint_id
        restarted = None
        if phase == PROTOCOL["restart_after"].split(":", 1)[0]:
            probe = predict(model, features[:8])
            store.close()
            store = SQLiteReplayStore(root / "replay.sqlite", **config)
            if not store.checkpoint_is_valid(checkpoint_id):
                raise AssertionError("valid persisted checkpoint did not recover")
            model = load(checkpoint)
            optimizer = torch.optim.Adam(model.parameters(), lr=PROTOCOL["learning_rate"])
            optimizer.load_state_dict(torch.load(checkpoint / "optimizer.pt", map_location="cpu", weights_only=True))
            restarted = dict(exact_prediction_equal=bool(np.array_equal(probe, predict(model, features[:8]))),
                             optimizer_state_entries=len(optimizer.state), checkpoint_revalidated=True)
            if not restarted["exact_prediction_equal"]:
                raise AssertionError("restart changed numerical predictions")
        evaluation_started = time.perf_counter()
        rows = current_rows(store)
        if {r["key"] for r in rows} != set(expected) or any(
            r["value"] != expected[r["key"]]["value"] or r["source_ids"] != expected[r["key"]]["source_ids"] for r in rows
        ):
            raise AssertionError("durable evidence differs from the frozen event stream")
        metrics, predictions = evaluate(model, features, views, rows, before, changed)
        evaluation_seconds = time.perf_counter() - evaluation_started
        total_evaluation += evaluation_seconds
        valid_sources = {source for row in rows for source in row["source_ids"]}
        if clean_rebuild and set(receipt["source_ids"]) != valid_sources:
            raise AssertionError("clean rebuild lineage differs from current evidence")
        exact_reference_correct = sum(store.current(key, "semantic")["value"] == row["value"] for key, row in expected.items())
        result = dict(phase=phase, metrics=metrics, actual_training_rows=len(batch.records),
                      new_rows=len(batch.pending_ids), replay_rows=len(batch.replay_ids),
                      clean_rebuild=clean_rebuild, clean_initial_parameter_sha256=clean_identity if clean_rebuild else None,
                      caller_reset_optimizer=clean_rebuild or phase == "initial",
                      previous_checkpoint_valid_after_write=parent_was_valid,
                      fit=receipt, checkpoint=committed, guards=guards, restart=restarted,
                      exact_reference_correct=exact_reference_correct, exact_reference_count=len(rows),
                      acquisition_seconds=acquisition_seconds, evaluation_seconds=evaluation_seconds,
                      cumulative_fit_seconds=total_fit, cumulative_rebuild_fit_seconds=total_rebuild,
                      cumulative_evaluation_seconds=total_evaluation, storage=store.stats())
        write_json(phase_root / "RESULT.json", result)
        write_json(phase_root / "PREDICTIONS.json", predictions)
        write_json(phase_root / "TRAINING_SOURCES.json", list(batch.records))
        phases.append(result)
    store.close()
    summary = dict(seed=seed, arm=arm, phases=phases, fit_seconds=total_fit,
                   rebuild_fit_seconds=total_rebuild, evaluation_seconds=total_evaluation,
                   checkpoint_bytes=sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and "checkpoint" in p.parts))
    write_json(root / "SUMMARY.json", summary)
    return summary


def run(output):
    output = Path(output)
    if output.exists():
        raise ValueError("formal run directory already exists; use a new run identity")
    output.mkdir(parents=True)
    torch.set_num_threads(PROTOCOL["cpu_threads"])
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    write_json(output / "PROTOCOL.json", PROTOCOL)
    source_directory = output / "sources"
    source_directory.mkdir()
    source_identity = {}
    for name in ("maintenance_experiment.py", "maintenance.py", "models.py"):
        source = Path(__file__).parent / name
        shutil.copy2(source, source_directory / name)
        source_identity[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    source_identity["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True).strip()
    source_identity["runtime"] = dict(python=sys.version, numpy=np.__version__, torch=torch.__version__)
    write_json(output / "SOURCE_IDENTITY.json", source_identity)
    summaries = []
    started = time.perf_counter()
    for seed in PROTOCOL["seeds"]:
        features, base, derived, views = corpus(seed)
        seed_root = output / f"seed-{seed}"
        seed_root.mkdir()
        np.save(seed_root / "features.npy", features, allow_pickle=False)
        for name, (view, unknown) in views.items():
            np.save(seed_root / f"{name}-features.npy", view, allow_pickle=False)
            np.save(seed_root / f"{name}-unknown.npy", unknown, allow_pickle=False)
        corrections = [source_record(base[i]["key"], i, np.asarray(base[i]["value"]) ^ PROTOCOL["correction_xor_mask"], version=2)
                       for i in PROTOCOL["correction_indices"]]
        write_json(seed_root / "FROZEN_INPUT_RECORDS.json", base + derived + corrections)
        write_json(seed_root / "INPUT_IDENTITY.json", {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in seed_root.iterdir() if p.is_file()})
        for arm in PROTOCOL["arms"]:
            print(f"maintenance seed={seed} arm={arm}", flush=True)
            summary = run_arm(seed_root / arm, arm, seed, features, base, derived, views)
            summaries.append(summary)
    aggregate = {}
    for arm in PROTOCOL["arms"]:
        for phase in PROTOCOL["phases"]:
            results = [next(p for p in s["phases"] if p["phase"] == phase) for s in summaries if s["arm"] == arm]
            metrics = [r["metrics"] for r in results]
            aggregate[f"{arm}/{phase}"] = dict(
                seed_results=[dict(seed=seed, **metric) for seed, metric in zip(PROTOCOL["seeds"], metrics, strict=True)],
                mean_held_accuracy=float(np.mean([m["held_accuracy"] for m in metrics])),
                mean_canonical_accuracy=float(np.mean([m["canonical_accuracy"] for m in metrics])),
                mean_held_known_coverage=float(np.mean([m["held_known_coverage"] for m in metrics])),
                mean_fit_seconds=float(np.mean([r["fit"]["wall_seconds"] for r in results])),
                mean_training_rows=float(np.mean([r["actual_training_rows"] for r in results])),
            )
    result = dict(schema="hepta.memory.v11.maintenance-experiment.v1", protocol=PROTOCOL,
                  source_identity=source_identity, aggregate=aggregate,
                  wall_seconds=time.perf_counter() - started,
                  all_checkpoints_and_predictions_retained=True,
                  raw_evidence_bytes=sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
                  promotion_claimed=False,
                  limitation="Controlled random feature memory; three seeds; no language, owner, compression, or universal-memory claim.")
    write_json(output / "SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.output)
