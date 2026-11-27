"""Execute the existing immutable Encoder owner for the frozen Cell-field cohort."""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np

from cell_learning_models import canonical


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(data, snapshot, protocol, output):
    import torch
    from real_cell_features import predictor_rows
    from real_encoder import CANDIDATES, FrozenRealEncoder
    from shared_feature_contract import SourceEvent
    from shared_feature_extract import SharedFeatureEncoder
    from teacher_snapshot import inventory

    data, output, protocol = Path(data), Path(output), Path(protocol)
    plan = json.loads(protocol.read_bytes())
    rows = predictor_rows(json.loads((data / "predictors.json").read_bytes())["rows"])
    output.mkdir(parents=True, exist_ok=False)
    fixed = {"protocol_sha256": file_hash(protocol),
             "predictors_sha256": file_hash(data / "predictors.json"),
             "data_receipt_sha256": file_hash(data / "data_receipt.json"),
             "source_ids": [row["source_id"] for row in rows],
             "labels_enter_encoder": False, "scope": "cell-parameter-field-20261024"}
    (output / "plan.json").write_bytes(canonical(fixed) + b"\n")
    torch.set_num_threads(plan["encoder_threads"])
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=plan["encoder"], snapshot=snapshot,
        revision=plan["encoder_revision"],
        expected_inventory_sha256=plan["encoder_inventory_sha256"],
        operator_accepted_terms=True, device="cpu", profile=plan["encoder_profile"],
        max_tokens=plan["encoder_max_tokens"], task="classification", generation=1,
        scope_id=fixed["scope"])
    load = {"wall_ns": time.perf_counter_ns() - began,
            "cpu_ns": time.process_time_ns() - cpu, "model": owner.accounting}
    shared = SharedFeatureEncoder(owner)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    matrices, receipts, source_digests = [], [], []
    observed_at = time.time_ns()
    token_lengths = [len(owner._tokenizer.encode(owner.prefix + row["text"])) for row in rows]
    for begin in range(0, len(rows), plan["encoder_batch_size"]):
        batch = rows[begin:begin + plan["encoder_batch_size"]]
        result = shared.extract_text([row["text"] for row in batch],
            events=[SourceEvent(row["source_id"], row["source_version"], observed_at) for row in batch],
            expected_identity=owner.identity, retention="global")
        matrices.append(result.read_global().numpy())
        source_digests.extend(result.source_record_digests)
        receipts.append(shared.last_receipt)
    matrix = np.concatenate(matrices).astype(np.float32, copy=False)
    encoding = {"wall_ns": time.perf_counter_ns() - began,
                "cpu_ns": time.process_time_ns() - cpu,
                "forward_calls": sum(row["model_forward_calls"] for row in receipts),
                "encoded_tokens": sum(row["token_count"] for row in receipts)}
    if (inventory(snapshot)["inventory_sha256"] != plan["encoder_inventory_sha256"]
            or file_hash(data / "predictors.json") != fixed["predictors_sha256"]
            or owner.accounting["trainable_parameter_count"] != 0):
        raise ValueError("frozen model or input identity changed")
    np.savez_compressed(output / "features.npz", features=matrix)
    report = {"schema": "hepta.cell-field-features.v1", "plan": fixed,
              "encoder_identity": asdict(owner.identity),
              "feature_identity": result.feature_identity_digest,
              "shape": list(matrix.shape), "dtype": str(matrix.dtype),
              "feature_sha256": file_hash(output / "features.npz"),
              "tensor_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
              "tensor_bytes": matrix.nbytes, "source_record_digests": source_digests,
              "encoder_load": load, "encoding": encoding, "receipts": receipts,
              "token_lengths": token_lengths,
              "truncated_inputs": sum(n > plan["encoder_max_tokens"] for n in token_lengths),
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "environment": {"python": platform.python_version(),
                  "packages": {name: importlib.metadata.version(name) for name in
                               ("numpy", "torch", "transformers", "tokenizers", "safetensors")}},
              "encoder_updates": 0, "authority": "DENY_ALL"}
    (output / "report.json").write_bytes(canonical(report) + b"\n")
    return report


def load_features(path, protocol_hash):
    path = Path(path)
    report = json.loads((path / "report.json").read_bytes())
    if (report["plan"]["protocol_sha256"] != protocol_hash
            or report["feature_sha256"] != file_hash(path / "features.npz")):
        raise ValueError("feature protocol or archive differs from its sealed identity")
    with np.load(path / "features.npz", allow_pickle=False) as archive:
        if archive.files != ["features"]:
            raise ValueError("unexpected feature arrays")
        features = archive["features"]
    if (list(features.shape) != report["shape"] or features.dtype != np.float32
            or not np.isfinite(features).all()
            or hashlib.sha256(features.tobytes()).hexdigest() != report["tensor_sha256"]):
        raise ValueError("feature tensor changed")
    return features, report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "snapshot", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    result = extract(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in
                      ("shape", "encoding", "truncated_inputs", "encoder_updates")}))
