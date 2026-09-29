"""Driver contract tests. Fake predictors are NOT model execution evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from laya_retrieval import (FORMAT, REQUIRED_FILES, REQUIRED_PACKAGES, EnteredFailure,
                            Rejected, RetrievalDriver, checkpoint_identity, digest,
                            encoded, load_pinned, prepare)


class Tokenizer:
    mask_token = "[MASK]"

    def __call__(self, value, **kwargs):
        return {"input_ids": value.split()}


class Predictor:
    tok = Tokenizer()
    cfg = {"max_len": 512, "head_max_len": 192}

    def __init__(self):
        self.calls = 0
        self.change = lambda result: result

    def predict(self, state, questions, **kwargs):
        self.calls += 1
        result = {"answers": {"source": {"choice": "source-a",
                  "probabilities": {"abstain": 0.2, "source-a": 0.8},
                  "act_probability": 1.0, "success": True}}}
        return self.change(result)


def request():
    return {"format": FORMAT, "operation_id": "op-1", "scope": "workspace-a",
            "objective_digest": "a" * 64, "snapshot_digest": "b" * 64,
            "query": "What is the project name?",
            "candidates": [{"id": "source-a", "source_digest": "c" * 64,
                            "excerpt": "The project name is Hepta."}]}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.model = Predictor()
        self.driver = RetrievalDriver(self.model, "d" * 64, 512, 192)

    def run_request(self, value=None):
        return self.driver.predict(encoded(request() if value is None else value),
                                   time.monotonic() + 10)

    def test_full_binding_and_no_self_authorized_success(self):
        result = self.run_request()
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(result["selected"], "source-a")
        self.assertFalse(result["authority"])
        self.assertFalse(result["calibration_verified"])
        self.assertIsNone(result["task_success"])
        self.assertEqual(result["input_digest"], digest(request()))
        self.assertEqual(result["candidates"], [{"id": "source-a", "source_digest": "c" * 64}])
        self.assertNotIn("excerpt", result["candidates"][0])
        receipt = result.pop("receipt_digest")
        self.assertEqual(receipt, digest(result))

    def test_scope_snapshot_candidate_order_bound(self):
        original = self.run_request()
        for field, value in [("scope", "workspace-b"), ("snapshot_digest", "e" * 64),
                             ("objective_digest", "f" * 64)]:
            changed = request()
            changed[field] = value
            self.assertNotEqual(self.run_request(changed)["input_digest"], original["input_digest"])
        value = request()
        value["candidates"].append({"id": "source-b", "source_digest": "e" * 64,
                                    "excerpt": "Another source."})
        first = digest(prepare(encoded(value))[0])
        value["candidates"].reverse()
        self.assertNotEqual(first, digest(prepare(encoded(value))[0]))

    def test_duplicate_json_rejected(self):
        with self.assertRaises(Rejected):
            prepare(b'{"scope":"one","scope":"two"}')
        with self.assertRaises(Rejected):
            prepare(b'{"score":NaN}')

    def test_unadmitted_fields_or_candidates_rejected_before_model(self):
        values = []
        bad = request(); bad["execute"] = True; values.append(bad)
        bad = request(); bad["candidates"] *= 2; values.append(bad)
        bad = request(); bad["candidates"][0]["id"] = "abstain"; values.append(bad)
        bad = request(); bad["candidates"] = []; values.append(bad)
        for bad in values:
            with self.subTest(bad=bad), self.assertRaises(Rejected):
                self.run_request(bad)
        self.assertEqual(self.model.calls, 0)

    def test_option_and_state_truncation_and_mask_substitution_rejected(self):
        for field in ("option", "query", "mask"):
            bad = request()
            if field == "option": bad["candidates"][0]["excerpt"] = "word " * 49
            elif field == "query": bad["query"] = "word " * 510
            else: bad["query"] = "literal [MASK] token"
            with self.subTest(field=field), self.assertRaises(Rejected):
                self.run_request(bad)
        self.assertEqual(self.model.calls, 0)

    def test_expired_and_busy_never_enter_model(self):
        with self.assertRaises(Rejected):
            self.driver.predict(encoded(request()), time.monotonic() - 1)
        self.driver._lock.acquire()
        try:
            with self.assertRaises(Rejected): self.run_request()
        finally:
            self.driver._lock.release()
        self.assertEqual(self.model.calls, 0)

    def test_invalid_output_is_entered_failure_not_unexecuted(self):
        for probabilities in ({"source-a": 1}, {"abstain": float("nan"), "source-a": 0.8},
                              {"abstain": -0.1, "source-a": 1.1}, {"abstain": 0.1, "source-a": 0.1}):
            def change(result):
                result["answers"]["source"]["probabilities"] = probabilities
                return result
            self.model.change = change
            with self.subTest(probabilities=probabilities), self.assertRaises(EnteredFailure):
                self.run_request()
        self.assertEqual(self.model.calls, 4)

    def test_late_model_result_is_not_published(self):
        # No sleeps: monotonic time crosses the same deadline after model entry.
        with patch("laya_retrieval.time.monotonic", side_effect=[0, 0, 0, 2, 2, 2]):
            with self.assertRaises(EnteredFailure):
                self.driver.predict(encoded(request()), 1)
        self.assertEqual(self.model.calls, 1)

    def test_argmax_tie_breaks_in_admitted_order(self):
        def change(result):
            result["answers"]["source"]["probabilities"] = {"source-a": 0.5, "abstain": 0.5}
            return result
        self.model.change = change
        result = self.run_request()
        self.assertEqual(result["selected"], "abstain")
        self.assertEqual(result["selected_propensity"], 1)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_bytes_inventory_runtime_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            files = {}
            for name in REQUIRED_FILES:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
                files[name] = hashlib.sha256(b"fixture").hexdigest()
            versions = {name: "fixture" for name in REQUIRED_PACKAGES}; versions["laya"] = "0.3.20"
            pins = {"format": FORMAT, "repository": "convaiinnovations/laya", "revision": "a" * 40,
                    "files": files, "runtime_versions": versions}
            with patch("laya_retrieval.importlib.metadata.version", side_effect=versions.__getitem__):
                self.assertEqual(checkpoint_identity(root, pins), digest(pins))
                path = root / "model.safetensors"; path.write_bytes(b"changed")
                with self.assertRaises(Rejected): checkpoint_identity(root, pins)
                path.write_bytes(b"fixture")
                extra = root / "unlisted"; extra.write_bytes(b"unexpected")
                with self.assertRaises(Rejected): checkpoint_identity(root, pins)
                extra.unlink(); extra.symlink_to(path)
                with self.assertRaises(Rejected): checkpoint_identity(root, pins)
                extra.unlink()
                bad = copy.deepcopy(pins); bad["revision"] = "main"
                with self.assertRaises(Rejected): checkpoint_identity(root, bad)
                bad = copy.deepcopy(pins); bad["runtime_versions"]["torch"] = "wrong"
                with self.assertRaises(Rejected): checkpoint_identity(root, bad)

    def test_online_worker_rejected_before_laya_import(self):
        with patch.dict("os.environ", {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0"}):
            with self.assertRaises(Rejected): load_pinned(Path("/missing"), {})


if __name__ == "__main__":
    unittest.main()
