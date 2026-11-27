"""Post-seal independent checks of retained training bytes and accounting.

This analysis is excluded from the scientific source seal. Numerical evidence
is decoded here independently of the producer's budget_io loader.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same_number(actual, expected, name, tolerance=1e-8):
    require(math.isfinite(float(actual)), f"nonfinite {name}")
    require(
        math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance),
        f"{name}: {actual!r} != {expected!r}",
    )


def read_json(path):
    return json.loads(Path(path).read_text())


def decode_arrays(directory, expected_manifest_sha=None):
    directory = Path(directory)
    if expected_manifest_sha is not None:
        require(
            sha(directory / "manifest.json") == expected_manifest_sha,
            "array manifest hash",
        )
    manifest = read_json(directory / "manifest.json")
    require(manifest["format"] == "hcsn_followup_arrays_v1", "array format")
    pieces = []
    for item in manifest["parts"]:
        require(Path(item["file"]).name == item["file"], "array part path")
        path = directory / item["file"]
        require(sha(path) == item["sha256"], "array part hash")
        with np.load(path, allow_pickle=False) as archive:
            require(archive.files == ["bytes"], "array part inventory")
            value = archive["bytes"]
            require(
                value.dtype == np.uint8 and value.ndim == 1, "array part dtype/shape"
            )
            pieces.append(value.tobytes())
    packed, offset, arrays = b"".join(pieces), 0, {}
    require(len(packed) == manifest["nbytes"], "array payload byte count")
    for name, item in sorted(manifest["arrays"].items()):
        dtype = np.dtype(item["dtype"])
        require(not dtype.hasobject and item["offset"] == offset, "array dtype/offset")
        length = math.prod(item["shape"]) * dtype.itemsize
        require(length == item["nbytes"], "array shape byte count")
        raw = packed[offset : offset + length]
        require(hashlib.sha256(raw).hexdigest() == item["sha256"], "array tensor hash")
        arrays[name] = np.frombuffer(raw, dtype=dtype).reshape(item["shape"]).copy()
        offset += length
    require(offset == len(packed), "array trailing bytes")
    return arrays


def checkpoint_bytes(directory, expected_sha, config, structure):
    directory = Path(directory)
    require(
        sha(directory / "manifest.json") == expected_sha, "checkpoint manifest hash"
    )
    manifest = read_json(directory / "manifest.json")
    require(manifest["format"] == "concatenated_state_v1", "checkpoint format")
    require(manifest["config"] == config, "checkpoint model config")
    pieces = []
    for part in manifest["parts"]:
        path = directory / part["file"]
        require(sha(path) == part["sha256"], "checkpoint part hash")
        with np.load(path, allow_pickle=False) as archive:
            pieces.append(archive["bytes"].tobytes())
    packed, offset, seen = b"".join(pieces), 0, set()
    for tensor in manifest["tensors"]:
        name, dtype = tensor["name"], np.dtype(tensor["dtype"])
        require(name not in seen and name in structure, "checkpoint tensor inventory")
        require(tensor["offset"] == offset, "checkpoint tensor offset")
        require(
            (tensor["shape"], dtype.str) == structure[name],
            "checkpoint tensor shape/dtype",
        )
        length = math.prod(tensor["shape"]) * dtype.itemsize
        require(length == tensor["nbytes"], "checkpoint tensor byte count")
        raw = packed[offset : offset + length]
        require(
            hashlib.sha256(raw).hexdigest() == tensor["sha256"],
            "checkpoint tensor hash",
        )
        require(
            bool(np.isfinite(np.frombuffer(raw, dtype=dtype)).all()),
            "nonfinite checkpoint tensor",
        )
        offset += length
        seen.add(name)
    require(
        seen == set(structure) and offset == len(packed),
        "checkpoint inventory/trailing bytes",
    )
    return manifest


def expected_sources(bundle):
    result = {}
    for split_name in ("train", "val", "test"):
        split = getattr(bundle, split_name)
        result[split_name + "_sample_ids"] = split.sample_ids
        result[split_name + "_group_ids"] = split.group_ids
        for field in (
            "image_source_ids",
            "audio_source_ids",
            "query_modalities",
            "image_labels",
            "audio_labels",
        ):
            if field in split.metadata:
                result[split_name + "_" + field] = np.asarray(split.metadata[field])
    return result


def classification_metrics(logits, labels, split):
    require(
        logits.ndim == 2 and logits.shape[0] == len(labels),
        "classification logits dimensions",
    )
    require(
        np.all((labels >= 0) & (labels < logits.shape[1])),
        "classification label domain",
    )
    require(np.isfinite(logits).all(), "nonfinite heldout logits")
    values = logits.astype(np.float64)
    values -= values.max(axis=1, keepdims=True)
    normalization = np.log(np.exp(values).sum(axis=1))
    probabilities = np.exp(values - normalization[:, None])
    correct = logits.argmax(axis=1) == labels
    target = np.eye(logits.shape[1])[labels]
    result = {
        "accuracy": float(correct.mean()),
        "cross_entropy": float(
            (normalization - values[np.arange(len(labels)), labels]).mean()
        ),
        "brier": float(((probabilities - target) ** 2).sum(axis=1).mean()),
        "cases": len(labels),
    }
    metadata = split.metadata
    if "query_modalities" in metadata:
        query = np.asarray(metadata["query_modalities"])
        for modality in ("image", "spoken"):
            mask = query == modality
            if mask.any():
                result[modality + "_accuracy"] = float(correct[mask].mean())
        image, audio = (
            np.asarray(metadata["image_labels"]),
            np.asarray(metadata["audio_labels"]),
        )
        mask = (image >= 0) & (audio >= 0) & (image != audio)
        if mask.any():
            result["conflict_accuracy"] = float(correct[mask].mean())
    return result


def audit_search_costs(result):
    costs = result["costs_seconds"]
    expected = {
        name + suffix
        for name in (
            "preparation",
            "data_record",
            "candidate_totals",
            "selected_reload",
            "test",
            "prediction_record",
        )
        for suffix in ("_cpu", "_wall")
    }
    require(set(costs) == expected, "search cost phase inventory")
    require(
        all(math.isfinite(value) and value >= 0 for value in costs.values()),
        "search cost domains",
    )
    remainders = {}
    for suffix in ("cpu", "wall"):
        total = result[f"total_{suffix}_seconds"]
        require(math.isfinite(total) and total >= 0, "search total cost domain")
        same_number(
            costs[f"candidate_totals_{suffix}"],
            sum(row[f"total_{suffix}_seconds"] for row in result["candidates"]),
            "all-candidate total " + suffix,
        )
        accounted = sum(
            value for key, value in costs.items() if key.endswith("_" + suffix)
        )
        require(
            total + 1e-7 >= accounted, "search nonoverlapping " + suffix + " phases"
        )
        remainders[suffix + "_seconds_outside_explicit_phase_timers"] = max(
            0.0, total - accounted
        )
    require(
        result["total_cpu_seconds"] >= result["training_cpu_seconds"],
        "nested training/search CPU",
    )
    return {
        **remainders,
        "scope": "phase costs are contained in full search time; candidate totals contain all updates including those after the selected checkpoint",
    }


def audit_candidate(
    directory, spec, index, candidate, bundle, structure, parameters, parameter_names
):
    directory = Path(directory)
    require(
        read_json(directory / "RESULT.json") == candidate,
        "candidate embedded/file disagreement",
    )
    require(candidate["candidate_index"] == index, "candidate index")
    require(
        candidate["learning_rate"] == spec["learning_rates"][index],
        "candidate learning rate",
    )
    require(candidate["parameters"] == parameters, "active parameter counts")
    config = candidate["model_config"]
    expected = dict(
        input_dim=bundle.input_dim,
        classes=bundle.num_classes,
        width=spec["width"],
        depth=spec.get("depth", 1),
        architecture=spec["architecture"],
        seed=spec["seed"],
        match_cell_budget=spec.get("match_cell_budget", False),
    )
    require(config == expected, "candidate model/spec/data mismatch")
    manifest = checkpoint_bytes(
        directory / "checkpoint",
        candidate["checkpoint_manifest_sha256"],
        config,
        structure,
    )
    arrays = decode_arrays(directory / "arrays", candidate["arrays_manifest_sha256"])
    require(
        set(arrays)
        == {
            "batch_indices",
            "update_records",
            "validation_anchor_logits",
            "validation_anchor_sample_ids",
        },
        "candidate evidence inventory",
    )
    count, batch = candidate["updates_completed"], spec["batch_size"]
    indices, updates = arrays["batch_indices"], arrays["update_records"]
    require(
        candidate["update_record_columns"]
        == ["loss", "gradient_norm", "cpu_seconds", "wall_seconds"],
        "update record semantics",
    )
    require(
        indices.dtype == np.int64 and indices.shape == (count, batch),
        "minibatch layout",
    )
    require(
        updates.shape == (count, 4) and np.isfinite(updates).all(),
        "update record layout/finite",
    )
    require(
        np.all(updates >= 0) and np.all(updates[:, 2:] > 0),
        "update loss/norm/time domains",
    )
    generator = torch.Generator().manual_seed(spec["seed"] + 777)
    rebuilt = np.stack(
        [
            torch.randint(len(bundle.train), (batch,), generator=generator).numpy()
            for _ in range(count)
        ]
    )
    require(np.array_equal(indices, rebuilt), "exact minibatch RNG stream")
    require(candidate["minibatch_rng_seed"] == spec["seed"] + 777, "minibatch seed")
    require(candidate["examples_seen"] == count * batch, "training exposure")
    require(
        candidate["unique_examples_seen"] == np.unique(indices).size,
        "unique training exposure",
    )
    require(
        candidate["sequence_positions"] == count * batch * spec["length"],
        "training sequence exposure",
    )
    cpu, wall = np.cumsum(updates[:, 2]), np.cumsum(updates[:, 3])
    budget = spec["candidate_cpu_seconds"]
    same_number(candidate["cpu_budget_seconds"], budget, "candidate CPU allowance")
    same_number(
        candidate["costs_seconds"]["training_cpu"], cpu[-1], "summed training CPU"
    )
    same_number(
        candidate["costs_seconds"]["training_wall"], wall[-1], "summed training wall"
    )
    same_number(candidate["last_update_cpu_seconds"], updates[-1, 2], "last update CPU")
    same_number(
        candidate["cpu_budget_overshoot_seconds"],
        max(0.0, cpu[-1] - budget),
        "budget overshoot",
    )
    exhausted = bool(cpu[-1] >= budget)
    require(candidate["budget_exhausted"] == exhausted, "CPU exhaustion flag")
    require(
        candidate["termination"] == ("cpu_budget" if exhausted else "max_updates"),
        "termination reason",
    )
    require(1 <= count <= spec["max_updates"], "update safeguard")
    if exhausted:
        require(count == 1 or cpu[-2] < budget, "continued updates after budget")
        require(
            candidate["cpu_budget_overshoot_seconds"] <= updates[-1, 2] + 1e-8,
            "overshoot exceeds final step",
        )
    else:
        require(count == spec["max_updates"], "stopped before either bound")
    pending, expected_history = list(spec["cpu_milestone_fractions"]), []
    for i, accumulated in enumerate(cpu, start=1):
        crossed = []
        while pending and accumulated >= budget * pending[0]:
            crossed.append(pending.pop(0))
        if crossed or i == count:
            expected_history.append((i, crossed))
    history = candidate["history"]
    require(len(history) == len(expected_history), "validation milestone count")
    for row, (step, crossed) in zip(history, expected_history, strict=True):
        require(
            row["update"] == step and row["crossed_milestone_fractions"] == crossed,
            "coalesced validation milestone",
        )
        require(row["final"] == (step == count), "final validation flag")
        require(row["examples_seen"] == step * batch, "milestone exposure")
        same_number(row["training_cpu_seconds"], cpu[step - 1], "milestone CPU")
        same_number(row["training_wall_seconds"], wall[step - 1], "milestone wall")
        same_number(
            row["last_train_loss"], updates[step - 1, 0], "milestone training loss"
        )
        same_number(
            row["last_gradient_norm"], updates[step - 1, 1], "milestone gradient norm"
        )
        require(row["validation"]["cases"] == len(bundle.val), "validation case count")
        require(
            math.isfinite(row["validation"]["cross_entropy"]), "validation CE finite"
        )
    best = min(history, key=lambda row: row["validation"]["cross_entropy"])
    require(
        candidate["selected_update"] == best["update"],
        "within-candidate checkpoint selection",
    )
    same_number(
        candidate["selected_validation_ce"],
        best["validation"]["cross_entropy"],
        "selected validation CE",
    )
    require(
        manifest["extra"]
        == {
            "candidate_index": index,
            "selected_update": best["update"],
            "selected_validation_ce": best["validation"]["cross_entropy"],
            "training_cpu_seconds": best["training_cpu_seconds"],
        },
        "checkpoint selection metadata",
    )
    require(
        candidate["checkpoint_reload_max_error"] == 0, "recorded strict reload result"
    )
    anchor_count = min(64, len(bundle.val))
    require(
        arrays["validation_anchor_logits"].shape == (anchor_count, bundle.num_classes),
        "anchor dimensions",
    )
    require(
        np.array_equal(
            arrays["validation_anchor_sample_ids"], bundle.val.sample_ids[:anchor_count]
        ),
        "anchor identities",
    )
    require(
        set(candidate["gradient_groups"]) == parameter_names,
        "gradient parameter inventory",
    )
    require(
        all(
            row["finite"]
            and row["l1"] is not None
            and math.isfinite(row["l1"])
            and row["l1"] >= 0
            for row in candidate["gradient_groups"].values()
        ),
        "first-update gradients",
    )
    require(
        all(
            math.isfinite(value) and value >= 0
            for value in candidate["costs_seconds"].values()
        ),
        "candidate cost domain",
    )
    accounted_cpu = candidate["initialization_cpu_seconds"] + sum(
        value
        for key, value in candidate["costs_seconds"].items()
        if key.endswith("_cpu")
    )
    require(
        candidate["total_cpu_seconds"] + 1e-7 >= accounted_cpu,
        "candidate nonoverlapping CPU phases",
    )
    receipt = {
        "candidate_index": index,
        "updates": count,
        "training_cpu_seconds": float(cpu[-1]),
        "budget_exhausted": exhausted,
        "overshoot_seconds": candidate["cpu_budget_overshoot_seconds"],
        "checkpoint_sha256": candidate["checkpoint_manifest_sha256"],
        "array_manifest_sha256": candidate["arrays_manifest_sha256"],
    }
    return receipt, indices
