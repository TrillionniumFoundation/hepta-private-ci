from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.hepta_supervisor_status import render
from scripts.hepta_supervisor_status import validate_history
from scripts.hepta_supervisor_status import validate_matrix


class SupervisorStatusTests(unittest.TestCase):
    def matrix(self) -> dict:
        return {
            "schema_version": 1,
            "module": "runtime.supervisor",
            "generated_status_path": "docs/modules/runtime.supervisor/CURRENT_STATUS.md",
            "status_semantics": {
                "source": ["implemented", "partial", "not_implemented"],
                "test_source": ["present", "partial", "absent"],
                "exact_head": ["pending", "passed", "failed", "not_applicable"],
                "merge_candidate": ["pending", "passed", "failed", "not_applicable"],
                "target_host": [
                    "not_run",
                    "pending",
                    "passed",
                    "failed",
                    "not_applicable",
                ],
                "independent_acceptance": [
                    "not_obtained",
                    "pending",
                    "accepted",
                    "rejected",
                    "not_applicable",
                ],
            },
            "current": {
                "source": "partial",
                "test_source": "present",
                "exact_head": "pending",
                "merge_candidate": "pending",
                "target_host": "not_run",
                "independent_acceptance": "not_obtained",
                "activated": False,
                "release": False,
                "claim": "candidate",
            },
            "capabilities": [
                {
                    "id": "one",
                    "summary": "one",
                    "source": "implemented",
                    "test_source": "present",
                    "exact_head": "pending",
                    "merge_candidate": "pending",
                    "target_host": "not_run",
                    "independent_acceptance": "not_obtained",
                    "activated": False,
                    "source_paths": ["source.txt"],
                }
            ],
        }

    def test_render_keeps_every_evidence_dimension_distinct(self):
        text = render(self.matrix())
        for heading in (
            "Source",
            "Test source",
            "Exact head",
            "Merge candidate",
            "Target host",
            "Independent acceptance",
            "Activated",
        ):
            self.assertIn(heading, text)
        self.assertNotIn("`passed`", text)

    def test_matrix_rejects_self_asserted_external_or_activation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("source")
            for field, value in (
                ("target_host", "passed"),
                ("independent_acceptance", "accepted"),
                ("activated", True),
                ("release", True),
            ):
                data = copy.deepcopy(self.matrix())
                data["current"][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate_matrix(root, data)

    def test_unimplemented_capability_cannot_claim_candidate_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("source")
            data = self.matrix()
            data["capabilities"][0]["source"] = "not_implemented"
            data["capabilities"][0]["test_source"] = "absent"
            with self.assertRaises(ValueError):
                validate_matrix(root, data)

    def test_history_inventory_is_closed_world(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs/modules/runtime.supervisor"
            docs.mkdir(parents=True)
            (docs / "ONE_REPAIR_20260930.md").write_text("history")
            (docs / "TECHNICAL.md").write_text("current")
            history = {
                "schema_version": 1,
                "module": "runtime.supervisor",
                "documents": [
                    {
                        "path": "ONE_REPAIR_20260930.md",
                        "status": "historical",
                        "normative": False,
                        "superseded_by": ["TECHNICAL.md"],
                    }
                ],
            }
            validate_history(root, history)
            (docs / "TWO_REPAIR_20260930.md").write_text("unclassified")
            with self.assertRaises(ValueError):
                validate_history(root, history)


if __name__ == "__main__":
    unittest.main()
