"""Synthetic capture + actual local sink/consumer; no teacher request or fit."""

import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import (
    chat_protocol,
    data,
    opaque_teacher_data as opaque,
    paired_opaque_teacher as consumer,
)
from . import paired_source, paired_source_train
from .test_opaque_teacher_data import fixture
from .test_paired_source import capture


def pair(root, *, training_allowed=True):
    originals = root / "originals"
    originals.mkdir(mode=0o700)
    failure = capture(root, "failure", "0", "a" * 64, {"action": "0"}, 1)
    draft, source, _ = fixture()
    for key in ("task_id", "lineage_id", "project_id", "task"):
        draft[key] = copy.deepcopy(failure[key])
    draft["authorization"]["training_allowed"] = training_allowed
    source["items"][0]["sdk_payload"]["content"][0]["text"] = draft["task"]["input"]
    raw = data.canonical(source)
    draft["source"].update(
        repository=failure["source"]["repository"],
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    paired_source._publish_bytes(originals / draft["source"]["sha256"], raw)
    correction = consumer.capture_correction(
        draft,
        originals,
        root / "correction.json",
        prompt_item_id="u",
        answer_item_id="a",
        student_policy_sha256="a" * 64,
    )
    return failure, correction, originals


class PairedOpaqueTeacherTests(unittest.TestCase):
    def test_actual_source_dispatch_preserves_pair_and_only_supervises_final_answer(
        self,
    ):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            derived = paired_source.derive(failure, correction, originals)
            self.assertEqual(
                derived["derivation"],
                {
                    "failure": data.record_digest(failure),
                    "correction": data.record_digest(correction),
                },
            )
            self.assertEqual(
                derived["original_pair"],
                {"failure": failure, "correction": correction},
            )
            self.assertFalse(correction["trajectory"][0]["executed"])
            for protocol in (chat_protocol.LEGACY, chat_protocol.NATIVE):
                example = chat_protocol.training_examples(
                    [derived], "final_answer", protocol
                )[0]
                self.assertEqual(
                    [(s["content"], s["train"]) for s in example["segments"]],
                    [("1", True)],
                )
                messages, duplicates = chat_protocol.training_messages(example)
                self.assertEqual([m["content"] for m in messages if m["train"]], ["1"])
                self.assertEqual(duplicates, 0)
                self.assertNotIn("1", [m["content"] for m in messages[:-1]])
                with self.assertRaisesRegex(ValueError, "final_answer only"):
                    chat_protocol.training_examples([derived], "trajectory", protocol)

    def test_capture_preserves_denied_training_and_both_consumers_refuse(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp), training_allowed=False)
            self.assertFalse(correction["authorization"]["training_allowed"])
            with self.assertRaisesRegex(ValueError, "permit training"):
                paired_source.derive(failure, correction, originals)
            with self.assertRaisesRegex(ValueError, "permit"):
                consumer._project(failure, correction)

    def test_full_recomputed_receipt_and_source_must_match(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            path = originals / correction["verified_outcome"]["receipt_sha256"]
            original = path.read_bytes()
            receipt = data._parse(original)
            receipt["evaluator_signature_created"] = True
            path.write_bytes(data.canonical(receipt))
            with self.assertRaisesRegex(ValueError, "complete unsigned"):
                paired_source.derive(failure, correction, originals)
            path.write_bytes(original)
            source = originals / correction["source"]["sha256"]
            source.write_bytes(source.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "original capture bytes"):
                paired_source.derive(failure, correction, originals)

    def test_student_policy_task_and_failure_execution_cannot_be_replaced(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            changed = copy.deepcopy(correction)
            changed["teacher_observation"]["student_policy_sha256"] = "b" * 64
            with self.assertRaisesRegex(ValueError, "student policy"):
                consumer._project(failure, changed)
            changed = copy.deepcopy(correction)
            changed["task_id"] = "other"
            with self.assertRaisesRegex(ValueError, "different tasks"):
                consumer._project(failure, changed)
            changed = copy.deepcopy(failure)
            changed["trajectory"][0]["executed"] = False
            with self.assertRaisesRegex(ValueError, "terminal executed"):
                paired_source.derive(changed, correction, originals)

    def test_derived_tampering_and_insecure_originals_are_refused(self):
        with TemporaryDirectory() as tmp:
            failure, correction, originals = pair(Path(tmp))
            derived = paired_source.derive(failure, correction, originals)
            derived["trajectory"][0]["trainable"] = True
            with self.assertRaisesRegex(ValueError, "derivation changed"):
                chat_protocol.training_examples(
                    [derived], "final_answer", chat_protocol.NATIVE
                )
            originals.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "private owned"):
                consumer.check_correction(correction, originals)

    def test_exact_claim_and_count_types_preserve_legitimate_payload_float(self):
        draft, source, _ = fixture()
        for key in ("claim", "count", "extra_payload"):
            value = copy.deepcopy(source)
            if key == "claim":
                value["claims"]["source_signed"] = 0
            if key == "count":
                value["returned_item_count"] = 2.0
            if key == "extra_payload":
                value["items"][1]["sdk_payload"]["reported_latency"] = 1.5
            raw = data.canonical(value)
            template = copy.deepcopy(draft)
            template["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
            args = dict(
                prompt_item_id="u", answer_item_id="a", student_policy_sha256="a" * 64
            )
            if key == "extra_payload":
                record = opaque.from_capture(template, raw, **args)
                opaque.verify_source(record, raw)
            else:
                with self.assertRaises(ValueError):
                    opaque.from_capture(template, raw, **args)

    def test_old_engineering_fit_entry_rejects_observed_records_before_fit(self):
        with TemporaryDirectory() as tmp:
            failure, correction, _ = pair(Path(tmp))
            owner = {
                "scope": "authored_engineering_fixture",
                "authenticated_human": False,
            }
            spec = {
                "trainer_source_sha256": "pin",
                "parent": "p",
                "retention": "r",
                "failure": "f",
                "correction": "c",
            }
            with (
                patch.object(paired_source_train, "check_spec"),
                patch.object(paired_source_train, "source_hash", return_value="pin"),
                patch.object(
                    paired_source,
                    "read_bound",
                    side_effect=[{"runtime": {}}, [], failure, correction],
                ),
                patch.object(paired_source_train.coding_sft, "verify_model"),
                patch.object(paired_source_train.paired_cold, "checked_panels"),
                patch.object(paired_source_train.paired_source_fit, "train") as fit,
            ):
                with self.assertRaisesRegex(ValueError, "original native owner"):
                    paired_source_train._fit_after_verification(tmp, spec, owner)
                fit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
