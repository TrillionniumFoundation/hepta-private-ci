"""Bounded genuine TF-IDF/linear-model fits with complete candidate retention."""

import io
import json
from pathlib import Path
import platform
import shutil
import time
import warnings
from collections import Counter

import numpy as np
import scipy
from scipy import sparse
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC

from .artifacts import compressed_json, store_payload
from .config import CANDIDATES, DEFAULT_CONFIG, NEGATIVE_TRAINING_FAMILIES
from .contracts import INTENTS, LABELS, REJECT, canonical, file_identity, normalized_request, sha256, unlabeled, write_json
from .corpus import build_public_corpus
from .features import FeatureBlock, combine, sparse_numeric_bytes
from .metrics import calibrate, primary_key, summarize
from .router import Router, parameter_digest


def runtime_identity():
    return {
        "python": platform.python_version(), "numpy": np.__version__,
        "scipy": scipy.__version__, "sklearn": sklearn.__version__,
        "platform": platform.platform(),
        "pretrained_encoder_used": False, "encoder_calls": 0, "encoder_bytes": 0,
    }


def prepare_features(folds, output, feature_names):
    path = output / "shared-training-features"
    path.mkdir()
    blocks, matrices, receipts = {}, {}, {}
    for name in feature_names:
        directory = path / name
        directory.mkdir()
        wall, cpu = time.perf_counter(), time.process_time()
        train_text = [normalized_request(unlabeled(row)) for row in folds["train"]]
        block, train = FeatureBlock.fit(name, train_text)
        receipt = {
            "fit_wall_seconds": time.perf_counter() - wall,
            "fit_process_cpu_seconds": time.process_time() - cpu,
            "fit_rows": len(train_text), "vocabulary_from_train_only": True,
            "feature_dimensions": train.shape[1], "folds": {},
        }
        blocks[name] = block
        matrices[name] = {"train": train}
        for partition, rows in folds.items():
            wall, cpu = time.perf_counter(), time.process_time()
            if partition != "train":
                matrices[name][partition] = block.transform([normalized_request(unlabeled(row)) for row in rows])
            matrix = matrices[name][partition]
            buffer = io.BytesIO()
            sparse.save_npz(buffer, matrix, compressed=True)
            payload = store_payload(directory, partition + ".csr.npz", buffer.getvalue())
            receipt["folds"][partition] = {
                "shape": list(matrix.shape), "nonzero_entries": int(matrix.nnz),
                "array_bytes": sparse_numeric_bytes(matrix), "storage": payload,
                "transform_and_save_wall_seconds": time.perf_counter() - wall,
                "transform_and_save_process_cpu_seconds": time.process_time() - cpu,
                "canonical_rows_sha256": sha256(canonical(rows)),
            }
        descriptor = {"feature": block.descriptor(), "idf": [float(x) for x in block.model.idf_]}
        receipt["training_transform_state"] = compressed_json(directory, "feature-state.json.zlib", descriptor)
        write_json(directory / "RECEIPT.json", receipt)
        receipts[name] = receipt
    return blocks, matrices, receipts


