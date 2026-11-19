"""Prospective C2 input provenance only: no historical job, execution, or adoption."""
import hashlib
import json
from pathlib import Path
from unittest import TestCase

from c2_program_freeze import REQUIRED_FILES, collect_manifest


CANDIDATE = Path(__file__).resolve().parent
ARCHIVE = CANDIDATE.parent / "evidence/p0p5-c2-launch-20261110/launch"
NAMES = (
    "POSTERIOR-POLICY.json",
    "OPTIMIZATION-POSTERIOR-POLICY-v2.json",
    "CONTRACT.json",
)
SHA256 = {
    NAMES[0]: "8be888e29389321a1e41921244931b7950aa2db63a0d870d55cc5e3fc412a137",
    NAMES[1]: "a1d5d5b8c11194506e9dea49e6b48eaa9c1edc72c6bc975d1e98bdc241b34875",
    NAMES[2]: "bc814b8913f5d5777f771030623bcd1f862a526f35144a8da0164e1da60f8e51",
}


class FrozenPolicyLineageTests(TestCase):
    def test_byte_identical_origin_and_fixed_digest(self):
        for name in NAMES:
            with self.subTest(file=name):
                archive = (ARCHIVE / name).read_bytes()
                candidate = (CANDIDATE / name).read_bytes()
                self.assertEqual(candidate, archive)
                self.assertEqual(hashlib.sha256(candidate).hexdigest(), SHA256[name])

    def test_cross_bound_policies_and_data(self):
        posterior, optimization, contract = (
            json.loads((CANDIDATE / name).read_bytes()) for name in NAMES
        )
        self.assertEqual(optimization["supplement_policy_sha256"], SHA256[NAMES[0]])
        self.assertEqual(contract["supplement_policy_sha256"], SHA256[NAMES[0]])
        self.assertEqual(contract["optimization_policy_sha256"], SHA256[NAMES[1]])
        self.assertEqual(
            len({posterior["data_manifest_sha256"],
                 optimization["data_manifest_sha256"],
                 contract["data_manifest_sha256"]}), 1,
        )

    def test_existing_hold_not_minted_into_authorization(self):
        for name in NAMES:
            with self.subTest(file=name):
                value = json.loads((CANDIDATE / name).read_bytes())
                self.assertIs(value["execution_authorized"], False)
                self.assertIs(value["confirmation_E_access"], False)
        contract = json.loads((CANDIDATE / NAMES[2]).read_bytes())
        self.assertEqual(contract["whole_training_numerical_admission"], "HOLD")

    def test_program_preflight_is_complete_but_still_unadopted(self):
        manifest = collect_manifest(CANDIDATE)
        self.assertEqual(set(manifest["files"]), set(REQUIRED_FILES))
        self.assertEqual(set(manifest["dependencies"]), {"recovery_v1/c2_durable.py"})
        self.assertEqual(manifest["scientific_admission"], "HOLD_NO_GO")
        self.assertIs(manifest["execution_authorized"], False)

    def test_preflight_does_not_publish_or_authorize(self):
        self.assertFalse((CANDIDATE / "PROGRAM-MANIFEST.json").exists())
        self.assertFalse((CANDIDATE / "EXECUTION-DECISION.json").exists())
