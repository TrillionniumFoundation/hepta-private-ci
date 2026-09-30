#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_eval_compat_fixture",
    Path(__file__).with_name("hepta-learning-eval-compat-fixture.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TrustedFixtureTests(unittest.TestCase):
    def test_materialized_manifest_has_no_template_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, test = MODULE.materialize(Path(directory))
            text = manifest.read_text()
            self.assertNotIn("@EVAL_PATH@", text)
            self.assertIn('features = ["trusted-inprocess-eval"]', text)
            self.assertIn("op_03_high_fit_without_retention_is_insufficient", test.read_text())

    def test_check_only_never_starts_cargo(self):
        with mock.patch.object(MODULE, "scan_manifests", return_value=[]), \
                mock.patch.object(MODULE.subprocess, "run") as run:
            self.assertEqual(MODULE.main(["--check-only"]), 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
