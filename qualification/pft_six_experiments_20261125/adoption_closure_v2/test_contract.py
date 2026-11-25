"""New adapter controls; synthetic bytes count zero human participants."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import intake_contract as intake
import native_adapter


def fixture(root):
    objects = {}
    for role in intake.ROLES:
        raw = ("explicit engineering object: " + role).encode()
        digest = intake.sha(raw)
        path = root / digest
        path.write_bytes(raw)
        path.chmod(0o600)
        objects[role] = {"sha256": digest, "bytes": len(raw)}
    return {
        "schema": intake.SCHEMA, "scope": "engineering_fixture",
        "pins": {k: intake.sha(("engineering pin: " + k).encode()) for k in intake.HASH_FIELDS},
        "objects": objects,
        "enrollment": {k: intake.sha(("fictional " + k).encode())
                       for k in ("authority", "person_a", "person_b")},
        "sequence": dict(zip(("a_success", "a_authorization", "freeze", "b_first_arrival",
                               "b_evaluation", "first_use", "second_use"), range(1, 8))),
    }


class PrivateIntakeControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.manifest = fixture(self.root)

    def test_original_owner_refuses_before_missing_private_root(self):
        self.manifest["scope"] = "protected_original_owner"
        with self.assertRaisesRegex(intake.Refused, intake.BLOCKER):
            intake.verify_private_objects(self.manifest, self.root / "must-not-open")
        with self.assertRaisesRegex(intake.Refused, intake.BLOCKER):
            native_adapter.authorize_owner(self.manifest, override=True, fixture=True)

    def test_engineering_bytes_never_authorize_people(self):
        result = intake.verify_private_objects(self.manifest, self.root)
        self.assertEqual(result["objects_verified"], 10)
        self.assertEqual(result["human_participants"], 0)
        self.assertFalse(result["production_authorization_available"])
        self.assertFalse(result["distinct_people_authenticated"])
        self.assertEqual((result["training_updates"], result["model_calls"]), (0, 0))
        public = json.dumps(result)
        for private in list(self.manifest["enrollment"].values()) + [
            item["sha256"] for item in self.manifest["objects"].values()
        ]:
            self.assertNotIn(private, public)

    def test_accounts_cannot_make_one_person_two_people(self):
        self.manifest["enrollment"]["person_b"] = self.manifest["enrollment"]["person_a"]
        with self.assertRaisesRegex(intake.Refused, "one person"):
            intake.validate(self.manifest)

    def test_reissued_future_and_duplicate_second_use_refused(self):
        for old, new in (("a_success", "b_future"), ("b_use_first", "b_use_again")):
            changed = copy.deepcopy(self.manifest)
            changed["objects"][new] = changed["objects"][old]
            with self.assertRaisesRegex(intake.Refused, "repeated"):
                intake.validate(changed)

    def test_old_arrival_cannot_become_prospective(self):
        self.manifest["sequence"]["b_first_arrival"] = self.manifest["sequence"]["freeze"]
        with self.assertRaisesRegex(intake.Refused, "chronology"):
            intake.validate(self.manifest)

    def test_authority_flag_and_extra_fields_not_accepted(self):
        self.manifest["production_authorization_available"] = True
        with self.assertRaisesRegex(intake.Refused, "closed intake"):
            intake.validate(self.manifest)

    def test_future_arrives_after_freeze_without_rewriting_originals(self):
        frozen = copy.deepcopy(self.manifest)
        frozen["objects"] = {k: v for k, v in frozen["objects"].items() if k in intake.BASE_ROLES}
        frozen["sequence"] = {k: v for k, v in frozen["sequence"].items() if k in intake.SEQUENCES[:3]}
        frozen["enrollment"]["person_b"] = None
        frozen["pins"]["loop"] = None
        self.assertEqual(intake.metadata_result(frozen)["intake_stage"], "frozen_waiting_b")
        arrived = copy.deepcopy(self.manifest)
        arrived["objects"] = {k: v for k, v in arrived["objects"].items() if k in intake.ROLE_GROUPS[1]}
        arrived["sequence"] = {k: v for k, v in arrived["sequence"].items() if k in intake.SEQUENCES[:5]}
        self.assertTrue(intake.advance(frozen, arrived)["immutable_prefix_checked"])
        changed = copy.deepcopy(arrived)
        changed["pins"]["candidate"] = intake.sha(b"changed after seeing B")
        with self.assertRaisesRegex(intake.Refused, "cannot change"):
            intake.advance(frozen, changed)
        changed = copy.deepcopy(arrived)
        changed["objects"]["keep"] = changed["objects"]["b_enrollment"]
        with self.assertRaisesRegex(intake.Refused, "prefix changed"):
            intake.advance(frozen, changed)
        with self.assertRaisesRegex(intake.Refused, "one forward"):
            intake.advance(frozen, self.manifest)

    def test_reissued_enrollment_and_consent_refused(self):
        for left, right in (("a_enrollment", "b_enrollment"), ("a_train_consent", "b_evaluate_consent")):
            changed = copy.deepcopy(self.manifest)
            changed["objects"][right] = changed["objects"][left]
            with self.assertRaisesRegex(intake.Refused, "reissued authority"):
                intake.validate(changed)

    def test_tampered_original_retains_failure(self):
        obj = self.manifest["objects"]["a_success"]
        path = self.root / obj["sha256"]
        raw = path.read_bytes()
        path.write_bytes(b"X" + raw[1:])
        with self.assertRaisesRegex(intake.Refused, "content changed"):
            intake.verify_private_objects(self.manifest, self.root)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "Linux private intake profile")
    def test_symlink_and_hardlink_originals_refused(self):
        obj = self.manifest["objects"]["a_failure"]
        path = self.root / obj["sha256"]
        original = self.root / "unlinked-original"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises(OSError):
            intake.verify_private_objects(self.manifest, self.root)
        path.unlink()
        os.link(original, path)
        with self.assertRaisesRegex(intake.Refused, "regular object"):
            intake.verify_private_objects(self.manifest, self.root)

    def test_duplicate_json_and_nonfinite_refused(self):
        for raw in (b'{"scope":1,"scope":2}', b'{"value":NaN}'):
            with self.assertRaises(intake.Refused):
                intake.parse(raw)

    def test_optimized_python_cannot_drop_authorization_guard(self):
        code = "import native_adapter; native_adapter.authorize_owner()"
        run = subprocess.run([sys.executable, "-O", "-c", code], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=10)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(intake.BLOCKER, run.stderr)
        self.assertEqual(run.stdout, "")


if __name__ == "__main__":
    unittest.main()
