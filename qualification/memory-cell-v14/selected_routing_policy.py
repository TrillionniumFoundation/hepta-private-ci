"""Restore and execute the calibration-selected research policy, without retraining.

The caller pins the original artifact inventory, encoder and training-source
identities. Every eligible model family is supported. A loader is not a native
installation or structural-admission grant. Cached-feature demonstrations are
explicitly distinguished from a live encoder call and from efficacy evaluation.
"""

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
V13 = ROOT.parent / "memory-cell-v13"
sys.path.insert(0, str(V13))
from adapter import Adapter
from baselines import BM25, Centroid, NearestExample
from structural import SparseExperts
from tasks import SKILLS, execute
from routing import CalibratedExperts, RoutingCalibration, partition_labels

NEURAL = ("single", "continue", "wide", "merge_retrain")
EXPERTS = tuple(name + suffix for name in ("fixed", "gradient", "random") for suffix in ("_raw", "_calibrated"))
ELIGIBLE = NEURAL + EXPERTS + ("ridge", "centroid", "nearest", "bm25")
RUNTIME_SOURCES = {"routing.py": ROOT / "routing.py", **{
    "v13-" + name: V13 / name for name in ("adapter.py", "baselines.py", "structural.py", "tasks.py", "backend.py", "download_model.py")}}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalize(values):
    values = np.asarray(values)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if values.ndim != 2 or not np.isfinite(values).all() or not np.isfinite(norms).all() or (norms <= 0).any():
        raise ValueError("finite nonzero features required")
    return values / norms


