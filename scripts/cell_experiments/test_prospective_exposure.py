"""Artificial intake records exercise the real, read-only historical freeze."""

import copy
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import (
    adoption,
    coding_sft,
    data,
    paired_cold,
    paired_freeze,
    prospective_exposure,
)
from .test_paired_cold import eval_task

QUAL = (
    Path(__file__).resolve().parents[2]
    / "qualification"
    / "public-historical-a-qwen2-052-20261123"
)
SNAPSHOT = QUAL / "run/FROZEN.json"
FREEZE = "447ace5cc8bc031cc772e63ccb90380f16fc81404003bc04057ec4f8b7470ef6"


def artificial(number, prompt=None):
    row = eval_task(number, prompt or f"Artificial new question {number}", 0)
    row.update(origin_kind="authorized_agent_run", exposure="unexposed", trajectory=[])
    row["source"]["repository"] = "unittest:fictional-intake"
    return row


class ProspectiveExposureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.future = self.directory / "synthetic.json"
        self.output = self.directory / "assembled.json"
        self.snapshot = adoption.read_json(SNAPSHOT)
        self.catalog = prospective_exposure.catalog_for(self.snapshot["candidate"])

    def request(self, *records):
        return {
            **self.snapshot,
            "schema": paired_freeze.REQUEST_SCHEMA,
            "future": records,
        }

    def assemble(self, *records, materials=None):
        self.future.write_bytes(data.canonical(records))
        return paired_freeze.assemble(
            SNAPSHOT, FREEZE, self.future, self.output, materials=materials
        )

    def test_renamed_known_inputs_and_repeated_record_id_do_not_publish(self):
        for prompt in ("Give the digit zero.", "Return the digit zero."):
            with (
                self.subTest(prompt=prompt),
                self.assertRaisesRegex(ValueError, "known historical input"),
            ):
                self.assemble(artificial(912, prompt))
        record = artificial(914)
        record["record_id"] = self.snapshot["retention"][0]["record_id"]
        with self.assertRaisesRegex(ValueError, "repeated experiment record"):
            self.assemble(record)
        self.assertFalse(self.output.exists())

    def test_public_archive_sources_have_original_locator_even_if_task_text_changes(
        self,
    ):
        public = self.catalog["public_origin"]
        for source, reason in [
            (dict(sha256=public["parquet_sha256"], row_zero_based=52), "seen public"),
            (
                dict(
                    repository="https://huggingface.co/datasets/OpenHands/openhands-feedback/",
                    revision=public["revision"],
                    row_zero_based=52,
                ),
                "seen public",
            ),
            (dict(sha256=public["parquet_sha256"]), "release row required"),
            (dict(sha256=public["parquet_sha256"], row_zero_based=51), "predates"),
            (
                dict(sha256=self.snapshot["retention"][0]["source"]["sha256"]),
                "seen source material",
            ),
        ]:
            row = artificial(941)
            row["source"].update(source)
            with (
                self.subTest(reason=reason),
                self.assertRaisesRegex(ValueError, reason),
            ):
                self.assemble(row)
        self.assertFalse(self.output.exists())

    def test_namespaced_original_ids_and_delivery_pointer(self):
        for field in ("original_task_id", "operation_id"):
            rows = [artificial(1), artificial(2)]
            for row in rows:
                row["source"][field] = "7"
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "namespaced original"),
            ):
                self.assemble(*rows)
            rows[1]["source"]["repository"] = "unittest:other-issuer"
            prospective_exposure.check_request(self.request(*rows), self.catalog)

        first, second = artificial(3), artificial(4)
        second["source"]["sha256"] = first["source"]["sha256"]
        with self.assertRaisesRegex(ValueError, "original intake material"):
            self.assemble(first, second)
        for row in (first, second):
            row["source"]["intake_receipt_sha256"] = data.digest(row["task_id"])
        prospective_exposure.check_request(self.request(first, second), self.catalog)
        second["source"]["intake_receipt_sha256"] = first["source"][
            "intake_receipt_sha256"
        ]
        with self.assertRaisesRegex(ValueError, "original intake material"):
            self.assemble(first, second)
        self.assertFalse(self.output.exists())

    def test_malformed_authorization_source_and_restitched_freeze(self):
        for field, value in (
            ("operation_id", " "),
            ("original_task_id", None),
            ("intake_receipt_sha256", "bad"),
            ("row_zero_based", True),
        ):
            row = artificial(950)
            row["source"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "invalid"),
            ):
                self.assemble(row)
        row = artificial(950)
        row["exposure"] = "previously_exposed"
        with self.assertRaisesRegex(ValueError, "unexposed"):
            self.assemble(row)
        request = self.request(artificial(951))
        request["timeout_seconds"] += 1
        self.future.write_bytes(data.canonical(request))
        with self.assertRaisesRegex(ValueError, "pre-arrival freeze"):
            paired_cold.checked_request(self.future, data.digest(request))
        self.assertFalse(self.output.exists())

    def test_missing_catalog_fails_closed_for_registered_candidate_only(self):
        candidate = self.snapshot["candidate"]
        with patch.object(
            prospective_exposure.adoption, "read_json", side_effect=FileNotFoundError
        ):
            with self.assertRaisesRegex(ValueError, "catalog is missing"):
                prospective_exposure.catalog_for(candidate)
            self.assertIsNone(prospective_exposure.catalog_for(self.snapshot["parent"]))
        with patch.object(prospective_exposure.adoption, "read_json", return_value={}):
            with self.assertRaisesRegex(ValueError, "catalog differs"):
                prospective_exposure.catalog_for(candidate)

    @unittest.skipUnless(
        importlib.util.find_spec("transformers"), "requires frozen tokenizer runtime"
    )
    def test_normal_assembly_with_distinct_tasks_same_provider_answer_and_no_external_id(
        self,
    ):
        first, second = artificial(971), artificial(972)
        second["source_id"] = first["source_id"]
        before = SNAPSHOT.read_bytes()
        digest = self.assemble(first, second)
        checked = paired_cold.checked_request(self.output, digest)
        self.assertEqual(checked["future"], [first, second])
        self.assertEqual(SNAPSHOT.read_bytes(), before)
        self.assertEqual(data.digest(self.snapshot), FREEZE)

    @unittest.skipUnless(
        importlib.util.find_spec("transformers"), "requires frozen tokenizer runtime"
    )
    def test_rendered_token_collision_or_missing_model_fails_before_publication(self):
        row = artificial(990)
        model = self.snapshot["candidate"]
        tokenizer = paired_cold.frozen_tokenizer(model, SNAPSHOT.parent)
        old_tokens = tokenizer.encode(
            coding_sft.prompt_text("Give the digit zero."), add_special_tokens=False
        )
        fingerprint = next(
            v for v in self.catalog["known_inputs"] if v["exposure"] == "old_rehearsal"
        )["input_ids_sha256"]
        self.assertEqual(data.digest(old_tokens), fingerprint)
        # Simulate two distinct texts mapping to the same model tokens.
        with (
            patch.object(tokenizer, "encode", return_value=old_tokens),
            patch.object(paired_cold, "frozen_tokenizer", return_value=tokenizer),
        ):
            with self.assertRaisesRegex(ValueError, "known historical input token IDs"):
                self.assemble(row)
        with self.assertRaises((FileNotFoundError, ValueError)):
            self.assemble(copy.deepcopy(row), materials=self.directory / "missing")
        self.assertFalse(self.output.exists())
