"""Sealed synthetic-media audits, including tampering behind re-sealed logs."""

from contextlib import redirect_stdout
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch

from ..v6.data import EOS, SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .evidence_audit import audit_training_arm, audit_tree_selected
from .output_training import fit_arm
from .trees import collect_tree


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def change_rows(directory, mutation, training=True):
    name = "training-outputs.jsonl.gz" if training else "raw-rows.jsonl.gz"
    path = directory / name
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    mutation(rows)
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(payload)
    summary = json.loads((directory / "summary.json").read_text())
    if training:
        summary["artifacts"][name] = {"sha256": file_sha(path), "bytes": path.stat().st_size}
        summary["training_rows_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    else:
        summary["records_file_sha256"] = file_sha(path)
    (directory / "summary.json").write_text(json.dumps(summary))


class EvidenceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        rng = torch.Generator().manual_seed(52)
        images = torch.randint(256, (16, 1, 28, 28), generator=rng, dtype=torch.uint8)
        source = SourceSplit(images, torch.arange(16) % 10, tuple(f"audit-unit:{i}" for i in range(16)),
                             tuple(hashlib.sha256(image.numpy().tobytes()).hexdigest() for image in images))
        cls.corpus = SourceCorpus({"train": source, "forecast_fit": source}, {"manifest_sha256": "audit-unit-only"})
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(92)
            model = SlotPortfolio()
            cls.observers = {name: Recognizer().eval().requires_grad_(False) for name in ("primary", "secondary")}
        with torch.no_grad():
            model.text_projection.weight.zero_()
            model.text_projection.bias.fill_(-80.)
            model.text_projection.bias[EOS] = 80.
        warm = Snapshot(model, {"source_manifest_sha256": "audit-unit-only"})
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        protocol.update(study="synthetic-audit-unit-only", training_seeds=[17])
        protocol["training"].update(fine_tuning_steps=2, fine_tuning_conditions_per_step=2,
                                    fine_tuning_scenarios_per_condition=2, checkpoint_interval=1)
        with redirect_stdout(io.StringIO()):
            fit_arm(warm, cls.corpus, cls.observers["primary"], cls.root / "training", 17, "output_mean", protocol)
        cls.data = collect_tree(warm, cls.corpus, cls.observers, cls.root / "tree", role="forecast_fit",
                                pair_start=1, pair_count=1, scenarios=2, training_seed=17)
        count = len(cls.data["cases"])
        cls.selections = {"root": [0] * count, "root_replay": torch.zeros(count, dtype=torch.long),
                          "other": [1 if index % 2 else 20 for index in range(count)]}

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def copy(self, destination, tree=False):
        return Path(shutil.copytree(self.root / ("tree" if tree else "training"), destination))

    def test_every_actual_training_media_score_matches_without_inflating_n(self):
        report = audit_training_arm(self.root / "training", self.corpus, self.observers["primary"])
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["counts"]["output_rows_rescored"], 8)
        self.assertEqual(report["counts"]["complete_steps_checked"], 2)
        self.assertEqual(report["counts"]["media_member_sha256_checks"], 16)
        self.assertEqual(report["counts"]["terminal_pixel_token_digest_checks"], 8)
        self.assertEqual(report["counts"]["physical_complete_outputs"], 0)
        self.assertEqual(report["condition_occurrences"], 4)
        self.assertIsNone(report["claimed_independent_sample_size"])
        self.assertEqual(report["independent_training_seeds"], 1)
        self.assertGreater(report["wall_ns"], 0)
        self.assertGreater(report["counts"]["file_bytes_hashed"], 0)

    def test_resealed_training_score_token_source_loss_and_census_tampering_fail(self):
        changes = {
            "score": lambda rows: rows[0]["metric"].__setitem__("utility", .987654321),
            "token": lambda rows: rows[0]["sampled_tokens"].__setitem__(1, 14),
            "source": lambda rows: rows[0]["source_ids"].__setitem__(0, "wrong-source"),
            "loss": lambda rows: rows[0].__setitem__("actual_observed_loss", 8.),
            "missing": lambda rows: rows.pop(),
            "duplicate": lambda rows: rows.insert(1, deepcopy(rows[0])),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, mutation in changes.items():
                with self.subTest(name=name):
                    path = self.copy(Path(directory) / name)
                    change_rows(path, mutation)
                    report = audit_training_arm(path, self.corpus, self.observers["primary"])
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["status"], "failed")
                    self.assertEqual(report["errors"][0]["phase"], "streaming_media_and_score_reconstruction")
                    self.assertTrue(report["errors"][0]["message"])

    def test_no_archive_open_before_completion_or_with_changed_raw_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = self.copy(Path(directory) / "pending")
            (pending / "summary.json").unlink()
            damaged = self.copy(Path(directory) / "damaged")
            with (damaged / "raw-media.zip").open("ab") as stream:
                stream.write(b"changed")
            for path in (pending, damaged):
                with self.subTest(path=path.name), patch("zipfile.ZipFile") as opened:
                    report = audit_training_arm(path, self.corpus, self.observers["primary"])
                    self.assertFalse(report["passed"])
                    opened.assert_not_called()

    def test_selected_tree_union_scores_both_observers_once_per_actual_choice(self):
        report = audit_tree_selected(self.root / "tree", self.data, self.selections, self.corpus, self.observers)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["policy_replay_rows"], 48)
        self.assertEqual(report["expected_unique_selected_outputs"], 32)
        self.assertEqual(report["counts"]["unique_selected_outputs_rescored"], 32)
        self.assertEqual(report["counts"]["selected_observer_output_rescores"], 64)
        self.assertEqual(report["counts"]["media_member_sha256_checks"], 64)
        self.assertEqual(report["independent_source_pairs"], 1)
        self.assertEqual(report["unselected_media_outputs_rescored"], 0)

    def test_selected_tree_raw_and_data_metrics_checked_without_certifying_other_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = self.copy(Path(directory) / "selected", tree=True)
            change_rows(selected, lambda rows: rows[0]["observer_scores"]["primary"].__setitem__("utility", .999), False)
            report = audit_tree_selected(selected, self.data, self.selections, self.corpus, self.observers)
            self.assertFalse(report["passed"])
            altered = deepcopy(self.data)
            altered["metrics"]["primary"]["utility"][0, 0] = .999
            report = audit_tree_selected(self.root / "tree", altered, self.selections, self.corpus, self.observers)
            self.assertFalse(report["passed"])
            unselected = self.copy(Path(directory) / "unselected", tree=True)
            change_rows(unselected, lambda rows: rows[2]["observer_scores"]["primary"].__setitem__("utility", .999), False)
            report = audit_tree_selected(unselected, self.data, self.selections, self.corpus, self.observers)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["unselected_media_outputs_rescored"], 0)


if __name__ == "__main__":
    unittest.main()
