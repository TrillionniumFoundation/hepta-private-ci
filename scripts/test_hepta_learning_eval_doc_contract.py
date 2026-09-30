#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_doc_contract",
    Path(__file__).with_name("hepta-learning-eval-doc-contract.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DocumentationContractTests(unittest.TestCase):
    def test_bare_verified_is_rejected_at_any_depth(self):
        with self.assertRaises(ValueError):
            MODULE.reject_bare_verified({"nested": {"verified": True}})

    def test_scoped_verified_name_is_allowed(self):
        MODULE.reject_bare_verified({"sourceInventoryVerified": True})

    def test_external_claims_must_remain_false(self):
        MODULE.require_external_false(
            {"claims": {"targetHostQualified": False, "releaseAuthorized": False}},
            "fixture",
        )
        with self.assertRaises(ValueError):
            MODULE.require_external_false(
                {"claims": {"independentAcceptanceIssued": True}}, "fixture"
            )


if __name__ == "__main__":
    unittest.main()
