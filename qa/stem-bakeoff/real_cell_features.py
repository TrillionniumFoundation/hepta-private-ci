"""Encode one fixed real-event corpus once, independently of its task labels.

The feature archive contains no labels or gold patches. Its receipt binds input
bytes, row order, native checkpoint/preprocessing identity and actual forwards.
This research exporter does not authenticate upstream publishers.
"""

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
import torch

from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent
from shared_feature_extract import SharedFeatureEncoder


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def predictor_rows(rows):
    """An explicit allowlist prevents target metadata entering model input."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("one bounded event corpus required")
    result, seen = [], set()
    for row in rows:
        public = {key: row[key] for key in ("source_id", "source_version", "text")}
        if isinstance(public["source_version"], dict):
            encoded = canonical(public["source_version"])
            if len(encoded) > 4096:
                raise ValueError("source version metadata exceeds budget")
            public["source_version"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if any(type(value) is not str or not value for value in public.values()):
            raise ValueError("nonempty source revision and text required")
        if (len(public["text"].encode()) > 16384
                or public["source_id"] in seen):
            raise ValueError("duplicate source or oversized predictor text")
        SourceEvent(public["source_id"], public["source_version"])
        seen.add(public["source_id"])
        result.append(public)
    return result


def export_features(dataset, snapshot, acquisition, output, *, candidate,
                    batch_size=16, max_tokens=192, threads=4):
    if (candidate not in ("granite97m", "embeddinggemma2_740m")
            or type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(max_tokens) is not int or not 32 <= max_tokens <= 512
            or type(threads) is not int or not 1 <= threads <= 16):
        raise ValueError("bounded fixed feature extraction plan required")
    dataset, acquisition = Path(dataset), Path(acquisition)
    if dataset.stat().st_size > 64 * 1024**2 or acquisition.stat().st_size > 1024**2:
        raise ValueError("input manifest exceeds budget")
    data_bytes, acquisition_bytes = dataset.read_bytes(), acquisition.read_bytes()
    rows = predictor_rows(json.loads(data_bytes)["rows"])
    acquired = json.loads(acquisition_bytes)
    spec = CANDIDATES[candidate]
    if (acquired["candidate"] != candidate or acquired["revision"] != spec["revision"]
            or acquired["repository"] != spec["repository"]):
        raise ValueError("acquisition receipt differs from the registered checkpoint")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    observation_ns = time.time_ns()
    plan = {"schema": "hepta.real-cell-feature-export.v1", "candidate": candidate,
            "dataset_sha256": hashlib.sha256(data_bytes).hexdigest(),
            "predictor_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
            "acquisition_sha256": hashlib.sha256(acquisition_bytes).hexdigest(),
            "batch_size": batch_size, "max_tokens": max_tokens, "threads": threads,
            "profile": "text", "retention": "global", "task": "classification",
            "row_count": len(rows), "source_ids": [row["source_id"] for row in rows],
            "observed_at_ns": observation_ns,
            "time_semantics": "local acquisition observation; original event dates stay in corpus metadata",
            "predictor_fields": ["text"], "gold_fields_enter_encoder": False,
            "truncation": "native tokenizer truncates to max_tokens; full source retained separately"}
    (root / "plan.json").write_bytes(canonical(plan) + b"\n")
    torch.set_num_threads(threads)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=candidate, snapshot=snapshot,
        revision=spec["revision"], expected_inventory_sha256=acquired["inventory_sha256"],
        operator_accepted_terms=True, profile="text", device="cpu", max_tokens=max_tokens,
        task="classification", generation=1, scope_id="repair-structure-20261023")
    load = {"wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu, "loaded_model": owner.accounting}
    shared = SharedFeatureEncoder(owner)
    receipts, matrices, digests, identity = [], [], [], None
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    for begin in range(0, len(rows), batch_size):
        batch_rows = rows[begin:begin + batch_size]
        events = [SourceEvent(row["source_id"], row["source_version"], observation_ns)
                  for row in batch_rows]
        batch = shared.extract_text([row["text"] for row in batch_rows], events=events,
                                    expected_identity=owner.identity, retention="global")
        if identity is not None and identity != batch.feature_identity_digest:
            raise ValueError("feature identity changed between corpus batches")
        identity = batch.feature_identity_digest
        matrices.append(batch.read_global().numpy())
        digests.extend(batch.source_record_digests)
        receipts.append({**shared.last_receipt, "first_row": begin})
        if len(receipts) % 10 == 0:
            print(json.dumps({"candidate": candidate, "encoded_rows": begin + len(batch_rows),
                              "forward_calls": owner._calls}), flush=True)
    encoding = {"wall_ns": time.perf_counter_ns() - started,
                "cpu_ns": time.process_time_ns() - cpu,
                "physical_forward_calls": owner._calls, "encoder_instances": 1}
    features = np.concatenate(matrices).astype(np.float32, copy=False)
    if features.shape != (len(rows), spec["width"]) or not np.isfinite(features).all():
        raise ValueError("native feature rows, width or values differ from the plan")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=features)
    report = {"plan": plan, "load": load, "encoding": encoding,
        "feature_identity": identity, "encoder_identity": asdict(owner.identity),
        "checkpoint_inventory_sha256": acquired["inventory_sha256"],
        "source_record_digests": digests, "feature_shape": list(features.shape),
        "retained_global_bytes": features.nbytes,
        "feature_archive_bytes": (root / "features.npz").stat().st_size,
        "feature_archive_sha256": sha_file(root / "features.npz"),
        "feature_tensor_sha256": hashlib.sha256(features.tobytes()).hexdigest(),
        "receipts": receipts,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
            "torch_threads": torch.get_num_threads(), "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "packages": {name: importlib.metadata.version(name) for name in
                         ("numpy", "torch", "transformers", "tokenizers", "safetensors")}},
        "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    if sha_file(dataset) != plan["dataset_sha256"]:
        raise ValueError("corpus changed during extraction")
    return report


def load_features(directory, dataset):
    root = Path(directory)
    report = json.loads((root / "report.json").read_bytes())
    if (sha_file(dataset) != report["plan"]["dataset_sha256"]
            or sha_file(root / "features.npz") != report["feature_archive_sha256"]):
        raise ValueError("source corpus or feature archive changed")
    with np.load(root / "features.npz", allow_pickle=False) as archive:
        if archive.files != ["features"]:
            raise ValueError("feature archive contains unexpected fields")
        features = archive["features"]
    if (list(features.shape) != report["feature_shape"] or features.dtype != np.float32
            or not np.isfinite(features).all()
            or hashlib.sha256(features.tobytes()).hexdigest() != report["feature_tensor_sha256"]):
        raise ValueError("feature matrix differs from its receipt")
    features.flags.writeable = False
    return features, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "snapshot", "acquisition", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--candidate", required=True, choices=("granite97m", "embeddinggemma2_740m"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    report = export_features(**vars(args))
    print(json.dumps({"candidate": args.candidate, "feature_identity": report["feature_identity"],
                      "feature_shape": report["feature_shape"], "encoding": report["encoding"]}))


if __name__ == "__main__":
    main()
