#!/usr/bin/env python3
"""Regression tests for exact-candidate implementation-map evidence."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from platform_types_implementation_map import (  # noqa: E402
    ImplementationMapError,
    expected_map,
    verify_repository,
)

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class ExactImplementationMapBindingTests(unittest.TestCase):
    def test_generated_map_binds_exact_checkout_and_source_documents(self) -> None:
        value = verify_repository(git("rev-parse", "HEAD"))
        binding = value["candidateBinding"]
        self.assertEqual(binding["policy"], "runtime_exact_git_candidate_v1")
        self.assertEqual(binding["commit"], git("rev-parse", "HEAD"))
        self.assertEqual(binding["tree"], git("rev-parse", "HEAD^{tree}"))
        self.assertRegex(binding["commit"], SHA_RE)
        self.assertRegex(binding["tree"], SHA_RE)
        self.assertRegex(binding["publicApiInventorySha256"], DIGEST_RE)
        self.assertRegex(binding["detailedImplementationMapSha256"], DIGEST_RE)

    def test_wrong_expected_commit_fails_closed(self) -> None:
        wrong = "0" * 40
        if wrong == git("rev-parse", "HEAD"):
            wrong = "1" * 40
        with self.assertRaises(ImplementationMapError):
            expected_map(wrong)


if __name__ == "__main__":
    unittest.main()
