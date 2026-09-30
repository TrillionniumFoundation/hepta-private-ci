"""Real tensor/feature fixtures; mocked provenance is never model qualification."""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

import decision_cell_bakeoff as bakeoff
import family_replay


class FamilyReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rows = bakeoff.build_dataset()
        _, dataset = bakeoff.write_dataset(rows, self.root / "dataset")
        features = bakeoff.save_embeddings(self.root, "fixture", [row.example_id for row in rows],
            np.zeros((len(rows), 8), dtype=np.float32), np.zeros((len(rows), 4, 8), dtype=np.float32))
        heads = bakeoff.TypedHeads(8, width=4)
        with torch.no_grad():
            for parameter in heads.parameters():
                parameter.zero_()
        self.source = {"commit": "a" * 40, "tree": "b" * 40}
        self.summary = "c" * 64
        self.receipts = {}
        self.verified = {"summary_sha256": self.summary, "models": []}
        for index, name in enumerate(sorted(bakeoff.MODEL_SPECS)):
            metadata = {"source": self.source, "script_sha256": "d" * 64,
                "base_model": {"snapshot_digest": "e" * 64}, "dataset_sha256": dataset,
                "training": {}, "calibration": {"minimum_confidence": 1., "maximum_ood_probability": 0.,
                "temperatures": {key: 1. for key in (*bakeoff.HEADS, "ood")}}}
            _, head = bakeoff.save_head_artifact(self.root, name, heads, metadata)
            path = self.root / "receipts" / (name + ".json")
            digest = f"{index + 1:064x}"
            self.receipts[path] = ({**metadata, "model_name": name, "synthetic_panel_only": True,
                                  "head_artifact": head, "embedding_artifact": features}, digest)
            self.verified["models"].append({"model_name": name, "receipt_path": str(path), "receipt_sha256": digest})

    def invoke(self, *, summary=None, sources=None, verifications=None):
        with ExitStack() as stack:
            check = stack.enter_context(patch.object(bakeoff, "verify_outputs",
                side_effect=verifications or [self.verified, self.verified]))
            stack.enter_context(patch.object(bakeoff, "repository_source", side_effect=sources or [self.source, self.source]))
            stack.enter_context(patch.object(bakeoff, "verified_receipt", side_effect=lambda path: self.receipts[path]))
            result = family_replay.replay_family(self.root, self.summary if summary is None else summary)
            self.assertEqual(check.call_count, 2)
            for call in check.call_args_list:
                self.assertEqual(call.args, (self.root, sorted(bakeoff.MODEL_SPECS)))
            return result

    def test_saved_real_tensors_are_consumed_with_exact_row_denominators(self):
        result = self.invoke()
        self.assertEqual(len(result["replays"]), len(bakeoff.MODEL_SPECS))
        for replay in result["replays"]:
            self.assertEqual(replay["counts"], {"ood_errors": 0, "ood_trials": 64,
                                              "decision_errors": 0, "decision_trials": 0})
            self.assertEqual(replay["held_out_rows"], 160)
            self.assertEqual(len(replay["prediction_trace"]), 160)
            self.assertEqual(len({r["example_id"] for r in replay["prediction_trace"]}), 160)
            self.assertFalse(any(row["supported"] for row in replay["prediction_trace"]))
        self.assertFalse(result["family_support"]["all_count_bounds_met"])
        self.assertFalse(result["training_executed_this_run"])
        self.assertFalse(result["base_reencoded_this_run"])

    def test_frozen_summary_mismatch_and_malformed_digest_reject(self):
        for digest in ("f" * 64, "not-a-digest"):
            with self.assertRaisesRegex(ValueError, "summary"):
                self.invoke(summary=digest)

    def test_missing_family_verifier_failure_is_not_swallowed(self):
        with self.assertRaisesRegex(RuntimeError, "missing candidate"):
            self.invoke(verifications=[RuntimeError("missing candidate")])

    def test_changed_receipt_and_unadmitted_population_reject(self):
        first = next(iter(self.receipts))
        receipt, digest = self.receipts[first]
        self.receipts[first] = (receipt, "f" * 64)
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self.invoke()
        self.receipts[first] = ({**receipt, "synthetic_panel_only": False}, digest)
        with self.assertRaisesRegex(ValueError, "synthetic panel"):
            self.invoke()

    def test_feature_substitution_is_rejected_by_real_loader(self):
        receipt = next(iter(self.receipts.values()))[0]
        with Path(receipt["embedding_artifact"]["path"]).open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.invoke()

    def test_source_or_frozen_family_changes_reject_before_publication(self):
        with self.assertRaisesRegex(ValueError, "changed during replay"):
            self.invoke(sources=[self.source, {**self.source, "commit": "f" * 40}])
        changed = copy.deepcopy(self.verified)
        changed["summary_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "changed during replay"):
            self.invoke(verifications=[self.verified, changed])

    def test_existing_cli_publishes_private_report_without_overwrite(self):
        report = self.root / "report.json"
        result = {"family_support": {"all_count_bounds_met": False}, "production_activation": False}
        parser = bakeoff.build_parser()
        args = parser.parse_args(["--output-dir", str(self.root), "family-support",
                                  "--summary-sha256", self.summary, "--report", str(report)])
        with patch.object(family_replay, "replay_family", return_value=result):
            self.assertEqual(args.handler(args), 0)
            original = report.read_bytes()
            self.assertEqual(json.loads(original), result)
            if os.name == "posix":
                self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                args.handler(args)
            self.assertEqual(report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
