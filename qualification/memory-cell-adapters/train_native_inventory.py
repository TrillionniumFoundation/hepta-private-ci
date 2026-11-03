"""Clean TensorCell rebuild from one canonical inventory owner export.

The input is historical training evidence, not authority. The native publisher
must reacquire and validate its owner cut before publishing and on every read.
This path deliberately avoids erasing inherited lineage on a warm-start model.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from export_native import canonical, digest, export_checkpoint, valid_digest
from tensor_cell import CellConfig, OutputSpec, TensorCell

def train(input_file, output, kind="semantic"):
    if kind not in ("semantic", "skill"):
        raise ValueError("only learned inventory cells can be rebuilt")
    if output.exists():
        raise FileExistsError(output)
    raw = input_file.read_bytes()
    if not 1 <= len(raw) <= 4 * 1024 * 1024:
        raise ValueError("bounded native owner training input required")
    document = json.loads(raw)
    owner = document["owner_snapshot"]
    encoder = document["encoder_sha256"]
    if document["schema"] != "hepta.memory.inventory-training-input.v1" or owner["schema"] != "hepta.memory.inventory-owner-snapshot.v1" or not valid_digest(encoder):
        raise ValueError("native owner training input profile")
    current = set(owner["current_source_ids"])
    rows = sorted((row for row in owner["records"] if row["source_id"] in current and row["record"]["kind"] == kind), key=lambda row: row["record"]["key"])
    feature_rows = [row for row in document["feature_rows"] if row["kind"] == kind]
    features = {row["key"]: row["features"] for row in feature_rows}
    if not rows or len(rows) > 256 or len(features) != len(feature_rows) or len({row["record"]["key"] for row in rows}) != len(rows) or set(features) != {row["record"]["key"] for row in rows}:
        raise ValueError("complete one-to-one cell feature bindings required")
    x = np.asarray([features[row["record"]["key"]] for row in rows], dtype=np.float32)
    if x.shape != (len(rows), 384) or not np.isfinite(x).all():
        raise ValueError("finite canonical 384-dimensional encoder inputs required")
    targets, ids = [], []
    for row in rows:
        record = row["record"]
        value = record["value"]
        if record["schema"] != "hepta.memory.inventory-cell-record.v1" or not valid_digest(row["source_id"]):
            raise ValueError("canonical cell source profile")
        if kind == "semantic":
            if set(value) != {"reserve", "pack", "limit"}:
                raise ValueError("canonical policy profile")
            values = [value[field] for field in ("reserve", "pack", "limit")]
            if any(type(item) is not int or not 0 <= item <= 15 for item in values):
                raise ValueError("four-bit canonical policy values required")
            targets.append([(item >> bit) & 1 for item in values for bit in range(4)])
        else:
            if set(value) != {"program"} or not isinstance(value["program"], list) or len(value["program"]) != 4 \
                    or any(type(opcode) is not int or not 0 <= opcode <= 6 for opcode in value["program"]):
                raise ValueError("four bounded canonical opcodes required")
            targets.append(value["program"])
        ids.append(row["source_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate canonical source identity")
    torch.set_num_threads(1)
    began, cpu = time.perf_counter(), time.process_time()
    specs = (OutputSpec("bits", "binary", 12),) if kind == "semantic" else tuple(OutputSpec(f"op{i}", "multiclass", 7) for i in range(4))
    targets = np.asarray(targets)
    fitted_targets = {"bits": targets} if kind == "semantic" else {f"op{i}": targets[:, i] for i in range(4)}
    cell = TensorCell(CellConfig(f"native-canonical-{kind}-clean-rebuild", rank=4, input_dim=384, outputs=specs, seed=731), encoder)
    receipt = cell.fit(x, fitted_targets, source_ids=ids, steps=600, batch_size=32, lr=.01, seed=731, train_head=True)
    if cell.source_ids != set(ids):
        raise ValueError("training did not visit every current canonical source")
    output.mkdir(parents=True)
    cell.save(output / "checkpoint")
    payload = canonical(export_checkpoint(output / "checkpoint"))
    (output / f"{kind}.native.json").write_bytes(payload)
    predicted = cell.predict(x)
    predicted = predicted["bits"] if kind == "semantic" else np.column_stack([predicted[f"op{i}"] for i in range(4)])
    equal = np.all(predicted == targets, axis=1)
    cell_training_cut = digest(canonical(["hepta.sqlite.inventory-cell-training-cut.v2", owner["scope"], kind,
                                         [[row["record"]["key"], row["source_id"]] for row in rows]]))
    report = {"schema": "hepta.memory.native-canonical-rebuild.v1", "input_sha256": digest(raw),
              "owner_cut_digest": owner["owner_cut_digest"], "owner_agent_id": owner["owner_agent_id"], "scope": owner["scope"],
              "cell_kind": kind, "cell_training_cut_digest": cell_training_cut,
              "source_ids": sorted(ids), "encoder_sha256": encoder, "parameter_sha256": cell.parameter_digest(),
              "native_sha256": digest(payload), "rows": len(rows), "correct": int(equal.sum()),
              "clean_initialization": True, "inherited_parameter_lineage_erased": False, "receipt": receipt,
              "wall_seconds_with_checkpoint_and_export": time.perf_counter() - began,
              "cpu_seconds_with_checkpoint_and_export": time.process_time() - cpu,
              "serialized_bytes": len(payload), "torch_version": torch.__version__,
              "trainer_sha256": digest(Path(__file__).read_bytes()),
              "tensor_cell_sha256": digest(Path(__file__).with_name("tensor_cell.py").read_bytes()),
              "exporter_sha256": digest(Path(__file__).with_name("export_native.py").read_bytes())}
    (output / "training-result.json").write_bytes(canonical(report))
    print(json.dumps(report))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=("semantic", "skill"), default="semantic")
    args = parser.parse_args(); train(args.input, args.output, args.kind)
