"""Contract tests use invented fixtures only; NEVER count as model qualification."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import bakeoff


class BakeoffContractTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.key = self.root / "private.pem"
        self.pub = self.root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(self.key)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.key), "-pubout", "-out", str(self.pub)], check=True, capture_output=True)
        self.rows = []
        for split in bakeoff.SPLITS:
            for index in range(2):
                self.rows.append({"case_id": split + str(index), "group_id": split + "-episode-" + str(index),
                                  "split": split, "label": "a" if index == 0 else "b",
                                  "labels": ["a", "b"], "language": "en" if index == 0 else "zh",
                                  "task_family": "intent", "ood": index == 1,
                                  "state": "example fixture", "question": "fixture question"})
        self.manifest = {"schema": bakeoff.SCHEMA, "source_commit": "a" * 40}
        self.manifest["dataset"] = self.put_jsonl("dataset.jsonl", self.rows)
        self.manifest["models"] = []
        training_sha = bakeoff.sha_bytes(bakeoff.canonical([r for r in sorted(self.rows, key=lambda x: x['case_id']) if r['split'] == 'train']))
        self.training = {"steps": 20, "examples_seen": 40, "batch_size": 2, "seed": 42,
                         "target_dim": 256, "optimizer_sha256": "1" * 64,
                         "training_dataset_sha256": training_sha}
        for arm in bakeoff.ARMS:
            weights = self.put(arm + ".weights", ("real-weights-placeholder:" + arm).encode())
            tokenizer = self.put(arm + ".tokenizer", ("real-tokenizer-placeholder:" + arm).encode())
            runtime = self.put(arm + ".runtime", ("real-runtime-placeholder:" + arm).encode())
            calibration = self.put(arm + ".calibration", ("calibration-fixture:" + arm).encode())
            head = self.put(arm + ".head", ("head-fixture:" + arm).encode()) if arm.endswith("-head") else None
            obs = [{"case_id": r["case_id"], "probabilities": {"a": 0.8, "b": 0.2}
                    if r["label"] == "a" else {"a": 0.3, "b": 0.7},
                    "abstained": False, "latency_ms": 1.5, "rss_bytes": 12345678,
                    "gpu_peak_bytes": None, "host_id": "test-host", "device": "cpu",
                    "model_weights_sha256": weights["sha256"],
                    "calibration_sha256": calibration["sha256"],
                    **({"head_sha256": head["sha256"]} if head else {})}
                   for r in self.rows if r["split"] in ("test", "future")]
            pin = bakeoff.candidate_registry()[arm]
            spec = {"arm": arm, "revision": pin["revision"], "repository": pin["repository"],
                    "subfolder": pin["subfolder"], "license": pin["license"],
                    "weights": weights, "tokenizer": tokenizer, "runtime": runtime,
                    "calibration": calibration,
                    "predictions": self.put_jsonl(arm + ".predictions.jsonl", obs)}
            if head is not None:
                spec["head_weights"] = head
                spec["head_training"] = dict(self.training)
                training_report = dict(self.training)
                training_report.update({"head_sha256": head["sha256"],
                                        "encoder_weights_sha256": weights["sha256"]})
                spec["training_report"] = self.put(arm + ".train.json",
                    bakeoff.canonical(training_report))
            self.manifest["models"].append(spec)
        # Complete synthetic traces test the verifier, not a real model or host.
        # Crucially, every declared Cell needs at least one request ID.
        workloads = []
        for arm in bakeoff.ARMS:
            weight_digest = next(s["weights"]["sha256"] for s in self.manifest["models"] if s["arm"] == arm)
            for scale in bakeoff.SCALES:
                active = min(scale, 16)
                n = max(100, scale)
                trace = []
                for i in range(n):
                    begin = 10_000_000 + (i // active) * 10_000_000
                    trace.append({
                        "request_id": f"{arm}-{scale}-req-{i}", "cell_id": f"cell-{i % scale}",
                        "submitted_ns": begin, "started_ns": begin + 10_000,
                        "completed_ns": begin + 5_010_000,
                        "arm": arm, "host_id": "test-host", "device": "cpu",
                        "model_weights_sha256": weight_digest, "rss_bytes": 12345678,
                        "gpu_peak_bytes": None})
                first = trace[0]["submitted_ns"]
                last = trace[-1]["completed_ns"]
                workloads.append({
                    "arm": arm, "logical_cells": scale, "active_cells": active,
                    "requests": n, "throughput_per_sec": n / ((last - first) / 1e9),
                    "p95_ms": 5.01, "p99_ms": 5.01, "load_ms": 1.0,
                    "load_started_ns": 0, "load_completed_ns": 1_000_000,
                    "peak_rss_bytes": 12345678, "peak_gpu_bytes": None,
                    "device": "cpu", "model_weights_sha256": weight_digest,
                    "host_id": "test-host", "execution_kind": "observed-real-model",
                    "trace": self.put_jsonl(f"trace.{arm}.{scale}.jsonl", trace)})
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", workloads)
        self.lifecycle = {"schema": "hepta.neuron-bakeoff.lifecycle.v1", "events": [
            {"name": name, "owner": owner, "status": "observed_success",
             "operation_id": "fixture:" + name, "generation": 9 if name == "stale_generation_reject" else 10,
             "receipt_path": (receipt := self.put(name + ".receipt", name.encode()))["path"],
             "receipt_sha256": receipt["sha256"]}
            for name, owner in bakeoff.EVENT_OWNERS.items()]}
        self.resign()

    def put(self, name, content):
        (self.root / name).write_bytes(content)
        return {"path": name, "sha256": bakeoff.sha_bytes(content)}

    def put_jsonl(self, name, rows):
        return self.put(name, ("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n").encode())

    def resign(self):
        obj = copy.deepcopy(self.lifecycle)
        obj.pop("signature_base64", None)
        raw = self.root / "signing-input"
        sig = self.root / "signing-output"
        raw.write_bytes(bakeoff.canonical(obj))
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(self.key), "-rawin",
                        "-in", str(raw), "-out", str(sig)], check=True, capture_output=True)
        self.lifecycle["signature_base64"] = base64.b64encode(sig.read_bytes()).decode()
        self.manifest["lifecycle"] = self.put("lifecycle.json", bakeoff.canonical(self.lifecycle))

    def run_eval(self):
        return bakeoff.evaluate(self.root, self.manifest, self.pub)

    def test_valid_fixture_proves_contract_only(self):
        report = self.run_eval()
        self.assertEqual(set(report["models"]), set(bakeoff.ARMS))
        self.assertEqual(len(report["workload"]), 20)
        self.assertEqual(report["models"]["laya-typed"]["test"]["accuracy_with_abstentions"], 1.0)
        self.assertEqual(report["lifecycle"]["generation"], 10)
        self.assertEqual(report["qualification"], "evaluation_evidence_only_not_release_or_promotion")
        self.assertFalse(report["independent_acceptance"])
        self.assertFalse(report["all_blockers_closed"])
        self.assertFalse(report["production_activation_allowed"])

    def test_group_leakage_fails(self):
        self.rows[0]["group_id"] = self.rows[2]["group_id"]
        self.manifest["dataset"] = self.put_jsonl("dataset.jsonl", self.rows)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "leakage"):
            self.run_eval()

    def test_missing_model_fails(self):
        self.manifest["models"].pop()
        with self.assertRaisesRegex(bakeoff.EvidenceError, "five candidate"):
            self.run_eval()

    def test_unpinned_candidate_revision_denied(self):
        self.manifest["models"][0]["revision"] = "c" * 40
        with self.assertRaisesRegex(bakeoff.EvidenceError, "differs from committed pins"):
            self.run_eval()

    def test_swapped_model_repository_denied(self):
        self.manifest["models"][2]["repository"] = "untrusted/publisher"
        with self.assertRaisesRegex(bakeoff.EvidenceError, "differs from committed pins"):
            self.run_eval()

    def test_changed_weights_fails_before_scoring(self):
        (self.root / "laya-typed.weights").write_bytes(b"altered")
        with self.assertRaisesRegex(bakeoff.EvidenceError, "mismatch"):
            self.run_eval()

    def test_mismatched_observation_weights_fails(self):
        spec = self.manifest["models"][1]
        data = bakeoff.records(self.root / spec["predictions"]["path"])
        data[0]["model_weights_sha256"] = "c" * 64
        spec["predictions"] = self.put_jsonl(spec["predictions"]["path"], data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "observed weights"):
            self.run_eval()

    def test_probability_nan_and_vocabulary_mismatch_fail(self):
        spec = self.manifest["models"][0]
        data = bakeoff.records(self.root / spec["predictions"]["path"])
        data[0]["probabilities"] = {"a": 1.0, "missing": 0.0}
        spec["predictions"] = self.put_jsonl(spec["predictions"]["path"], data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "probability keys"):
            self.run_eval()

    def test_calibration_binding_drift_fails(self):
        spec = self.manifest["models"][0]
        data = bakeoff.records(self.root / spec["predictions"]["path"])
        data[0]["calibration_sha256"] = "f" * 64
        spec["predictions"] = self.put_jsonl(spec["predictions"]["path"], data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "observed calibration"):
            self.run_eval()

    def test_trained_head_binding_drift_fails(self):
        spec = self.manifest["models"][-1]
        data = bakeoff.records(self.root / spec["predictions"]["path"])
        data[0]["head_sha256"] = "f" * 64
        spec["predictions"] = self.put_jsonl(spec["predictions"]["path"], data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "observed head"):
            self.run_eval()

    def test_missing_actual_lifecycle_receipt_fails(self):
        (self.root / "signed_load.receipt").unlink()
        with self.assertRaisesRegex(bakeoff.EvidenceError, "artifact is missing"):
            self.run_eval()

    def test_training_budget_drift_fails(self):
        self.manifest["models"][-1]["head_training"]["steps"] = 21
        with self.assertRaisesRegex(bakeoff.EvidenceError, "training report|identical budgets"):
            self.run_eval()

    def test_test_set_not_admitted_as_train_fails(self):
        self.manifest["models"][-1]["head_training"]["training_dataset_sha256"] = "e" * 64
        with self.assertRaisesRegex(bakeoff.EvidenceError, "unregistered dataset"):
            self.run_eval()

    def test_absent_workload_scale_fails(self):
        data = bakeoff.records(self.root / "workload.jsonl")
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", data[:-1])
        with self.assertRaisesRegex(bakeoff.EvidenceError, "not all 5 models"):
            self.run_eval()

    def test_forged_workload_p99_is_rejected(self):
        rows = bakeoff.records(self.root / "workload.jsonl")
        rows[0]["p99_ms"] = 0.00001
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", rows)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "p99"):
            self.run_eval()

    def test_missing_trace_cannot_prove_p99(self):
        rows = bakeoff.records(self.root / "workload.jsonl")
        rows[0].pop("trace")
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", rows)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "raw request trace"):
            self.run_eval()

    def test_same_stateful_cell_cannot_overlap_its_own_tick(self):
        workloads = bakeoff.records(self.root / "workload.jsonl")
        selected = next(r for r in workloads if r["logical_cells"] == 64)
        traces = bakeoff.records(self.root / selected["trace"]["path"])
        traces[1]["cell_id"] = traces[0]["cell_id"]
        traces[64]["cell_id"] = "cell-1"  # preserve 64-cell coverage; still overlaps.
        selected["trace"] = self.put_jsonl(selected["trace"]["path"], traces)
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", workloads)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "overlapping request spans"):
            self.run_eval()

    def test_fake_throughput_rejected(self):
        workloads = bakeoff.records(self.root / "workload.jsonl")
        workloads[0]["throughput_per_sec"] *= 10
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", workloads)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "throughput_per_sec"):
            self.run_eval()

    def test_4096_cell_claim_with_one_cell_observed_is_rejected(self):
        workloads = bakeoff.records(self.root / "workload.jsonl")
        selected = next(r for r in workloads if r["logical_cells"] == 4096)
        traces = bakeoff.records(self.root / selected["trace"]["path"])
        for record in traces:
            record["cell_id"] = "same-cell"
        selected["trace"] = self.put_jsonl(selected["trace"]["path"], traces)
        self.manifest["workload"] = self.put_jsonl("workload.jsonl", workloads)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "not all declared logical Cells"):
            self.run_eval()

    def test_lifecycle_no_trusted_key_fails(self):
        with self.assertRaisesRegex(bakeoff.EvidenceError, "trusted public key"):
            bakeoff.evaluate(self.root, self.manifest, None)

    def test_lifecycle_tampering_rejected_even_if_manifest_hash_updated(self):
        self.lifecycle["events"][0]["operation_id"] = "tampered"
        self.manifest["lifecycle"] = self.put("lifecycle.json", bakeoff.canonical(self.lifecycle))
        with self.assertRaisesRegex(bakeoff.EvidenceError, "signature invalid"):
            self.run_eval()

    def test_lifecycle_old_generation_must_be_stale(self):
        for ev in self.lifecycle["events"]:
            if ev["name"] == "stale_generation_reject":
                ev["generation"] = 10
        self.resign()
        with self.assertRaisesRegex(bakeoff.EvidenceError, "previous generation"):
            self.run_eval()

    def test_artifact_path_traversal_fails(self):
        self.manifest["models"][0]["tokenizer"]["path"] = "../external.bin"
        with self.assertRaisesRegex(bakeoff.EvidenceError, "path traversal"):
            self.run_eval()


if __name__ == "__main__":
    unittest.main()
