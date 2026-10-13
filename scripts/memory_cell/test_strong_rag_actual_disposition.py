"""Pure-stdlib fixtures for the offline assessor, never model evidence."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from strong_rag_actual_disposition import (
    digest, open_verified, strict_json, validate_answers,
)


def fixture():
    content = "source event"
    doc = dict(identity="doc1", scope="q1", root="root1", content=content)
    case = dict(query=dict(identity="q1", content="Where?"), candidate_ids=["doc1"],
                candidate_digest=digest(("doc1",)))
    answer = "site_12345678 [E1]"
    delivered = dict(label="E1", original_id="doc1", id="native_digest", root="root1",
                     scope="q1", excerpt=content, source_start=0,
                     source_end=len(content.encode()), source_digest=digest(content))
    row = dict(question_id="q1", arm="k1", status="succeeded", kind="new_fact",
               answer=answer, selected=["doc1"], candidate_digest=case["candidate_digest"],
               receipt=dict(delivered_evidence=[delivered], input_ids_digest="prompt_digest",
                            input_tokens=10, generated_tokens=5, seconds=0.1,
                            trainable_parameters=0, production_accepted=False),
               citation_audit=dict(request=dict(answer=answer, query_id="q1",
                                                  question="Where?", prompt_digest="prompt_digest",
                                                  sources=[dict(label="E1", id="native_digest", excerpt=content)])))
    scored = row | dict(parsed_identifier="site_12345678", strict_task_success=True,
                        required_sources_covered=True)
    label = dict(id="q1", kind="new_fact", expected="site_12345678", support=["doc1"])
    return case, doc, row, scored, label


def make_zip(files, *, declared=None, symlink=False):
    payloads = dict(files)
    if declared is None:
        declared = {key: hashlib.sha256(content).hexdigest() for key, content in payloads.items()}
    sums = "".join(f"{sha}  ./{name}\n" for name, sha in sorted(declared.items()))
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        path = Path(tmp.name)
    with zipfile.ZipFile(path, "w") as z:
        for name, content in payloads.items():
            if symlink and name == "data.txt":
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, content)
            else:
                z.writestr(name, content)
        z.writestr("SHA256SUMS", sums)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


class IndependentReplayTests(unittest.TestCase):
    def score(self, raw=None, scored=None):
        case, doc, expected_raw, expected_scored, label = fixture()
        return validate_answers("calibration", [case], [doc],
                                [raw if raw is not None else expected_raw],
                                [scored if scored is not None else expected_scored],
                                [label], ("k1",), lambda case, arm: ["doc1"])

    def test_exact_original_source_is_scored_and_cited(self):
        stats, records = self.score()
        self.assertEqual(stats["k1"]["success"], 1)
        self.assertEqual(stats["k1"]["full_citation"], 1)
        self.assertEqual(stats["k1"]["prompt_tokens"], 10)
        self.assertEqual(set(records), {"q1"})

    def test_answer_or_receipt_rewrite_is_rejected(self):
        _, _, raw, scored, _ = fixture()
        edited = deepcopy(scored)
        edited["answer"] = "site_00000000 [E1]"
        with self.assertRaisesRegex(ValueError, "scorer altered"):
            self.score(raw, edited)
        edited = deepcopy(raw)
        edited["receipt"]["delivered_evidence"][0]["excerpt"] = "fabricated"
        with self.assertRaisesRegex(ValueError, "original evidence"):
            self.score(edited, edited | dict(parsed_identifier="site_12345678",
                                             strict_task_success=True,
                                             required_sources_covered=True))

    def test_faked_task_score_and_missing_citation_rejected(self):
        _, _, raw, scored, _ = fixture()
        forged = deepcopy(scored)
        forged["strict_task_success"] = False
        with self.assertRaisesRegex(ValueError, "task success"):
            self.score(raw, forged)
        edited = deepcopy(raw)
        edited["citation_audit"]["request"]["answer"] = "different answer"
        with self.assertRaisesRegex(ValueError, "citation request"):
            self.score(edited, edited | dict(parsed_identifier="site_12345678",
                                             strict_task_success=True,
                                             required_sources_covered=True))

    def test_duplicate_or_nonfinite_json_rejected(self):
        for payload in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(payload)

    def test_zip_manifest_accepts_complete_and_rejects_changed_member(self):
        good, sha = make_zip({"data.txt": b"correct"})
        try:
            z, meta = open_verified(good, expected_sha=sha)
            self.assertEqual(meta["verified_members"], 1)
            z.close()
        finally:
            good.unlink()
        wrong, sha = make_zip({"data.txt": b"wrong"},
                              declared={"data.txt": hashlib.sha256(b"correct").hexdigest()})
        try:
            with self.assertRaisesRegex(ValueError, "inner archive member"):
                open_verified(wrong, expected_sha=sha)
        finally:
            wrong.unlink()

    def test_extra_zip_member_and_symlink_rejected(self):
        extra, sha = make_zip({"data.txt": b"correct", "undisclosed.txt": b"leak"},
                              declared={"data.txt": hashlib.sha256(b"correct").hexdigest()})
        try:
            with self.assertRaisesRegex(ValueError, "unlisted"):
                open_verified(extra, expected_sha=sha)
        finally:
            extra.unlink()
        link, sha = make_zip({"data.txt": b"destination"}, symlink=True)
        try:
            with self.assertRaisesRegex(ValueError, "symlink"):
                open_verified(link, expected_sha=sha)
        finally:
            link.unlink()


if __name__ == "__main__":
    unittest.main()
