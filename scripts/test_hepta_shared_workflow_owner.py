"""Shared qualification belongs to one integration package, not parallel leases."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "hepta_workflow_owner", ROOT / "scripts/hepta-docs.py"
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)
SHARED = ".github/workflows/hepta-lane-b-truth.yml"


class SharedWorkflowOwnerTests(unittest.TestCase):
    def setUp(self):
        self.packages = json.loads(
            (ROOT / "docs/delivery/WORK_PACKAGES.json").read_text()
        )["packages"]
        self.paths = json.loads(
            (ROOT / "docs/delivery/PATH_OWNERSHIP.json").read_text()
        )
        self.graphs = []
        for filename in ("DEVELOPMENT_DAG.json", "ACTIVATION_DAG.json"):
            dag = json.loads((ROOT / "docs/delivery" / filename).read_text())
            self.graphs.append(DOCS.reach(dag["nodes"], dag["edges"]))

    def test_one_integrating_writer_with_both_domain_coowners(self):
        writers = [p for p in self.packages if SHARED in p["allowedWritePaths"]]
        self.assertEqual([p["id"] for p in writers], ["P0.8D-VERTICAL-SLICE"])
        self.assertTrue(
            {"automation.taskflow", "channel.matrix"}
            <= set(writers[0]["coOwnerModules"])
        )
        self.assertEqual(writers[0]["authorityDelta"], "none")

    def test_actual_shared_workflow_change_requires_no_imaginary_attestation(self):
        result = DOCS.validate_path_leases(
            self.paths, self.packages, *self.graphs, {SHARED}
        )
        self.assertEqual(result["touchedLeaseCount"], 0)
        self.assertEqual(result["externallyAttestedLeaseCount"], 0)

    def test_restoring_parallel_module_ownership_is_rejected(self):
        packages = copy.deepcopy(self.packages)
        for package in packages:
            if package["id"] in {
                "MATRIX-1-CHANNEL-BOUNDARY",
                "TASKFLOW-1-EXECUTION-BOUNDARY",
            }:
                package["allowedWritePaths"].append(SHARED)
        with self.assertRaisesRegex(SystemExit, "missing or unused path lease"):
            DOCS.validate_path_leases(self.paths, packages, *self.graphs, {SHARED})

    def test_other_lease_rejections_remain_in_force(self):
        # Includes exact-head review, authority, prefix alias and partial lease
        # rejection fixtures. No production verifier gate was weakened.
        self.assertEqual(DOCS.self_test(), 0)


if __name__ == "__main__":
    unittest.main()
