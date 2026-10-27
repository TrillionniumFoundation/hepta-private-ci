"""Bounded public train/selection experiment; does not accept a held path."""

import argparse
import json
from pathlib import Path
import platform
import resource
import time
import warnings

import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression

from compact_features import Encoder
from compact_router import CompactRouter, deterministic_decisions, digest
from v5.contracts import LABELS, canonical, file_identity, normalized_request, unlabeled, write_json
from v5.corpus import build_public_corpus
from v5.metrics import calibrate, summarize


CANDIDATES = (("word", 4.0), ("semantic", 0.25), ("semantic", 1.0),
              ("semantic", 4.0), ("combined", 1.0), ("combined", 4.0))
SEED = 26027


def source_inventory():
    root = Path(__file__).resolve().parent
    files = [root / name for name in ("train.py", "semantic_cues.py", "compact_features.py", "compact_router.py", "serve.py", "native_router.py", "PROTOCOL.json")]
    files += list((root.parent / "memory-cell-v5" / "v5").glob("*.py"))
    return {str(path.relative_to(root.parent)): file_identity(path) for path in sorted(files)}


def train(output):
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    output.mkdir(parents=True, exist_ok=False)
    sources = source_inventory()
    folds, audit = build_public_corpus()
    corpus_ids = {name: digest(canonical(rows)) for name, rows in folds.items()}
    write_json(output / "PUBLIC_CORPUS_AUDIT.json", audit)
    write_json(output / "SOURCES.json", sources)
    write_json(output / "SOURCE_SNAPSHOT.json", {name: (Path(__file__).resolve().parent.parent / name).read_text() for name in sources})
    texts = {name: [normalized_request(unlabeled(row)) for row in rows] for name, rows in folds.items()}
    labels = [row["intent"] for row in folds["train"]]
    encoders = {name: Encoder(name).fit(texts["train"]) for name in ("word", "semantic", "combined")}
    matrices = {mode: {fold: encoder.transform(rows) for fold, rows in texts.items()} for mode, encoder in encoders.items()}
    reports = []
    for mode, strength in CANDIDATES:
        name = mode + "-lr-c" + str(strength)
        encoder = encoders[mode]
        model = LogisticRegression(C=strength, solver="lbfgs", max_iter=2000, tol=1e-7,
            class_weight="balanced", random_state=SEED)
        wall, cpu = time.perf_counter(), time.process_time()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            model.fit(matrices[mode]["train"], labels)
        fit_wall, fit_cpu = time.perf_counter() - wall, time.process_time() - cpu
        order = [list(model.classes_).index(label) for label in LABELS]
        router = CompactRouter(encoder, model.coef_[order], model.intercept_[order],
            {"minimum_confidence": 0.0, "minimum_margin": 0.0, "reject_all": False},
            {"candidate": name, "seed": SEED, "training_rows_sha256": corpus_ids["train"],
             "source_inventory_sha256": digest(canonical(sources)), "encoder": "finite hand-authored cue encoder and train-only ngrams", "pretrained": False})
        scores = {fold: np.asarray(matrix @ router.coefficients.T + router.intercept) for fold, matrix in matrices[mode].items()}
        if not np.array_equal(scores["selection"], model.decision_function(matrices[mode]["selection"])[:, order]):
            raise AssertionError("portable numerical inference differs from sklearn")
        _, _, grid = calibrate(folds["selection"], scores["selection"])
        # Disclosed final development revision: use zero observed selection
        # false accepts as a conservative tuning target; held gate remains 5%.
        chosen = min((item for item in grid if item["ood_false_accepted"] == 0),
            key=lambda item: (-item["known_correct_accepted"], item["known_wrong_accepted"],
                item["calibration"]["minimum_confidence"], item["calibration"]["minimum_margin"]))
        router.calibration = chosen["calibration"]
        selection = summarize(folds["selection"], router.decisions([unlabeled(row) for row in folds["selection"]]))
        candidate_dir = output / name
        candidate_dir.mkdir()
        artifact = router.save(candidate_dir / "model.json")
        loaded = CompactRouter.load(candidate_dir / "model.json", artifact["sha256"])
        diagnostics = {}
        for partition in ("selection", "development"):
            requests = [unlabeled(row) for row in folds[partition]]
            decisions = router.decisions(requests)
            if decisions != loaded.decisions(requests):
                raise AssertionError("artifact roundtrip changed predictions")
            diagnostics[partition] = summarize(folds[partition], decisions)
            write_json(candidate_dir / (partition + ".json"), {
                "row_ids": [row["id"] for row in folds[partition]], "decisions": decisions,
                "metrics": diagnostics[partition]})
        write_json(candidate_dir / "calibration-grid.json", grid)
        report = {"candidate": name, "mode": mode, "C": strength, "artifact": artifact,
            "calibration": router.calibration, "selection": selection,
            "development_diagnostic": diagnostics["development"],
            "fit_wall_seconds": fit_wall, "fit_cpu_seconds": fit_cpu,
            "iterations": model.n_iter_.tolist(), "warnings": [str(item.message) for item in captured]}
        reports.append(report)
        print(json.dumps({"candidate": name, "selection_coverage": selection["correct_known_coverage"],
            "selection_ood": selection["ood_false_accept_rate"],
            "development_coverage": diagnostics["development"]["correct_known_coverage"],
            "development_ood": diagnostics["development"]["ood_false_accept_rate"], "artifact_bytes": artifact["bytes"]}), flush=True)
    selected = min(reports, key=lambda r: (-r["selection"]["known_correct_accepted"],
        r["selection"]["known_wrong_accepted"], r["selection"]["ood_false_accepted"],
        r["artifact"]["bytes"], r["candidate"]))
    deterministic = {name: summarize(rows, deterministic_decisions([unlabeled(row) for row in rows])) for name, rows in folds.items() if name != "train"}
    report = {"schema": "memory-cell-v6.public-training-run.v1", "corpus": corpus_ids,
        "source_inventory_sha256": digest(canonical(sources)), "candidate_budget": len(CANDIDATES),
        "candidates": reports, "selected": selected, "deterministic": deterministic,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
            "scipy": scipy.__version__, "sklearn": sklearn.__version__, "platform": platform.platform()},
        "total_wall_seconds": time.perf_counter() - started_wall, "total_cpu_seconds": time.process_time() - started_cpu,
        "peak_process_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "pretrained_encoder_calls": 0, "external_model_calls": 0, "held_rows_read": 0,
        "confidence": "softmax of learned multinomial logits, not calibrated probability", 
        "scope": "synthetic public train/selection/development; tuning on these folds is disclosed; independent held remains sealed"}
    if source_inventory() != sources:
        raise AssertionError("training sources changed while fitting")
    write_json(output / "TRAINING_RUN.json", report)
    write_json(output / "SELECTED.json", selected)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    train(parser.parse_args().output)
