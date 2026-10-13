"""Original byte / prompt / answer binding, NOT an independent human review."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reader_originals_attestation import (
    SCHEMA, audit_originals, canonical_sha, load_strict_json_file,
    source_fingerprint,
)


QTIME = "2026-01-02T00:00:00+00:00"
STIME = "2026-01-01T00:00:00+00:00"
ARMS = ("no_evidence", "ordinary_retrieval", "human_sufficient",
        "critical_premise_removed")


def question(qid):
    return dict(identity=qid, family="synthetic-test", scope=qid,
                content="What device?", observed_at=QTIME)


def source(qid, tag):
    content = f"Fact {tag} about {qid}."
    return dict(identity=f"{qid}-{tag}", root=f"root-{qid}-{tag}",
                scope=qid, session=f"session-{qid}", observed_at=STIME,
                content=content, start=0, end=len(content.encode("utf-8")))


def example():
    cohort = ["q1", "q2"]
    binding = dict(weights_sha256="a"*64, tokenizer_sha256="b"*64,
                   prompt_sha256="c"*64, dataset_sha256="d"*64,
                   revision="r1", decode_budget=64)
    originals = dict(schema=SCHEMA, cohort=cohort.copy(), model_binding=copy.deepcopy(binding), items=[])
    reviewed = []
    for qid in cohort:
        for arm in ARMS:
            src = dict(no_evidence=[], ordinary_retrieval=[source(qid, "b")],
                       human_sufficient=[source(qid, "a"), source(qid, "b")],
                       critical_premise_removed=[source(qid, "b")])[arm]
            grounded = arm == "human_sufficient"
            refusal = arm == "no_evidence" or arm == "critical_premise_removed"
            answer = "correct [E1]" if grounded else (
                "I do not have enough evidence." if refusal else "unverified")
            orig = dict(item_id=qid, condition=arm, question_record=question(qid),
                        input_ids=[ord(c) for c in qid + arm], raw_answer=answer,
                        delivered_sources=src)
            originals["items"].append(orig)
            reviewed.append(dict(item_id=qid, condition=arm,
                question_sha256=canonical_sha(orig["question_record"]),
                prompt_input_ids_sha256=canonical_sha(orig["input_ids"]),
                raw_answer_sha256=canonical_sha(answer),
                delivered_source_sha256=[source_fingerprint(x) for x in src],
                cited_source_sha256=[source_fingerprint(src[0])] if grounded else [],
                grounded_and_cited=grounded, exact_refusal=refusal))
    return cohort, binding, reviewed, originals


class OriginalAttestationTests(unittest.TestCase):
    def setUp(self):
        self.cohort, self.binding, self.reviewed, self.originals = example()

    def audit(self):
        return audit_originals(self.cohort, self.binding,
                               self.reviewed, self.originals)

    def test_valid_original_questions_answers_sources_and_citations(self):
        self.assertIsNone(self.audit())
        self.assertEqual(len(self.originals["items"]), 8)

    def test_answer_byte_change_fails(self):
        self.originals["items"][2]["raw_answer"] += " extra"
        self.assertEqual(self.audit(), "original-question-prompt-answer-or-citation-drift")

    def test_model_binding_change_fails(self):
        self.originals["model_binding"]["revision"]="r2"
        self.assertEqual(self.audit(), "original-source-manifest-schema-or-binding-mismatch")

    def test_unauthorized_source_byte_change_fails(self):
        self.originals["items"][2]["delivered_sources"][0]["content"]="different fact"
        self.assertTrue(self.audit() is not None)

    def test_prompt_retokenization_changes_digest(self):
        self.originals["items"][2]["input_ids"][0] += 1
        self.assertEqual(self.audit(), "original-question-prompt-answer-or-citation-drift")

    def test_citation_dropped_from_model_answer_cannot_be_claimed(self):
        self.originals["items"][2]["raw_answer"]="correct"
        self.reviewed[2]["raw_answer_sha256"] = canonical_sha("correct")
        self.assertEqual(self.audit(), "original-question-prompt-answer-or-citation-drift")

    def test_mention_of_e1_without_brackets_is_not_citation(self):
        self.originals["items"][2]["raw_answer"]="correct E1"
        self.reviewed[2]["raw_answer_sha256"] = canonical_sha("correct E1")
        self.assertEqual(self.audit(), "original-question-prompt-answer-or-citation-drift")

    def test_unknown_citation_is_rejected_even_when_claimed(self):
        self.originals["items"][2]["raw_answer"]="correct [E3]"
        self.assertEqual(self.audit(), "original-answer-cites-nonexistent-evidence")

    def test_future_source_is_invalid(self):
        self.originals["items"][2]["delivered_sources"][0]["observed_at"]="2027-01-01T00:00:00+00:00"
        self.assertEqual(self.audit(), "original-source-scope-time-or-identity-invalid")

    def test_cross_scope_source_is_invalid(self):
        self.originals["items"][2]["delivered_sources"][0]["scope"]="different-scope"
        self.assertEqual(self.audit(), "original-source-scope-time-or-identity-invalid")

    def test_valid_unicode_original_with_aligned_partial_utf8_window(self):
        source = self.originals["items"][2]["delivered_sources"][0]
        source["content"] = "前缀🙂目标知识"
        source["start"] = len("前缀".encode("utf-8"))
        source["end"] = len(source["content"].encode("utf-8"))
        new_fingerprint = source_fingerprint(source)
        self.reviewed[2]["delivered_source_sha256"][0] = new_fingerprint
        self.reviewed[2]["cited_source_sha256"][0] = new_fingerprint
        self.assertIsNone(self.audit())

    def test_changed_utf8_offset_is_rejected(self):
        self.originals["items"][2]["delivered_sources"][0]["end"] += 2
        self.assertEqual(self.audit(), "original-case-bytes-malformed")

    def test_missing_and_duplicate_originals_fail(self):
        removed = self.originals["items"].pop()
        self.assertEqual(self.audit(), "original-source-manifest-incomplete")
        self.originals["items"].append(copy.deepcopy(self.originals["items"][0]))
        self.assertEqual(self.audit(), "original-case-identity-incomplete-or-duplicate")
        self.originals["items"][-1]=removed
        self.assertIsNone(self.audit())

    def test_mixed_model_and_cohort_rejected(self):
        self.originals["cohort"]=["q2","q1"]
        self.assertEqual(self.audit(), "original-source-manifest-schema-or-binding-mismatch")

    def test_invalid_utf8_slice_boundary(self):
        s=self.originals["items"][2]["delivered_sources"][0]
        s["content"]="🎯match"
        s["start"]=1
        s["end"]=len(s["content"].encode())
        self.assertEqual(self.audit(), "original-case-bytes-malformed")

    def test_source_identity_duplicate(self):
        src=self.originals["items"][2]["delivered_sources"]
        src[1]["identity"]=src[0]["identity"]
        self.assertEqual(self.audit(), "original-source-scope-time-or-identity-invalid")

    def test_refusal_with_forged_bracket_citation_rejected(self):
        original=self.originals["items"][0]
        original["raw_answer"] = "I do not have enough evidence. [E1]"
        self.assertEqual(self.audit(), "original-answer-cites-nonexistent-evidence")

    def test_wrong_answer_hash_reviewer_cannot_change_source_artifact(self):
        self.reviewed[2]["raw_answer_sha256"]="f"*64
        self.assertEqual(self.audit(), "original-question-prompt-answer-or-citation-drift")


class OriginalFilePinTests(unittest.TestCase):
    """No artificial reviewer approval, model use or source ingress in these tests."""

    def source_bytes(self, root, raw):
        path = Path(root) / "originals.json"
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def test_unicode_raw_bytes_and_canonical_object_are_distinct_pins(self):
        payload = dict(观察="可信来源 🎯", nested={"答案": "设备"})
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, raw)
            decoded = load_strict_json_file(
                path, expected_file_sha256=sha, require_pin=True
            )
            self.assertEqual(decoded, payload)
            self.assertEqual(canonical_sha(decoded), canonical_sha(payload))
            # Unicode escapes produce the same object but DIFFERENT file bytes.
            escaped = json.dumps(payload, ensure_ascii=True,
                                 sort_keys=True).encode("utf-8")
            path.write_bytes(escaped)
            self.assertEqual(json.loads(escaped), payload)
            with self.assertRaisesRegex(ValueError, "raw-file SHA256 mismatch"):
                load_strict_json_file(
                    path, expected_file_sha256=sha, require_pin=True
                )

    def test_originals_file_pin_cannot_be_self_supplied(self):
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, b'{"items":[]}')
            with self.assertRaisesRegex(ValueError, "out-of-band-original-file-pin-required"):
                load_strict_json_file(path, require_pin=True)
            with self.assertRaisesRegex(ValueError, "out-of-band-original-file-pin-required"):
                load_strict_json_file(path, expected_file_sha256="not-sha", require_pin=True)
            self.assertEqual(
                load_strict_json_file(path, expected_file_sha256=sha, require_pin=True),
                {"items": []},
            )

    def test_duplicate_keys_fail_even_when_whole_file_hash_is_recalculated(self):
        raw = b'{"cohort":[],"cohort":["redefined"]}'
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, raw)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                load_strict_json_file(path, expected_file_sha256=sha, require_pin=True)

    def test_nested_duplicate_keys_are_rejected(self):
        raw = b'{"items":[{"raw_answer":"no","raw_answer":"yes"}]}'
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, raw)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                load_strict_json_file(path, expected_file_sha256=sha, require_pin=True)

    def test_nonfinite_numbers_and_invalid_utf8_fail(self):
        for raw in (b'{"metric":NaN}', b'{"metric":Infinity}',
                    b'{"content":"\xff"}', b''):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as root:
                path, sha = self.source_bytes(root, raw)
                with self.assertRaises(ValueError):
                    load_strict_json_file(path, expected_file_sha256=sha, require_pin=True)

    def test_json_array_or_scalar_cannot_be_reviewed_manifest(self):
        for raw in (b'[]', b'"signed"', b'123', b'null'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as root:
                path, sha = self.source_bytes(root, raw)
                with self.assertRaisesRegex(ValueError, "root must be an object"):
                    load_strict_json_file(path, expected_file_sha256=sha, require_pin=True)

    def test_bounded_read_rejects_oversize_without_unbounded_allocation(self):
        raw = b'{"payload":"' + b"a" * 100 + b'"}'
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, raw)
            with self.assertRaisesRegex(ValueError, "byte limit"):
                load_strict_json_file(path, expected_file_sha256=sha,
                                      require_pin=True, max_bytes=32)
            with self.assertRaisesRegex(ValueError, "file budget"):
                load_strict_json_file(path, expected_file_sha256=sha,
                                      require_pin=True, max_bytes=0)

    def test_symlink_source_and_ancestor_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            path, sha = self.source_bytes(root, b'{"valid":true}')
            link = Path(root) / "insecure.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_strict_json_file(link, expected_file_sha256=sha, require_pin=True)
            alias = Path(root) / "insecure_parent"
            alias.symlink_to(Path(root), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_strict_json_file(
                    alias / path.name, expected_file_sha256=sha, require_pin=True
                )


if __name__ == "__main__":
    unittest.main()
