"""Replay every candidate's development records and every confirmation episode."""

import numpy as np

from .audit_core import (
    ARMS,
    COUNTERS,
    LEARNED,
    SEEDS,
    checked_file,
    close,
    episode,
    read,
    require,
    sha,
    streams,
    strict_json,
    verify_checkpoint,
    verify_context_counters,
)
from .audit_training import load_shard, training_arrays, verify_export, verify_fit


def audit_shard(
    root,
    item,
    seed,
    arm,
    split,
    checkpoint,
    identity,
    profile,
    refs,
    contexts=8,
    paths=16,
):
    require(
        item["seed"] == seed and item["arm"] == arm and item["split"] == split,
        "Shard phase/arm/seed binding mismatch",
    )
    records = load_shard(root, item)
    require(
        len(records) == contexts * paths and len(item["counts"]) == contexts,
        "Missing/duplicate complete context/path roster",
    )
    verified = []
    for index in range(contexts):
        ref = refs[seed, split, index]
        initial, slots, stream_id = streams(seed, split, index, paths, ref)
        group = records[index * paths : (index + 1) * paths]
        for path_index, row in enumerate(group):
            require(
                row["train_seed"] == seed
                and row["arm"] == arm
                and row["split"] == split
                and row["episode_id"] == f"{seed}.{split}.c{index}.p{path_index}"
                and row["eval_seed"] == stream_id
                and row["checkpoint_sha256"] == identity,
                "Episode/phase/random-stream/checkpoint identity mismatch",
            )
            verified.append(
                episode(
                    row,
                    checkpoint,
                    ref,
                    profile,
                    int(initial[path_index]),
                    slots[:, path_index],
                )
            )
        verify_context_counters(group, item["counts"][index])
    counts = {name: sum(row[name] for row in verified) for name in COUNTERS}
    return verified, counts


def verify_training(
    root,
    selection,
    refs,
    seeds=SEEDS,
    training_contexts=12,
    training_paths=8,
    development_contexts=8,
    development_paths=8,
    epochs=120,
    candidates=(0, 1, 2),
):
    selected = {}
    for item in selection["checkpoints"]:
        key = item["seed"], item["arm"]
        require(
            key not in selected and key[0] in seeds and key[1] in ARMS,
            "Duplicate/undeclared selected checkpoint",
        )
        require(
            item["path"] == f"checkpoints/{key[0]}/{key[1]}.json",
            "Selected checkpoint path changed",
        )
        selected[key] = item
    require(
        set(selected) == {(seed, arm) for seed in seeds for arm in ARMS},
        "Incomplete selected head/control roster",
    )
    checkpoints, profiles, training, exports, dev_counts, files = (
        {},
        {},
        {},
        {},
        {},
        set(),
    )
    for seed in seeds:
        features, teacher = training_arrays(
            root, seed, refs, training_contexts, training_paths
        )
        activation, physical, export = verify_export(
            root, seed, features, teacher, training_contexts, training_paths
        )
        exports[seed] = export
        export_hash = sha((root / f"datasets/{seed}/FEATURE_EXPORT.json").read_bytes())
        meta = read(root, f"datasets/{seed}/training.json")
        files |= {
            f"datasets/{seed}/training.json",
            meta["path"],
            f"datasets/{seed}/FEATURE_EXPORT.json",
            export["path"],
            export["profile_path"],
            export["native_export"]["path"],
        }
        for arm in ARMS:
            item = selected[seed, arm]
            path = checked_file(root, item["path"], item["sha256"])
            checkpoint = strict_json(path.read_bytes())
            profile = verify_checkpoint(root, checkpoint, seed, arm)
            checkpoints[seed, arm], profiles[seed, arm] = (
                (checkpoint, item["sha256"]),
                profile,
            )
            files.add(item["path"])
            if arm == "finite_grid_dp":
                continue
            name = f"training/{seed}/{arm}/TRAINING.json"
            receipt = read(root, name)
            files.add(name)
            require(
                receipt["schema"] == "hepta.native-readout-objective.training.v1"
                and receipt["seed"] == seed
                and receipt["arm"] == arm
                and receipt["test_data_used"] is False
                and [c["candidate_index"] for c in receipt["candidates"]]
                == list(candidates),
                "Training selection/phase/candidate budget changed",
            )
            training[seed, arm] = receipt
            dev_counts[seed, arm] = dict.fromkeys(COUNTERS, 0)
            for candidate in receipt["candidates"]:
                index = candidate["candidate_index"]
                require(
                    candidate["path"]
                    == f"training/{seed}/{arm}/candidates/{index}.json",
                    "Candidate artifact path changed",
                )
                candidate_path = checked_file(
                    root, candidate["path"], candidate["sha256"]
                )
                ckpt = strict_json(candidate_path.read_bytes())
                prof = verify_checkpoint(root, ckpt, seed, arm)
                require(
                    ckpt["candidate_index"] == index
                    and ckpt["candidate"] == candidate["candidate"]
                    and ckpt["shared_feature_export_sha256"] == export_hash
                    and ckpt["training_activation_q24_sha256"]
                    == candidate["activation_q24_sha256"]
                    == export["activation_q24_sha256"]
                    and ckpt["physical_teacher_sha256"]
                    == candidate["physical_q_sha256"]
                    == export["physical_q_sha256"],
                    "Candidate common inputs or teacher units differ",
                )
                require(
                    candidate["observed_active_columns"]
                    == int(np.count_nonzero(np.any(activation > 0, axis=0))),
                    "Observed active parameter coverage changed",
                )
                verify_fit(candidate, ckpt, activation, physical, epochs)
                files |= {candidate["path"], ckpt["profile_path"]}
                require(
                    len(candidate["development_shards"]) == 1,
                    "Development shard roster changed",
                )
                shard = candidate["development_shards"][0]
                require(
                    shard["path"]
                    == f"training/{seed}/{arm}/development/{index}.jsonl.gz",
                    "Development evidence path changed",
                )
                files.add(shard["path"])
                result, counts = audit_shard(
                    root,
                    shard,
                    seed,
                    arm,
                    "development",
                    ckpt,
                    candidate["sha256"],
                    prof,
                    refs,
                    development_contexts,
                    development_paths,
                )
                returns = [row["net_utility"] for row in result]
                close(
                    candidate["development_returns"],
                    returns,
                    "development episode returns",
                )
                close(
                    candidate["development_mean_net_utility"],
                    np.mean(returns),
                    "candidate selection score",
                )
                for key, value in counts.items():
                    dev_counts[seed, arm][key] += value
            winner = max(
                receipt["candidates"],
                key=lambda c: (
                    c["development_mean_net_utility"],
                    -c["candidate_index"],
                ),
            )
            require(
                receipt["selected_index"] == winner["candidate_index"]
                and path.read_bytes() == (root / winner["path"]).read_bytes()
                and winner["sha256"] == item["sha256"],
                "Selected head differs from development-only winner",
            )
    return checkpoints, profiles, training, exports, dev_counts, files
