"""Independent per-run metrics, provenance, checkpoint and boundary checks."""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np


TOLERANCE = 1e-6


class AuditError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise AuditError(message)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path):
    return json.loads(Path(path).read_text())


def _inside(directory, name):
    directory = Path(directory).resolve()
    path = (directory / name).resolve()
    _require(
        path.is_relative_to(directory), f"Artifact path escapes its directory: {name}"
    )
    return path


def _npz(path):
    with np.load(path, allow_pickle=False) as loaded:
        return {key: loaded[key] for key in loaded.files}


def _close(actual, expected, label, tolerance=TOLERANCE):
    _require(np.isfinite(actual) and np.isfinite(expected), f"Nonfinite {label}.")
    _require(
        abs(float(actual) - float(expected)) <= tolerance,
        f"{label}: independently computed {actual}, recorded {expected}.",
    )


def classification_metrics(logits, labels):
    logits = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(labels)
    _require(
        logits.ndim == 2 and labels.shape == (len(logits),) and len(labels) > 0,
        "Invalid prediction/label dimensions.",
    )
    _require(
        labels.dtype.kind in "iu"
        and np.all((labels >= 0) & (labels < logits.shape[1])),
        "Class labels are outside the logit classes.",
    )
    _require(np.isfinite(logits).all(), "Nonfinite prediction logits.")
    centered = logits - logits.max(axis=1, keepdims=True)
    log_probability = centered - np.log(np.exp(centered).sum(axis=1, keepdims=True))
    probabilities = np.exp(log_probability)
    target = np.eye(logits.shape[1])[labels]
    return {
        "accuracy": float(np.mean(logits.argmax(1) == labels)),
        "cross_entropy": float(-log_probability[np.arange(len(labels)), labels].mean()),
        "brier": float(np.square(probabilities - target).sum(1).mean()),
        "cases": len(labels),
    }


def verify_checkpoint(directory, expected_sha):
    """Check packed bytes independently of model construction or checkpoint_load."""
    directory = Path(directory)
    path = directory / "manifest.json"
    _require(_sha(path) == expected_sha, "Checkpoint manifest SHA-256 mismatch.")
    manifest = _json(path)
    _require(
        manifest.get("format") == "concatenated_state_v1",
        "Unsupported checkpoint format.",
    )
    buffers, filenames = [], set()
    for part in manifest["parts"]:
        _require(part["file"] not in filenames, "Duplicate checkpoint chunk.")
        filenames.add(part["file"])
        path = _inside(directory, part["file"])
        _require(_sha(path) == part["sha256"], "Checkpoint chunk SHA-256 mismatch.")
        chunk = _npz(path)
        _require(
            set(chunk) == {"bytes"}
            and chunk["bytes"].dtype == np.uint8
            and chunk["bytes"].ndim == 1,
            "Malformed checkpoint byte chunk.",
        )
        _require(
            chunk["bytes"].size <= 360000,
            "Checkpoint chunk exceeds the declared raw bound.",
        )
        buffers.append(chunk["bytes"].tobytes())
    packed = b"".join(buffers)
    offset, elements, names = 0, 0, set()
    for tensor in manifest["tensors"]:
        _require(tensor["name"] not in names, "Duplicate checkpoint tensor name.")
        names.add(tensor["name"])
        dtype = np.dtype(tensor["dtype"])
        _require(not dtype.hasobject, "Object dtype in checkpoint.")
        shape = tuple(tensor["shape"])
        _require(
            all(isinstance(v, int) and v >= 0 for v in shape),
            "Invalid checkpoint shape.",
        )
        count = math.prod(shape)
        _require(
            tensor["offset"] == offset and tensor["nbytes"] == count * dtype.itemsize,
            "Checkpoint tensor byte layout has a gap, overlap or wrong size.",
        )
        raw = packed[offset : offset + tensor["nbytes"]]
        _require(
            len(raw) == tensor["nbytes"]
            and hashlib.sha256(raw).hexdigest() == tensor["sha256"],
            f"Checkpoint tensor SHA-256 mismatch: {tensor['name']}.",
        )
        if dtype.kind in "fc":
            _require(
                np.isfinite(np.frombuffer(raw, dtype=dtype)).all(),
                "Nonfinite checkpoint tensor.",
            )
        offset += len(raw)
        elements += count
    _require(offset == len(packed), "Unassigned trailing checkpoint bytes.")
    return {
        "manifest_sha256": expected_sha,
        "tensors": len(names),
        "parts": len(filenames),
        "state_elements_including_buffers": elements,
        "bytes": offset,
        "config": manifest["config"],
        "extra": manifest.get("extra", {}),
    }


