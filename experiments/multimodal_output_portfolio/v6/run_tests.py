"""Failure custody and single-use experiment directory regressions."""

import json
import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from .data import SourceCorpus, SourceSplit
from .run import registered_cases, run, source_identity


class RunCustodyTests(unittest.TestCase):
    def test_preparation_failure_is_preserved_without_changing_cwd(self):
        config = {"training": {"threads": 1}, "observer_sources": 100,
                  "hard_output_modalities": ["text", "image"]}
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed-run"
            with patch("experiments.multimodal_output_portfolio.v6.run.load_corpus",
                       side_effect=OSError("injected unavailable dataset")):
                with self.assertRaisesRegex(OSError, "unavailable dataset"):
                    run(config, Path(directory) / "cache", output)
            status = json.loads((output / "status.json").read_text())
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["rows"], 0)
            self.assertIn("unavailable dataset", status["traceback"])
            self.assertEqual(json.loads((output / "requested-config.json").read_text()), config)
            self.assertEqual(Path.cwd(), previous)
            original = (output / "status.json").read_bytes()
            with self.assertRaises(FileExistsError):
                run(config, Path(directory) / "cache", output)
            self.assertEqual((output / "status.json").read_bytes(), original)

    def test_native_dependencies_are_bound_into_source_identity(self):
        files = source_identity()["files"]
        self.assertIn("codex-rs/hepta-ndu/src/lib.rs", files)
        self.assertIn("codex-rs/Cargo.lock", files)
        self.assertIn("codex-rs/rust-toolchain.toml", files)
        self.assertIn("experiments/multimodal_output_portfolio/v6/protocol.json", files)
        self.assertTrue(all(len(value) == 64 for value in files.values()))


class HeldoutRegistrationTests(unittest.TestCase):
    def setUp(self):
        # Synthetic data tests source custody only, never generation quality.
        splits = {}
        for name, first in (("test", 0), ("retention", 20)):
            values = torch.arange(first, first + 20, dtype=torch.uint8)
            pixels = values.reshape(20, 1, 1, 1).expand(-1, 1, 28, 28).clone()
            hashes = tuple(hashlib.sha256(bytes([int(i)]) * 784).hexdigest() for i in values)
            identities = tuple(f"fixture:{name}:{i}:{value}" for i, value in enumerate(hashes))
            splits[name] = SourceSplit(pixels, values.long() % 10, identities, hashes)
        self.corpus = SourceCorpus(splits, {"fixture_only": True})
        self.config = {"future_cases": 3, "retention_cases": 2,
                       "corruptions": ["clean", "wrong_hint", "missing_no_hint"]}

    def test_new_registration_excludes_previous_source_pixels(self):
        old = registered_cases(self.corpus, self.config)
        exclusion = sorted({source.rsplit(":", 1)[-1] for cases in old.values()
                            for case in cases for source in case["source_ids"]})
        new_config = {**self.config, "evaluation_case_offsets": {"future": 3, "retention": 2},
                      "prior_heldout_exclusion": {"protocol_sha256": "1" * 64,
                                                 "source_pixel_sha256": exclusion}}
        new = registered_cases(self.corpus, new_config)
        new_pixels = {source.rsplit(":", 1)[-1] for cases in new.values()
                      for case in cases for source in case["source_ids"]}
        self.assertTrue(new_pixels.isdisjoint(exclusion))
        self.assertEqual([case["index"] for case in new["future"]], [3, 4, 5])
        self.assertEqual([case["corruption"] for case in new["future"]], self.config["corruptions"])
        with self.assertRaisesRegex(ValueError, "reuses a source"):
            registered_cases(self.corpus, {**new_config, "evaluation_case_offsets":
                                          {"future": 2, "retention": 2}})

    def test_aliasing_pixel_identity_cannot_evade_the_exclusion(self):
        old = registered_cases(self.corpus, self.config)
        excluded = old["future"][0]["source_ids"][0].rsplit(":", 1)[-1]
        source = self.corpus.splits["test"]
        self.corpus.splits["test"] = replace(
            source, ids=tuple(f"renamed:{value}" for value in source.pixel_hashes))
        with self.assertRaisesRegex(ValueError, "reuses a source"):
            registered_cases(self.corpus, {**self.config, "prior_heldout_exclusion":
                                          {"protocol_sha256": "a" * 64,
                                           "source_pixel_sha256": [excluded]}})

    def test_invalid_offsets_and_out_of_range_cohorts_fail_before_training(self):
        for offsets in ({"future": -1, "retention": 0},
                        {"future": True, "retention": 0}, {"future": 0}):
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                registered_cases(self.corpus, {**self.config, "evaluation_case_offsets": offsets})
        with self.assertRaisesRegex(ValueError, "range exceeds"):
            registered_cases(self.corpus, {**self.config, "evaluation_case_offsets":
                                          {"future": 9, "retention": 0}})


if __name__ == "__main__":
    unittest.main()
