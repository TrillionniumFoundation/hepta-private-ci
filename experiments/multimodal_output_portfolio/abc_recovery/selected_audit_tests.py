"""Both observers independently rescore actual paired intervention media."""

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .interventions import evaluate_intervention
from .selected_audit import INTERVENTIONS, audit_intervention
from .trees import collect_tree


class SelectedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        rng = torch.Generator().manual_seed(52)
        images = torch.randint(256, (1218, 1, 28, 28), dtype=torch.uint8, generator=rng)
        labels = torch.randint(10, (1218,), generator=rng)
        ids = tuple(f"selected-audit-unit:{i}" for i in range(1218))
        cls.corpus = SourceCorpus({"development": SourceSplit(images, labels, ids, ids)}, {"manifest_sha256": "synthetic-audit-only"})
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(46)
            snapshot = Snapshot(SlotPortfolio())
            cls.observers = {name: Recognizer().eval().requires_grad_(False) for name in ("primary", "secondary")}
        cls.reference = collect_tree(snapshot, cls.corpus, cls.observers, cls.root / "reference",
                                     role="development", pair_start=608, pair_count=1, scenarios=2, training_seed=17)
        for profile in INTERVENTIONS:
            evaluate_intervention(snapshot, cls.corpus, cls.observers, cls.root / profile, cls.reference, profile)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_both_actual_interventions_all_observers_and_pairing(self):
        for profile in INTERVENTIONS:
            with self.subTest(profile=profile):
                report = audit_intervention(self.root / profile, self.reference, self.corpus, self.observers)
                self.assertTrue(report["passed"], report["errors"])
                self.assertEqual(report["counts"]["unique_intervention_outputs_rescored"], 16)
                self.assertEqual(report["counts"]["observer_output_rescores"], 32)
                self.assertEqual(report["counts"]["media_member_sha256_checks"], 32)
                self.assertEqual(report["independent_source_pairs"], 1)
                if profile.startswith("shared_state"):
                    self.assertEqual(report["initial_drafts_matching_reference"], 16)

    def test_resealed_secondary_score_or_initial_pairing_tampering_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind in ("secondary_score", "initial_pairing"):
                with self.subTest(kind=kind):
                    destination = Path(shutil.copytree(self.root / "shared_state_clamp_semantic_couple", Path(directory) / kind))
                    path = destination / "raw-rows.jsonl.gz"
                    with gzip.open(path, "rt") as stream:
                        rows = [json.loads(line) for line in stream]
                    if kind == "secondary_score":
                        rows[0]["observer_scores"]["secondary"]["utility"] = .9234567
                    else:
                        rows[0]["initial_matches_reference"] = False
                    with gzip.open(path, "wt") as stream:
                        for row in rows:
                            stream.write(json.dumps(row) + "\n")
                    summary = json.loads((destination / "summary.json").read_text())
                    summary["raw_rows_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    (destination / "summary.json").write_text(json.dumps(summary))
                    report = audit_intervention(destination, self.reference, self.corpus, self.observers)
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["errors"][0]["phase"], "intervention_media_and_score_reconstruction")


if __name__ == "__main__":
    unittest.main()
