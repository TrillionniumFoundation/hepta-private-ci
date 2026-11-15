"""Checkpoint replay identity and pre-execution boundary regressions."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .replay import compare_original, replay


class ReplayTests(unittest.TestCase):
    def fixture(self):
        trace = {"actions": ["refine_image"], "initial_content_plan": ["refine_text"],
                 "decisions": [{"action": "refine_image", "value": .125, "complete": True}],
                 "calls": {"forecast": 2}, "final_state_sha256": "a" * 64,
                 "cost": {"modeled_work": 9.25, "search_units": 1.25,
                          "execution_units": 3, "wall_ns": 200}}
        metrics, hashes = {"utility": .25}, {"text": "b" * 64, "image": "c" * 64}
        old = {**deepcopy(trace), "metrics": metrics, "output_hashes": hashes}
        old["cost"]["wall_ns"] = 500
        return old, trace, metrics, hashes

    def test_only_physical_timings_may_change(self):
        old, trace, metrics, hashes = self.fixture()
        compare_original(old, trace, metrics, hashes)
        for name, value in (("actions", []), ("initial_content_plan", []),
                            ("decisions", [{"action": "refine_image", "value": .1250000001, "complete": True}]),
                            ("calls", {"forecast": 1}), ("final_state_sha256", "d" * 64)):
            with self.subTest(name=name):
                changed = deepcopy(trace)
                changed[name] = value
                with self.assertRaisesRegex(ValueError, "Replay changed"):
                    compare_original(old, changed, metrics, hashes)
        for name in ("modeled_work", "search_units", "execution_units"):
            with self.subTest(name=name):
                changed = deepcopy(trace)
                changed["cost"][name] += .001
                with self.assertRaisesRegex(ValueError, "Replay changed"):
                    compare_original(old, changed, metrics, hashes)
        for new_metrics, new_hashes in (({"utility": .250000001}, hashes),
                                        (metrics, {**hashes, "image": "d" * 64})):
            with self.assertRaisesRegex(ValueError, "emitted bytes"):
                compare_original(old, trace, new_metrics, new_hashes)

    def test_incomplete_original_fails_before_data_or_checkpoint_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            original.mkdir()
            raw_status = '{"state":"running"}\n'
            (original / "status.json").write_text(raw_status)
            with self.assertRaisesRegex(ValueError, "completed original"):
                replay(original, root / "missing-cache", root / "replay", root / "missing-binary")
            status = json.loads((root / "replay/status.json").read_text())
            self.assertEqual((status["state"], status["rows"]), ("failed", 0))
            self.assertEqual((original / "status.json").read_text(), raw_status)
            self.assertEqual(set(path.name for path in original.iterdir()), {"status.json"})

    def test_original_tree_is_never_an_output_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            original.mkdir()
            for output in (original, original / "child", root):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, "separate"):
                    replay(original, root / "cache", output, root / "native")
            for cache in (original, original / "cache"):
                with self.subTest(cache=cache), self.assertRaisesRegex(ValueError, "cache must be outside"):
                    replay(original, cache, root / "replay", root / "native")
            self.assertEqual(list(original.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
