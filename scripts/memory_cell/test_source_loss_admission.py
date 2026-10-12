"""Immutable parity admission contracts, not pretrained model experiments."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from source_loss_admission import require_parity


def sample():
    return {
        "schema": "hepta.source-only.pretrained-loss-parity.v2",
        "generating_commit": "a" * 40,
        "source_sha256": "b" * 64,
        "model_inventory_digest": "c" * 64,
        "model_repository": "Qwen/Qwen2.5-3B-Instruct",
        "model_revision": "d" * 40,
        "curriculum": "single_hop",
        "dependency_versions": {
            "torch": "2.5.1+cpu",
            "transformers": "4.57.1",
            "peft": "0.17.1",
        },
        "source_example_selected_from_write_schedule": True,
        "frozen_pretrained_base_unchanged": True,
        "matched_optimization_step": True,
        "original_task_plan_opened": False,
        "new_answer_generations": 0,
        "significant_task_gain": None,
        "independent_semantic_citation_precision": None,
        "production_accepted": False,
        "compared_input_tokens": 112,
        "compared_supervised_tokens": 6,
        "full_projection_positions": 112,
        "selected_projection_positions": 6,
        "full_loss": 2.5,
        "selected_loss": 2.5001,
        "maximum_gradient_absolute_difference": 0.0001,
        "maximum_updated_parameter_absolute_difference": 0.00001,
    }


class SourceLossAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "parity.json"
        self.arguments = dict(
            source_sha="b" * 64,
            source_commit="a" * 40,
            model_identity="c" * 64,
            repository="Qwen/Qwen2.5-3B-Instruct",
            revision="d" * 40,
        )

    def admit(self, payload=None, *, digest=None):
        encoded = json.dumps(payload if payload is not None else sample()).encode()
        self.file.write_bytes(encoded)
        pin = hashlib.sha256(encoded).hexdigest()
        return require_parity(
            "supervised_positions",
            self.file,
            digest if digest is not None else pin,
            **self.arguments,
        )

    def test_exact_source_model_and_optimizer_parity_admitted(self):
        self.assertEqual(
            self.admit(), hashlib.sha256(self.file.read_bytes()).hexdigest()
        )
        self.assertIsNone(require_parity("full", None, None, **self.arguments))

    def test_full_path_does_not_accept_a_spurious_receipt(self):
        with self.assertRaises(ValueError):
            require_parity("full", self.file, "1" * 64, **self.arguments)
        with self.assertRaises(ValueError):
            require_parity("supervised_positions", None, None, **self.arguments)
        with self.assertRaises(ValueError):
            require_parity("unknown", None, None, **self.arguments)

    def test_changed_source_model_revision_or_commit_cannot_authorize(self):
        for key, wrong in (
            ("source_sha256", "e" * 64),
            ("model_inventory_digest", "e" * 64),
            ("model_revision", "e" * 40),
            ("generating_commit", "e" * 40),
            ("model_repository", "other"),
            ("curriculum", "source_two_hop"),
            ("source_example_selected_from_write_schedule", False),
        ):
            row = deepcopy(sample())
            row[key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.admit(row)

    def test_fake_task_or_bad_counts_or_unverified_model_reject(self):
        for key, wrong in (
            ("original_task_plan_opened", True),
            ("new_answer_generations", 1),
            ("frozen_pretrained_base_unchanged", False),
            ("matched_optimization_step", False),
            ("production_accepted", True),
            ("selected_projection_positions", 112),
            ("full_projection_positions", 6),
            ("full_loss", float("nan")),
            ("selected_loss", 6.5),
            ("maximum_gradient_absolute_difference", -1),
        ):
            row = sample()
            row[key] = wrong
            if key == "full_loss":
                # JSON standards forbid nonfinite observations.
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.admit(row)
            else:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.admit(row)

    def test_optimizer_parity_aggregate_and_dependency_drift_reject(self):
        wrong_torch = dict(sample()["dependency_versions"])
        wrong_torch["torch"] = "2.5.1"
        wrong_peft = dict(sample()["dependency_versions"])
        wrong_peft["peft"] = "0.17.2"
        for field, wrong in (
            ("maximum_gradient_absolute_difference", 0.025),
            ("maximum_updated_parameter_absolute_difference", 0.021),
            ("compared_input_tokens", 2113),
            ("dependency_versions", wrong_torch),
            ("dependency_versions", wrong_peft),
        ):
            item = deepcopy(sample())
            item[field] = wrong
            if field == "compared_input_tokens":
                item["full_projection_positions"] = wrong
            with self.subTest(field=field, value=wrong), self.assertRaises(ValueError):
                self.admit(item)

    def test_missing_versions_do_not_authorize_optimized_writer(self):
        item = sample()
        del item["dependency_versions"]
        with self.assertRaises(ValueError):
            self.admit(item)

    def test_tampered_json_or_symlink_cannot_cross_admission(self):
        original = self.admit()
        encoded = self.file.read_bytes()
        self.file.write_bytes(encoded + b" ")
        with self.assertRaises(ValueError):
            require_parity(
                "supervised_positions", self.file, original, **self.arguments
            )
        link = Path(self.temp.name) / "symlink.json"
        link.symlink_to(self.file)
        with self.assertRaises(ValueError):
            require_parity(
                "supervised_positions",
                link,
                hashlib.sha256(self.file.read_bytes()).hexdigest(),
                **self.arguments,
            )

    def test_source_two_hop_requires_a_separate_actual_parity_receipt(self):
        with self.assertRaisesRegex(ValueError, "source-two-hop optimization"):
            require_parity(
                "supervised_positions",
                None,
                None,
                curriculum="source_two_hop",
                **self.arguments,
            )
        self.assertIsNone(
            require_parity(
                "full", None, None, curriculum="source_two_hop", **self.arguments
            )
        )
        with self.assertRaisesRegex(ValueError, "unregistered source write curriculum"):
            require_parity("full", None, None, curriculum="unknown", **self.arguments)


if __name__ == "__main__":
    unittest.main()
