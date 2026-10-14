"""Temporal mechanics with synthetic features and actual optimizer execution."""
from pathlib import Path
import tempfile
import unittest

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import video_temporal as v


def paired_features(sources, width=4):
    rows, labels = [], []
    for source in range(sources):
        base = torch.stack([torch.tensor([float(t), float(source), float(t*t), 1.0]) for t in range(8)])
        rows.extend([base, base.flip(0)])
        labels.extend([0, 1])
    x = torch.stack(rows).float()
    mask = torch.ones(len(x), 8, dtype=torch.bool)
    times = torch.arange(8, dtype=torch.long).repeat(len(x), 1) * 40000
    return (x[:, :, :width], mask, times), torch.tensor(labels, dtype=torch.long)


class FakeBase:
    simulated = True

    def __init__(self):
        self.calls = {"clip": 0}
        self.identities = {"clip": "fixture"}
        self.models = {}
        self.processors = {}
        self.materializations = {}

    def encode(self, name, item, root):
        self.calls["clip"] += 1
        values = []
        for frame in item:
            n = int(frame["sha256"][:2], 16)
            values.append(torch.tensor([n, n*n % 17, 1.0], dtype=torch.float32))
        return torch.stack(values), torch.tensor([f["timestamp_us"] for f in item], dtype=torch.long)

    def close(self):
        pass


class TemporalTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_order_blind_is_exactly_invariant_to_reversal(self):
        item, _ = paired_features(3)
        model = v.OrderBlind(4).eval()
        with torch.no_grad():
            p = model(item)
        for i in range(0, len(p), 2):
            self.assertTrue(torch.allclose(p[i], p[i+1], atol=1e-6, rtol=1e-6))

    def test_endpoint_and_gru_learn_direction_without_holdout_targets(self):
        train, train_y = paired_features(8)
        calibration, calibration_y = paired_features(3)
        holdout, holdout_y = paired_features(3)
        result = v.trial(train, train_y, calibration, calibration_y, holdout, steps=80, seed=11)
        endpoint = torch.tensor(result["predictions"]["endpoint_delta"]["selected"])
        gru = torch.tensor(result["predictions"]["temporal_gru"]["selected"])
        blind = torch.tensor(result["predictions"]["order_blind"]["selected"])
        self.assertGreaterEqual(int((endpoint.argmax(-1) == holdout_y).sum()), 5)
        self.assertGreaterEqual(int((gru.argmax(-1) == holdout_y).sum()), 5)
        self.assertEqual(int((blind.argmax(-1) == holdout_y).sum()), 3)

    def test_cache_reuses_exact_frames_and_preserves_requested_order(self):
        base = FakeBase()
        cache = v.FrameCacheTowers(base)
        refs = [{"path": f"{i}.png", "sha256": f"{i:02x}" + "0"*62,
                 "timestamp_us": i*40000} for i in range(8)]
        forward, _ = cache.encode("video", refs, Path("."))
        reverse_refs = [dict(frame, timestamp_us=i*40000) for i, frame in enumerate(reversed(refs))]
        reverse, _ = cache.encode("video", reverse_refs, Path("."))
        self.assertEqual(base.calls["clip"], 1)
        self.assertEqual(cache.frame_cache_hits, 8)
        self.assertTrue(torch.equal(forward.flip(0), reverse))

    def test_invalid_video_rejected_before_model_math(self):
        item, labels = paired_features(2)
        x, mask, times = item
        with self.assertRaises(e.InputError):
            v.validate_video((x[:, :7], mask[:, :7], times[:, :7]), labels)
        bad = x.clone()
        bad[0, 0, 0] = float("nan")
        with self.assertRaises(e.InputError):
            v.validate_video((bad, mask, times), labels)

    def test_cohort_requires_exact_reverse_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for direction, frames in (("forward", [str(i) for i in range(8)]),
                                      ("reverse", [str(i) for i in range(8)])):
                rows.append({"case_id": direction, "pair_id": "p", "source_id": "s",
                             "split": "train", "direction": direction,
                             "frame_sha256s": frames})
            raw = e.canonical(rows)
            (root / "cohort.json").write_bytes(raw)
            with self.assertRaises(e.InputError):
                v.cohort(root, {"path": "cohort.json", "sha256": e.sha(raw)})


if __name__ == "__main__":
    unittest.main()
