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

    def test_public_modules_have_operation_owners(self) -> None:
        value = expected_map(git("rev-parse", "HEAD"))
        self.assertEqual(
            value["coveragePolicy"],
            "closed_world_exact_pub_use_and_pub_mod_exports",
        )
        by_operation = {
            row["operation"]: row
            for row in value["operations"]
        }
        expected = {
            "registered_numeric_conversion_v2": (
                "numeric_registry_v2",
                "codex-rs/hepta-types/src/numeric_registry_v2.rs",
            ),
            "prompt_delivery_observation_v2": (
                "prompt_delivery_v2",
                "codex-rs/hepta-types/src/prompt_delivery_v2.rs",
            ),
            "protocol_catalog_v2": (
                "protocol_catalog_v2",
                "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
            ),
        }
        for operation, (symbol, source_path) in expected.items():
            row = by_operation[operation]
            self.assertEqual(row["sourcePaths"], [source_path])
            self.assertEqual(row["exportCount"], 1)
            self.assertEqual(row["exports"][0]["symbol"], symbol)
            self.assertEqual(row["exports"][0]["sourcePath"], source_path)

    def test_wrong_expected_commit_fails_closed(self) -> None:
        wrong = "0" * 40
        if wrong == git("rev-parse", "HEAD"):
            wrong = "1" * 40
        with self.assertRaises(ImplementationMapError):
            expected_map(wrong)


if __name__ == "__main__":
    unittest.main()
