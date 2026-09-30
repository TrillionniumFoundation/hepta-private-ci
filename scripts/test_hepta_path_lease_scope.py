"""Repository metadata reports overlap; it never manufactures reviewer authority."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "path_lease_docs", ROOT / "scripts/hepta-docs.py"
)
DOCS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DOCS)


class PathLeaseScopeTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(
            (ROOT / "docs/delivery/PATH_OWNERSHIP.json").read_text()
        )
        self.packages = json.loads(
            (ROOT / "docs/delivery/WORK_PACKAGES.json").read_text()
        )["packages"]
        self.graphs = []
        for name in ("DEVELOPMENT_DAG.json", "ACTIVATION_DAG.json"):
            graph = json.loads((ROOT / "docs/delivery" / name).read_text())
            self.graphs.append(DOCS.reach(graph["nodes"], graph["edges"]))
        self.path = self.registry["activeLeases"][0]["normalizedExactPaths"][0]

    def validate(self, **options):
        return DOCS.validate_path_leases(
            self.registry, self.packages, *self.graphs, {self.path}, **options
        )

    def test_ordinary_changed_lease_is_visible_without_self_attestation(self):
        result = self.validate()
        self.assertEqual(result["touchedLeaseCount"], 1)
        self.assertEqual(result["externallyAttestedLeaseCount"], 0)
        self.assertIs(self.registry["activeLeases"][0]["authorityGranted"], False)

    def test_explicit_activation_gate_still_requires_external_attestation(self):
        with self.assertRaisesRegex(
            SystemExit, "external path lease attestation required"
        ):
            self.validate(require_attestation=True)

    def test_lease_key_order_does_not_change_review_policy(self):
        lease = self.registry["activeLeases"][0]
        lease["reviewBinding"] = dict(reversed(list(lease["reviewBinding"].items())))
        self.registry["activeLeases"][0] = dict(reversed(list(lease.items())))
        self.assertEqual(self.validate()["externallyAttestedLeaseCount"], 0)

    def test_no_mode_accepts_forged_owner_review_or_authority(self):
        baseline = copy.deepcopy(self.registry)
        for field, value in [
            ("reviewerMustDifferFromAuthor", False),
            ("invalidateOnHeadChange", 1),
            ("reusable", 0),
        ]:
            for strict in (False, True):
                with self.subTest(field=field, strict=strict):
                    self.registry = copy.deepcopy(baseline)
                    self.registry["activeLeases"][0]["reviewBinding"][field] = value
                    with self.assertRaisesRegex(SystemExit, "external review policy"):
                        self.validate(require_attestation=strict)
        for strict in (False, True):
            self.registry = copy.deepcopy(baseline)
            self.registry["activeLeases"][0]["authorityGranted"] = True
            with self.assertRaisesRegex(SystemExit, "authority posture"):
                self.validate(require_attestation=strict)
            self.registry = copy.deepcopy(baseline)
            self.registry["activeLeases"][0]["packageA"] = "UNREGISTERED-OWNER"
            with self.assertRaisesRegex(SystemExit, "canonical package pair"):
                self.validate(require_attestation=strict)


if __name__ == "__main__":
    unittest.main()
