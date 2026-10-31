"""Actual neural tree, raw media and pairing tests on synthetic sources only."""

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.data import VIEWS, make_batch
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .critic import ActionCritic, bootstrap_two_step_targets
from .emission import output_digests
from .media import reopen_archive_records
from .runtime import initialize, transition
from .trees import PLANS, collect_tree, stable_seed


class TreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        rng = torch.Generator().manual_seed(81)
        images = torch.randint(256, (8, 1, 28, 28), dtype=torch.uint8, generator=rng)
        pool = SourceSplit(images, torch.arange(8) % 10, tuple(f"synthetic:{i}" for i in range(8)),
                           tuple(hashlib.sha256(image.numpy().tobytes()).hexdigest() for image in images))
        self.corpus = SourceCorpus({"forecast_fit": pool}, {"manifest_sha256": "synthetic-only"})
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            model = SlotPortfolio()
            self.snapshot = Snapshot(model)
            self.observer = Recognizer().eval().requires_grad_(False)
            self.secondary = Recognizer().eval().requires_grad_(False)

    def test_actual_tree_replay_raw_media_source_pairs_and_public_feature_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = dict(role="forecast_fit", pair_start=1, pair_count=1, scenarios=2, training_seed=17)
            a = collect_tree(self.snapshot, self.corpus, {"primary": self.observer}, root / "a", **args)
            b = collect_tree(self.snapshot, self.corpus, {"primary": self.observer, "secondary": self.secondary}, root / "b", **args)
            self.assertEqual((a["cases"], a["views"], a["scenarios"], a["source_ids"]),
                             ([1] * 16, [view for view in VIEWS for _ in range(2)], [0, 1] * 8,
                              [("synthetic:2", "synthetic:3")] * 16))
            self.assertEqual(tuple(a["features"].shape), (16, 5, 673))
            self.assertTrue(torch.equal(a["features"], b["features"]))
            for metric in a["metrics"]["primary"]:
                self.assertTrue(torch.equal(a["metrics"]["primary"][metric], b["metrics"]["primary"][metric]))
                self.assertTrue(torch.equal(a["metrics"]["primary"][metric][:, 0], a["metrics"]["primary"][metric][:, 1]))
            self.assertFalse(torch.equal(a["features"][:, 0, :96], a["features"][:, 1, :96]))
            self.assertEqual(set(b["metrics"]), {"primary", "secondary"})
            self.assertEqual(tuple(b["metrics"]["secondary"]["utility"].shape), (16, 21))
            summary = json.loads((root / "a/summary.json").read_text())
            work = summary["actual_incremental_generation_work"]
            self.assertEqual({key: work[key] for key in ("encoder_calls", "state_transition_calls", "emission_calls")},
                             {"encoder_calls": 8, "state_transition_calls": 176, "emission_calls": 128})
            with gzip.open(root / "a/raw-rows.jsonl.gz", "rt") as stream:
                rows = [json.loads(line) for line in stream]
            self.assertEqual(len(rows), 16 * 21)
            self.assertEqual([(row["row_index"], row["plan_index"]) for row in rows],
                             [(i, plan) for i in range(16) for plan in range(21)])
            roots = [row for row in rows if row["plan_index"] == 0]
            pixels, captions = reopen_archive_records(root / "a" / roots[0]["view_archive"], roots[:2])
            self.assertEqual(output_digests(pixels, a["root_tokens"][:2]), tuple(a["root_emission_sha256"][:2]))
            self.assertTrue(torch.equal(pixels, a["root_pixels"][:2].float()))
            self.assertEqual([row["output_sha256"] for row in roots], a["root_emission_sha256"])
            semantic_ledger = [json.loads(line) for line in (root / "a/ledgers/clean/01.jsonl").read_text().splitlines()]
            self.assertFalse(semantic_ledger[0]["new_emission_on_this_edge"])
            self.assertEqual(semantic_ledger[0]["owner_rng_before_sha256"], semantic_ledger[0]["owner_rng_after_sha256"])
            loaded = torch.load(root / "a/data.pt", weights_only=True)
            self.assertEqual(loaded["plans"], list(PLANS))
            self.assertTrue(torch.equal(loaded["root_tokens"], a["root_tokens"]))
            head = ActionCritic(673, 2., 1, 7)
            with self.assertRaisesRegex(ValueError, "child_features"):
                bootstrap_two_step_targets(a["metrics"]["primary"]["utility"][:, 0],
                                           a["features"].repeat(1, 4, 1)[:, :16], head)
            with self.assertRaises(FileExistsError):
                collect_tree(self.snapshot, self.corpus, {"primary": self.observer}, root / "a", **args)

    def test_allocation_masked_local_paths_match_full_control_actual_outputs(self):
        batch = make_batch(self.corpus, "forecast_fit", 1, stable_seed("observation", "forecast_fit", 1),
                           view="noise", offset=1)
        model = self.snapshot._model
        full = initialize(model, batch.observation, generator=torch.Generator().manual_seed(13))
        allocation = initialize(model, batch.observation, generator=torch.Generator().manual_seed(13), content_mode="allocation_only")
        for seed, action in enumerate(("refine_image", "refine_text"), 14):
            full = transition(model, full, action, generator=torch.Generator().manual_seed(seed))
            allocation = transition(model, allocation, action, generator=torch.Generator().manual_seed(seed))
        self.assertEqual(output_digests(full.pixels, full.tokens), output_digests(allocation.pixels, allocation.tokens))
        self.assertTrue(torch.equal(full.state.h, allocation.state.h))


if __name__ == "__main__":
    unittest.main()
