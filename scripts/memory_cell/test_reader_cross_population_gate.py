"""Fail-closed cross-population reconciliation tests; no simulated model scores."""

from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import reader_cross_population_gate as gate


def fixture_zip(root, records):
    target = root / "fixture.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in records.items():
            archive.writestr(name, content)
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


class CrossPopulationGateTests(unittest.TestCase):
    def test_original_experiment_hash_pins_are_complete(self):
        self.assertEqual(len(gate.PINS), 7)
        self.assertEqual(len(set(gate.PINS.values())), 7)
        self.assertTrue(all(len(p) == 64 for p in gate.PINS.values()))
        self.assertEqual(sum(gate.EVENT_COUNTS.values()), 41)
        self.assertEqual(gate.EVENT_COUNTS["organized"], 8)
        self.assertEqual(gate.EVENT_COUNTS["entity_time"], 8)
        self.assertEqual(gate.EVENT_CITED["organized"], 4)

    def test_bounded_externally_pinned_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, external = fixture_zip(root, {"receipt.json": "{}"})
            with gate.pinned_zip(path, external) as archive:
                self.assertEqual(gate.json_at(archive, "receipt.json"), {})
            with self.assertRaisesRegex(ValueError, "externally pinned"):
                gate.pinned_zip(path, "0" * 64)

    def test_manifest_rejects_changed_or_omitted_members(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, digest = fixture_zip(
                root,
                {"result.json": "{}", "SHA256SUMS": "0" * 64 + "  result.json\n"},
            )
            with self.assertRaisesRegex(ValueError, "modified inner"):
                gate.pinned_zip(path, digest)
            path, digest = fixture_zip(
                root,
                {
                    "result.json": "{}",
                    "additional.json": "{}",
                    "SHA256SUMS": gate.sha(b"{}") + "  result.json\n",
                },
            )
            with self.assertRaisesRegex(ValueError, "incomplete artifact"):
                gate.pinned_zip(path, digest)

    def test_reject_duplicate_entries_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, digest = fixture_zip(root, {"../escape.json": "{}"})
            with self.assertRaisesRegex(ValueError, "unsafe artifact"):
                gate.pinned_zip(path, digest)
            path, digest = fixture_zip(root, {"safe\\path": "{}"})
            with self.assertRaisesRegex(ValueError, "unsafe artifact"):
                gate.pinned_zip(path, digest)

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        for payload in (
            b'{"answer":1,"answer":2}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1e309}',
        ):
            with self.assertRaises(ValueError):
                gate.strict_json(payload)

    def test_missing_or_duplicate_model_call_is_not_hidden(self):
        def row(q, arm):
            return {"question_id": q, "arm": arm, "status": "succeeded"}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = [row(q, a) for q in ("q1", "q2") for a in ("k4", "k8")]
            for subset in (
                valid[:-1],
                valid + valid[:1],
                [dict(valid[0], status="failed")] + valid[1:],
            ):
                path, digest = fixture_zip(
                    root,
                    {"raw.jsonl": "\n".join(json.dumps(r) for r in subset)},
                )
                with gate.pinned_zip(path, digest) as archive:
                    with self.assertRaises(ValueError):
                        gate.journal(archive, "raw.jsonl", 4, ("k4", "k8"))

    def test_mixed_model_inventories_fail_before_promotion(self):
        left = {"model_identity": gate.READER_INVENTORY, "original_model_calls": 112}
        right = {"model_identity": "another-model", "original_model_calls": 32}
        with (
            patch.object(gate, "pinned_zip", return_value=BytesIO()),
            patch.object(gate, "event_summary", return_value=left),
            patch.object(gate, "locomo_summary", return_value=right),
        ):
            with self.assertRaisesRegex(ValueError, "different model"):
                gate.reconcile(dict.fromkeys(gate.PINS, "synthetic"))

    def test_even_equal_model_cannot_pool_incompatible_metrics(self):
        left = {"model_identity": gate.READER_INVENTORY, "original_model_calls": 112}
        right = {"model_identity": gate.READER_INVENTORY, "original_model_calls": 32}
        with (
            patch.object(gate, "pinned_zip", return_value=BytesIO()),
            patch.object(gate, "event_summary", return_value=left),
            patch.object(gate, "locomo_summary", return_value=right),
        ):
            result = gate.reconcile(dict.fromkeys(gate.PINS, "synthetic"))
        self.assertEqual(result["observed_completed_model_calls"], 144)
        self.assertIsNone(result["pooled_accuracy"])
        self.assertFalse(
            result["qualification"]["parametric_memory_training_qualified"]
        )
        self.assertFalse(result["qualification"]["production_accepted"])

    def test_original_archives_reconcile_when_explicitly_supplied(self):
        """Run only with mounted original model/source ZIPs, never fake inputs."""
        root = Path(__file__).resolve().parent
        files = {
            "event_model": "strong-rag-complete-38224780900.zip",
            "event_replay": "strong-rag-independent-replay-38224780900.zip",
            "locomo_public": "locomo-public-source-20261013.zip",
            "locomo_retrieval": "locomo-retrieval-20261013.zip",
            "locomo_targets": "locomo-labels-20261013.zip",
            "locomo_model": "locomo-reader-32-20261013.zip",
            "locomo_score": "locomo-hosted-score-20261013.zip",
        }
        if not all((root / file).exists() for file in files.values()):
            self.skipTest("original externally pinned artifacts not mounted")
        r = gate.reconcile({k: root / name for k, name in files.items()})
        self.assertEqual(r["observed_completed_model_calls"], 144)
        self.assertEqual(
            r["controlled_authored_event"]["arms"]["organized"][
                "correct_with_full_public_citation_path"
            ],
            4,
        )


if __name__ == "__main__":
    unittest.main()
