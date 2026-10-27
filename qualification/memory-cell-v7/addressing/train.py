"""Train all declared candidates, select, then independently tighten admission."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT.parents[1] / "memory-cell-v6"))

from addressing.calibration import calibrate, select_policy
from addressing.contracts import OPERATIONS, canonical, digest, normalize
from addressing.corpus import corpora
from addressing.model import IntentModel
from v6.encoder import MiniLMEncoder


CANDIDATES = [
    (kind, regularization)
    for kind in ("semantic", "hybrid")
    for regularization in (2.0, 8.0, 32.0)
]


def dump(path, value):
    path.write_bytes(canonical(value) + b"\n")


def train(encoder_path, output, calibration_path=None):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    rows = corpora()
    # The first development calibration is now public diagnostic material.
    # A new run may select candidates without calibration, but a serving
    # artifact requires a separately supplied, independently authored corpus.
    rows.pop("calibration")
    calibration_rows = None
    source_files = [
        *PROJECT.glob("*.py"),
        PROJECT.parents[1] / "memory-cell-v6/v6/encoder.py",
        PROJECT.parents[1] / "memory-cell-v6/v6/training_language.py",
    ]
    repo = PROJECT.parents[2]
    source_hashes = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_files)
    }
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    committed = True
    for name, expected in source_hashes.items():
        result = subprocess.run(
            ["git", "show", head + ":" + name],
            cwd=repo,
            capture_output=True,
            check=False,
        )
        committed &= (
            result.returncode == 0
            and hashlib.sha256(result.stdout).hexdigest() == expected
        )
    design = {
        "schema": "hepta.memory.v7.addressing-design.v1",
        "source_commit": head,
        "execution_source_is_committed": bool(committed),
        "source_files": source_hashes,
        "candidates": [
            {"kind": kind, "C": regularization} for kind, regularization in CANDIDATES
        ],
        "threshold_grid": [0.0, 0.35, 0.5, 0.65, 0.8],
        "margin_grid": [0.0, 0.05, 0.1, 0.2, 0.3],
        "data": {
            name: {
                "rows": len(values),
                "sha256": digest(values),
                "families": len({item["family"] for item in values}),
            }
            for name, values in rows.items()
        },
        "calibration": {
            "candidate_fixed_before_calibration": True,
            "external_path": str(calibration_path) if calibration_path else None,
            "not_read_until_selection_locked": True,
            "risk_target": 0.05,
            "delta": 0.05,
            "policy_only_tightened": True,
            "population_risk_established": False,
        },
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "scikit-learn", "onnxruntime", "tokenizers")
        },
        "python": platform.python_version(),
        "held_read": False,
        "limits": [
            "Only six registered operations; no invented primitive.",
            "Exact owner-listed alias resolution is not open-world entity linking.",
            "Synthetic authored calibration does not establish a human population risk bound.",
            "One deterministic language model; repeated memory seeds are not independent language samples.",
        ],
    }
    dump(output / "DESIGN.json", design)
    for path in source_files:
        target = output / "execution-sources" / path.relative_to(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    for name, values in rows.items():
        dump(output / (name + ".json"), values)
    start, cpu = time.perf_counter(), time.process_time()
    encoder = MiniLMEncoder(encoder_path)
    encoding_start, encoding_cpu = time.perf_counter(), time.process_time()
    # Calibration is deliberately not encoded until the candidate has been
    # selected. It cannot enter a model fit or candidate-selection feature set.
    dense = {
        name: encoder.encode([row["text"] for row in rows[name]])
        for name in ("train", "selection")
    }
    np.savez_compressed(output / "development-features.npz", **dense)
    encoding_cost = {
        "wall_seconds": time.perf_counter() - encoding_start,
        "cpu_seconds": time.process_time() - encoding_cpu,
        "encoded_rows": sum(len(rows[name]) for name in dense),
        "numeric_feature_bytes": sum(value.nbytes for value in dense.values()),
    }
    candidates = []
    for number, (kind, regularization) in enumerate(CANDIDATES):
        directory = output / f"candidate-{number:02}"
        candidate_start, candidate_cpu = time.perf_counter(), time.process_time()
        model = IntentModel(encoder, kind, regularization)
        fitting = model.fit(rows["train"], dense=dense["train"])
        hypotheses = model.hypotheses(
            [row["text"] for row in rows["selection"]], dense=dense["selection"]
        )
        selection = select_policy(model, rows["selection"], hypotheses)
        identity = model.save(directory)
        dump(directory / "selection-hypotheses.json", hypotheses)
        dump(directory / "SELECTION.json", selection)
        record = {
            "candidate": number,
            "directory": directory.name,
            "kind": kind,
            "C": regularization,
            "training": fitting,
            "selection": selection["selected"],
            "identity": identity,
            "wall_seconds": time.perf_counter() - candidate_start,
            "cpu_seconds": time.process_time() - candidate_cpu,
        }
        candidates.append(record)
        dump(output / "PROGRESS.json", candidates)
        print(
            json.dumps(
                {
                    "candidate": number,
                    "selection": record["selection"]["metrics"],
                    "cpu_seconds": record["cpu_seconds"],
                }
            ),
            flush=True,
        )
    chosen = max(
        candidates,
        key=lambda item: (
            *item["selection"]["selection_key"],
            -item["identity"]["deployment_bytes_excluding_base"],
            -item["candidate"],
        ),
    )
    dump(
        output / "SELECTION_LOCK.json",
        {
            "selected_candidate": chosen["candidate"],
            "selected_identity": chosen["identity"],
            "calibration_not_yet_encoded": True,
            "selection_sha256": digest(rows["selection"]),
            "all_candidates_sha256": digest(candidates),
        },
    )
    model = IntentModel.load(
        output / chosen["directory"], encoder, chosen["identity"]["manifest_sha256"]
    )
    if calibration_path is None:
        selected_identity = model.save(output / "selected-unadmitted")
        outcome = {
            "schema": "hepta.memory.v7.addressing-training.v1",
            "source": design,
            "candidates": candidates,
            "selected_candidate": chosen["candidate"],
            "selected_identity": selected_identity,
            "calibration": None,
            "serving_admitted": False,
            "encoding": encoding_cost,
            "actual_head_fits": 2 * len(candidates),
            "base_bytes": encoder.base_bytes,
            "encoder_digest": encoder.digest,
            "total_wall_seconds_before_final_report": time.perf_counter() - start,
            "total_cpu_seconds_before_final_report": time.process_time() - cpu,
            "retained_bytes_before_final_report": sum(
                path.stat().st_size for path in output.rglob("*") if path.is_file()
            ),
            "formal_held_opened": False,
        }
        dump(output / "TRAINING.json", outcome)
        return outcome
    calibration_path = Path(calibration_path).absolute()
    if (
        calibration_path.is_symlink()
        or not calibration_path.is_file()
        or calibration_path.stat().st_size > 8_000_000
    ):
        raise ValueError("invalid independent calibration file")
    calibration_input = calibration_path.read_bytes()
    calibration_rows = json.loads(calibration_input)
    if (
        not isinstance(calibration_rows, list)
        or not 120 <= len(calibration_rows) <= 4096
    ):
        raise ValueError("bounded independent calibration corpus required")
    seen = {normalize(item["text"]) for values in rows.values() for item in values}
    ids = set()
    for row in calibration_rows:
        if not isinstance(row, dict) or not {
            "id",
            "text",
            "operation",
            "language",
            "family",
        } <= set(row):
            raise ValueError("invalid independent calibration fields")
        if (
            any(
                not isinstance(row[name], str) or not row[name]
                for name in ("id", "text", "family")
            )
            or row["operation"] not in (*OPERATIONS, "reject")
            or row["language"] not in ("en", "zh")
            or row["id"] in ids
        ):
            raise ValueError("invalid independent calibration row")
        row["text"] = normalize(
            row["text"]
            .replace("{entity}", "entity")
            .replace("{at}", "date")
            .replace("{since}", "date")
        )
        if row["text"] in seen:
            raise ValueError("invalid or overlapping independent calibration row")
        seen.add(row["text"])
        ids.add(row["id"])
    rows["calibration"] = calibration_rows
    dump(output / "calibration.json", calibration_rows)
    (output / "CALIBRATION_INPUT.json").write_bytes(calibration_input)
    calibration_start, calibration_cpu = time.perf_counter(), time.process_time()
    calibration_dense = encoder.encode([row["text"] for row in rows["calibration"]])
    np.savez_compressed(
        output / "calibration-features.npz", calibration=calibration_dense
    )
    hypotheses = model.hypotheses(
        [row["text"] for row in rows["calibration"]], dense=calibration_dense
    )
    calibration, decisions = calibrate(model, rows["calibration"], hypotheses)
    calibration["external_input_sha256"] = hashlib.sha256(calibration_input).hexdigest()
    selected_identity = model.save(output / "selected")
    dump(output / "CALIBRATION.json", calibration)
    dump(
        output / "calibration-readouts.json",
        [
            {
                "id": row["id"],
                "expected": row["operation"],
                "hypothesis": hypothesis,
                "decision": decision,
            }
            for row, hypothesis, decision in zip(
                rows["calibration"], hypotheses, decisions
            )
        ],
    )
    calibration_cost = {
        "wall_seconds": time.perf_counter() - calibration_start,
        "cpu_seconds": time.process_time() - calibration_cpu,
        "encoded_rows": len(rows["calibration"]),
        "head_fit_calls": 0,
    }
    outcome = {
        "schema": "hepta.memory.v7.addressing-training.v1",
        "source": design,
        "candidates": candidates,
        "selected_candidate": chosen["candidate"],
        "selected_identity": selected_identity,
        "calibration": calibration,
        "encoding": encoding_cost,
        "calibration_cost": calibration_cost,
        "actual_head_fits": 2 * len(candidates),
        "base_bytes": encoder.base_bytes,
        "encoder_digest": encoder.digest,
        "total_wall_seconds_before_final_report": time.perf_counter() - start,
        "total_cpu_seconds_before_final_report": time.process_time() - cpu,
        "retained_bytes_before_final_report": sum(
            path.stat().st_size for path in output.rglob("*") if path.is_file()
        ),
        "formal_held_opened": False,
    }
    dump(output / "TRAINING.json", outcome)
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    arguments = parser.parse_args()
    result = train(arguments.encoder, arguments.output, arguments.calibration)
    print(
        json.dumps(
            {
                "selected_identity": result["selected_identity"],
                "calibration": result["calibration"],
            },
            indent=2,
        )
    )
