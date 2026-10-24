"""Failure custody and single-use experiment directory regressions."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .run import run, source_identity


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


if __name__ == "__main__":
    unittest.main()
