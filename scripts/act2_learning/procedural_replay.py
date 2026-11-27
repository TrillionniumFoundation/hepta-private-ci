"""Offline ACT2 procedural imitation replay; no provider or factual-memory API.

The ordered/shuffled contrast reuses the original TRAIN examples. Shuffling
changes sequence context, not individual feature/label pairs. It supplies no
independent task, policy adoption, causal replay or production-effect evidence.
"""

import argparse
import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np

import models


ORIGIN = "0584b3344f70ed51d9e09224e105bfa4d1a4635f"
SUMS_SHA256 = "16de01ad186843a08f115562ba6c3ade48ca43fe42b6c437399958d8cafb44df"
TRAIN_SHA256 = "5512824dc9706ef8c5735eb94c6d500ec0a60ad42ea084db448398ab878b6eec"
PURPOSE = "procedural_skill_selection"
SCHEMA = "hepta.act.procedural-replay.v1"
OPTIONS = ("inspect", "ensure", "stop")
SHUFFLE_SEED = 20261110


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(path, expected):
    data = path.read_bytes()
    require(sha(data) == expected, "pinned artifact mismatch: " + path.name)
    return data


def load_training(archive):
    sums = json.loads(pinned(archive / "SHA256SUMS.json", SUMS_SHA256))
    require(sums["training-trajectories.jsonl.gz"] == TRAIN_SHA256, "TRAIN pin differs")
    manifest = json.loads(
        pinned(archive / "FROZEN_MANIFEST.json", sums["FROZEN_MANIFEST.json"])
    )
    allowed = {task["id"] for task in manifest["train_tasks"]}
    rows = [
        json.loads(line)
        for line in gzip.decompress(
            pinned(archive / "training-trajectories.jsonl.gz", TRAIN_SHA256)
        ).splitlines()
    ]
    require(
        len(rows) == len(allowed) == 80, "original TRAIN panel must contain 80 tasks"
    )
    records = []
    for row in rows:
        require(
            row.get("arm") == "B1_macro" and row.get("goal_label_available") is True,
            "missing original trajectory labels",
        )
        records.append(
            {
                "schema": SCHEMA,
                "purpose": PURPOSE,
                "split": "TRAIN",
                "source_sha256": TRAIN_SHA256,
                "task_id": row["task_id"],
                "features": row["policy_visible_features"],
                "actions": row["decisions"],
            }
        )
    require(
        {record["task_id"] for record in records} == allowed,
        "incomplete original TRAIN identity set",
    )
    approved = {record["task_id"]: sha(canonical(record)) for record in records}
    replay_arrays(records, approved, "ordered")
    return records, approved, sums


def replay_arrays(records, allowed, order):
    """Use content digests supplied by the pinned loader, never record claims."""
    require(order in ("ordered", "shuffled"), "unknown replay order")
    require(isinstance(records, list) and 0 < len(records) <= 80, "replay count bound")
    seen, sequences, permutations = set(), [], []
    random = np.random.default_rng(SHUFFLE_SEED)
    fields = {
        "schema",
        "purpose",
        "split",
        "source_sha256",
        "task_id",
        "features",
        "actions",
    }
    for record in records:
        require(
            isinstance(record, dict) and set(record) == fields,
            "procedural schema fields",
        )
        require(
            record["schema"] == SCHEMA
            and record["purpose"] == PURPOSE
            and record["split"] == "TRAIN",
            "procedural purpose/TRAIN boundary",
        )
        require(record["source_sha256"] == TRAIN_SHA256, "procedural source pin")
        identity = record["task_id"]
        require(
            isinstance(identity, str)
            and identity.startswith("train/")
            and identity in allowed
            and identity not in seen,
            "unapproved or repeated TRAIN identity",
        )
        seen.add(identity)
        features, actions = record["features"], record["actions"]
        require(
            isinstance(features, list)
            and isinstance(actions, list)
            and 0 < len(features) == len(actions) <= 64,
            "missing or unaligned action labels",
        )
        require(
            all(
                isinstance(row, list)
                and len(row) == 10
                and all(type(value) in (int, float) for value in row)
                for row in features
            ),
            "feature shape/type",
        )
        values = np.asarray(features, dtype=np.float64)
        require(np.isfinite(values).all(), "nonfinite procedural feature")
        require(
            all(action in OPTIONS for action in actions),
            "missing or unsupported action label",
        )
        require(
            sha(canonical(record)) == allowed[identity],
            "record differs from pinned TRAIN content",
        )
        labels = np.asarray([OPTIONS.index(action) for action in actions])
        permutation = (
            random.permutation(len(actions))
            if order == "shuffled"
            else np.arange(len(actions))
        )
        permutations.append({"task_id": identity, "permutation": permutation.tolist()})
        sequences.append((values[permutation], labels[permutation]))
    width = max(len(labels) for _, labels in sequences)
    x, y, mask = (
        np.zeros((len(records), width, 10)),
        np.zeros((len(records), width, 3)),
        np.zeros((len(records), width)),
    )
    for i, (values, labels) in enumerate(sequences):
        x[i, : len(labels)], y[i, : len(labels)], mask[i, : len(labels)] = (
            values,
            np.eye(3)[labels],
            1,
        )
    return x, y, mask, permutations


