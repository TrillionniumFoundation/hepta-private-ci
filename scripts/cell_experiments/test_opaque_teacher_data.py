"""Authored codec controls only: no live teacher, original human, fit, or authority."""

import copy
import hashlib
import unittest

from . import data, opaque_teacher_data as opaque


def fixture(answer="1"):
    prompt = "Return JSON integer one."
    source = {
        "schema": opaque.SOURCE,
        "read_method": "AsyncThread.read(include_turns=True)",
        "sdk_version": "synthetic-codec-control",
        "serialization": "pydantic-json-aliases-exclude-unset/utf8-sorted-compact-v1",
        "thread": {
            "id": "thread",
            "sessionId": "session",
            "modelProvider": "reported-provider",
        },
        "turn": {"id": "turn", "status": "completed", "itemsView": "full"},
        "items_view_explicit": True,
        "returned_item_count": 2,
        "items": [
            {
                "source_index": 0,
                "item_id": "u",
                "type": "userMessage",
                "sdk_payload": {
                    "id": "u",
                    "type": "userMessage",
                    "content": [{"type": "text", "text": prompt}],
                },
            },
            {
                "source_index": 1,
                "item_id": "a",
                "type": "agentMessage",
                "sdk_payload": {"id": "a", "type": "agentMessage", "text": answer},
            },
        ],
        "omitted_items": [],
        "teacher_opaque_id": None,
        "teacher_model_sha256": None,
        "claims": copy.deepcopy(opaque.SOURCE_CLAIMS),
    }
    raw = data.canonical(source)
    draft = {
        "schema": opaque.SCHEMA,
        "record_id": "correction",
        "task_id": "task",
        "lineage_id": "lineage",
        "family_id": "family",
        "project_id": "project",
        "source_id": "capture",
        "teacher_id": "explicit-unattested-label",
        "model_digest": None,
        "teacher_output_receipt_sha256": None,
        "observed_at": 2,
        "available_at": 2,
        "split": "train",
        "origin_kind": "authorized_agent_run",
        "exposure": "development",
        "authorization": {
            "training_allowed": False,
            "evaluation_allowed": True,
            "scope": "authored codec control only",
            "rights_basis": "synthetic fixture",
        },
        "source": {
            "repository": "synthetic",
            "path": "capture",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "task": {
            "input": prompt,
            "verifier": {
                "name": "json_artifact",
                "version": "1",
                "parameters": {"expected": 1},
            },
        },
        "production_eligible": False,
        "human_training_consent_proven": False,
    }
    return draft, source, raw


def observe(draft, raw):
    return opaque.from_capture(
        draft,
        raw,
        prompt_item_id="u",
        answer_item_id="a",
        student_policy_sha256="a" * 64,
    )


class OpaqueTeacherDataTests(unittest.TestCase):
    def test_explicit_observation_preserves_unknown_weights_and_no_consent(self):
        draft, _, raw = fixture()
        original = copy.deepcopy(draft)
        record = observe(draft, raw)
        self.assertEqual(draft, original)
        self.assertEqual(record["authorization"], original["authorization"])
        self.assertIsNone(record["model_digest"])
        self.assertIsNone(record["teacher_output_receipt_sha256"])
        self.assertIsNone(record["teacher_observation"]["reported_phase"])
        self.assertEqual(
            record["trajectory"],
            [
                {
                    "index": 0,
                    "actor": "teacher",
                    "kind": "observation",
                    "content": "1",
                    "executed": False,
                    "trainable": False,
                    "receipt_sha256": None,
                    "source_item_id": "a",
                    "source_item_sha256": record["teacher_observation"][
                        "answer_item_sha256"
                    ],
                }
            ],
        )
        opaque.verify_source(record, raw)
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            data.validate_record(record, require_outcome=False)

    def test_model_labels_hashes_and_execution_claims_cannot_be_promoted(self):
        draft, _, raw = fixture()
        original = observe(draft, raw)
        changes = [
            ("model_digest", data.digest("provider/model")),
            ("teacher_output_receipt_sha256", "b" * 64),
            ("production_eligible", True),
            ("human_training_consent_proven", True),
        ]
        for key, value in changes:
            record = copy.deepcopy(original)
            record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                opaque.validate_record(record, require_outcome=False)
        for key, value in (
            ("weights_sha256", "b" * 64),
            ("generation_authenticated", True),
            ("execution_authenticated", True),
            ("generation_receipt_sha256", "c" * 64),
        ):
            record = copy.deepcopy(original)
            record["teacher_observation"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                opaque.validate_record(record, require_outcome=False)
        for key, value in (
            ("actor", "student"),
            ("kind", "action"),
            ("executed", True),
            ("trainable", True),
        ):
            record = copy.deepcopy(original)
            record["trajectory"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                opaque.validate_record(record, require_outcome=False)

    def test_raw_source_and_explicit_item_inventory_are_bound(self):
        draft, source, raw = fixture()
        with self.assertRaisesRegex(ValueError, "original capture bytes"):
            observe(draft, raw + b" ")
        for change in (
            "duplicate",
            "partial",
            "running",
            "false_signature",
            "missing_answer",
            "noncanonical",
        ):
            altered = copy.deepcopy(source)
            if change == "duplicate":
                altered["items"][1]["item_id"] = "u"
            if change == "partial":
                altered["turn"]["itemsView"] = "summary"
            if change == "running":
                altered["turn"]["status"] = "inProgress"
            if change == "false_signature":
                altered["claims"]["source_signed"] = True
            if change == "missing_answer":
                altered["items"][1]["item_id"] = "other"
            changed = data.canonical(altered) + (
                b" " if change == "noncanonical" else b""
            )
            template = copy.deepcopy(draft)
            template["source"]["sha256"] = hashlib.sha256(changed).hexdigest()
            with self.subTest(change=change), self.assertRaises(ValueError):
                observe(template, changed)

    def test_prompt_payload_identity_and_order_are_exact(self):
        draft, source, _ = fixture()
        for change in ("input", "payload_id", "order", "image"):
            altered = copy.deepcopy(source)
            if change == "input":
                altered["items"][0]["sdk_payload"]["content"][0]["text"] = (
                    "another task"
                )
            if change == "payload_id":
                altered["items"][1]["sdk_payload"]["id"] = "different"
            if change == "order":
                (
                    altered["items"][0]["source_index"],
                    altered["items"][1]["source_index"],
                ) = 1, 0
            if change == "image":
                altered["items"][0]["sdk_payload"]["content"].append({"type": "image"})
            raw = data.canonical(altered)
            template = copy.deepcopy(draft)
            template["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
            with self.subTest(change=change), self.assertRaises(ValueError):
                observe(template, raw)

    def test_local_semantic_receipt_is_bound_and_never_signed_authority(self):
        draft, _, raw = fixture()
        record = observe(draft, raw)
        receipt = opaque.verify_answer(record)
        self.assertTrue(receipt["success"])
        self.assertFalse(receipt["evaluator_signature_created"])
        self.assertFalse(receipt["production_eligible"])
        self.assertFalse(receipt["teacher_execution_claimed"])
        self.assertEqual(
            receipt["teacher_observation_sha256"],
            data.digest(record["teacher_observation"]),
        )
        record["verified_outcome"] = {
            "success": receipt["success"],
            "receipt_sha256": receipt["receipt_sha256"],
            "verifier_name": "json_artifact",
            "verifier_version": "1",
        }
        opaque.validate_record(record)
        wrong, _, wrong_raw = fixture("0")
        self.assertFalse(opaque.verify_answer(observe(wrong, wrong_raw))["success"])

    def test_profile_rejects_floats_fake_targets_and_unsupported_fields(self):
        draft, _, raw = fixture()
        original = observe(draft, raw)
        for key, value in (
            ("observed_at", 2.5),
            ("observed_at", 2**64),
            ("target", 1),
            ("features", {"values": [1]}),
            ("authority_granted", True),
        ):
            record = copy.deepcopy(original)
            record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                opaque.validate_record(record, require_outcome=False)

    def test_source_rebuild_rejects_changed_provider_phase_or_selected_text(self):
        draft, _, raw = fixture()
        original = observe(draft, raw)
        for key, value in (
            ("provider_reported", "different"),
            ("reported_phase", "final_answer"),
            ("answer_item_sha256", "b" * 64),
        ):
            record = copy.deepcopy(original)
            record["teacher_observation"][key] = value
            if key == "answer_item_sha256":
                record["trajectory"][0]["source_item_sha256"] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "record differs"),
            ):
                opaque.verify_source(record, raw)


if __name__ == "__main__":
    unittest.main()
