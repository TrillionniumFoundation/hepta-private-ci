"""Dependency-free load ordering tests; no actual CUDA memory assertion."""

import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import onpolicy_train as training


class LoadCacheTests(unittest.TestCase):
    def exercise(self, available, cache_error=None):
        events = []
        manifest = {"runtime": {"device": "cuda:0", "min_cuda_free_bytes": 4294967296}}
        original = copy.deepcopy(manifest)
        expected = object()

        def availability():
            events.append("cuda_available")
            return available

        def empty():
            events.append("empty_unused_process_cache")
            if cache_error:
                raise cache_error

        def load(given, root):
            events.append("unchanged_predictor_admission")
            self.assertEqual(given, original)
            self.assertEqual(root, "/fixture-root")
            return expected

        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=availability, empty_cache=empty)
        )
        with (
            patch.object(
                training.gc, "collect", side_effect=lambda: events.append("collect")
            ),
            patch.object(training.probe, "_libraries", return_value=(torch, None)),
            patch.object(training, "Predictor", side_effect=load) as constructor,
        ):
            if cache_error:
                with self.assertRaises(RuntimeError) as caught:
                    training.load_predictor(manifest, "/fixture-root")
                self.assertIs(caught.exception, cache_error)
                constructor.assert_not_called()
            else:
                self.assertIs(
                    training.load_predictor(manifest, "/fixture-root"), expected
                )
                constructor.assert_called_once()
        self.assertEqual(manifest, original)
        return events

    def test_unused_process_cache_is_released_before_predictor_admission(self):
        self.assertEqual(
            self.exercise(True),
            [
                "collect",
                "cuda_available",
                "empty_unused_process_cache",
                "unchanged_predictor_admission",
            ],
        )

    def test_cpu_availability_branch_skips_cuda_empty_but_keeps_admission(self):
        self.assertEqual(
            self.exercise(False),
            ["collect", "cuda_available", "unchanged_predictor_admission"],
        )

    def test_cleanup_failure_cannot_bypass_admission_or_start_loading(self):
        self.assertEqual(
            self.exercise(True, RuntimeError("cache cleanup failed")),
            ["collect", "cuda_available", "empty_unused_process_cache"],
        )


if __name__ == "__main__":
    unittest.main()
