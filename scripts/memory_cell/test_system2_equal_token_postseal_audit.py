"""Deterministic negative controls for authenticated model-output replay."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import system2_equal_token_postseal_audit as audit

ARCHIVE_ENV = "HEPTA_QWEN_EQUAL_TOKEN_ARCHIVE"


def artifact_path():
    return Path(os.environ.get(ARCHIVE_ENV, "/dev/null"))


def repackage(changed):
    """Construct a new, internally consistent ZIP to test semantic checks."""
    with zipfile.ZipFile(artifact_path()) as z:
        data = {name: z.read(name) for name in z.namelist()}
    data.update(changed)
    data["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  ./{name}\n"
        for name, content in sorted(data.items())
        if name != "SHA256SUMS"
    ).encode()
    dst = BytesIO()
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in data.items():
            z.writestr(name, content)
    return dst.getvalue()


class LocalContracts(unittest.TestCase):
    def test_literal_digest_follows_stable_json_semantics(self):
        self.assertEqual(audit.digest("abc"), hashlib.sha256(b'"abc"').hexdigest())
        self.assertNotEqual(audit.digest("abc"), hashlib.sha256(b"abc").hexdigest())

    def test_duplicate_keys_and_nonfinite_constants_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit.load_json('{"answer":"a","answer":"b"}')
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            audit.load_json('{"rate":NaN}')

    def test_risky_archive_and_unpinned_zip_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "externally pinned"):
            audit.read_archive(b"not an archive")
        with self.assertRaisesRegex(ValueError, "externally pinned"):
            audit.read_archive(b"A" * (8 * 1024 * 1024 + 1))

    def test_bad_symlink_member_with_own_sha_is_rejected(self):
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            info = zipfile.ZipInfo("nested/file")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            z.writestr(info, b"target")
            z.writestr("SHA256SUMS", b"")
        raw = out.getvalue()
        with self.assertRaisesRegex(ValueError, "unsafe"):
            audit.read_archive(raw, hashlib.sha256(raw).hexdigest())

    def test_missing_position_is_not_implicitly_scored_as_a_failure(self):
        expected = {("q", "arm", "view")}
        with self.assertRaisesRegex(ValueError, "missing"):
            audit.index([], expected)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit.index([dict(qid="q", arm="arm", view="view")] * 2, expected)

    def test_raw_fact_source_must_match_exact_rational_corpus_contract(self):
        doc = dict(
            excerpt="Device DEV-1234ABC requires clearance token TAG-1234ABC.",
            source_start=0,
            source_end=56,
        )
        doc["source_end"] = len(doc["excerpt"].encode())
        doc["source_digest"] = audit.digest(doc["excerpt"])
        self.assertEqual(audit.fact_from_source(doc), ("DEV-1234ABC", "TAG-1234ABC"))
        doc["source_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "detached"):
            audit.fact_from_source(doc)


@unittest.skipUnless(artifact_path().is_file(), "exact hosted ZIP not mounted")
class HostedArchiveAudit(unittest.TestCase):
    def test_original_200_outputs_validate_and_fail_safe_promotion(self):
        result = audit.audit(artifact_path())
        self.assertEqual((result["completed"], result["unique_questions"]), (200, 20))
        self.assertEqual(result["archive_verified_entries"], 21)
        self.assertFalse(result["safe_reader_adequacy"])
        lookup = {(x["arm"], x["view"]): x for x in result["groups"]}
        self.assertEqual(lookup["target_decoy_first", "unlabeled"]["exact_answers"], 19)
        self.assertEqual(lookup["target_decoy_last", "unlabeled"]["exact_answers"], 19)
        self.assertEqual(lookup["no_evidence", "unlabeled"]["exact_refusals"], 20)
        for view in ("e_label", "neutral_alias", "unlabeled"):
            self.assertEqual(lookup["decoy_only", view]["exact_refusals"], 0)
            self.assertEqual(lookup["decoy_only", view]["unsupported_copies"], 20)
        for arm in ("target_decoy_first", "target_decoy_last", "decoy_only"):
            paired = next(
                x
                for x in result["pairwise"]
                if x["arm"] == arm and x["second"] == "neutral_alias"
            )
            self.assertEqual(paired["input_token_delta"], 0)

    def test_outer_zip_pin_not_derived_from_the_archive_itself(self):
        original = artifact_path().read_bytes()
        tampered = original + b"tamper"
        with self.assertRaisesRegex(ValueError, "externally pinned"):
            audit.read_archive(tampered)

    def test_rehashed_manifest_cannot_replace_original_raw_answer_seal(self):
        with zipfile.ZipFile(artifact_path()) as z:
            rows = z.read("trial/raw-answers.jsonl").splitlines()
        changed = json.loads(rows[0])
        changed["answer"] = "TAG-FAKE000"
        rows[0] = json.dumps(changed, sort_keys=True).encode()
        forged = repackage({"trial/raw-answers.jsonl": b"\n".join(rows) + b"\n"})
        members = audit.read_archive(forged, hashlib.sha256(forged).hexdigest())
        with self.assertRaisesRegex(ValueError, "sealed"):
            audit.validate_replay(members)

    def test_rehashed_producer_summary_cannot_fabricate_safer_result(self):
        with zipfile.ZipFile(artifact_path()) as z:
            summary = json.loads(z.read("trial/summary.json"))
        summary["conditions"][0]["answers"] = 20
        forged = repackage({"trial/summary.json": json.dumps(summary).encode()})
        with self.assertRaisesRegex(ValueError, "score/cost replay"):
            # Caller can give a different outer hash only in this local test;
            # the production CLI pins the original GitHub ZIP unconditionally.
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "f.zip"
                f.write_bytes(forged)
                audit.audit(f, hashlib.sha256(forged).hexdigest())

    def test_rehashed_wrong_model_identity_rejected_even_with_seal_repin(self):
        with zipfile.ZipFile(artifact_path()) as z:
            rows = z.read("trial/raw-answers.jsonl").splitlines()
            seal = json.loads(z.read("trial/raw-seal.json"))
        item = json.loads(rows[0])
        item["reader"]["reader_identity"] = "attacker"
        rows[0] = json.dumps(item, sort_keys=True).encode()
        modified = b"\n".join(rows) + b"\n"
        seal["sha256"] = hashlib.sha256(modified).hexdigest()
        forged = repackage(
            {
                "trial/raw-answers.jsonl": modified,
                "trial/raw-seal.json": json.dumps(seal).encode(),
            }
        )
        members = audit.read_archive(forged, hashlib.sha256(forged).hexdigest())
        with patch.object(audit, "RAW_SEAL", seal["sha256"]):
            with self.assertRaisesRegex(ValueError, "provenance"):
                audit.validate_replay(members)

    def test_rehashed_token_alias_cost_drift_is_not_same_budget(self):
        with zipfile.ZipFile(artifact_path()) as z:
            lines = z.read("trial/raw-answers.jsonl").splitlines()
            seal = json.loads(z.read("trial/raw-seal.json"))
        item = json.loads(lines[0])
        item["reader"]["input_tokens"] += 1
        lines[0] = json.dumps(item, sort_keys=True).encode()
        modified = b"\n".join(lines) + b"\n"
        seal["sha256"] = hashlib.sha256(modified).hexdigest()
        forged = repackage(
            {
                "trial/raw-answers.jsonl": modified,
                "trial/raw-seal.json": json.dumps(seal).encode(),
            }
        )
        members = audit.read_archive(forged, hashlib.sha256(forged).hexdigest())
        with patch.object(audit, "RAW_SEAL", seal["sha256"]):
            with self.assertRaisesRegex(ValueError, "provenance"):
                audit.validate_replay(members)

    def test_model_outputs_remain_byte_identical_after_audit(self):
        before = hashlib.sha256(artifact_path().read_bytes()).hexdigest()
        audit.audit(artifact_path())
        after = hashlib.sha256(artifact_path().read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
