"""Fail-closed review-handoff upload tests; fixtures never become human verdicts."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import locomo_handoff_upload_audit as audit

ROLES = ("source", "answer", "manifest", "reader")
ENV_KEYS = {
    "source": "HEPTA_LOCOMO_SOURCE_REVIEW_ZIP",
    "answer": "HEPTA_LOCOMO_ANSWER_REVIEW_ZIP",
    "manifest": "HEPTA_LOCOMO_REVIEW_MANIFEST_ZIP",
    "reader": "HEPTA_LOCOMO_ORIGINAL_READER_ZIP",
}


def zip_copy(source: Path, target: Path, changes):
    """Rewrite a research ZIP for an adversarial fixture, not a real artifact."""
    with (
        zipfile.ZipFile(source) as old,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as new,
    ):
        for name in old.namelist():
            new.writestr(name, changes.get(name, old.read(name)))
    return sha256(target.read_bytes()).hexdigest()


def encoded(obj):
    return (
        json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode()


class OriginalUploadedHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = {
            role: Path(os.environ.get(env, "")) for role, env in ENV_KEYS.items()
        }
        if not all(
            os.environ.get(env) and cls.paths[role].is_file()
            for role, env in ENV_KEYS.items()
        ):
            raise unittest.SkipTest("original four source ZIPs not provided")
        cls.orig = {}
        for role, path in cls.paths.items():
            with zipfile.ZipFile(path) as source:
                cls.orig[role] = {name: source.read(name) for name in source.namelist()}
        cls.src = json.loads(cls.orig["source"]["sufficiency-only.json"])
        cls.ans = json.loads(cls.orig["answer"]["answer-and-citation.json"])
        cls.meta = json.loads(
            cls.orig["manifest"]["locomo-unreviewed-worklists/manifest.json"]
        )

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.paths_now = dict(self.paths)
        self.pins = dict(audit.PINS)

    def run_check(self):
        with patch.dict(audit.PINS, self.pins):
            return audit.audit(*(self.paths_now[name] for name in ROLES))

    def modify(self, *, first=None, second=None, model=None, update_manifest=True):
        """Re-pin adversarial changes so inner and outer hash checks alone can pass."""
        altered = {
            "source": encoded(first)
            if first is not None
            else self.orig["source"]["sufficiency-only.json"],
            "answer": encoded(second)
            if second is not None
            else self.orig["answer"]["answer-and-citation.json"],
        }
        for role, payload in altered.items():
            if (role == "source" and first is None) or (
                role == "answer" and second is None
            ):
                continue
            path = Path(self.dir.name) / f"changed-{role}.zip"
            member = (
                "sufficiency-only.json"
                if role == "source"
                else "answer-and-citation.json"
            )
            self.pins[role] = zip_copy(self.paths[role], path, {member: payload})
            self.paths_now[role] = path
        if update_manifest and (first is not None or second is not None):
            meta = deepcopy(self.meta)
            meta["sufficiency_worklist_sha256"] = sha256(altered["source"]).hexdigest()
            meta["answer_citation_worklist_sha256"] = sha256(
                altered["answer"]
            ).hexdigest()
            meta_raw = encoded(meta)
            sums = "".join(
                f"{sha256(value).hexdigest()}  ./{name}\n"
                for name, value in sorted(
                    {
                        "sufficiency-only.json": altered["source"],
                        "answer-and-citation.json": altered["answer"],
                        "manifest.json": meta_raw,
                    }.items()
                )
            ).encode()
            path = Path(self.dir.name) / "changed-manifest.zip"
            changes = {
                "locomo-unreviewed-worklists/manifest.json": meta_raw,
                "locomo-unreviewed-worklists/SHA256SUMS": sums,
            }
            self.pins["manifest"] = zip_copy(self.paths["manifest"], path, changes)
            self.paths_now["manifest"] = path
        if model is not None:
            model_raw = b"".join(encoded(row) for row in model)
            original = dict(self.orig["reader"])
            original["run/raw-answers.jsonl"] = model_raw
            sums = "".join(
                f"{sha256(value).hexdigest()}  ./{name}\n"
                for name, value in sorted(original.items())
                if name != "SHA256SUMS"
            ).encode()
            path = Path(self.dir.name) / "changed-reader.zip"
            self.pins["reader"] = zip_copy(
                self.paths["reader"],
                path,
                {"run/raw-answers.jsonl": model_raw, "SHA256SUMS": sums},
            )
            self.paths_now["reader"] = path

    def test_all_uploaded_stage_members_are_reproducible(self):
        result = self.run_check()
        self.assertEqual(result["original_model_answers_exact_match"], 32)
        self.assertEqual(result["original_delivered_source_spans_verified"], 192)
        self.assertEqual(result["actual_independent_reviewer_decisions"], 0)
        self.assertFalse(result["reviewer_access_separation_certified"])
        self.assertFalse(result["production_accepted"])

    def test_missing_first_stage_case_rejected_even_with_valid_reblessed_manifest(self):
        altered = deepcopy(self.src)
        altered["review_cases"].pop()
        self.modify(first=altered)
        with self.assertRaisesRegex(ValueError, "incomplete reviewer handoff"):
            self.run_check()

    def test_swapped_question_in_both_stages_rejected_by_original_query_digest(self):
        first, second = deepcopy(self.src), deepcopy(self.ans)
        first["review_cases"][0]["question"] = "Fabricated reviewer question"
        second["review_cases"][0]["question"] = "Fabricated reviewer question"
        self.modify(first=first, second=second)
        with self.assertRaisesRegex(ValueError, "review question or time detached"):
            self.run_check()

    def test_reblessed_original_reader_answer_change_rejected(self):
        original = [
            json.loads(line)
            for line in self.orig["reader"]["run/raw-answers.jsonl"].splitlines()
        ]
        original[0]["answer"] = "fabricated model answer"
        self.modify(model=original)
        with self.assertRaisesRegex(
            ValueError, "human review worklist falsely promoted"
        ):
            self.run_check()

    def test_reblessed_stage_two_answer_change_rejected(self):
        altered = deepcopy(self.ans)
        altered["review_cases"][0]["unedited_reader_answer"] = "different answer"
        self.modify(second=altered)
        with self.assertRaisesRegex(ValueError, "worklist answer altered"):
            self.run_check()

    def test_reblessed_stage_source_excerpt_change_rejected(self):
        first, second = deepcopy(self.src), deepcopy(self.ans)
        first["review_cases"][0]["evidence"][0]["original_text"] += " fabricated"
        second["review_cases"][0]["evidence"][0]["original_text"] += " fabricated"
        self.modify(first=first, second=second)
        with self.assertRaisesRegex(ValueError, "stage source is not"):
            self.run_check()

    def test_source_only_stage_cannot_contain_model_answer(self):
        altered = deepcopy(self.src)
        altered["review_cases"][0]["unedited_reader_answer"] = "future model answer"
        self.modify(first=altered)
        with self.assertRaisesRegex(ValueError, "source-only stage exposes"):
            self.run_check()

    def test_fabricated_human_verdict_rejected_even_after_reblessing(self):
        altered = deepcopy(self.src)
        altered["review_cases"][0]["sufficient_to_answer"] = True
        self.modify(first=altered)
        with self.assertRaisesRegex(
            ValueError, "stage-one reviewer verdict fabricated"
        ):
            self.run_check()

    def test_fabricated_second_stage_semantics_rejected(self):
        altered = deepcopy(self.ans)
        altered["review_cases"][0]["cited_claims_entailed"] = True
        self.modify(second=altered)
        with self.assertRaisesRegex(ValueError, "stage-two human verdict fabricated"):
            self.run_check()

    def test_reblessed_citation_labels_cannot_change_original_generation(self):
        altered = deepcopy(self.ans)
        altered["review_cases"][0]["cited_labels"] = ["E98765"]
        self.modify(second=altered)
        with self.assertRaisesRegex(
            ValueError, "model citation markers were rewritten"
        ):
            self.run_check()

    def test_truncated_original_reader_rejected(self):
        original = [
            json.loads(line)
            for line in self.orig["reader"]["run/raw-answers.jsonl"].splitlines()
        ]
        self.modify(model=original[:-1])
        with self.assertRaisesRegex(
            ValueError, "human review worklist falsely promoted"
        ):
            self.run_check()


class LocalProtocolTests(unittest.TestCase):
    def test_reject_duplicate_or_nonfinite_json(self):
        for raw in (b'{"x": 1, "x": 2}', b'{"x": NaN}', b'{"x": Infinity}'):
            with self.assertRaises(ValueError):
                audit.checked_json(raw)

    def test_manifest_detects_deleted_and_replaced_member(self):
        values = {"SHA256SUMS": b"0" * 64 + b"  file.txt\n", "file.txt": b"data"}
        with self.assertRaises(ValueError):
            audit.check_sha256sums(values)
        values.pop("file.txt")
        with self.assertRaises(ValueError):
            audit.check_sha256sums(values)

    def test_outer_zip_pin_must_match_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("file.txt", "data")
            with self.assertRaisesRegex(ValueError, "uploaded ZIP hash"):
                audit.load_zip(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
