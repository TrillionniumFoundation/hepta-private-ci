"""Generate native differential inputs from frozen V6 models and source SQLite.

Additional readbacks are labeled and costed. No training, recalibration, or
held-language reads occur. Expected values come from the immutable source rows.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

from native_export import AssociativeCell
from native_export import canonical
from native_export import export_cell
from v6.cells import encode


def identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def generate(case, output):
    started, cpu = time.perf_counter(), time.process_time()
    case, output = Path(case).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    training = json.loads((case / "TRAINING.json").read_bytes())
    truth = json.loads((case / "truth.json").read_bytes())
    project = Path(__file__).resolve().parent
    reports = project.parent / "memory-cell-v6/reports"
    freeze = json.loads((reports / "FREEZE.json").read_bytes())
    if identity(reports / "PREPARED.json") != freeze["prepared"]:
        raise ValueError("frozen preparation identity differs")
    prepared = json.loads((reports / "PREPARED.json").read_bytes())
    selected_case = next(row for row in prepared["cases"] if row["seed"] == truth["seed"] and row["domain"] == truth["domain"])
    for name in ("v6/cells.py", "v6/contracts.py", "v6/values.py"):
        if identity(project.parent / "memory-cell-v6" / name) != freeze["source_files"]["qualification/memory-cell-v6/" + name]:
            raise ValueError("Python model reader differs from original frozen source")
    inputs = {name: identity(case / name) for name in ("TRAINING.json", "truth.json", "source.sqlite")}
    if any(selected_case["files"][name] != actual for name, actual in inputs.items()):
        raise ValueError("case source files differ from frozen preparation")
    connection = sqlite3.connect("file:" + str(case / "source.sqlite") + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    sources = {row["source_id"]: dict(row) for row in connection.execute("SELECT * FROM records")}
    if connection.execute("SELECT count(*) FROM revocations").fetchone()[0] != 0:
        raise ValueError("fixture generator requires the frozen initial, unrevoked source case")
    connection.close()
    artifacts, reads = [], 0
    for kind in ("semantic", "procedure"):
        original = case / "artifacts/objects" / training["cells"][kind]["sha256"]
        raw = original.read_bytes()
        if identity(original) != training["cells"][kind]:
            raise ValueError("original trained cell identity differs")
        inputs[str(original.relative_to(case))] = identity(original)
        if selected_case["files"][str(original.relative_to(case))] != identity(original):
            raise ValueError("trained model differs from frozen preparation")
        cell = AssociativeCell.from_bytes(raw)
        native = export_cell(raw)
        (output / f"{kind}.native.json").write_bytes(native)
        (output / f"{kind}.v6.json").write_bytes(raw)
        rows = []
        for source in sorted(sources.values(), key=lambda row: row["entity"]):
            if source["kind"] != kind:
                continue
            expected = json.loads(source["payload"])
            if hashlib.sha256(canonical(expected)).hexdigest() != source["value_digest"]:
                raise ValueError("source payload identity differs")
            predicted = cell.read(source["entity"])
            reads += 1
            if predicted["abstain"] is not None or predicted["value"] != expected or predicted["support_ids"] != [source["source_id"]]:
                raise ValueError("frozen Python cell disagrees with source truth")
            rows.append({"key": source["entity"], "value": expected, "source_ids": predicted["support_ids"],
                "confidence": predicted["confidence"], "parameter_sha256": predicted["parameter_digest"]})
        feature_values = encode([rows[0]["key"]], cell.dimension)[0]
        quantized = np.sign(feature_values) * np.floor(np.abs(feature_values) * 2**24 + 0.5)
        q_logits = (np.tanh((quantized / 2**24) @ cell.A + cell.a) @ cell.B + cell.b).clip(-8, 8) * 2**24
        q_logits = np.sign(q_logits) * np.floor(np.abs(q_logits) + 0.5)
        artifacts.append({"kind": kind, "native": identity(output / f"{kind}.native.json"),
            "original": identity(output / f"{kind}.v6.json"), "rows": rows,
            "lineage_sources": cell.lineage_sources, "feature_key": rows[0]["key"],
            "features": feature_values.tolist(), "port_features_q24": quantized.astype(np.int64).tolist(),
            "port_drive_q24": q_logits.astype(np.int64).tolist()})
    for name, expected in inputs.items():
        if identity(case / name) != expected:
            raise ValueError("original formal input changed")
    result = {"schema": "hepta.memory.v7.native-differential-fixture.v1",
        "original_source_commit": freeze["source_commit"],
        "freeze": identity(reports / "FREEZE.json"), "prepared": identity(reports / "PREPARED.json"),
        "generator": identity(__file__), "exporter": identity(project / "native_export.py"),
        "source_scope": truth["scope"], "source_cut": truth["source_cut"], "inputs": inputs,
        "models": artifacts, "post_hoc_additional_readbacks": True,
        "additional_reads": reads, "additional_port_reference_forwards": 2, "fit_calls": 0, "calibration_calls": 0,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "probability_absolute_tolerance": 1e-10,
        "numeric_scope": "Original stored weights are float32. Both readers use float64 feature arithmetic, tanh and softmax; accumulation order may differ."}
    (output / "expected.json").write_bytes(canonical(result) + b"\n")
    print(json.dumps({"additional_reads": reads, "files": [path.name for path in sorted(output.iterdir())]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    generate(args.case, args.output)
