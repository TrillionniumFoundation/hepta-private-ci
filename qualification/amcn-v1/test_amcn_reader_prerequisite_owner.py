"""Existing dual-signed Reader owner integration, never a real human review.

Only the real Hepta repository has the owner fixture. Keys are ephemeral and
produced exclusively inside the test process; no keys or signed receipts are
published, nor does passing this fixture qualify Reader performance.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest

from amcn_reader_prerequisite import reader_prerequisite
from amcn_core import digest


class RealOwnerReaderGateIntegration(unittest.TestCase):
    def test_existing_dual_signed_owner_cannot_promote(self):
        repo_root = Path(__file__).resolve().parents[2]
        owner_dir = repo_root / "scripts" / "memory_cell"
        if not (owner_dir / "test_full_cell_matrix.py").is_file():
            self.skipTest("full repository Reader owner unavailable in isolated source copy")
        sys.path.insert(0, str(owner_dir))
        reference = importlib.import_module("test_full_cell_matrix")
        receipt, trust, roster = reference.gate_fixture()
        actual = reader_prerequisite(
            gate_receipt=receipt, trust_manifest=trust, reviewer_roster=roster,
            externally_pinned_trust_sha256=reference.fingerprint(trust),
            externally_pinned_roster_sha256=reference.fingerprint(roster),
            expected_model_binding_sha256=digest(receipt["model_binding"]),
            original_answers_sha256="a" * 64,
            original_judgments_sha256="b" * 64,
        )
        self.assertEqual(actual["metrics"]["disposition"],
                         "reader_adequate_with_retrieval_headroom_research_only")
        self.assertFalse(actual["production_accepted"])
        self.assertFalse(actual["metrics"]["may_scale_cell_population"])
        self.assertFalse(actual["metrics"]["reviewer_real_world_identity_proven_by_this_module"])
        unpinned = reader_prerequisite(
            gate_receipt=receipt, trust_manifest=trust, reviewer_roster=roster,
            expected_model_binding_sha256=digest(receipt["model_binding"]),
            original_answers_sha256="a" * 64,
            original_judgments_sha256="b" * 64,
        )
        self.assertEqual(unpinned["metrics"]["disposition"], "blocked_reader_adequacy")


if __name__ == "__main__":
    unittest.main()
