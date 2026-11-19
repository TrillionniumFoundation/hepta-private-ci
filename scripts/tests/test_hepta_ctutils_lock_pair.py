"""Regression: Cargo and generated Bazel lock must agree on a fixed ctutils release.

The full cargo-deny and platform builds remain mandatory; this test only detects
accidental rollback or desynchronization of this one security repair.
"""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MINIMUM_SAFE = (0, 4, 4)


class CtutilsLockPairTests(unittest.TestCase):
    def test_pinned_cargo_and_bazel_ctutils_match(self):
        cargo = tomllib.loads((ROOT / "codex-rs" / "Cargo.lock").read_text())
        packages = [pkg for pkg in cargo["package"] if pkg["name"] == "ctutils"]
        self.assertEqual(len(packages), 1)
        version = packages[0]["version"]
        parts = tuple(int(part) for part in version.split("."))
        self.assertGreaterEqual(parts, MINIMUM_SAFE)
        self.assertEqual(
            packages[0]["source"],
            "registry+https://github.com/rust-lang/crates.io-index",
        )
        self.assertEqual(len(packages[0]["checksum"]), 64)
        bazel = (ROOT / "MODULE.bazel.lock").read_text()
        json.loads(bazel)
        self.assertIn(f'"ctutils_{version}":', bazel)
        self.assertNotIn('"ctutils_0.4.3":', bazel)


if __name__ == "__main__":
    unittest.main()