def fit_candidate(candidate, seed, folds, blocks, matrices, output, *, source_commit, source_inventory_sha256):
    matrix = combine([matrices[name]["train"] for name in candidate["features"]])
    model_labels = LABELS
    if candidate.get("negative_subclasses", False):
        observed = {row["family"] for row in folds["train"] if row["intent"] == REJECT}
        if observed != set(NEGATIVE_TRAINING_FAMILIES):
            raise ValueError("negative taxonomy differs from the original training metadata")
        model_labels = (*INTENTS, *(REJECT + "::" + family for family in NEGATIVE_TRAINING_FAMILIES))
    labels = np.asarray([
        REJECT + "::" + row["family"] if row["intent"] == REJECT and candidate.get("negative_subclasses", False) else row["intent"]
        for row in folds["train"]
    ])
    original_counts = Counter(row["intent"] for row in folds["train"])
    original_weights = {label: len(labels) / (len(LABELS) * original_counts[label]) for label in LABELS}
    effective_weights = {label: original_weights[label if label in INTENTS else REJECT] for label in model_labels}
    class_weight = effective_weights if candidate.get("negative_subclasses", False) else DEFAULT_CONFIG["class_weight"]
    permutation = np.random.default_rng(seed).permutation(len(labels))
    if candidate["learner"] == "logistic":
        estimator = LogisticRegression(
            C=candidate["C"], solver=DEFAULT_CONFIG["logistic_solver"],
            max_iter=DEFAULT_CONFIG["solver_max_iter"], tol=DEFAULT_CONFIG["solver_tolerance"],
            class_weight=class_weight, random_state=seed,
        )
    else:
        estimator = LinearSVC(
            C=candidate["C"], dual=True,
            max_iter=DEFAULT_CONFIG["solver_max_iter"], tol=DEFAULT_CONFIG["solver_tolerance"],
            class_weight=class_weight, random_state=seed,
        )
    wall, cpu = time.perf_counter(), time.process_time()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        estimator.fit(matrix[permutation], labels[permutation])
    fit_wall, fit_cpu = time.perf_counter() - wall, time.process_time() - cpu
    reorder = [list(estimator.classes_).index(label) for label in model_labels]
    coefficients = np.asarray(estimator.coef_[reorder], dtype=np.float64)
    intercept = np.asarray(estimator.intercept_[reorder], dtype=np.float64)
    identity = {
        "seed": seed,
        "source_commit": source_commit,
        "source_inventory_sha256": source_inventory_sha256,
        "training_canonical_sha256": sha256(canonical(folds["train"])),
        "selection_canonical_sha256": sha256(canonical(folds["selection"])),
        "config_sha256": sha256(canonical(DEFAULT_CONFIG)),
        "training_row_permutation_sha256": sha256(permutation.astype("<i8").tobytes()),
        "optimizer": estimator.__class__.__name__,
        "source_is_new_V5_not_recovered_V4": True,
        "learned_label_counts": dict(Counter(str(label) for label in labels)),
        "effective_training_weight_per_model_class": effective_weights,
    }
    router = Router([blocks[name] for name in candidate["features"]], coefficients, intercept,
                    {"minimum_confidence": 0.0, "minimum_margin": 0.0, "reject_all": False}, candidate, identity, model_labels)
    scores = {}
    for partition in ("selection", "development"):
        design = combine([matrices[name][partition] for name in candidate["features"]])
        model_scores = np.asarray(design @ coefficients.T + intercept, dtype=np.float64)
        sklearn_scores = estimator.decision_function(design)[:, reorder]
        if not np.array_equal(model_scores, sklearn_scores):
            raise AssertionError("explicit parameter inference differs from fitted estimator")
        scores[partition] = router.canonical_scores(model_scores)
    wall, cpu = time.perf_counter(), time.process_time()
    calibration, selection, grid = calibrate(folds["selection"], scores["selection"])
    calibration_wall, calibration_cpu = time.perf_counter() - wall, time.process_time() - cpu
    router.calibration = calibration
    model_path = output / "candidates" / candidate["name"]
    artifact = router.save(model_path)
    loaded = Router.load(model_path, artifact["files"]["manifest.json"]["sha256"])
    if parameter_digest(router) != parameter_digest(loaded):
        raise AssertionError("saved numerical parameters changed on reload")
    expected = router.decisions([unlabeled(row) for row in folds["development"]])
    actual = loaded.decisions([unlabeled(row) for row in folds["development"]])
    if expected != actual:
        raise AssertionError("router save/load prediction differs")
    diagnostics = output / "candidate-diagnostics" / candidate["name"]
    diagnostics.mkdir(parents=True)
    write_json(diagnostics / "calibration-grid.json", grid)
    for partition in ("selection", "development"):
        decisions = router.decisions([unlabeled(row) for row in folds[partition]])
        write_json(diagnostics / (partition + "-decisions.json"), {"row_ids": [row["id"] for row in folds[partition]], "decisions": decisions})
    report = {
        "name": candidate["name"], "candidate": candidate, "seed": seed,
        "fit_rows": matrix.shape[0], "feature_dimensions": matrix.shape[1],
        "fit_design_array_bytes": sparse_numeric_bytes(matrix),
        "actual_fit_wall_seconds": fit_wall, "actual_fit_process_cpu_seconds": fit_cpu,
        "solver_reported_n_iter": [int(x) for x in np.asarray(estimator.n_iter_).reshape(-1)],
        "iteration_semantics": "SAGA passes for logistic; maximum per-class liblinear iterations for LinearSVC; not exact FLOPs or example-update counts",
        "solver_warnings": [{"category": warning.category.__name__, "message": str(warning.message)} for warning in captured],
        "calibration_wall_seconds": calibration_wall, "calibration_process_cpu_seconds": calibration_cpu,
        "actual_calibration_pairs_evaluated": len(grid),
        "calibration": calibration, "selection": selection,
        "development_diagnostic_only": summarize(folds["development"], actual),
        "artifact": artifact, "parameter_digest": parameter_digest(router),
        "save_load_exact_decision_parity": True,
        "training_identity": identity,
        "training_feature_cache_reused": list(candidate["features"]),
        "pretrained_encoder_calls": 0,
    }
    write_json(diagnostics / "RECEIPT.json", report)
    return report


