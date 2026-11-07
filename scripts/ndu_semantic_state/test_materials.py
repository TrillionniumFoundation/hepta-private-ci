"""Synthetic integrity fixtures; they can never qualify natural-task efficacy."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from ndu_semantic_state.materials import (
    MODEL_ROLES, REGISTRY_SCHEMA, SCHEMA, TASK_FAMILIES, load_public_case, validate_materials,
)


class MaterialAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cases, sources = [], []
        for index, (split, family) in enumerate(
                [(split, family) for split in ("train", "development") for family in TASK_FAMILIES]
                + [("retention", TASK_FAMILIES[0])]):
            text = self.write(f"source-{index}.txt", f"Contract fixture only {index}: 中文🙂\npublic input".encode())
            image_path = self.root / f"source-{index}.png"
            Image.new("RGB", (3, 2), (index * 19, 7, 11)).save(image_path)
            image = self.binding(image_path.name)
            evidence = self.write(f"source-{index}-evidence.json", json.dumps({"fixture": True, "source": index}).encode())
            reference = self.write(f"source-{index}-private.txt", f"PRIVATE EXPECTED ANSWER {index}, NEVER PUBLIC INPUT".encode())
            self.cases.append({"id": f"case-{index}", "source_id": f"source-{index}", "source_family": f"family-{split}",
                "split": split, "task_family": family, "text": text, "image": image,
                "reference": reference, "source_evidence": evidence})
            sources.append({"source_id": f"source-{index}", "source_family": f"family-{split}", "allowed_split": split,
                "text_sha256s": [text["sha256"]], "image_sha256s": [image["sha256"]],
                "source_evidence_sha256": evidence["sha256"], "used_in_training": split in {"train", "retention"},
                "previously_observed": True, "case_bindings": [{"case_id": f"case-{index}", "task_family": family,
                    "text_sha256": text["sha256"], "image_sha256": image["sha256"],
                    "reference_sha256": reference["sha256"]}]})
        weights = self.write("not-a-real-model.weights", b"synthetic contract fixture bytes; not a runnable model")
        config = self.write("not-a-real-model-config.json", b'{"fixture":true}')
        executable = self.write("not-a-real-model.py", b"raise RuntimeError('contract fixture is not a real model')\n")
        models = [{"id": f"fixture-{role}", "role": role, "architecture": "SYNTHETIC_TEST_ONLY",
            "weights": [weights], "config": config, "executable": executable, "parameter_count": 1} for role in MODEL_ROLES]
        self.registry = {"schema": REGISTRY_SCHEMA, "sources": sources}
        self.manifest = {"schema": SCHEMA, "experiment_id": "contract-test-no-scientific-evidence",
            "registry_sha256": "", "cases": self.cases, "models": models}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def binding(self, relative):
        data = (self.root / relative).read_bytes()
        return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def write(self, relative, data):
        (self.root / relative).write_bytes(data)
        return self.binding(relative)

    def save(self):
        self.write("registry.json", json.dumps(self.registry, sort_keys=True).encode())
        self.pin = self.binding("registry.json")["sha256"]
        self.manifest["registry_sha256"] = self.pin
        self.write("manifest.json", json.dumps(self.manifest, sort_keys=True).encode())

    def validate(self, **kwargs):
        return validate_materials(self.root, "manifest.json", "registry.json", expected_registry_sha256=self.pin, **kwargs)

    def add_confirmation_cases(self):
        for index, family in enumerate(TASK_FAMILIES):
            text = self.write(f"confirmation-{index}.txt", f"New unconsumed contract fixture {index}".encode())
            image_path = self.root / f"confirmation-{index}.png"
            Image.new("RGB", (3, 2), (17, 40 + index, 91)).save(image_path)
            image = self.binding(image_path.name)
            evidence = self.write(f"confirmation-{index}-evidence.json", json.dumps({"fixture": True, "confirmation": index}).encode())
            reference = self.write(f"confirmation-{index}-private.txt", f"PRIVATE CONFIRMATION REFERENCE {index}".encode())
            source_id, case_id = f"confirmation-source-{index}", f"confirmation-case-{index}"
            self.cases.append({"id": case_id, "source_id": source_id, "source_family": "confirmation-fixture-family",
                "split": "confirmation", "task_family": family, "text": text, "image": image,
                "reference": reference, "source_evidence": evidence})
            self.registry["sources"].append({"source_id": source_id, "source_family": "confirmation-fixture-family",
                "allowed_split": "confirmation", "text_sha256s": [text["sha256"]], "image_sha256s": [image["sha256"]],
                "source_evidence_sha256": evidence["sha256"], "used_in_training": False, "previously_observed": False,
                "case_bindings": [{"case_id": case_id, "task_family": family, "text_sha256": text["sha256"],
                                   "image_sha256": image["sha256"], "reference_sha256": reference["sha256"]}]})
        self.save()

    def test_decodable_fixtures_verify_bytes_but_never_semantics_or_model_execution(self):
        report = self.validate()
        self.assertEqual(report["integrity_status"], "VERIFIED")
        self.assertEqual(report["case_counts"], {"train": 5, "development": 5, "retention": 1})
        self.assertEqual(report["research_status"], "HOLD")
        self.assertFalse(report["scientific_admission"])
        self.assertFalse(report["model_execution_verified"])
        self.assertFalse(report["natural_semantic_provenance_verified"])
        self.assertFalse(report["new_training_started"])

    def test_public_input_excludes_answer_task_family_split_and_model_labels(self):
        public = load_public_case(self.root, self.cases[0])
        self.assertEqual(set(public), {"text", "image_rgb"})
        self.assertIn("中文🙂\n", public["text"])
        self.assertNotIn("PRIVATE EXPECTED ANSWER", public["text"])
        self.assertEqual(public["image_rgb"].shape, (2, 3, 3))
        self.assertFalse(public["image_rgb"].flags.writeable)

    def test_self_asserted_real_true_is_rejected(self):
        self.manifest["real"] = True
        self.save()
        with self.assertRaises(ValueError):
            self.validate()

    def test_tampered_bytes_and_changed_external_registry_pin_are_rejected(self):
        (self.root / self.cases[0]["text"]["path"]).write_text("tampered")
        with self.assertRaises(ValueError):
            self.validate()
        with self.assertRaises(ValueError):
            validate_materials(self.root, "manifest.json", "registry.json", expected_registry_sha256="0" * 64)

    def test_false_image_with_matching_hash_is_not_accepted_as_pixels(self):
        binding = self.write("pretend-image.png", b"this is not image bytes")
        self.cases[0]["image"] = binding
        self.registry["sources"][0]["image_sha256s"] = [binding["sha256"]]
        self.registry["sources"][0]["case_bindings"][0]["image_sha256"] = binding["sha256"]
        self.save()
        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_invalid_utf8_with_matching_hash_is_rejected(self):
        binding = self.write("invalid-text.txt", b"\xff\xfe")
        self.cases[0]["text"] = binding
        self.registry["sources"][0]["text_sha256s"] = [binding["sha256"]]
        self.registry["sources"][0]["case_bindings"][0]["text_sha256"] = binding["sha256"]
        self.save()
        with self.assertRaises(ValueError):
            self.validate()

    def test_exposed_development_source_cannot_be_relabelled_confirmation(self):
        self.cases[5]["split"] = "confirmation"
        self.registry["sources"][5]["allowed_split"] = "confirmation"
        self.save()
        with self.assertRaisesRegex(ValueError, "previously consumed"):
            self.validate()

    def test_original_source_role_cannot_be_reassigned_inside_case_manifest(self):
        self.cases[5]["split"] = "train"
        self.save()
        with self.assertRaisesRegex(ValueError, "source role"):
            self.validate()

    def test_identical_images_cannot_cross_splits_under_different_source_ids(self):
        self.cases[5]["image"] = deepcopy(self.cases[0]["image"])
        self.registry["sources"][5]["image_sha256s"] = [self.cases[0]["image"]["sha256"]]
        self.registry["sources"][5]["case_bindings"][0]["image_sha256"] = self.cases[0]["image"]["sha256"]
        self.save()
        with self.assertRaisesRegex(ValueError, "same image bytes"):
            self.validate()

    def test_full_history_blocks_archived_image_aliases_absent_from_current_cases(self):
        self.add_confirmation_cases()
        self.assertEqual(self.validate(stage="confirmation")["integrity_status"], "VERIFIED")
        archived = deepcopy(self.registry["sources"][0])
        archived.update(source_id="archived-source-not-in-current-cases", case_bindings=[],
                        image_sha256s=[self.cases[-1]["image"]["sha256"]])
        self.registry["sources"].append(archived)
        self.save()
        with self.assertRaisesRegex(ValueError, "full registry"):
            self.validate(stage="confirmation")

    def test_reference_substitution_cannot_change_an_owner_pinned_case(self):
        original_pin = self.pin
        for replacement in (self.cases[0]["text"], self.cases[1]["reference"]):
            self.cases[0]["reference"] = deepcopy(replacement)
            self.write("manifest.json", json.dumps(self.manifest, sort_keys=True).encode())
            self.assertEqual(self.binding("registry.json")["sha256"], original_pin)
            with self.assertRaisesRegex(ValueError, "original owner case binding"):
                self.validate()

    def test_old_registry_without_case_references_requires_explicit_migration(self):
        self.registry["schema"] = "hepta.source-use-registry.v1"
        for source in self.registry["sources"]:
            source.pop("case_bindings")
        self.save()
        with self.assertRaisesRegex(ValueError, "Invalid source-use registry"):
            self.validate()

    def test_all_five_families_and_old_capabilities_are_required(self):
        original = deepcopy(self.cases)
        self.manifest["cases"] = self.cases[:-1]
        self.save()
        with self.assertRaisesRegex(ValueError, "old-capability"):
            self.validate()
        self.manifest["cases"] = original[:7] + original[8:]
        self.save()
        with self.assertRaisesRegex(ValueError, "task families"):
            self.validate()

    def test_confirmation_requires_all_five_actual_registered_families(self):
        with self.assertRaisesRegex(ValueError, "confirmation"):
            self.validate(stage="confirmation")

    def test_material_paths_cannot_escape_or_use_symlinks(self):
        original = deepcopy(self.cases[0]["text"])
        self.cases[0]["text"]["path"] = "../outside.txt"
        self.save()
        with self.assertRaises(ValueError):
            self.validate()
        (self.root / "alias.txt").symlink_to(self.root / original["path"])
        self.cases[0]["text"] = {**original, "path": "alias.txt"}
        self.save()
        with self.assertRaises(OSError):
            self.validate()

    def test_models_need_real_byte_bindings_for_all_roles(self):
        (self.root / "not-a-real-model.weights").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.validate()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO regression is POSIX-specific")
    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        os.mkfifo(self.root / "fifo")
        script = """import sys
from ndu_semantic_state.materials import check_file
try:
    check_file(sys.argv[1], {'path':'fifo', 'sha256':sys.argv[2], 'bytes':0}, limit=1)
except ValueError as error:
    assert 'regular file' in str(error)
else:
    raise AssertionError('FIFO accepted')
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.root), hashlib.sha256(b"").hexdigest()],
                                capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_duplicate_json_keys_cannot_hide_manifest_fields(self):
        data = (self.root / "manifest.json").read_text()
        (self.root / "manifest.json").write_text('{"schema":"hidden",' + data[1:])
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
