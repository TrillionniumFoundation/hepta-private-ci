"""Paired real emission interventions retain media, cases and frozen observers."""

import json
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .interventions import evaluate_intervention
from .trees import collect_tree


class InterventionTests(unittest.TestCase):
    def test_actual_fixed_path_census_and_initial_pairing(self):
        torch.set_num_threads(2)
        with torch.random.fork_rng():
            torch.manual_seed(77)
            snapshot = Snapshot(SlotPortfolio())
            observer = Recognizer().eval().requires_grad_(False)
        count = 1218
        generator = torch.Generator().manual_seed(52)
        images = torch.randint(256, (count, 1, 28, 28), dtype=torch.uint8, generator=generator)
        labels = torch.randint(10, (count,), generator=generator)
        ids = tuple(f"synthetic:{i}" for i in range(count))
        corpus = SourceCorpus({"development": SourceSplit(images, labels, ids, ids)},
                              {"manifest_sha256": "synthetic-source-only"})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            base = collect_tree(snapshot, corpus, {"primary": observer}, directory / "base",
                                role="development", pair_start=608, pair_count=1, scenarios=2, training_seed=17)
            for profile in ("shared_state_clamp_semantic_couple", "encoder_initial_only_fixed"):
                result = evaluate_intervention(snapshot, corpus, {"primary": observer},
                                               directory / profile, base, profile)
                for key in ("cases", "views", "scenarios", "source_ids"):
                    self.assertEqual(result[key], base[key])
                self.assertEqual(result["metrics"]["primary"]["utility"].shape, (16,))
                summary = json.loads((directory / profile / "summary.json").read_text())
                self.assertEqual(summary["status"], "completed")
                if profile == "shared_state_clamp_semantic_couple":
                    self.assertEqual(summary["initial_matches_reference"], 16)


if __name__ == "__main__":
    unittest.main()
