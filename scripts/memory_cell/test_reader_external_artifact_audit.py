"""Adversarial external GitHub artifact authority; fixtures are NOT model results."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from reader_external_artifact_audit import (
    audit,
    checked_archive,
    checked_metadata,
    sha,
    strict_json,
)

SOURCE = "45388fefac75b08f2715584abd7062699bd461c0"
RUN_ID = 38538369649
NAME = "memory-reader-bottleneck-smol-1.7b-0"


def run():
    return dict(
        id=RUN_ID,
        head_sha=SOURCE,
        head_branch="codex/memorycell-reader-bottleneck-ablation-20261014",
        name="MemoryCell real Reader capacity and one-premise ablation",
        event="push",
        run_attempt=1,
        status="queued",
        repository={"full_name": "TrillionniumFoundation/hepta-private-ci"},
    )


def sealed_zip(*, eligible=False, inference=False):
    host = dict(
        schema="hepta.memory-strong-rag.bf16-host-gate.v1",
        new_model_calls=0,
        production_accepted=False,
        host_eligible=eligible,
        all_cpus_bf16_accelerated=eligible,
        machine="x86_64",
        same_original_model_weights_required=True,
    )
    files = {
        "host-gate.json": json.dumps(host).encode(),
        "checkout-commit.txt": (SOURCE + "\n").encode(),
    }
    if inference:
        record = dict(
            question_id="controlled",
            arm="none",
            status="succeeded",
            answer="I do not have enough evidence.",
            receipt={
                "reader_identity": "a" * 64,
                "trainable_parameters": 0,
                "answer_postprocessed": False,
            },
        )
        files["raw-answers.jsonl"] = (json.dumps(record) + "\n").encode()
    files["SHA256SUMS"] = "".join(
        f"{sha(raw)}  ./{name}\n" for name, raw in sorted(files.items())
    ).encode()
    with BytesIO() as stream:
        with zipfile.ZipFile(stream, "w") as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        return stream.getvalue()


def listing(data):
    record = dict(
        id=114,
        name=NAME,
        digest="sha256:" + sha(data),
        size_in_bytes=len(data),
        expired=False,
        workflow_run={
            "id": RUN_ID,
            "head_sha": SOURCE,
            "head_branch": run()["head_branch"],
        },
    )
    return {"total_count": 1, "artifacts": [record]}


class ExternalArtifactAuditTests(unittest.TestCase):
    def test_one_real_hardware_refusal_is_not_an_answer_failure(self):
        raw = sealed_zip()
        result = self.audited(raw)
        self.assertEqual(result["github_artifact_count"], 1)
        self.assertEqual(result["absent_artifact_count"], 15)
        self.assertEqual(result["original_succeeded_generation_rows"], 0)
        self.assertEqual(result["dispositions"], {"hardware_ineligible": 1})
        self.assertTrue(result["github_outer_zip_sha256_verified"])
        self.assertIsNone(result["original_model_task_score"])
        self.assertFalse(result["production_accepted"])

    def test_one_partial_real_answer_is_not_five_completed_calls(self):
        value = self.audited(sealed_zip(eligible=True, inference=True))
        self.assertEqual(value["original_succeeded_generation_rows"], 1)
        self.assertEqual(value["original_attempt_rows"], 1)
        self.assertEqual(value["completed_original_journal_shards"], 0)
        self.assertEqual(value["dispositions"], {"incomplete_original_journal": 1})
        self.assertEqual(value["expected_original_model_calls"], 80)

    def test_run_identity_and_attempt_are_exact(self):
        raw = sealed_zip()
        good = listing(raw)
        for key, value in (
            ("head_sha", "f" * 40),
            ("run_attempt", 2),
            ("id", RUN_ID + 1),
            ("event", "pull_request"),
            ("head_branch", "main"),
        ):
            with self.subTest(key=key):
                wrong = run()
                wrong[key] = value
                with self.assertRaises(ValueError):
                    checked_metadata(wrong, good, run_id=RUN_ID, source=SOURCE)

    def test_external_artifact_meta_cannot_be_substituted(self):
        raw = sealed_zip()
        for key, value in (
            ("id", -1),
            ("expired", True),
            ("name", "memory-reader-bottleneck-source-diagnostics"),
            ("size_in_bytes", 0),
            ("digest", "sha256:garbage"),
        ):
            with self.subTest(key=key):
                wrong = listing(raw)
                wrong["artifacts"][0][key] = value
                with self.assertRaises(ValueError):
                    checked_metadata(
                        run(), wrong, run_id=RUN_ID, source=SOURCE
                    )

    def test_other_github_run_must_not_sign_model_artifacts(self):
        raw = sealed_zip()
        for field, value in (("id", 0), ("head_sha", "f" * 40)):
            with self.subTest(field=field):
                wrong = listing(raw)
                wrong["artifacts"][0]["workflow_run"][field] = value
                with self.assertRaises(ValueError):
                    checked_metadata(
                        run(), wrong, run_id=RUN_ID, source=SOURCE
                    )

    def test_duplicate_ids_names_and_missing_page_are_rejected(self):
        raw = sealed_zip()
        for field in ("id", "name"):
            with self.subTest(field=field):
                bad = listing(raw)
                extra = deepcopy(bad["artifacts"][0])
                extra[field] = bad["artifacts"][0][field]
                if field == "name":
                    extra["id"] += 1
                else:
                    extra["name"] = "memory-reader-bottleneck-smol-1.7b-1"
                bad["artifacts"].append(extra)
                bad["total_count"] = 2
                with self.assertRaises(ValueError):
                    checked_metadata(run(), bad, run_id=RUN_ID, source=SOURCE)
        bad = listing(raw)
        bad["total_count"] = 2
        with self.assertRaises(ValueError):
            checked_metadata(run(), bad, run_id=RUN_ID, source=SOURCE)

    def test_external_archive_digest_is_not_self_reported(self):
        raw = sealed_zip()
        record = checked_metadata(
            run(), listing(raw), run_id=RUN_ID, source=SOURCE
        )[0]
        checked_archive(raw, record)
        with self.assertRaisesRegex(ValueError, "external GitHub SHA256"):
            checked_archive(raw + b"edited", record)

    def test_valid_external_zip_with_false_inner_digest_is_rejected(self):
        raw = sealed_zip()
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files["host-gate.json"] = b'{"host_eligible":true}'
        with BytesIO() as out:
            with zipfile.ZipFile(out, "w") as archive:
                for name, value in files.items():
                    archive.writestr(name, value)
            corrupted = out.getvalue()
        record = dict(sha256=sha(corrupted), bytes=len(corrupted))
        with self.assertRaisesRegex(ValueError, "inner member SHA256"):
            checked_archive(corrupted, record)

    def test_ineligible_hardware_cannot_forge_original_answer(self):
        with self.assertRaisesRegex(ValueError, "hardware"):
            self.audited(sealed_zip(eligible=False, inference=True))

    def test_duplicate_or_nonfinite_json_is_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict_json(raw)

    @staticmethod
    def audited(data):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "artifact-114.zip").write_bytes(data)
            return audit(
                run(), listing(data), root, run_id=RUN_ID, source=SOURCE
            )


if __name__ == "__main__":
    unittest.main()
