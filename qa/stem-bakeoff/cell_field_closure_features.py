"""Run the existing frozen real Encoder owner on only the new V4 sources."""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np

from cell_field_action_io import deny_withheld_labels
from cell_field_closure_data import registered_source_directory, run_new_stage, write
from cell_field_features import file_hash


def extract(data, snapshot, protocol, v3_data, v3_features, output):
    sys.addaudithook(deny_withheld_labels)
    plan = json.loads(Path(protocol).read_bytes())
    data, root = registered_source_directory(plan, data), Path(output)
    import torch
    from real_encoder import FrozenRealEncoder
    from shared_feature_contract import SourceEvent
    from shared_feature_extract import SharedFeatureEncoder
    from teacher_snapshot import inventory

    receipt = json.loads((data / "data_receipt.json").read_bytes())
    if (receipt["protocol_sha256"] != file_hash(protocol)
            or receipt["source_owner_directory"] != plan["source_owner_directory"]
            or receipt["prepared_source_directory"] != str(data)
            or receipt["files"]["predictors.json"]["sha256"] != file_hash(data / "predictors.json")):
        raise ValueError("source/feature protocol mismatch")
    rows = json.loads((data / "predictors.json").read_bytes())["rows"]
    root.mkdir(parents=True, exist_ok=False)
    fixed = {"protocol_sha256": file_hash(protocol), "predictors_sha256": file_hash(data / "predictors.json"),
             "data_receipt_sha256": file_hash(data / "data_receipt.json"),
             "source_ids": [x["source_id"] for x in rows], "labels_enter_encoder": False,
             "scope": "hepta-cell-state-closure-v4-20261025"}
    write(root / "plan.json", fixed)
    torch.set_num_threads(plan["encoder_threads"])
    torch.set_num_interop_threads(plan["encoder_threads"])
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=plan["encoder"], snapshot=snapshot,
        revision=plan["encoder_revision"], expected_inventory_sha256=plan["encoder_inventory_sha256"],
        operator_accepted_terms=True, device="cpu", profile=plan["encoder_profile"],
        max_tokens=plan["encoder_max_tokens"], task="classification", generation=1, scope_id=fixed["scope"])
    loading = {"wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
               "model": owner.accounting}
    shared, matrices, receipts = SharedFeatureEncoder(owner), [], []
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    observed_at = time.time_ns()
    v3_data, v3_features = Path(v3_data), Path(v3_features)
    if (file_hash(v3_data / "sources.json") != plan["v3_sources_sha256"]
            or file_hash(v3_features / "features.npz") != plan["v3_features_sha256"]):
        raise ValueError("encoder bridge requires the exact original real features and source census")
    old_receipt = json.loads((v3_data / "data_receipt.json").read_bytes())
    if file_hash(v3_data / "predictors.json") != old_receipt["files"]["predictors.json"]["sha256"]:
        raise ValueError("encoder bridge predictors changed")
    old_sources = json.loads((v3_data / "sources.json").read_bytes())["rows"]
    old_predictors = json.loads((v3_data / "predictors.json").read_bytes())["rows"]
    marks = [x["index"] for x in old_sources if x["role"] == plan["encoder_bridge"]["role"]][:plan["encoder_bridge"]["rows"]]
    bridge_rows = [old_predictors[i] for i in marks]
    result = shared.extract_text([x["text"] for x in bridge_rows],
        events=[SourceEvent(x["source_id"], x["source_version"], observed_at) for x in bridge_rows],
        expected_identity=owner.identity, retention="global")
    observed_bridge = result.read_global().numpy()
    with np.load(v3_features / "features.npz", allow_pickle=False) as archive:
        expected_bridge = archive["features"][marks]
    difference = float(np.max(np.abs(observed_bridge - expected_bridge)))
    bridge = {"source_indices": marks, "source_ids": [x["source_id"] for x in bridge_rows],
              "maximum_absolute_feature_difference": difference, "receipt": shared.last_receipt,
              "passed": difference <= plan["encoder_bridge"]["maximum_absolute_feature_difference"]}
    write(root / "bridge.json", bridge)
    with (root / "bridge.npz").open("xb") as stream:
        np.savez_compressed(stream, actual=observed_bridge, reference=expected_bridge)
    if not bridge["passed"]:
        raise ValueError("new encoder environment differs beyond the registered feature bridge tolerance")
    token_lengths = [len(owner._tokenizer.encode(owner.prefix + row["text"])) for row in rows]
    for first in range(0, len(rows), plan["encoder_batch_size"]):
        batch = rows[first:first + plan["encoder_batch_size"]]
        result = shared.extract_text([x["text"] for x in batch],
            events=[SourceEvent(x["source_id"], x["source_version"], observed_at) for x in batch],
            expected_identity=owner.identity, retention="global")
        matrices.append(result.read_global().numpy())
        receipts.append(shared.last_receipt)
    matrix = np.concatenate(matrices).astype(np.float32, copy=False)
    if (matrix.shape != (receipt["selected_components"], 384) or not np.isfinite(matrix).all()
            or owner.accounting["trainable_parameter_count"] != 0
            or inventory(snapshot)["inventory_sha256"] != plan["encoder_inventory_sha256"]
            or file_hash(data / "predictors.json") != fixed["predictors_sha256"]):
        raise ValueError("unexpected real frozen features or changed model")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=matrix)
    report = {"schema": "hepta.cell-closure-features.v4", "plan": fixed,
              "encoder_identity": asdict(owner.identity), "feature_identity": result.feature_identity_digest,
              "encoder_load": loading, "encoder_updates": 0, "shape": list(matrix.shape), "dtype": str(matrix.dtype),
              "tensor_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
              "feature_sha256": file_hash(root / "features.npz"), "receipts": receipts,
              "bridge": bridge, "bridge_tensor_sha256": file_hash(root / "bridge.npz"),
              "token_lengths": token_lengths,
              "truncated_inputs": sum(x > plan["encoder_max_tokens"] for x in token_lengths),
              "encoding": {"wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
                           "forward_calls": sum(x["model_forward_calls"] for x in receipts) + bridge["receipt"]["model_forward_calls"],
                           "encoded_tokens": sum(x["token_count"] for x in receipts) + bridge["receipt"]["token_count"],
                           "includes_old_training_source_bridge": True},
              "environment": {name: importlib.metadata.version(name) for name in ("numpy", "torch", "transformers", "tokenizers")},
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "authority": "DENY_ALL", "production_authority": False}
    write(root / "report.json", report)
    return {k: report[k] for k in ("shape", "encoder_updates", "encoding", "feature_sha256")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "snapshot", "protocol", "v3-data", "v3-features", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_new_stage(extract, vars(parser.parse_args())), sort_keys=True))
