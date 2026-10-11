"""Model-free integrity checks; never mistake partial calibration for success."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import interrupted_qwen_receipt as audit


class InterruptedQwenTests(unittest.TestCase):
    def fixture(self, path, *, alter=None):
        content = json.dumps(
            dict(
                schema="hepta.controlled-event.v1",
                id="e0",
                entity="service_0",
                attribute="location",
                value="site_1",
                revision=1,
                supersedes=[],
            ),
            sort_keys=True,
        )
        doc = dict(
            identity="e0",
            root="r0",
            scope="q0",
            session="q0",
            observed_at="2026-10-11T00:00:00Z",
            content=content,
            assets=[],
        )
        cases = [
            dict(
                query=dict(identity=f"q{i}", scope=f"q{i}"),
                candidate_ids=["e0"] if i == 0 else [f"unknown{i}"],
                candidate_digest="pool",
            )
            for i in range(8)
        ]
        plan = dict(
            source_commit=audit.SOURCE_COMMIT,
            calibration_only=True,
            test_cases_materialized=False,
            ks=list(audit.EXPECTED_K),
            cases=cases,
        )
        plan["cases"][0]["candidate_digest"] = "pool0"
        staged = dict(tier="qwen-3b", research_only=True)
        reader = dict(
            input_tokens=15,
            generated_tokens=2,
            seconds=1.5,
            token_limit=2048,
            reader_identity=audit.READER_IDENTITY,
            trainable_parameters=0,
            answer_postprocessed=False,
            production_accepted=False,
            semantic_citation_precision=None,
            input_ids_digest="p" * 64,
            delivered_evidence=[
                dict(
                    original_id="e0",
                    label="E1",
                    root="r0",
                    excerpt=content,
                    source_digest=audit.canonical_digest(content),
                )
            ],
        )
        row = dict(
            question_id="q0",
            arm="k1",
            status="succeeded",
            candidate_digest="pool0",
            selected=["e0"],
            answer="site_1 [E1]",
            receipt=reader,
            citation_audit=dict(
                request=dict(answer="site_1 [E1]", prompt_digest="p" * 64),
                judgement=None,
                production_accepted=False,
            ),
        )
        files = {
            "tested-commit.txt": (audit.SOURCE_COMMIT + "\n").encode(),
            "stage.json": json.dumps(staged).encode(),
            "prep/calibration-plan.json": json.dumps(plan).encode(),
            "prep/calibration-sources.json": json.dumps([doc]).encode(),
            "calibration/raw-answers.jsonl": (json.dumps(row) + "\n").encode(),
        }
        files["calibration/run.json"] = json.dumps(
            dict(
                source_commit=audit.SOURCE_COMMIT,
                stage="calibration",
                test_tasks_opened=False,
                optimizer_executed=False,
                production_accepted=False,
                calibration_sha256=hashlib.sha256(
                    files["prep/calibration-plan.json"]
                ).hexdigest(),
                model_stage_sha256=hashlib.sha256(files["stage.json"]).hexdigest(),
                model=dict(inventory_digest=audit.READER_IDENTITY),
            )
        ).encode()
        if alter is not None:
            alter(files)
        pins = "".join(
            f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
            for name, data in sorted(files.items())
        )
        files["SHA256SUMS"] = pins.encode()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        return files

    def guarded(self, path, *, alter=None):
        files = self.fixture(path, alter=alter)
        with (
            patch.object(
                audit, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
            ),
            patch.object(
                audit,
                "CALIBRATION_PLAN_SHA256",
                hashlib.sha256(files["prep/calibration-plan.json"]).hexdigest(),
            ),
        ):
            return audit.audit(path)

    def test_partial_rows_not_promoted_to_calibrated_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ok.zip"
            result = self.guarded(p)
            self.assertEqual(result["observed_calls"], 1)
            self.assertEqual(result["missing_calls"], 39)
            self.assertIsNone(result["selected_k"])
            self.assertFalse(result["evaluation_started"])
            self.assertFalse(result["production_accepted"])

    def test_outer_pin_must_reject_modified_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "tampered.zip"
            self.fixture(p)
            with self.assertRaisesRegex(ValueError, "outer SHA"):
                audit.audit(p)

    def test_citation_tamper_rejected_after_all_files_resealed(self):
        def alter(files):
            name = "calibration/raw-answers.jsonl"
            row = json.loads(files[name])
            row["citation_audit"]["request"]["prompt_digest"] = "wrong"
            files[name] = (json.dumps(row) + "\n").encode()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "citation queue"):
                self.guarded(Path(tmp) / "tampered.zip", alter=alter)

    def test_source_text_replacement_cannot_be_hidden_with_resealing(self):
        def alter(files):
            key = "calibration/raw-answers.jsonl"
            row = json.loads(files[key])
            row["receipt"]["delivered_evidence"][0]["excerpt"] = "invented"
            files[key] = (json.dumps(row) + "\n").encode()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "original source bytes"):
                self.guarded(Path(tmp) / "tampered.zip", alter=alter)

    def test_duplicate_call_rejected(self):
        def alter(files):
            key = "calibration/raw-answers.jsonl"
            files[key] += files[key]

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                self.guarded(Path(tmp) / "duplicate.zip", alter=alter)

    def test_fake_frozen_policy_refused(self):
        def alter(files):
            files["calibration/frozen-policy.json"] = b"{}"

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "future or scored"):
                self.guarded(Path(tmp) / "fake.zip", alter=alter)

    def test_json_parser_rejects_duplicate_and_nonfinite(self):
        for content in (b'{"a":1,"a":2}', b'{"value":NaN}'):
            with self.assertRaises(ValueError):
                audit.strict_json(content)


if __name__ == "__main__":
    unittest.main()