def train_routing(output, seeds, *, source_commit, development, candidate_names=None):
    selected_candidates = [candidate for candidate in CANDIDATES if candidate_names is None or candidate["name"] in candidate_names]
    if not selected_candidates or (candidate_names is not None and set(candidate_names) != {candidate["name"] for candidate in selected_candidates}):
        raise ValueError("unknown or empty candidate subset")
    if candidate_names is not None and not development:
        raise ValueError("formal execution requires the full predeclared candidate family")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    folds, corpus_audit = build_public_corpus()
    corpus_dir = output / "public-corpus"
    corpus_dir.mkdir()
    corpus_files = {}
    for partition, rows in folds.items():
        corpus_files[partition] = compressed_json(corpus_dir, partition + ".json.zlib", rows)
    write_json(corpus_dir / "CORPUS.json", corpus_audit)
    write_json(output / "CONFIG.json", DEFAULT_CONFIG)
    root = Path(__file__).resolve().parents[1]
    sources = {str(path.relative_to(root)): file_identity(path) for path in sorted((root / "v5").glob("*.py"))}
    for name in ("train_routing.py", "read_router.py"):
        sources[name] = file_identity(root / name)
    write_json(output / "SOURCE.json", {"source_commit": source_commit, "development": development, "files": sources})
    feature_names = sorted({name for candidate in selected_candidates for name in candidate["features"]})
    blocks, matrices, cache = prepare_features(folds, output, feature_names)
    seed_reports = []
    for seed in seeds:
        seed_path = output / f"seed-{seed}"
        seed_path.mkdir()
        candidates = [fit_candidate(candidate, seed, folds, blocks, matrices, seed_path,
                                    source_commit=source_commit, source_inventory_sha256=sha256(canonical(sources)))
                      for candidate in selected_candidates]
        selected = min(candidates, key=primary_key)
        shutil.copytree(seed_path / "candidates" / selected["name"], seed_path / "selected")
        loaded = Router.load(seed_path / "selected", selected["artifact"]["files"]["manifest.json"]["sha256"])
        if parameter_digest(loaded) != selected["parameter_digest"]:
            raise AssertionError("selected copy differs from candidate")
        primary = {
            "schema": "memory-cell-v5.primary-router.v1", "seed": seed,
            "candidate": selected["name"], "calibration": selected["calibration"],
            "artifact": selected["artifact"], "parameter_digest": selected["parameter_digest"],
            "selection": selected["selection"],
            "development_diagnostic_only": selected["development_diagnostic_only"],
            "selection_rule": DEFAULT_CONFIG["selection_rule"],
            "selected_using_new_held": False,
        }
        primary_identity = write_json(seed_path / "PRIMARY.json", primary)
        write_json(seed_path / "CANDIDATES.json", candidates)
        seed_reports.append({
            "seed": seed, "primary": primary, "primary_identity": primary_identity,
            "candidate_artifact_bytes": sum(item["artifact"]["bytes"] for item in candidates),
            "selected_copy_bytes": selected["artifact"]["bytes"],
            "candidate_fit_wall_seconds": sum(item["actual_fit_wall_seconds"] for item in candidates),
            "candidate_fit_cpu_seconds": sum(item["actual_fit_process_cpu_seconds"] for item in candidates),
            "actual_candidates_fitted": len(candidates),
        })
        print(json.dumps({"seed": seed, "selected": selected["name"], "selection": {k: selected["selection"][k] for k in ("correct_known_coverage", "ood_false_accept_rate", "qualified")}, "development": {k: selected["development_diagnostic_only"][k] for k in ("correct_known_coverage", "ood_false_accept_rate", "qualified")}}, sort_keys=True), flush=True)
    inventory = {str(path.relative_to(output)): file_identity(path) for path in sorted(output.rglob("*")) if path.is_file()}
    summary = {
        "schema": "memory-cell-v5.training-run.v1", "source_commit": source_commit,
        "development": development, "seeds": list(seeds), "runtime": runtime_identity(),
        "public_corpus": corpus_audit, "corpus_storage": corpus_files,
        "shared_feature_caches": cache, "seed_reports": seed_reports,
        "total_wall_seconds": time.perf_counter() - wall,
        "total_process_cpu_seconds": time.process_time() - cpu,
        "actual_candidates_fitted": len(selected_candidates) * len(seeds),
        "executed_candidate_names": [candidate["name"] for candidate in selected_candidates],
        "retained_bytes_before_summary": sum(item["bytes"] for item in inventory.values()),
        "retained_files_before_summary": inventory,
        "loaded_shared_csr_array_bytes": sum(sparse_numeric_bytes(matrix) for by_fold in matrices.values() for matrix in by_fold.values()),
        "pretrained_encoder_calls": 0,
        "limits": ["No independent held evaluation performed by this training program.", "Repeated seeds share the same authored language corpus and are not independent language samples.", "Serialized model bytes exclude the Python/sklearn runtime; arrays are separately counted, not total RSS.", "This is new V5 code, not reconstruction of lost V4 files or results."],
    }
    write_json(output / "TRAINING_RUN.json", summary)
    return summary
