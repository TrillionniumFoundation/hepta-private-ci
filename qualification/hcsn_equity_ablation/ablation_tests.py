"""State-invariant feature substitution and global holdout-seal behavior."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from qualification.hcsn_adaptive.campaign import digest, write_json
from qualification.hcsn_adaptive.checkpoint import claim_final_holdout
from qualification.hcsn_adaptive.datasets import file_digest
from qualification.hcsn_adaptive.features import build_encoder
from qualification.hcsn_history.call_adapters import FrozenHXCurve
from .campaign import FLOW, finalize, groups, seal
from .features import ARMS, extract_arms


class EquityAblationTests(unittest.TestCase):
    def test_only_call_columns_change_and_complete_state_matches_independent_flow(self):
        previous = torch.get_num_threads()
        torch.set_num_threads(1)
        try:
            model = build_encoder(2, seed=11, flow=FLOW).requires_grad_(False)
            original = {key: value.clone() for key, value in model.state_dict().items()}
            x = np.array([[[.2, -.4], [.8, .5], [-.7, .3]], [[-.1, .9], [.4, -.6], [.5, .2]]])
            curve = FrozenHXCurve.build(model.centers)
            outputs, diagnostics, actual = extract_arms(model, x, np.full((2, 3), .1), curve)
            state, baseline, equity = None, [], []
            with torch.no_grad():
                for index in range(3):
                    feature, state, _ = model.step(torch.as_tensor(x[:, index]), state, dt=.1, boundary_override=0.0)
                    baseline.append(feature)
                    equity.append(curve.apply(model, state))
            d = len(model.feature_names)
            expected = torch.cat((baseline[-1], torch.stack(baseline).mean(0)), 1)
            torch.testing.assert_close(outputs["finite_policy"], expected, rtol=0, atol=1e-14)
            unchanged = [index for index in range(2*d) if index not in (d-1, 2*d-1)]
            for arm in ARMS:
                torch.testing.assert_close(outputs[arm][:, unchanged], expected[:, unchanged], rtol=0, atol=1e-14)
            torch.testing.assert_close(outputs["full_hx"][:, d-1], equity[-1], rtol=0, atol=0)
            torch.testing.assert_close(outputs["full_hx"][:, -1], torch.stack(equity).mean(0), rtol=0, atol=1e-14)
            self.assertEqual(int(torch.count_nonzero(outputs["drop_call"][:, [d-1, 2*d-1]])), 0)
            torch.testing.assert_close(actual.density, state.density, rtol=0, atol=0)
            torch.testing.assert_close(actual.boundary, state.boundary, rtol=0, atol=0)
            self.assertEqual(actual.time_micros, state.time_micros)
            for key, value in model.state_dict().items():
                torch.testing.assert_close(value, original[key], rtol=0, atol=0)
            self.assertTrue(diagnostics["original_call_solve_always_paid"])
        finally:
            torch.set_num_threads(previous)

    def test_global_seal_and_exactly_once_claim_precede_any_test_loading(self):
        manifest = {"sha256": "fixture", "tasks": {"future_return": {}}, "seeds": [11, 29]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("qualification.hcsn_equity_ablation.campaign.load_split") as loader:
                with self.assertRaisesRegex(ValueError, "globally sealed"):
                    finalize(manifest, root)
                loader.assert_not_called()
            records = []
            for task, seed, name in groups(manifest):
                directory = root/name
                directory.mkdir()
                (directory/"selected.pt").write_bytes(b"unopened fixture payload")
                row = {"identity": digest({"manifest": manifest["sha256"], "group": name}), "status": "completed",
                       "arms": {arm: {"dev_mse": (index+1)/seed} for index, arm in enumerate(ARMS)},
                       "selected_sha256": file_digest(directory/"selected.pt")}
                write_json(directory/"training.json", row)
                records.append((directory, row))
            sealed = seal(manifest, root)
            directory, row = records[-1]
            changed = json.loads(json.dumps(row))
            changed["arms"]["full_hx"]["dev_mse"] = 99.0
            write_json(directory/"training.json", changed)
            with patch("qualification.hcsn_equity_ablation.campaign.load_split") as loader:
                with self.assertRaisesRegex(ValueError, "globally sealed"):
                    finalize(manifest, root)
                loader.assert_not_called()
            write_json(directory/"training.json", row)
            claim_final_holdout(root/"final.started", digest(sealed))
            with patch("qualification.hcsn_equity_ablation.campaign.load_split") as loader:
                with self.assertRaises(FileExistsError):
                    finalize(manifest, root)
                loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
