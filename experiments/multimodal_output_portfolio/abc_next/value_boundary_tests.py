"""Independent boundary tests using synthetic sources and adversarial heads."""

import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..abc_recovery.control import PLANS
from ..v7.data import VIEWS
from .compact_tree import decode_media, encode_media
from . import value


class FixedHead(torch.nn.Module):
    def __init__(self, predictions):
        super().__init__()
        self.predictions = torch.tensor(predictions, dtype=torch.float32)

    def forward(self, public):
        return self.predictions.repeat(len(public), 1)


class ValueBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def fixture(self, directory):
        ids = [f"synthetic-source:{i}" for i in range(2000)]
        manifest = Path(directory) / "synthetic-manifest.json"
        manifest.write_text(json.dumps({"roles": {"forecast_fit": {"source_ids": ids}}}))
        census = [(case, view, scenario) for case in range(480, 736) for view in VIEWS for scenario in range(2)]
        # Source IDs in this artificial feature are test instrumentation only.
        # Real public features never contain source IDs or case indices.
        public = torch.tensor([row[0] for row in census], dtype=torch.float32)[:, None, None].expand(-1, 5, 763)
        return manifest, {"role": "forecast_fit", "pair_start": 480, "pair_count": 256,
            "scenarios_per_source": 2, "plans": PLANS, "features": public,
            "metrics": {"primary": {"utility": torch.zeros(4096, 21)}},
            "cases": [row[0] for row in census], "views": [row[1] for row in census],
            "scenarios": [row[2] for row in census],
            "source_ids": [tuple(ids[2 * row[0]:2 * row[0] + 2]) for row in census]}

    def test_wrong_source_interval_identity_or_census_never_reaches_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, data = self.fixture(directory)
            changed_ids = list(data["source_ids"])
            changed_ids[0] = changed_ids[1][::-1]
            duplicated_scenarios = list(data["scenarios"])
            duplicated_scenarios[0] = duplicated_scenarios[1]
            cases = (
                ({"pair_start": 448}, "interval"),
                ({"source_ids": changed_ids}, "identities"),
                ({"scenarios": duplicated_scenarios}, "census"),
                ({"cases": data["cases"][:-1]}, "census"),
                ({"plans": tuple(reversed(PLANS))}, "plan order"),
            )
            with patch.object(value, "MANIFEST", manifest), patch.object(value, "fit_head", side_effect=AssertionError("Invalid sources reached fitting")):
                for mutation, message in cases:
                    with self.subTest(mutation=list(mutation)):
                        with self.assertRaisesRegex(ValueError, message):
                            value.fit_controller({**data, **mutation}, "base", 32, 19)

    def test_q2_backups_use_unseen_sources_and_exclude_dominated_h1_action(self):
        fits, predictions = [], []

        class SourceGuard(FixedHead):
            def __init__(self, fitted_sources, enforce):
                super().__init__([2., .001, 3., 4., 5.])
                self.fitted_sources, self.enforce = fitted_sources, enforce

            def forward(self, public):
                held = set(public[:, 0].tolist())
                if self.enforce:
                    if self.fitted_sources & held:
                        raise AssertionError("A fold head predicted its own training source")
                    predictions.append((self.fitted_sources, held))
                return super().forward(public)

        def fake_fit(x, y, **kwargs):
            sources = set(x[:, 0].tolist())
            index = len(fits)
            fits.append({"sources": sources, "x_rows": len(x), "target": y.clone()})
            return SourceGuard(sources, index < 2), {"synthetic_spy": True}

        with tempfile.TemporaryDirectory() as directory:
            manifest, data = self.fixture(directory)
            with patch.object(value, "MANIFEST", manifest), patch.object(value, "fit_head", side_effect=fake_fit):
                result = value.fit_controller(data, "base", 32, 19)
        self.assertEqual(len(predictions), 2)
        self.assertEqual([len(f["sources"]) for f in fits], [128, 128, 256, 256, 256])
        self.assertEqual([f["x_rows"] for f in fits], [10240, 10240, 20480, 4096, 4096])
        for trained, held in predictions:
            self.assertFalse(trained & held)
            self.assertEqual(trained | held, set(range(480, 736)))
        torch.testing.assert_close(fits[3]["target"][:, 0], torch.ones(4096))
        torch.testing.assert_close(fits[3]["target"][:, 1:], torch.full((4096, 4), 2 * math.exp(.004)))
        self.assertTrue(result.report["H1_semantic_strict_dominance_enforced_for_all_candidates"])

    def test_every_candidate_prunes_h1_semantic_but_preserves_delayed_h2_route(self):
        route = [10.] * len(PLANS)
        for i, plan in enumerate(PLANS):
            if plan and plan[-1] == "refine_semantic":
                route[i] = .0001
        desired = PLANS.index(("refine_semantic", "couple"))
        route[desired] = .5
        public = torch.zeros(2, 763)
        for mode, hidden in value.CANDIDATES:
            with self.subTest(mode=mode, hidden=hidden):
                controller = value.Controller(mode, hidden, FixedHead([2, .001, 3, 4, 5]),
                    FixedHead([2, .001, 3, 4, 5]), FixedHead(route), {})
                self.assertEqual(controller.choose(public, 1).tolist(), [0, 0])
                self.assertEqual(controller.choose(public, 2).tolist(), [1, 1])
                self.assertEqual(controller.choose_plan(public).tolist(), [desired, desired])

    def test_invalid_route_predictions_are_refused_before_argmin(self):
        for invalid in (float("nan"), float("inf"), 0., -1.):
            route = [1.] * len(PLANS)
            route[0] = invalid
            controller = value.Controller("base", 32, FixedHead([1] * 5), FixedHead([1] * 5), FixedHead(route), {})
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "route moment"):
                controller.choose_plan(torch.zeros(1, 763))

    def test_final_optimizer_update_cannot_return_corrupt_head(self):
        class CorruptFinalAdam(torch.optim.Adam):
            def step(self, closure=None):
                result = super().step(closure)
                with torch.no_grad():
                    self.param_groups[0]["params"][0].fill_(float("nan"))
                return result

        with patch.dict(value.CONFIG, {"steps": 1}), patch.object(torch.optim, "Adam", CorruptFinalAdam):
            with self.assertRaisesRegex(ValueError, "Nonfinite final"):
                value.fit_head(torch.zeros(4, 3), torch.ones(4, 5), hidden=2, seed=72)

    def test_closed_npz_is_lossless_and_changed_pixels_or_tokens_are_rejected(self):
        pixels = torch.randint(2, (3, 1, 28, 56), generator=torch.Generator().manual_seed(303)).float()
        tokens = torch.tensor([[1, 3, 14, 4, 15, 5, 6, 2]]).repeat(3, 1)
        bits, stored_tokens, hashes = encode_media(pixels, tokens)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-actual-media.npz"
            with path.open("xb") as stream:
                np.savez_compressed(stream, pixels_bits=bits, tokens=stored_tokens, output_sha256=hashes)
            with np.load(path, allow_pickle=False) as archive:
                restored = {key: archive[key].copy() for key in archive.files}
            decoded_pixels, decoded_tokens, captions = decode_media(restored["pixels_bits"], restored["tokens"], restored["output_sha256"])
        self.assertTrue(torch.equal(decoded_pixels, pixels))
        self.assertTrue(torch.equal(decoded_tokens, tokens))
        self.assertEqual(captions, ["left 0 right 1 relation less"] * 3)
        broken_bits = bits.copy()
        broken_bits[0, 0] ^= 1
        with self.assertRaisesRegex(ValueError, "identity differs"):
            decode_media(broken_bits, stored_tokens, hashes)
        broken_tokens = stored_tokens.copy()
        broken_tokens[0, 2] = 16
        with self.assertRaisesRegex(ValueError, "identity differs"):
            decode_media(bits, broken_tokens, hashes)
        probabilities = pixels.clone()
        probabilities[0, 0, 0, 0] = .5
        with self.assertRaisesRegex(ValueError, "binary"):
            encode_media(probabilities, tokens)


if __name__ == "__main__":
    unittest.main()
