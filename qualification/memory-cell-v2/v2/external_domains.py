"""Three pinned perceptual classification sources, separate from episodic memory.

Same learner and train-only normalization across datasets. Repeated split seeds
do not create additional independent source domains. No sklearn or network calls
are needed to run these saved source snapshots.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import statistics
import time

import numpy as np

from .tasks import canonical


SOURCE_MANIFEST_SHA256 = (
    "916866205153dfa0c6d439e981382b4e7fc61cb3495cb2397334dbf2b13d603b"
)
DEFAULT_PROFILE = {
    "input_dim": 65,
    "rank": 32,
    "steps": 600,
    "learning_rate": 0.03,
    "split_fractions": [0.6, 0.2, 0.2],
    "neighbor_candidates": [1, 5],
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def _row_key(row):
    return np.asarray(row, dtype="<f8").tobytes()


def stratified_group_split(X, y, seed):
    """Class-stratified 60/20/20 group split; identical inputs never cross cuts."""
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    groups, labels = defaultdict(list), {}
    for index, (row, label) in enumerate(zip(X, y)):
        key = _row_key(row)
        if key in labels and labels[key] != int(label):
            raise ValueError("identical features have conflicting labels")
        groups[key].append(index)
        labels[key] = int(label)
    rng, result = (
        np.random.default_rng(seed),
        {name: [] for name in ("train", "selection", "test")},
    )
    for label in sorted(set(labels.values())):
        keys = sorted(key for key in groups if labels[key] == label)
        if len(keys) < 5:
            raise ValueError(
                "each class requires at least five distinct feature groups"
            )
        order = rng.permutation(len(keys))
        first, second = len(keys) * 3 // 5, len(keys) * 4 // 5
        for name, positions in zip(
            result, (order[:first], order[first:second], order[second:])
        ):
            result[name].extend(
                index for pos in positions for index in groups[keys[int(pos)]]
            )
    return {
        name: np.asarray(sorted(indices), dtype=np.int64)
        for name, indices in result.items()
    }


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, train):
        train = np.asarray(train, dtype=np.float64)
        if (
            train.ndim != 2
            or not 1 <= train.shape[1] <= 64
            or not len(train)
            or not np.isfinite(train).all()
        ):
            raise ValueError("finite training features with 1..64 columns are required")
        scale = train.std(axis=0)
        return cls(train.mean(axis=0), np.where(scale == 0, 1.0, scale))

    def standardize(self, raw):
        raw = np.asarray(raw, dtype=np.float64)
        if (
            raw.ndim != 2
            or raw.shape[1] != len(self.mean)
            or not np.isfinite(raw).all()
        ):
            raise ValueError("query feature shape or numeric values differ")
        return (raw - self.mean) / self.scale

    def transform(self, raw):
        standardized = self.standardize(raw)
        result = np.zeros((len(standardized), 65), dtype=np.float64)
        result[:, : len(self.mean)] = standardized
        result[:, 64] = 1.0
        return result

    def manifest(self):
        return {
            "schema": "memory-cell-v2.standardizer.v1",
            "dimension": 65,
            "source_features": len(self.mean),
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "fit_split": "train",
            "ddof": 0,
            "zero_variance_scale": 1.0,
            "padding": "zeros through feature 63; bias at 64",
        }

    @classmethod
    def from_manifest(cls, manifest):
        if manifest.get("schema") != "memory-cell-v2.standardizer.v1":
            raise ValueError("unsupported normalizer schema")
        mean, scale = (
            np.asarray(manifest["mean"], dtype=float),
            np.asarray(manifest["scale"], dtype=float),
        )
        if (
            mean.ndim != 1
            or scale.shape != mean.shape
            or not 1 <= len(mean) <= 64
            or not np.isfinite(mean).all()
            or not np.isfinite(scale).all()
            or np.any(scale <= 0)
        ):
            raise ValueError("invalid normalizer state")
        normalizer = cls(mean, scale)
        if normalizer.manifest() != manifest:
            raise ValueError("normalizer contract mismatch")
        return normalizer


@dataclass(frozen=True)
class ExternalTask:
    name: str
    X: np.ndarray
    y: np.ndarray
    indices: dict
    normalizer: Standardizer
    source: dict
    preparation_seconds: dict


def build_external_tasks(seed=8001, source_dir=None):
    directory = Path(
        source_dir or Path(__file__).resolve().parents[1] / "sources" / "external"
    )
    raw_manifest = (directory / "SOURCES.json").read_bytes()
    if _sha(raw_manifest) != SOURCE_MANIFEST_SHA256:
        raise ValueError("external source manifest differs from frozen identity")
    manifest, tasks = json.loads(raw_manifest), {}
    for source in manifest["sources"]:
        started = time.perf_counter()
        path = directory / source["snapshot_file"]
        if _sha(path.read_bytes()) != source["snapshot_sha256"]:
            raise ValueError("external array snapshot differs")
        bundled = directory / source["bundled_source_file"]
        if _sha(bundled.read_bytes()) != source["bundled_source_sha256"]:
            raise ValueError("original bundled data differs")
        with np.load(path, allow_pickle=False) as archive:
            X, y = archive["X"], archive["y"]
        if (
            list(X.shape) != source["shape"]
            or y.shape != (len(X),)
            or _sha(X.astype("<f8").tobytes()) != source["feature_sha256"]
            or _sha(y.astype("<i8").tobytes()) != source["target_sha256"]
        ):
            raise ValueError("source array identity or shape mismatch")
        load_seconds = time.perf_counter() - started
        started = time.perf_counter()
        indices = stratified_group_split(X, y, seed)
        split_seconds = time.perf_counter() - started
        started = time.perf_counter()
        normalizer = Standardizer.fit(X[indices["train"]])
        fit_seconds = time.perf_counter() - started
        X.flags.writeable, y.flags.writeable = False, False
        tasks[source["name"]] = ExternalTask(
            source["name"],
            X,
            y,
            indices,
            normalizer,
            source,
            {
                "source_verification_load": load_seconds,
                "stratified_partition": split_seconds,
                "normalizer_fit_train_only": fit_seconds,
            },
        )
    return tasks


def exact_index(X, y):
    result = {}
    for row, label in zip(X, y):
        key = _row_key(row)
        if key in result and result[key] != int(label):
            raise ValueError("conflicting exact source association")
        result[key] = int(label)
    return result


def exact_predict(index, raw):
    return [index.get(_row_key(row)) for row in raw]


def neighbors_predict(index_X, index_y, query_X, k, classes):
    """Exact Euclidean kNN; stable row-order ties, then lowest class vote ties."""
    if k not in (1, 5) or len(index_X) < k:
        raise ValueError("frozen neighbor candidates are 1 and 5")
    result = []
    for offset in range(0, len(query_X), 256):
        batch = query_X[offset : offset + 256]
        distance = np.maximum(
            0,
            (batch**2).sum(axis=1)[:, None]
            + (index_X**2).sum(axis=1)[None, :]
            - 2 * batch @ index_X.T,
        )
        nearest = (
            distance.argmin(axis=1)[:, None]
            if k == 1
            else np.argsort(distance, axis=1, kind="stable")[:, :k]
        )
        result.extend(
            int(np.bincount(index_y[indices], minlength=classes).argmax())
            for indices in nearest
        )
    return result


def select_k(selection_targets, predictions):
    """Selection-only choice; no test arrays or test outcome are accepted."""
    scores = {
        k: float(np.mean(np.asarray(predictions[k]) == selection_targets))
        for k in (1, 5)
    }
    return max(scores, key=lambda k: (scores[k], -k)), scores


def _predict_phase(task, cell, index, numeric_index, indices):
    raw, labels = task.X[indices], task.y[indices]
    methods = {
        "model": lambda: cell.predict(task.normalizer.transform(raw)).tolist(),
        "exact": lambda: exact_predict(index, raw),
        "1nn": lambda: neighbors_predict(
            numeric_index,
            task.y[task.indices["train"]],
            task.normalizer.standardize(raw),
            1,
            len(task.source["classes"]),
        ),
        "5nn": lambda: neighbors_predict(
            numeric_index,
            task.y[task.indices["train"]],
            task.normalizer.standardize(raw),
            5,
            len(task.source["classes"]),
        ),
    }
    values, seconds = {}, {}
    for name, method in methods.items():
        started = time.perf_counter()
        values[name] = method()
        seconds[name] = time.perf_counter() - started
    return values, seconds, labels


def _run_case(task, profile, directory, source_commit, seed):
    from memory_cells.metrics import break_even_reads, summarize_predictions
    from memory_cells.model import MemoryCell
    from .adapter import load_cell, save_cell

    started_case = time.perf_counter()
    directory.mkdir(parents=True, exist_ok=False)
    train_ids = task.indices["train"]
    train_X, train_y = task.X[train_ids], task.y[train_ids]
    _write(
        directory / "partition.json",
        {name: ids.tolist() for name, ids in task.indices.items()},
    )
    started = time.perf_counter()
    _write(directory / "normalizer.json", task.normalizer.manifest())
    normalizer_save_seconds = time.perf_counter() - started
    started = time.perf_counter()
    _write(directory / "labels.json", task.source["target_names"])
    labels_save_seconds = time.perf_counter() - started
    encoder_manifest = {
        "schema": "memory-cell-v2.padded-numeric-features.v1",
        "dimension": 65,
        "normalizer_sha256": _sha((directory / "normalizer.json").read_bytes()),
    }
    support = _sha(train_X.astype("<f8").tobytes() + train_y.astype("<i8").tobytes())
    started = time.perf_counter()
    with (directory / "written-records.npz").open("wb") as stream:
        np.savez_compressed(stream, X=train_X, y=train_y, source_indices=train_ids)
    replay_write_seconds = time.perf_counter() - started
    started = time.perf_counter()
    index = exact_index(train_X, train_y)
    exact_build_seconds = time.perf_counter() - started
    started = time.perf_counter()
    numeric_index = task.normalizer.standardize(train_X)
    numeric_index_seconds = time.perf_counter() - started
    started = time.perf_counter()
    index_manifest = {
        "algorithm": "exact Euclidean scan",
        "k_candidates": [1, 5],
        "persistent_payload": "written-records.npz",
        "normalizer": "normalizer.json",
        "runtime_index_rebuilt_from_source": True,
        "tie_policy": "ascending source row index, then lowest class ID",
    }
    _write(directory / "index.json", index_manifest)
    index_manifest_save_seconds = time.perf_counter() - started
    started = time.perf_counter()
    features = task.normalizer.transform(train_X)
    encoding_seconds = time.perf_counter() - started
    cell = MemoryCell(65, profile["rank"], len(task.source["classes"]), seed=seed)
    training = cell.fit(
        features, train_y, steps=profile["steps"], lr=profile["learning_rate"]
    )
    started = time.perf_counter()
    saved = save_cell(
        cell,
        directory / "model",
        encoder_manifest,
        source_commit=source_commit,
        support_digest=support,
    )
    model_save_seconds = time.perf_counter() - started
    started = time.perf_counter()
    loaded, _ = load_cell(
        directory / "model", expected_encoder_digest=saved["encoder_digest"]
    )
    normalizer_bytes = (directory / "normalizer.json").read_bytes()
    if _sha(normalizer_bytes) != encoder_manifest["normalizer_sha256"]:
        raise ValueError("saved normalization artifact changed")
    task = replace(
        task, normalizer=Standardizer.from_manifest(json.loads(normalizer_bytes))
    )
    model_load_seconds = time.perf_counter() - started
    if not np.array_equal(cell.predict(features), loaded.predict(features)):
        raise ValueError("reloaded model disagrees on written features")
    selection, selection_seconds, labels = _predict_phase(
        task, loaded, index, numeric_index, task.indices["selection"]
    )
    selected_k, selection_scores = select_k(
        labels, {1: selection["1nn"], 5: selection["5nn"]}
    )
    started = time.perf_counter()
    _write(directory / "index.json", {**index_manifest, "selected_k": selected_k})
    index_manifest_save_seconds += time.perf_counter() - started
    _write(
        directory / "selection.json",
        {
            "selected_k": selected_k,
            "scores": selection_scores,
            "source_indices": task.indices["selection"].tolist(),
            "targets": labels.tolist(),
            "predictions": selection,
            "tie_policy": "prefer smaller K",
            "test_targets_used": False,
        },
    )
    results, phase_seconds, rows = {}, {"selection": selection_seconds}, []
    majority = int(np.bincount(train_y).argmax())
    for phase, indices in (
        ("written_recovery", train_ids),
        ("unseen_test", task.indices["test"]),
    ):
        values, read_seconds, labels = _predict_phase(
            task, loaded, index, numeric_index, indices
        )
        values["selected_knn"] = values[f"{selected_k}nn"]
        values["majority"] = [majority] * len(indices)
        read_seconds["selected_knn"] = read_seconds[f"{selected_k}nn"]
        results[phase] = {
            name: summarize_predictions(labels.tolist(), predicted)
            for name, predicted in values.items()
        }
        phase_seconds[phase] = read_seconds
        rows.extend(
            {
                "phase": phase,
                "source_index": int(index_id),
                "target": int(labels[pos]),
                "predictions": {
                    name: predicted[pos] for name, predicted in values.items()
                },
            }
            for pos, index_id in enumerate(indices)
        )
    _write(directory / "predictions.json", rows)
    normalization = task.preparation_seconds["normalizer_fit_train_only"]
    write_seconds = {
        "model": normalization
        + normalizer_save_seconds
        + labels_save_seconds
        + encoding_seconds
        + training["seconds"]
        + model_save_seconds
        + model_load_seconds
        + replay_write_seconds,
        "exact": replay_write_seconds + exact_build_seconds + labels_save_seconds,
        "1nn": normalization
        + normalizer_save_seconds
        + labels_save_seconds
        + replay_write_seconds
        + numeric_index_seconds
        + index_manifest_save_seconds,
        "5nn": normalization
        + normalizer_save_seconds
        + labels_save_seconds
        + replay_write_seconds
        + numeric_index_seconds
        + index_manifest_save_seconds,
    }
    write_seconds["selected_knn"] = (
        write_seconds[f"{selected_k}nn"]
        + selection_seconds["1nn"]
        + selection_seconds["5nn"]
    )
    sizes = {
        name: (directory / name).stat().st_size
        for name in (
            "normalizer.json",
            "labels.json",
            "written-records.npz",
            "index.json",
        )
    }
    model_bytes = sum(path.stat().st_size for path in (directory / "model").iterdir())
    deployed = {
        "model_without_replay": model_bytes
        + sizes["normalizer.json"]
        + sizes["labels.json"],
        "model_with_replay": model_bytes
        + sizes["normalizer.json"]
        + sizes["labels.json"]
        + sizes["written-records.npz"],
        "exact": sizes["written-records.npz"] + sizes["labels.json"],
        "knn": sum(sizes.values()),
    }
    break_even = {}
    for name, phase in (
        ("exact", "written_recovery"),
        ("1nn", "unseen_test"),
        ("5nn", "unseen_test"),
        ("selected_knn", "unseen_test"),
    ):
        count = results[phase]["model"]["total"]
        break_even[name] = {
            **break_even_reads(
                write_seconds["model"],
                write_seconds[name],
                phase_seconds[phase]["model"] / count,
                phase_seconds[phase][name] / count,
            ),
            "phase": phase,
            "unit": "seconds",
            "accuracy_equivalence_not_assumed": True,
        }
    result = {
        "dataset": task.name,
        "seed": seed,
        "profile": profile,
        "source": task.source,
        "partition_counts": {name: len(ids) for name, ids in task.indices.items()},
        "selected_k": selected_k,
        "selection_scores": selection_scores,
        "scores": results,
        "costs": {
            "parameter_bytes": cell.parameter_bytes,
            "model_artifact_bytes": model_bytes,
            "stored_components_bytes": sizes,
            "deployment_bytes": deployed,
            "normalizer_numeric_bytes": task.normalizer.mean.nbytes
            + task.normalizer.scale.nbytes,
            "runtime_knn_numeric_index_bytes": numeric_index.nbytes + train_y.nbytes,
            "runtime_exact_logical_payload_bytes": sum(len(key) + 8 for key in index),
            "full_source_snapshot_bytes_evaluation_only": task.source["snapshot_bytes"],
            "full_bundled_source_bytes_evaluation_only": task.source[
                "bundled_source_bytes"
            ],
            "source_verification_and_partition_seconds_evaluation_only": {
                name: value
                for name, value in task.preparation_seconds.items()
                if name != "normalizer_fit_train_only"
            },
            "normalizer_fit_seconds": normalization,
            "write_seconds": write_seconds,
            "read_seconds": phase_seconds,
            "model_load_seconds": model_load_seconds,
            "model_save_seconds": model_save_seconds,
            "normalizer_save_seconds": normalizer_save_seconds,
            "encoding_seconds": encoding_seconds,
            "labels_save_seconds": labels_save_seconds,
            "index_manifest_save_seconds": index_manifest_save_seconds,
            "exact_build_seconds": exact_build_seconds,
            "knn_index_build_seconds": numeric_index_seconds,
            "replay_write_seconds": replay_write_seconds,
            "break_even_reads_time_only": break_even,
            "cost_scope": "write includes replay and model reload; logical index RAM excludes Python overhead; single batch timings; no energy/hardware pricing",
            "candidate_selection_read_seconds": selection_seconds["1nn"]
            + selection_seconds["5nn"],
        },
        "training": training,
        "model_reload_parity": True,
        "effective_inputs_disjoint": True,
        "scaler_fit_split": "train",
        "query_scope": "unseen feature generalization and written-feature recovery reported separately",
        "claim": "perceptual/semantic pattern classification, not episodic or general memory",
        "case_wall_seconds_before_serialization": time.perf_counter() - started_case,
    }
    _write(directory / "result.json", result)
    return result


def run_external(protocol, output, source_commit, seeds, *, development=False):
    """Write under output/external; retain every fixed-learner comparison and cost."""
    profile = {**DEFAULT_PROFILE, **protocol.get("external_v2_profile", {})}
    if (
        not isinstance(seeds, (list, tuple))
        or not seeds
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("nonempty distinct split seeds are required")
    if any(
        profile[key] != DEFAULT_PROFILE[key]
        for key in DEFAULT_PROFILE
        if key != "steps"
    ):
        raise ValueError(
            "external learner, preprocessing and neighbor profile are frozen"
        )
    if (development and not set(seeds) <= {8001, 8003}) or (
        not development and profile["steps"] != 600
    ):
        raise ValueError(
            "development seeds or formal optimizer steps differ from the frozen profile"
        )
    directory = Path(output) / "external"
    directory.mkdir(parents=True, exist_ok=False)
    _write(
        directory / "profile.json",
        {
            "profile": profile,
            "seeds": list(seeds),
            "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "source_commit": source_commit,
            "development_only": development,
            "independent_source_datasets": 3,
        },
    )
    runs = []
    for seed in seeds:
        for task in build_external_tasks(seed).values():
            runs.append(
                _run_case(
                    task,
                    profile,
                    directory / f"seed-{seed}" / task.name,
                    source_commit,
                    seed,
                )
            )
    summaries = {}
    for name in sorted({row["dataset"] for row in runs}):
        cases = [row for row in runs if row["dataset"] == name]
        summaries[name] = {
            phase: {
                arm: {
                    "mean": statistics.mean(
                        row["scores"][phase][arm]["known_accuracy"] for row in cases
                    ),
                    "minimum": min(
                        row["scores"][phase][arm]["known_accuracy"] for row in cases
                    ),
                    "maximum": max(
                        row["scores"][phase][arm]["known_accuracy"] for row in cases
                    ),
                }
                for arm in cases[0]["scores"][phase]
            }
            for phase in ("written_recovery", "unseen_test")
        }
    source_bytes = sum(
        runs[index]["source"]["snapshot_bytes"]
        + runs[index]["source"]["bundled_source_bytes"]
        for index in range(3)
    )
    result = {
        "runs": runs,
        "datasets": summaries,
        "independent_source_datasets": 3,
        "shared_raw_source_files_bytes_counted_once": source_bytes,
        "shared_source_manifest_bytes": (
            Path(__file__).resolve().parents[1]
            / "sources"
            / "external"
            / "SOURCES.json"
        )
        .stat()
        .st_size,
        "split_seeds_are_repeated_splits_not_new_domains": True,
        "statistics": "descriptive split variability; no independent-domain CI from repeated splits",
        "claim": "fixed-learner pattern classification reuse across three datasets",
        "exact_baseline_role": "written-feature lookup; abstention on genuinely unseen inputs is expected",
        "general_memory_system_established": False,
        "development_only": development,
    }
    _write(directory / "summary.json", result)
    return result