class SelectedRoutingPolicy:
    def __init__(self, routing_dir, inventory_path, *, expected_inventory_sha256,
                 expected_encoder_hash, expected_source_version, seed=713):
        wall, cpu = time.perf_counter(), time.process_time()
        self.root, self.seed = Path(routing_dir), int(seed)
        raw = Path(inventory_path).read_bytes()
        if not expected_inventory_sha256 or sha(raw) != expected_inventory_sha256:
            raise ValueError("original inventory identity mismatch")
        inventory = json.loads(raw)
        self.files = inventory["files"]
        self.inventory_sha256 = expected_inventory_sha256
        self.read_bytes, self.checked_files, self.materialization_notes = len(raw), {}, []
        runtime_bytes = 0
        self.source_commit = inventory["source_commit"]
        for name, path in RUNTIME_SOURCES.items():
            runtime_source = path.read_bytes()
            runtime_bytes += len(runtime_source)
            if sha(runtime_source) != self.files["routing/EXECUTED_SOURCE/" + name]["sha256"]:
                raise ValueError("runtime source differs from the frozen experiment: " + name)
        self.encoder = self._json("encoder_manifest.json")
        self.encoder_hash = self.encoder["encoder_hash"]
        self.source_version = self.encoder["source_version"]
        if not expected_encoder_hash or self.encoder_hash != expected_encoder_hash:
            raise ValueError("encoder identity mismatch")
        if not expected_source_version or self.source_version != expected_source_version:
            raise ValueError("training source version mismatch")
        if sha(canonical(self.encoder["encoder"])) != self.encoder_hash:
            raise ValueError("encoder descriptor hash mismatch")
        self.selection = self._json(f"seed-{self.seed}/SELECTION.json")
        self.selected = self.selection["selected"]
        if set(self.selection["scores"]) != set(ELIGIBLE) or self.selected not in ELIGIBLE:
            raise ValueError("incomplete or unsupported winner inventory")
        if self.selection.get("new_holdout_scored") is not False:
            raise ValueError("selection was not frozen before held scoring")
        if self.selection["scores"][self.selected] != max(self.selection["scores"].values()):
            raise ValueError("selected candidate is not a calibration winner")
        self.rows, self.features = {}, {}
        for split, count in (("train", 120), ("calibration", 48)):
            self.rows[split] = self._json(split + "_rows.json")
            arrays = self._arrays(split + "_features.npz")
            X, y = arrays["X"], arrays["y"]
            if X.shape != (count, 384) or len(self.rows[split]) != count or not np.isfinite(X).all():
                raise ValueError("invalid original feature population")
            if not np.array_equal(y, [r["label"] for r in self.rows[split]]):
                raise ValueError("cached source/feature labels differ")
            self.features[split] = X
        if sha(canonical(self.rows["train"])) != self.source_version:
            raise ValueError("actual training rows differ from the declared source version")
        self.support = normalize(self.features["train"])
        similarity = (normalize(self.features["calibration"]) @ self.support.T).max(axis=1)
        self.novelty_threshold = float(np.quantile(similarity, .05))
        self.prefix = f"seed-{self.seed}/{self.selected}/"
        self.model = self._restore()
        self.policy_identity = sha(canonical({"inventory": self.inventory_sha256, "seed": self.seed,
                                             "selected": self.selected, "files": self.checked_files}))
        self.load_receipt = {"wall_seconds": time.perf_counter() - wall, "cpu_seconds": time.process_time() - cpu,
                             "verified_artifact_bytes_read": self.read_bytes,
                             "runtime_source_bytes_read": runtime_bytes,
                             "checkpoint_bytes_read": sum(v["bytes"] for n, v in self.checked_files.items() if n.startswith(self.prefix)),
                             "materialization_notes": self.materialization_notes,
                             "source_sha256": sha(Path(__file__).read_bytes()), "complete_neural_training_state_restored": self.selected in NEURAL + EXPERTS,
                             "shared_encoder_resident_in_this_loader": False, "resident_ram_unmeasured": True}
        self.query_count = 0

    def _read(self, relative):
        expected = self.files["routing/" + relative]
        raw = (self.root / relative).read_bytes()
        self.read_bytes += len(raw)
        if sha(raw) != expected["sha256"]:
            # A recorded local text-materialization issue; arbitrary JSON changes fail.
            if relative.endswith(".json") and raw.endswith(b"\n\n") and sha(raw[:-1]) == expected["sha256"]:
                self.materialization_notes.append({"path": relative, "extra_final_newline_removed_for_verification": True})
                raw = raw[:-1]
            else:
                raise ValueError("artifact digest mismatch: " + relative)
        if len(raw) != expected["bytes"]:
            raise ValueError("artifact size mismatch: " + relative)
        self.checked_files[relative] = expected
        return raw

    def _json(self, relative):
        return json.loads(self._read(relative))

    def _arrays(self, relative):
        with np.load(io.BytesIO(self._read(relative)), allow_pickle=False) as saved:
            result = {name: saved[name].copy() for name in saved.files}
        if any(not np.isfinite(v).all() for v in result.values()):
            raise ValueError("nonfinite checkpoint arrays")
        return result

    def _adapter(self, relative, classes, data_id):
        model = Adapter.load(io.BytesIO(self._read(relative)), expected_encoder_hash=self.encoder_hash,
                             expected_source_version=self.source_version, expected_data_id=data_id)
        if model.config["input_dim"] != 384 or model.config["num_classes"] != classes:
            raise ValueError("checkpoint dimensions differ from routing contract")
        return model

    def _restore(self):
        name, prefix = self.selected, self.prefix
        if name in NEURAL:
            return self._adapter(prefix + "model.npz", 12, "v14-original-skills")
        if name in EXPERTS:
            desc = self._json(prefix + "network/network.json")
            if partition_labels(desc["partition"]) != 12 or desc["num_classes"] != 12 or desc["top_k"] != 2 or len(desc["partition"]) != 3:
                raise ValueError("unsupported frozen sparse network contract")
            network = object.__new__(SparseExperts)
            network.partition, network.top_k, network.num_classes = desc["partition"], desc["top_k"], 12
            network.experts = [self._adapter(prefix + f"network/expert-{g}.npz", len(part), f"v14-original-skills:partition:{g}")
                               for g, part in enumerate(network.partition)]
            raw = self._read(prefix + "network/router.npy")
            if sha(raw) != desc["router_sha256"]:
                raise ValueError("router descriptor/checkpoint mismatch")
            network.router = np.load(io.BytesIO(raw), allow_pickle=False)
            if network.router.shape != (385, 3) or not np.isfinite(network.router).all():
                raise ValueError("invalid router weights")
            network.stats = {"requests": 0, "expert_example_invocations": 0, "batch_calls": 0}
            calibration = RoutingCalibration(network.partition)
            receipt = self._json(prefix + "calibration.json")
            if receipt["status"] not in ("identity", "fitted", "identity_after_fit_failure"):
                raise ValueError("unsupported calibration receipt")
            calibration.theta = np.asarray(receipt.get("parameters", np.zeros(7)), dtype=np.float64)
            if calibration.theta.shape != (7,) or not np.isfinite(calibration.theta).all() or (abs(calibration.theta) > 2).any():
                raise ValueError("invalid calibration parameters")
            if receipt["status"] != "fitted" and np.any(calibration.theta):
                raise ValueError("identity calibration contains fitted weights")
            calibration.receipt = receipt
            return CalibratedExperts(network, calibration)
        arrays, metadata = self._arrays(prefix + "arrays.npz"), self._json(prefix + "metadata.json")
        if name == "ridge":
            if set(arrays) != {"weights"} or arrays["weights"].shape != (385, 12) or metadata:
                raise ValueError("invalid ridge checkpoint")
            return arrays["weights"]
        if name in ("centroid", "nearest"):
            count = 12 if name == "centroid" else 120
            if set(arrays) != {"labels", "features"} or arrays["features"].shape != (count, 384) or arrays["labels"].shape != (count,) or metadata:
                raise ValueError("invalid prototype/example checkpoint")
            model = object.__new__(Centroid if name == "centroid" else NearestExample)
            model.labels, model.features = arrays["labels"], arrays["features"]
        else:
            if set(arrays) != {"labels"} or arrays["labels"].shape != (120,) or len(metadata["documents"]) != 120:
                raise ValueError("invalid lexical checkpoint")
            model = object.__new__(BM25)
            model.__dict__.update(metadata)
            model.documents = [Counter(doc) for doc in metadata["documents"]]
            model.labels = arrays["labels"]
        if not np.issubdtype(model.labels.dtype, np.integer) or model.labels.min() < 0 or model.labels.max() >= 12:
            raise ValueError("invalid serialized operation labels")
        return model

    def _predict(self, text, feature, *, source_version, selective, encoder_receipt):
        if source_version != self.source_version:
            raise ValueError("caller source version is stale or different")
        if not isinstance(text, str):
            raise TypeError("one query text required")
        X = np.asarray(feature, dtype=self.features["train"].dtype).reshape(1, -1)
        if X.shape != (1, 384):
            raise ValueError("one 384-dimensional encoder feature required")
        wall, cpu = time.perf_counter(), time.process_time()
        similarity = float((normalize(X) @ self.support.T).max())
        accepted = not selective or similarity >= self.novelty_threshold
        label, expert_calls = None, 0
        if accepted:
            if self.selected == "ridge":
                label = int((np.column_stack([X, np.ones(1)]) @ self.model).argmax(axis=1)[0])
            elif hasattr(self.model, "batch_predict"):
                label = int(self.model.batch_predict([text], X)[0])
            else:
                label = int(self.model.predict(X)[0])
                expert_calls = 2 if self.selected in EXPERTS else 1
        self.query_count += 1
        return {"prediction": label, "operation_id": None if label is None else SKILLS[label], "accepted": accepted,
                "receipt": {"policy_identity": self.policy_identity, "selected": self.selected, "seed": self.seed,
                    "request_text_sha256": sha(text.encode()), "feature_sha256": sha(np.ascontiguousarray(X).tobytes()),
                    "encoder_hash": self.encoder_hash, "source_version": self.source_version,
                    "novelty_similarity": similarity, "novelty_threshold": self.novelty_threshold,
                    "wall_seconds_excluding_encoder_and_executor": time.perf_counter() - wall,
                    "cpu_seconds_excluding_encoder_and_executor": time.process_time() - cpu,
                    "expert_example_invocations": expert_calls, "checkpoint_bytes_read_this_prediction": 0,
                    "load_cost_charged_once_separately": True, "encoder": encoder_receipt,
                    "query_count": self.query_count, "native_installation_authority": False,
                    "source_freshness_authority_checked": False}}

    def predict_text(self, text, encoder, *, source_version, selective=True):
        """New text must go through a matching live encoder, never hash features."""
        if source_version != self.source_version:
            raise ValueError("caller source version is stale or different")
        if encoder.manifest_hash != self.encoder_hash:
            raise ValueError("live query encoder differs from selected policy")
        before = dict(encoder.stats)
        wall, cpu = time.perf_counter(), time.process_time()
        feature = encoder.encode([text])
        receipt = {"mode": "live", "wall_seconds": time.perf_counter() - wall, "cpu_seconds": time.process_time() - cpu,
                   "statistics_delta": {k: encoder.stats[k] - before[k] for k in before if k != "load_seconds"},
                   "encoder_load_seconds_external_to_policy": encoder.stats["load_seconds"]}
        return self._predict(text, feature, source_version=source_version, selective=selective, encoder_receipt=receipt)

    def predict_cached(self, split, row, *, source_version, selective=True):
        """Replay a verified old train/cal feature; never touch held data or labels."""
        if split not in self.rows or not isinstance(row, int) or not 0 <= row < len(self.rows[split]):
            raise ValueError("only a verified original train/calibration feature can be replayed")
        return self._predict(self.rows[split][row]["text"], self.features[split][row], source_version=source_version,
                             selective=selective, encoder_receipt={"mode": "verified_cached_original_feature", "split": split,
                                 "row": row, "live_encoder_called": False, "new_generalization_observation": False,
                                 "cache_bytes_charged_in_policy_load": True})

    @staticmethod
    def execute_prediction(prediction, payload):
        """Consume only selected operation and caller payload, never fixture goldens."""
        wall, cpu = time.perf_counter(), time.process_time()
        output, error = None, None
        if prediction["accepted"]:
            try:
                output = execute(prediction["prediction"], payload)
            except (ValueError, TypeError, ArithmeticError, OverflowError, csv.Error) as exc:
                error = type(exc).__name__
        else:
            error = "abstained"
        return {**prediction, "output": output, "error": error,
                "executor_wall_seconds": time.perf_counter() - wall, "executor_cpu_seconds": time.process_time() - cpu}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--encoder-hash", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--seed", type=int, default=713)
    parser.add_argument("--cached-split", choices=("train", "calibration"), default="train")
    parser.add_argument("--cached-row", type=int, default=0)
    parser.add_argument("--payload-json", help="Optional actual caller payload; defaults to the cached request payload.")
    parser.add_argument("--live-probe", action="store_true", help="Encode and execute the single frozen integration probe.")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite selected-policy evidence")
    protocol = json.loads((ROOT / "SELECTED_POLICY_PROTOCOL.json").read_text())
    if args.live_probe and (args.model_dir is None or args.payload_json is not None):
        raise ValueError("live probe requires --model-dir and its frozen protocol payload")
    policy = SelectedRoutingPolicy(args.routing, args.inventory, expected_inventory_sha256=args.inventory_sha256,
                                   expected_encoder_hash=args.encoder_hash, expected_source_version=args.source_version, seed=args.seed)
    if args.live_probe:
        from backend import FrozenEncoder
        encoder = FrozenEncoder(args.model_dir, threads=1)
        text, payload = protocol["live_probe"]["text"], protocol["live_probe"]["payload"]
        result = policy.predict_text(text, encoder, source_version=args.source_version)
    else:
        text = policy.rows[args.cached_split][args.cached_row]["text"]
        payload = (policy.rows[args.cached_split][args.cached_row]["payload"] if args.payload_json is None else json.loads(args.payload_json))
        result = policy.predict_cached(args.cached_split, args.cached_row, source_version=args.source_version)
    result = policy.execute_prediction(result, payload)
    output = {"schema": "hepta.memory.selected-policy-recovery.v14", "load": policy.load_receipt,
              "request_text": text, "caller_payload": payload, "protocol_sha256": sha(canonical(protocol)),
              "next_query": result, "no_training_or_held_selection_performed": True,
              "scope": "Original-checkpoint recovery and callable research inference; no native installation or new efficacy claim."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".source.py").write_bytes(Path(__file__).read_bytes())
    args.output.with_suffix(".protocol.json").write_bytes((ROOT / "SELECTED_POLICY_PROTOCOL.json").read_bytes())
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"selected": policy.selected, "operation_id": result["operation_id"], "error": result["error"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
