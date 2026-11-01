"""Prospective long-distance diagnostics for unchanged symbolic checkpoints.

Freeze this extension before opening core confirmation results. Execution follows
core evaluation, whose verified base predictions only define paired switch
statistics. No model, optimizer or training data is updated by this script.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np

from . import synthetic_data


TASKS = ("mqar", "selective", "binding")
ARMS = ("flow", "diagonal", "gru", "snn", "transformer")
SEEDS = (17, 29, 43)
CONDITIONS = ("long_tokens_64", "long_tokens_128", "matched_silence_64",
              "matched_silence_128", "query_swap")
EPISODES = 512
PREDICT_BATCH = 16
DISTRACTOR_SEED = 910731


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def query_arrays(data, logits):
    selected = data["y"] >= 0
    if not np.all(selected.sum(1) == 4):
        raise ValueError("Exactly four original queries are required")
    n = len(selected)
    return (logits[selected].reshape(n, 4, logits.shape[-1]),
            data["y"][selected].reshape(n, 4),
            data["sample_weight"][selected].reshape(n, 4))


def stress_data(task, base, condition):
    """Transform an existing episode without regenerating or exposing answers.

    The filler stream is independent of the original content/test seed. For a
    given episode, the 64-token filler is a prefix of the 128-token filler.
    """
    if task not in TASKS or condition not in CONDITIONS:
        raise ValueError("Unknown extension task or condition")
    data = {key: np.array(base[key], copy=True) for key in
            ("x", "dt", "observed", "y", "sample_weight")}
    n, steps, width = data["x"].shape
    first_query = steps - 4
    if (width != 24 or not np.all(data["y"][:, :first_query] == -100)
            or not np.all(data["y"][:, first_query:] >= 0)):
        raise ValueError("Expected the frozen symbolic generator's final four queries")
    if condition == "query_swap":
        # Swap query identities and targets, preserving the clock at each slot.
        order = [first_query + 1, first_query]
        for key in ("x", "y", "sample_weight"):
            data[key][:, first_query:first_query + 2] = data[key][:, order].copy()
    else:
        target_length = int(condition.rsplit("_", 1)[1])
        inserted = target_length - steps
        if inserted <= 0:
            raise ValueError("Long-distance target must exceed the base sequence")
        if condition.startswith("matched_silence"):
            data["dt"][:, first_query] += np.float32(inserted * .25)
        else:
            rng = np.random.default_rng(np.random.SeedSequence(
                [DISTRACTOR_SEED, synthetic_data.TASKS[task], 301]))
            capacity = 128 - steps
            keys = rng.integers(0, 4, size=(n, capacity))[:, :inserted]
            values = rng.integers(0, 8, size=(n, capacity))[:, :inserted]
            filler = np.zeros((n, inserted, width), np.float32)
            rows, positions = np.arange(n)[:, None], np.arange(inserted)[None, :]
            filler[rows, positions, keys] = 1
            filler[rows, positions, 4 + values] = 1
            filler[..., 14] = 1  # type 2: distractor, never a retained write.
            filler[..., 16] = 1  # Modality A; no B-key or bridge information.
            inserted_arrays = dict(x=filler,
                dt=np.full((n, inserted), .25, np.float32),
                observed=np.ones((n, inserted), bool),
                y=np.full((n, inserted), -100, np.int64),
                sample_weight=np.zeros((n, inserted), np.float32))
            data = {key: np.concatenate((value[:, :first_query], inserted_arrays[key],
                                         value[:, first_query:]), axis=1)
                    for key, value in data.items()}
    data["query_mask"] = data["y"] >= 0
    if np.any(data["x"][..., 4:12][data["query_mask"]]):
        raise ValueError("A transformed query contains a target value")
    return data


def metrics(logits, labels, weights, condition, base_logits, base_labels):
    predicted = logits.argmax(-1)
    correct = predicted == labels
    result = dict(accuracy=float((correct * weights).sum() / weights.sum()),
                  all_queries_correct=float(correct.all(-1).mean()),
                  episodes=len(labels), queries=int(labels.size))
    if condition == "query_swap":
        switched_correctly = ((predicted[:, 0] == base_labels[:, 1])
                              & (predicted[:, 1] == base_labels[:, 0]))
        initially_correct = (base_logits.argmax(-1)[:, :2] == base_labels[:, :2]).all(-1)
        result.update(correct_switch=float(switched_correctly.mean()),
            original_pair_correct_episodes=int(initially_correct.sum()),
            conditional_correct_switch=(float(switched_correctly[initially_correct].mean())
                                        if initially_correct.any() else None),
            original_and_swapped_pairs_correct=float((initially_correct & switched_correctly).mean()))
    return result


def contract(args, parent, candidate_sha256):
    return dict(schema="hcsn-four-stage.extended-protocol.v1",
        core_frozen_commit=args.frozen_commit,
        parent_protocol_sha256=digest(args.run / "PROTOCOL.json"),
        candidate_freeze_sha256=candidate_sha256,
        extension_source_sha256=digest(__file__), core_source_hashes=parent["source_hashes"],
        tasks=list(TASKS), arms=list(ARMS), fit_seeds=list(SEEDS), episodes=EPISODES,
        test_content_seed=synthetic_data.FIXED_SEEDS["test"], distractor_seed=DISTRACTOR_SEED,
        conditions=list(CONDITIONS), total_condition_rows=45 * 5, predict_batch_size=PREDICT_BATCH,
        long_tokens=dict(total_lengths=[64, 128], insertion="After the original prelude and before all queries",
            count="target total length minus original episode length", dt_seconds=.25,
            observed=True, type=2, keys="Uniform A-key", values="Uniform value; independent of labels",
            paired_lengths="The shorter filler is a per-episode prefix of the longer filler"),
        matched_silence="No inserted observations; add exactly filler_count * .25 seconds to first-query dt",
        query_swap="Exchange first two query identities and labels; keep every dt and prelude token fixed",
        switch_metrics=dict(correct_switch="Both first-two predictions equal their exchanged true targets",
            conditional_correct_switch="Same event restricted to episodes whose original first-two predictions were correct",
            interpretation="Output changes alone are never counted as successful binding"),
        pairing="Same task/test-content-seed/episode-index identifier across fits and conditions",
        training="Forbidden; every checkpoint is verified against the already frozen candidate artifact",
        baseline="Verified core test__base predictions used only for paired switch statistics, never selection",
        saved_arrays=["query logits", "query labels", "query weights", "paired sample IDs"],
        scope="Controlled symbolic long-distance/interference diagnostics; no foundation-model or LLM claim",
        cost="Per-condition generation+forward+serialization and separate fit setup; no energy measurement",
        selection="All 45 fits and five fixed conditions; preserve failures without dropping conditions")


def baseline_reference(run, key, base, protocol, frozen, candidate_sha256):
    folder = run / key
    result = json.loads((folder / "result.json").read_text())
    predictions_path = folder / "predictions.npz"
    if (result["status"] != "completed"
            or result["frozen_commit"] != protocol["core_frozen_commit"]
            or result["protocol_sha256"] != protocol["parent_protocol_sha256"]
            or result["checkpoint_sha256"] != frozen["checkpoint_sha256"]
            or result["candidate_freeze_sha256"] != candidate_sha256
            or result["predictions_sha256"] != digest(predictions_path)):
        raise ValueError("Core baseline prediction identity mismatch")
    with np.load(predictions_path, allow_pickle=False) as stored:
        logits = stored["test__base__logits"]
        if (not np.array_equal(stored["test__base__y"], base["y"])
                or not np.array_equal(stored["test__base__weight"], base["sample_weight"])
                or not np.isfinite(logits).all()):
            raise ValueError("Core baseline does not match the frozen regenerated episodes")
    query_logits, labels, _ = query_arrays(base, logits)
    return query_logits, labels, dict(result_sha256=digest(folder / "result.json"),
                                     predictions_sha256=digest(predictions_path))


def execute(args, protocol, candidate, runner, torch):
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    save_json(args.out / "EXECUTION_STARTED.json", dict(utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=digest(args.out / "EXTENDED_PROTOCOL.json")))
    rows, fit_costs = [], []
    for task in TASKS:
        base = synthetic_data.batch(task, EPISODES, synthetic_data.FIXED_SEEDS["test"], "test", "base")
        identifiers = np.asarray([f"{task}:seed{synthetic_data.FIXED_SEEDS['test']}:episode{i:05d}"
                                  for i in range(EPISODES)])
        for seed in SEEDS:
            for arm in ARMS:
                key = f"{task}__{arm}__{seed}"
                folder = args.out / key
                folder.mkdir()
                setup_wall, setup_cpu = time.perf_counter(), time.process_time()
                setup_error, model = None, None
                frozen = candidate["checkpoints"][key]
                try:
                    base_logits, base_labels, reference = baseline_reference(
                        args.run, key, base, protocol, frozen, protocol["candidate_freeze_sha256"])
                    checkpoint = args.run / key / "checkpoint.pt"
                    if digest(checkpoint) != frozen["checkpoint_sha256"]:
                        raise ValueError("Checkpoint changed after extension verification")
                    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
                    if ((saved["task"], saved["arm"], saved["seed"]) != (task, arm, seed)
                            or saved["protocol_sha256"] != protocol["parent_protocol_sha256"]
                            or saved["frozen_commit"] != args.frozen_commit):
                        raise ValueError("Checkpoint payload differs from the frozen fit")
                    model = runner.new_model(task, arm)
                    model.load_state_dict(saved["model"], strict=True)
                    model.eval()
                except Exception:
                    setup_error = traceback.format_exc()
                    reference = None
                setup = dict(wall_seconds=time.perf_counter() - setup_wall,
                             cpu_seconds=time.process_time() - setup_cpu)
                fit_records = []
                for condition in CONDITIONS:
                    wall, cpu = time.perf_counter(), time.process_time()
                    row = dict(task=task, arm=arm, seed=seed, condition=condition,
                               checkpoint_sha256=frozen["checkpoint_sha256"])
                    try:
                        if setup_error:
                            raise RuntimeError("Fit setup failed; see fit.json")
                        data = stress_data(task, base, condition)
                        logits = runner.predict(model, data, batch_size=PREDICT_BATCH)
                        query_logits, labels, weights = query_arrays(data, logits)
                        if not np.isfinite(query_logits).all():
                            raise ArithmeticError("Nonfinite query prediction")
                        path = folder / f"{condition}.npz"
                        with path.open("xb") as stream:
                            np.savez_compressed(stream, logits=query_logits, labels=labels,
                                                weights=weights, sample_id=identifiers)
                        row.update(status="completed", metrics=metrics(query_logits, labels, weights,
                            condition, base_logits, base_labels), predictions_sha256=digest(path),
                            sequence_length=data["x"].shape[1],
                            elapsed_seconds_min=float(data["dt"].sum(1).min()),
                            elapsed_seconds_max=float(data["dt"].sum(1).max()))
                    except Exception:
                        row.update(status="failed", traceback=traceback.format_exc())
                    row.update(wall_seconds=time.perf_counter() - wall,
                               cpu_seconds=time.process_time() - cpu)
                    save_json(folder / f"{condition}.json", row)
                    rows.append(row)
                    fit_records.append(row)
                fit_summary = dict(task=task, arm=arm, seed=seed, setup=setup,
                    setup_error=setup_error, baseline_reference=reference,
                    condition_wall_seconds=sum(row["wall_seconds"] for row in fit_records),
                    condition_cpu_seconds=sum(row["cpu_seconds"] for row in fit_records))
                save_json(folder / "fit.json", fit_summary)
                fit_costs.append(fit_summary)
                print(json.dumps(dict(task=task, arm=arm, seed=seed,
                    completed=sum(row["status"] == "completed" for row in fit_records))), flush=True)
    summary = dict(schema="hcsn-four-stage.extended-summary.v1", expected_rows=225,
        completed=sum(row["status"] == "completed" for row in rows),
        failed=sum(row["status"] != "completed" for row in rows),
        extension_source_unchanged=digest(__file__) == protocol["extension_source_sha256"],
        protocol_sha256=digest(args.out / "EXTENDED_PROTOCOL.json"),
        wall_seconds=time.perf_counter() - started_wall,
        cpu_seconds=time.process_time() - started_cpu, energy_joules=None,
        scope="Execution body after imports and candidate verification; outer process receipt supplies complete cost",
        cost_rule="Setup and condition clocks partition fit work; do not add their sum to this enclosing clock",
        fits=fit_costs, conditions=rows)
    save_json(args.out / "SUMMARY.json", summary)
    if summary["failed"] or not summary["extension_source_unchanged"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidate-freeze", type=Path, required=True)
    parser.add_argument("--frozen-commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    import torch
    from . import runner
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    parent = json.loads((args.run / "PROTOCOL.json").read_text())
    if parent["source_hashes"] != runner.source_hashes():
        raise ValueError("Frozen core changed; extension cannot reinterpret old checkpoints")
    candidate, candidate_sha256 = runner.read_candidate(args.candidate_freeze, args.run,
        TASKS, ARMS, SEEDS, args.frozen_commit)
    current = contract(args, parent, candidate_sha256)
    protocol_path = args.out / "EXTENDED_PROTOCOL.json"
    if args.freeze_only:
        args.out.mkdir(parents=True, exist_ok=False)
        save_json(protocol_path, dict(frozen_utc=datetime.now(timezone.utc).isoformat(), **current))
        return
    protocol = json.loads(protocol_path.read_text())
    expected = dict(protocol)
    expected.pop("frozen_utc")
    if expected != current:
        raise ValueError("Extension protocol or identity drift after freeze")
    execute(args, protocol, candidate, runner, torch)


if __name__ == "__main__":
    main()