def _fingerprint(arrays):
    digest = hashlib.sha256()
    for key in sorted(arrays):
        array = np.ascontiguousarray(arrays[key])
        digest.update(json.dumps([key, array.dtype.str, array.shape]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def verify_classification(directory, result):
    directory = Path(directory)
    spec = result["spec"]
    predictions = _npz(directory / "predictions.npz")
    metrics = classification_metrics(predictions["logits"], predictions["labels"])
    for key, value in metrics.items():
        _close(value, result["test"][key], f"Reported test {key}")
    source_path = directory / "split_sources.npz"
    _require(
        _sha(source_path) == result["split_sources_sha256"],
        "Split-source SHA-256 mismatch.",
    )
    sources = _npz(source_path)
    sizes = {
        "train": spec["train_size"],
        "val": spec.get("val_size", 512),
        "test": spec.get("test_size", 1024),
    }
    for split, size in sizes.items():
        ids = sources[f"{split}_sample_ids"]
        _require(
            ids.shape == (size,) and len(set(ids.tolist())) == size,
            f"Invalid {split} episode IDs.",
        )
        _require(
            sources[f"{split}_group_ids"].shape == (size,),
            f"Missing/malformed {split} groups.",
        )
        for key, values in sources.items():
            if key.startswith(split + "_"):
                _require(
                    values.shape == (size,), f"Source metadata length mismatch: {key}."
                )
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        for key in ("sample_ids", "image_source_ids", "audio_source_ids"):
            a, b = sources.get(f"{left}_{key}", []), sources.get(f"{right}_{key}", [])
            _require(
                not ((set(a) - {""}) & (set(b) - {""})),
                f"Cross-split source leakage: {key}.",
            )
        if set(sources.get(f"{left}_audio_source_ids", [])) - {""}:
            _require(
                not (
                    set(sources[f"{left}_group_ids"])
                    & set(sources[f"{right}_group_ids"])
                ),
                "Audio speaker groups overlap across splits.",
            )
    data = _json(directory / "DATA.json")
    _require(
        data["task"] == spec["task"], "Data manifest task disagrees with run spec."
    )
    if "source_counts" in data:
        for split in sizes:
            for kind, field in (
                ("image", "unique_images"),
                ("audio", "unique_recordings"),
            ):
                count = len(set(sources.get(f"{split}_{kind}_source_ids", [])) - {""})
                _require(
                    count == data["source_counts"][split][field],
                    "Recorded independent-source count mismatch.",
                )
    for key in ("sample_ids", "group_ids"):
        _require(
            np.array_equal(predictions[key], sources[f"test_{key}"]),
            f"Prediction/test source {key} mismatch.",
        )
    _require(metrics["cases"] == sizes["test"], "Test case count disagrees with spec.")
    correct = predictions["logits"].argmax(1) == predictions["labels"]
    if "test_query_modalities" in sources:
        query = sources["test_query_modalities"]
        images, audio = sources["test_image_labels"], sources["test_audio_labels"]
        target = np.where(query == "spoken", audio, images)
        _require(
            np.array_equal(target, predictions["labels"]),
            "Test labels disagree with query-selected sources.",
        )
        for modality in ("image", "spoken"):
            mask = query == modality
            if mask.any():
                _close(
                    correct[mask].mean(),
                    result["test"][f"{modality}_accuracy"],
                    f"{modality} accuracy",
                )
        conflict = (images >= 0) & (audio >= 0) & (images != audio)
        if conflict.any():
            _close(
                correct[conflict].mean(),
                result["test"]["conflict_accuracy"],
                "Conflict accuracy",
            )
        elif "conflict_accuracy" in result["test"]:
            raise AuditError(
                "Conflict accuracy was reported without any two-modality conflict."
            )
        _require(
            np.all(images[query == "both"] == audio[query == "both"]),
            "Class-paired query has unequal source labels.",
        )
    indices = _npz(directory / "batch_indices.npz")["indices"]
    _require(
        indices.dtype.kind in "iu"
        and indices.shape == (spec["updates"], spec.get("batch_size", 32)),
        "Batch index dimensions/dtype disagree with spec.",
    )
    _require(
        np.all((indices >= 0) & (indices < sizes["train"])),
        "Training batch index outside training split.",
    )
    seen = {
        "training_examples_seen": int(indices.size),
        "unique_training_examples_seen": int(np.unique(indices).size),
        "training_sequence_positions": int(indices.size * spec["length"]),
    }
    for key, count in seen.items():
        _require(result[key] == count, f"Training exposure count mismatch: {key}.")
    checkpoint = verify_checkpoint(
        directory / "checkpoint", result["checkpoint_manifest_sha256"]
    )
    for key in ("architecture", "width", "depth", "seed"):
        _require(
            checkpoint["config"][key] == spec.get(key, 1 if key == "depth" else None),
            f"Checkpoint/spec mismatch: {key}.",
        )
    _require(
        checkpoint["extra"]["selected_step"] == result["selected_step"],
        "Checkpoint selected step mismatch.",
    )
    best = min(result["history"], key=lambda row: row["validation"]["cross_entropy"])
    _require(
        best["update"] == result["selected_step"],
        "Selected checkpoint is not the first minimum validation CE.",
    )
    _close(
        result["checkpoint_reload_max_error"], 0, "Checkpoint reload error", tolerance=0
    )
    counts = result["parameters"]
    for key in ("training_cpu_seconds", "total_cpu_seconds"):
        _require(
            np.isfinite(result[key]) and result[key] >= 0,
            f"Invalid CPU measurement: {key}.",
        )
    _require(
        counts["total"]
        == sum(counts[key] for key in ("frontend", "backbone", "readout")),
        "Parameter subtotal mismatch.",
    )
    _require(
        0 <= counts["total"] <= checkpoint["state_elements_including_buffers"],
        "Invalid parameter count versus retained state.",
    )
    hashes = {
        name: _sha(directory / name)
        for name in (
            "RESULT.json",
            "DATA.json",
            "predictions.npz",
            "batch_indices.npz",
            "split_sources.npz",
        )
    }
    return {
        "metrics": metrics,
        "checkpoint": checkpoint,
        "exposures": seen,
        "artifact_hashes": hashes,
        "heldout_fingerprint": _fingerprint(
            {
                **{k: v for k, v in sources.items() if k.startswith("test_")},
                "labels": predictions["labels"],
            }
        ),
        "batch_fingerprint": _fingerprint({"indices": indices}),
    }


def verify_boundary(directory, result):
    """Recompute per-episode execution and utility; do not re-solve Bellman tables."""
    directory = Path(directory)
    actor = result["actor"]
    checkpoint = verify_checkpoint(
        directory / "actor_checkpoint", actor["checkpoint_manifest_sha256"]
    )
    _require(
        result["first_observation_charged"] is True
        and result["bayes_teacher"] is False,
        "Boundary accounting/teacher contract changed.",
    )
    _close(
        actor["checkpoint_reload_max_error"], 0, "Boundary actor reload", tolerance=0
    )
    sums, counts, identifiers, file_names = (
        defaultdict(lambda: defaultdict(lambda: np.zeros(4))),
        defaultdict(int),
        set(),
        set(),
    )
    for item in result["episode_files"]:
        _require(item["file"] not in file_names, "Repeated boundary shard.")
        file_names.add(item["file"])
        path = _inside(directory, item["file"])
        _require(_sha(path) == item["sha256"], "Boundary episode SHA-256 mismatch.")
        rows = _npz(path)
        n = len(rows["label"])
        _require(
            n == item["cases"] and rows["observations"].ndim == 2,
            "Boundary shard dimensions mismatch.",
        )
        ids = rows["episode_id"].tolist()
        _require(
            len(set(ids)) == n and not (set(ids) & identifiers),
            "Boundary episode IDs overlap.",
        )
        identifiers.update(ids)
        horizon = rows["observations"].shape[1]
        _require(np.all(rows["horizon"] == horizon), "Boundary horizon mismatch.")
        remaining = np.broadcast_to(np.arange(horizon - 1, -1, -1), (n, horizon))
        _require(
            np.array_equal(rows["remaining_steps"], remaining),
            "Boundary remaining-time contract mismatch.",
        )
        bayes = (2 * rows["snr"][:, None] * rows["observations"]).cumsum(1)
        _require(
            np.allclose(bayes, rows["bayes_log_odds"], rtol=2e-6, atol=2e-5),
            "Saved Bayes evidence does not match observations.",
        )
        for arm in ("fixed", "direct", "value", "oracle"):
            mask = rows[f"{arm}_stop_mask"].astype(bool)
            _require(
                mask.shape == (n, horizon) and mask[:, -1].all(),
                "Boundary stop-mask horizon contract mismatch.",
            )
            index = mask.argmax(1)
            _require(
                np.array_equal(index, rows[f"{arm}_stop_index"]),
                "Boundary index is not first recorded stop.",
            )
            odds = rows["bayes_log_odds"] if arm == "oracle" else rows["actor_log_odds"]
            _require(np.isfinite(odds).all(), "Nonfinite boundary log odds.")
            action = (odds[np.arange(n), index] >= 0).astype(int)
            correct = action == rows["label"]
            observations = index + 1
            cost = rows["cost"].astype(float) * observations
            utility = correct.astype(float) - cost
            for key, expected in (
                ("action", action),
                ("correct", correct),
                ("observations", observations),
                ("total_cost", cost),
                ("net_utility", utility),
            ):
                _require(
                    np.allclose(rows[f"{arm}_{key}"], expected, rtol=0, atol=TOLERANCE),
                    f"Boundary {arm}/{key} accounting mismatch.",
                )
            if arm in ("fixed", "direct"):
                confidence = 1 / (1 + np.exp(-np.abs(odds.astype(float))))
                if arm == "fixed":
                    threshold = result["fixed"]["threshold"]
                else:
                    parameters = result["direct"]["parameters"]
                    features = np.stack(
                        (
                            np.log1p(remaining),
                            np.broadcast_to(
                                np.log(np.maximum(rows["snr"], 1e-6))[:, None],
                                remaining.shape,
                            ),
                            np.broadcast_to(
                                np.log(np.maximum(rows["cost"], 1e-6))[:, None],
                                remaining.shape,
                            ),
                        ),
                        axis=-1,
                    )
                    score = parameters["direct_bias"] + features @ np.array(
                        parameters["direct_context"]
                    )
                    threshold = 0.5 + 0.4999 / (1 + np.exp(-np.clip(score, -700, 700)))
                resolved = np.abs(confidence - threshold) > 1e-6
                expected = (confidence >= threshold) | (remaining == 0)
                _require(
                    np.array_equal(mask[resolved], expected[resolved]),
                    f"Boundary {arm} threshold mask mismatch.",
                )
            sums[item["split"]][arm] += np.array(
                [correct.sum(), observations.sum(), cost.sum(), utility.sum()]
            )
        counts[item["split"]] += n
    recomputed = {}
    for split, arms in sums.items():
        recomputed[split] = {}
        for arm, total in arms.items():
            metrics = dict(
                zip(
                    ("accuracy", "mean_observations", "mean_total_cost", "net_utility"),
                    (total / counts[split]).tolist(),
                )
            )
            metrics["cases"] = counts[split]
            for key, value in metrics.items():
                _close(
                    value,
                    result["metrics"][split][arm][key],
                    f"Boundary {split}/{arm}/{key}",
                )
            recomputed[split][arm] = metrics
    _require(
        set(recomputed) == set(result["metrics"]), "Missing boundary metric split."
    )
    return {
        "boundary_status": "execution_and_reported_metrics_verified",
        "metrics": recomputed,
        "checkpoint": checkpoint,
        "episode_files": len(file_names),
        "episodes": len(identifiers),
        "bellman_scope": "First-stop execution independently checked; Bellman tables were not independently re-solved per episode.",
    }
