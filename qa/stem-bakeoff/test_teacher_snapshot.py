import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import teacher_snapshot
from teacher_snapshot import (TeacherSnapshotError, inventory, verify_snapshot)

REVISION = "d" * 40


def fixture(folder: pathlib.Path, *, model_type: str = "embedding_gemma2") -> None:
    (folder / "config.json").write_text(json.dumps({"model_type": model_type}), encoding="utf-8")
    (folder / "model.safetensors").write_bytes(b"fixture only, not trained model")
    (folder / "tokenizer.json").write_bytes(b"offline-fixture")


def checked(folder: pathlib.Path, *, candidate: str = "embeddinggemma2_740m",
            license_accepted: bool = True, pin: str | None = None):
    return verify_snapshot(
        folder, candidate=candidate, revision=REVISION,
        expected_inventory_sha256=pin or inventory(folder)["inventory_sha256"],
        operator_accepted_terms=license_accepted,
    )


class TeacherSnapshotTests(unittest.TestCase):
    def test_verified_local_bytes_never_claim_training_or_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            receipt = checked(folder)
            self.assertTrue(receipt["bytes_match_operator_pin"])
            self.assertEqual(receipt["candidate"], "embeddinggemma2_740m")
            self.assertEqual(receipt["authority"], "DENY_ALL")
            self.assertFalse(receipt["publisher_identity_independently_verified"])
            self.assertFalse(receipt["pretrained_capability_verified"])
            self.assertFalse(receipt["production_activation_allowed"])

    def test_teacher_can_use_t5_encoder_checkpoint_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder, model_type="t5gemma2")
            self.assertEqual(checked(folder, candidate="t5gemma2_encoder_270m")["mode"],
                             "SHADOW_ONLY")

    def test_detect_checkpoint_mutation_against_pinned_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            pin = inventory(folder)["inventory_sha256"]
            (folder / "model.safetensors").write_bytes(b"changed!")
            with self.assertRaisesRegex(TeacherSnapshotError, "does not match"):
                checked(folder, pin=pin)

    def test_reject_missing_operator_license_or_bad_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            for accepted, digest, revision in (
                (False, inventory(folder)["inventory_sha256"], REVISION),
                (True, "not-a-digest", REVISION),
                (True, inventory(folder)["inventory_sha256"], "branch-name"),
            ):
                with self.subTest(accepted=accepted, digest=digest, revision=revision):
                    with self.assertRaises(TeacherSnapshotError):
                        verify_snapshot(
                            folder, candidate="embeddinggemma2_740m",
                            revision=revision, expected_inventory_sha256=digest,
                            operator_accepted_terms=accepted,
                        )

    def test_reject_wrong_model_type_and_missing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder, model_type="other")
            with self.assertRaisesRegex(TeacherSnapshotError, "model_type"):
                checked(folder)
            (folder / "model.safetensors").unlink()
            with self.assertRaisesRegex(TeacherSnapshotError, "safetensors"):
                checked(folder)

    def test_reject_symlink_checkpoint_or_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            (folder / "linked.safetensors").symlink_to(folder / "model.safetensors")
            with self.assertRaisesRegex(TeacherSnapshotError, "regular files"):
                inventory(folder)
            (folder / "linked.safetensors").unlink()
            (folder / "outside_dir").symlink_to(folder, target_is_directory=True)
            with self.assertRaisesRegex(TeacherSnapshotError, "symlink directories"):
                inventory(folder)

    def test_reject_wrong_candidate_and_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            with self.assertRaisesRegex(TeacherSnapshotError, "unregistered"):
                checked(folder, candidate="unregistered")
            with self.assertRaisesRegex(TeacherSnapshotError, "config"):
                checked(folder)

    def test_hardlink_alias_is_not_a_checkpoint_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            alias = folder / "alias.safetensors"
            try:
                alias.hardlink_to(folder / "model.safetensors")
            except (OSError, NotImplementedError):
                self.skipTest("hardlinks unsupported on this test host")
            with self.assertRaisesRegex(TeacherSnapshotError, "hardlink aliases"):
                inventory(folder)

    def test_config_mutation_between_hash_and_parse_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            fixture(folder)
            pinned = inventory(folder)["inventory_sha256"]
            real_inventory = teacher_snapshot.inventory

            def modified_inventory(root):
                measured = real_inventory(root)
                (folder / "config.json").write_text(
                    json.dumps({"model_type": "t5gemma2"}), encoding="utf-8"
                )
                return measured

            with mock.patch.object(teacher_snapshot, "inventory", side_effect=modified_inventory):
                with self.assertRaisesRegex(TeacherSnapshotError, "changed after hashing"):
                    verify_snapshot(
                        folder, candidate="embeddinggemma2_740m", revision=REVISION,
                        expected_inventory_sha256=pinned,
                        operator_accepted_terms=True,
                    )



if __name__ == "__main__":
    unittest.main()
