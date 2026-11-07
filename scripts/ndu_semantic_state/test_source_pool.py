"""Synthetic boundary tests only; these fixtures are not real research material."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, PngImagePlugin

from .source_pool import (
    HISTORY_SCHEMA,
    SCHEMA,
    admit_candidate_pool,
    evaluator_public_view,
    load_candidate_public_case,
    pixel_digest,
    score_vizwiz_reference,
)


class CandidateBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = []
        for index, split in enumerate(("train", "development")):
            image = Image.new("RGB", (3, 2), (index + 1, 40, 80))
            image.save(self.root / f"{index}.png")
            source = f"fixture-{index}"
            self.cases.append(
                {
                    "id": source,
                    "source_id": source,
                    "source_group_id": source,
                    "episode_group_id": source,
                    "derivative_root_ids": [source],
                    "group_evidence": "SYNTHETIC_TEST_ONLY",
                    "upstream_grouping_complete": False,
                    "upstream_split": "fixture",
                    "project_split": split,
                    "task_family": None,
                    "retention_capability": None,
                    "text": self.write(
                        f"{index}.txt", f"public fixture {index}".encode()
                    ),
                    "image": self.bind(f"{index}.png"),
                    "reference": self.write(
                        f"{index}-private.json",
                        json.dumps(
                            {"answers": [{"answer": "private fixture answer"}] * 10}
                        ).encode(),
                    ),
                    "source_evidence": self.write(
                        f"{index}-source.json", b'{"synthetic_fixture":true}'
                    ),
                    "image_pixel_sha256": pixel_digest(np.array(image)),
                    "used_in_project_training": split == "train",
                    "observed_in_project": True,
                    "pretraining_exposure": "unknown",
                }
            )
        self.history = {"schema": HISTORY_SCHEMA, "cases": deepcopy(self.cases)}
        self.manifest = {
            "schema": SCHEMA,
            "study_id": "synthetic-boundary-fixture",
            "history_sha256": "",
            "acquisition_plan": self.write("plan.json", b'{"synthetic_fixture":true}'),
            "acquisition_receipt": self.write(
                "acquisition.json", b'{"synthetic_fixture":true}'
            ),
            "cases": self.cases,
        }

    def bind(self, name):
        data = (self.root / name).read_bytes()
        return {
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    def write(self, name, data):
        (self.root / name).write_bytes(data)
        return self.bind(name)

    def run_admission(self):
        pin = self.write("history.json", json.dumps(self.history).encode())["sha256"]
        self.manifest["history_sha256"] = pin
        self.write("manifest.json", json.dumps(self.manifest).encode())
        return admit_candidate_pool(
            self.root, "manifest.json", "history.json", expected_history_sha256=pin
        )

    def test_integrity_cannot_create_scientific_readiness(self):
        result = self.run_admission()
        self.assertEqual(result["integrity_status"], "VERIFIED")
        self.assertEqual(result["research_status"], "HOLD")
        self.assertIsNone(result["independent_cluster_count"])
        self.assertFalse(result["owner_registration_verified"])
        self.assertFalse(result["scientific_admission"])

    def test_historical_groups_cannot_be_erased_by_selection(self):
        self.manifest["cases"] = [self.cases[1]]
        for field in (
            "source_id",
            "source_group_id",
            "episode_group_id",
            "derivative_root_ids",
        ):
            with self.subTest(field=field):
                history = deepcopy(self.history)
                history["cases"][0][field] = deepcopy(self.cases[1][field])
                self.history, saved = history, self.history
                with self.assertRaisesRegex(ValueError, "group crosses splits"):
                    self.run_admission()
                self.history = saved

    def test_reencoded_identical_pixels_cannot_cross_roles(self):
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("changed_container_only", "true")
        with Image.open(self.root / "0.png") as image:
            image.save(self.root / "1.png", pnginfo=metadata)
        self.cases[1]["image"] = self.bind("1.png")
        self.cases[1]["image_pixel_sha256"] = self.cases[0]["image_pixel_sha256"]
        self.history["cases"] = deepcopy(self.cases)
        self.assertNotEqual(
            self.cases[0]["image"]["sha256"], self.cases[1]["image"]["sha256"]
        )
        with self.assertRaisesRegex(ValueError, "group crosses splits"):
            self.run_admission()

    def test_consumed_source_cannot_become_confirmation(self):
        self.cases[1]["project_split"] = "confirmation"
        self.history["cases"] = deepcopy(self.cases)
        with self.assertRaisesRegex(ValueError, "Consumed sources"):
            self.run_admission()

    def test_recombined_reference_and_source_role_are_rejected(self):
        self.cases[1]["reference"] = self.write(
            "replacement.json", b'{"hidden_answer":"changed"}'
        )
        with self.assertRaisesRegex(ValueError, "reassigns"):
            self.run_admission()

    def test_family_label_cannot_turn_candidate_into_real_family(self):
        self.cases[1]["task_family"] = "preparation_required"
        self.history["cases"] = deepcopy(self.cases)
        with self.assertRaisesRegex(ValueError, "cannot certify"):
            self.run_admission()

    def test_actor_and_model_evaluator_cannot_receive_private_or_future_fields(self):
        public = load_candidate_public_case(self.root, self.cases[0])
        self.assertEqual(set(public), {"text", "image_rgb"})
        self.assertFalse(public["image_rgb"].flags.writeable)
        delivered = {"text": "current output only", "image_rgb": None}
        view = evaluator_public_view(public, delivered)
        self.assertEqual(set(view), {"input", "current_output"})
        self.assertFalse(
            np.shares_memory(public["image_rgb"], view["input"]["image_rgb"])
        )
        for private in (
            "reference",
            "task_family",
            "source_id",
            "future_outcomes",
            "answerable",
            "split",
        ):
            with self.subTest(private=private), self.assertRaises(ValueError):
                evaluator_public_view({**public, private: "forbidden"}, delivered)
            with self.subTest(private=private), self.assertRaises(ValueError):
                evaluator_public_view(public, {**delivered, private: "forbidden"})

    def test_external_consensus_does_not_claim_official_or_image_quality(self):
        reference = {
            "image": "synthetic.png",
            "question": "Fixture?",
            "answer_type": "yes/no",
            "answerable": 1,
            "answers": [
                {"answer": answer, "answer_confidence": "yes"}
                for answer in ["Yes"] * 3 + ["no"] * 7
            ],
        }
        row = score_vizwiz_reference(reference, " YES ")
        self.assertAlmostEqual(row["score"], 0.9)
        self.assertFalse(row["official_vqa_score"])
        self.assertIsNone(row["image_quality"])
        self.assertFalse(row["scientific_admission"])
        self.assertEqual(score_vizwiz_reference(reference, "unmatched")["score"], 0)
        with self.assertRaises(ValueError):
            score_vizwiz_reference({**reference, "future_outcomes": [1]}, "YES")


if __name__ == "__main__":
    unittest.main()