def fit_replay(records, allowed, order, seed, epochs=220):
    x, y, mask, permutations = replay_arrays(records, allowed, order)
    model = models.Model("gru", seed)
    initial = sha(
        b"".join(
            key.encode() + value.tobytes() for key, value in sorted(model.p.items())
        )
    )
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    losses = model.fit(x, y, mask, epochs=epochs)
    elapsed, cpu_elapsed = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
    require(
        len(losses) == epochs
        and np.isfinite(losses).all()
        and all(np.isfinite(value).all() for value in model.p.values()),
        "nonfinite or incomplete fit",
    )
    return model, {
        "order": order,
        "seed": seed,
        "optimizer_calls": len(losses),
        "losses": losses,
        "initial_parameter_sha256": initial,
        "training_array_sha256": sha(x.tobytes() + y.tobytes() + mask.tobytes()),
        "examples_per_epoch": int(mask.sum()),
        "fit_wall_ns": elapsed,
        "fit_cpu_ns": cpu_elapsed,
        "permutations_sha256": sha(canonical(permutations)),
    }


def main(archive, output):
    records, allowed, sums = load_training(archive)
    unique = len(
        {sha(canonical([record["features"], record["actions"]])) for record in records}
    )
    require(unique == 9, "original normalized trajectory diversity changed")
    output.mkdir(parents=True, exist_ok=False)
    permutations = {
        order: replay_arrays(records, allowed, order)[3]
        for order in ("ordered", "shuffled")
    }
    source = {
        path.name: sha(path.read_bytes())
        for path in (Path(__file__), Path(models.__file__))
    }
    frozen = {
        "schema": SCHEMA,
        "purpose": PURPOSE,
        "origin_commit": ORIGIN,
        "train_archive_sha256": TRAIN_SHA256,
        "train_tasks": sorted(allowed),
        "train_record_sha256": allowed,
        "seeds": list(range(700, 708)),
        "epochs": 220,
        "orders": ["ordered", "shuffled"],
        "shuffle_seed": SHUFFLE_SEED,
        "permutations": permutations,
        "source_sha256": source,
        "labels": "observed fixed-macro actions; no terminal success/failure target",
        "tool_effect_authority": False,
        "factual_memory_training": False,
        "confirmation_used_for_selection": False,
    }
    (output / "FROZEN_MANIFEST.json").write_text(json.dumps(frozen, indent=2) + "\n")
    (output / "procedural-traces.jsonl.gz").write_bytes(
        gzip.compress(
            b"\n".join(canonical(record) for record in records) + b"\n", mtime=0
        )
    )
    fits = []
    for seed in frozen["seeds"]:
        for order in frozen["orders"]:
            model, fit = fit_replay(records, allowed, order, seed)
            target = output / f"{order}-seed-{seed}.npz"
            np.savez(target, **model.p)
            fit.update(
                weights_file=target.name, weights_sha256=sha(target.read_bytes())
            )
            if order == "ordered":
                original = archive / f"B4_gru-seed-{seed}.npz"
                pinned(original, sums[original.name])
                with np.load(original, allow_pickle=False) as expected:
                    fit["matches_original_saved_tensors"] = set(expected.files) == set(
                        model.p
                    ) and all(
                        np.array_equal(expected[key], value)
                        for key, value in model.p.items()
                    )
                require(
                    fit["matches_original_saved_tensors"],
                    "ordered replay did not reproduce original weights",
                )
                fit["matches_original_saved_bytes"] = (
                    fit["weights_sha256"] == sums[original.name]
                )
                require(
                    fit["matches_original_saved_bytes"],
                    "ordered replay did not reproduce original checkpoint bytes",
                )
            fits.append(fit)
            (output / f"{order}-seed-{seed}-fit.json").write_text(
                json.dumps(fit, indent=2) + "\n"
            )
    for seed in frozen["seeds"]:
        pair = [fit for fit in fits if fit["seed"] == seed]
        require(
            pair[0]["initial_parameter_sha256"] == pair[1]["initial_parameter_sha256"]
            and pair[0]["examples_per_epoch"] == pair[1]["examples_per_epoch"]
            and pair[0]["optimizer_calls"] == pair[1]["optimizer_calls"],
            "unmatched replay pair",
        )
    final_source = {
        path.name: sha(path.read_bytes())
        for path in (Path(__file__), Path(models.__file__))
    }
    require(final_source == source, "replay source changed during fitting")
    result = {
        "status": "OFFLINE_PROCEDURAL_REPLAY_COMPLETED",
        "adoption": "NoUpdate",
        "promotion": False,
        "new_independent_tasks": 0,
        "reused_train_trajectories": len(records),
        "unique_normalized_trajectories": unique,
        "fits": len(fits),
        "optimizer_calls": sum(fit["optimizer_calls"] for fit in fits),
        "fit_records": fits,
        "source_sha256": source,
        "source_stable": True,
        "train_archive_sha256": TRAIN_SHA256,
        "tool_effect_calls": 0,
        "factual_memory_training": False,
        "confirmation_evaluation": "NOT_RUN",
        "scope": "offline imitation on original procedural TRAIN examples; paired within-sequence feature/action permutation",
        "holds": [
            "independent task benefit",
            "complete operation costs",
            "production replay owner",
            "causal replay contribution",
            "learned policy adoption",
        ],
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "SHA256SUMS.json").write_text(
        json.dumps(
            {
                path.name: sha(path.read_bytes())
                for path in sorted(output.iterdir())
                if path.is_file()
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "fits",
                    "optimizer_calls",
                    "unique_normalized_trajectories",
                    "new_independent_tasks",
                    "adoption",
                )
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    main(arguments.archive.resolve(), arguments.output.resolve())
