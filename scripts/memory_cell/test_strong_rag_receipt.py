"""Independent-replay integrity tests; all synthetic answers remain fixtures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from native import digest
import strong_rag_receipt as audit


def source_case():
    event = dict(
        schema="hepta.controlled-event.v1", id="event_1", entity="service_1",
        attribute="location", value="site_11111111", revision=1,
        supersedes=[],
    )
    content = json.dumps(event, sort_keys=True)
    q = dict(
        identity="q1", family="f1", scope="scope1",
        content="Which site?", observed_at="2026-01-01T00:00:00+00:00",
    )
    doc = dict(
        identity="event_1", root="root_1", scope="scope1",
        session="scope1", observed_at=q["observed_at"], content=content,
        assets=[],
    )
    derivation = dict(
        label="E1", original_id="event_1", original_digest=digest(content),
        text=(
            "Event event_1: at logical revision 1, entity service_1 has attribute "
            "location with value site_11111111. Superseded event IDs: none "
            "explicitly named. This is a logical state revision, not a calendar date."
        ),
        derivation_profile=audit.VIEW,
    )
    delivered = dict(
        label="E1", original_id="event_1", root="root_1", scope="scope1",
        observed_at=q["observed_at"], source_start=0,
        source_end=len(content.encode()), excerpt=content,
        source_digest=digest(content),
    )
    receipt = dict(
        reader_identity="r" * 64,
        reader_profile="a" * 64,
        view_profile=audit.VIEW,
        query_digest=digest(q),
        token_limit=audit.LIMIT,
        input_tokens=155,
        generated_tokens=12,
        trainable_parameters=0,
        answer_postprocessed=False,
        production_accepted=False,
        seconds=0.1,
        input_ids_digest="b" * 64,
        delivered_evidence=[delivered],
        derived_evidence=[derivation],
        derived_view_digest=digest([derivation]),
    )
    answer = "site_11111111 [E1]"
    row = dict(
        question_id="q1", kind="new_fact", arm="k1",
        selected=["event_1"], candidate_digest="pool1", status="succeeded",
        answer=answer, receipt=receipt,
        citation_audit=dict(
            request=dict(
                query_id="q1", scope="scope1", question=q["content"],
                question_time=q["observed_at"], answer=answer,
                prompt_digest="b" * 64,
            ),
            judgement=None, production_accepted=False,
        ),
    )
    case = dict(query=q, kind="new_fact", candidate_digest="pool1")
    return row, case, doc


def seal(root):
    files = []
    for path in root.rglob("*"):
        if path.is_file() and path.name != "SHA256SUMS":
            rel = path.relative_to(root).as_posix()
            files.append((rel, hashlib.sha256(path.read_bytes()).hexdigest()))
    (root / "SHA256SUMS").write_text(
        "".join(f"{h}  ./{rel}\n" for rel, h in sorted(files)), encoding="utf-8"
    )


class ReceiptValidationTests(unittest.TestCase):
    def test_exact_pinned_original_and_derived_source_in_historical_profile(self):
        row, case, doc = source_case()
        profiles = set()
        audit._check_row(row, case, ("event_1",), {doc["identity"]: doc}, "r" * 64, profiles=profiles)
        self.assertEqual(profiles, {"a" * 64})

    def test_rejects_source_replacement_or_fake_derived_value(self):
        row, case, doc = source_case()
        for target, field, replacement in (
            ("delivered_evidence", "excerpt", "fake evidence"),
            ("delivered_evidence", "source_start", 1),
            ("derived_evidence", "text", "fabricated summary"),
        ):
            bad = deepcopy(row)
            bad["receipt"][target][0][field] = replacement
            with self.assertRaises(ValueError):
                audit._check_row(bad, case, ("event_1",), {doc["identity"]: doc}, "r" * 64, profiles=set())

    def test_rejects_changed_reader_generation_and_citation_trace(self):
        row, case, doc = source_case()
        for target, field, replacement in (
            ("receipt", "reader_identity", "fake"),
            ("receipt", "trainable_parameters", 1),
            ("receipt", "token_limit", 8192),
            ("receipt", "input_tokens", 2049),
            ("receipt", "answer_postprocessed", True),
            ("citation_audit", "judgement", "fake independent judge"),
        ):
            bad = deepcopy(row)
            bad[target][field] = replacement
            with self.assertRaises(ValueError):
                audit._check_row(bad, case, ("event_1",), {doc["identity"]: doc}, "r" * 64, profiles=set())

    def test_failed_generation_may_not_supply_oracle_answer(self):
        row, case, doc = source_case()
        row["status"] = "failed"
        with self.assertRaises(ValueError):
            audit._check_row(row, case, ("event_1",), {doc["identity"]: doc}, "r" * 64, profiles=set())
        for key in ("answer", "receipt", "citation_audit"):
            row.pop(key)
        audit._check_row(row, case, ("event_1",), {doc["identity"]: doc}, "r" * 64, profiles=set())

    def test_archive_manifest_detects_replacements_additions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "run").mkdir()
            (root / "run/result.json").write_text('{"ok": true}')
            seal(root)
            self.assertEqual(audit.verify_manifest(root), 1)
            (root / "run/result.json").write_text('{"ok": false}')
            with self.assertRaises(ValueError):
                audit.verify_manifest(root)
            seal(root)
            (root / "other").write_text("not accounted")
            with self.assertRaises(ValueError):
                audit.verify_manifest(root)
            (root / "other").unlink()
            (root / "other").symlink_to(root / "run/result.json")
            with self.assertRaises(ValueError):
                audit.verify_manifest(root)

    def test_json_duplicates_nonfinite_and_orphan_lines_reject(self):
        with self.assertRaises(ValueError):
            audit.strict_json('{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            audit.strict_json('{"x":NaN}')
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "raw-answers.jsonl"
            out.write_text('{"status":"succeeded"}')
            with self.assertRaises(ValueError):
                audit._raw_lines(out, expected=1)
            out.write_text('{"status":"succeeded"}\n')
            self.assertEqual(len(audit._raw_lines(out, expected=1)), 1)

    def test_scorer_does_not_rewrite_original_answer_or_hide_wrong_answer(self):
        row, _, _ = source_case()
        labels = [dict(
            id="q1", kind="new_fact", expected="site_11111111",
            support=["event_1"],
        )]
        raw = [row]
        scored = deepcopy(raw)
        audit._score(scored, labels, expected=["q1"], arms=("k1",))
        result = audit._check_scored(raw, scored, labels, ["q1"], ("k1",))
        self.assertTrue(result[0]["strict_task_success"])
        bad = deepcopy(scored)
        bad[0]["answer"] = "site_22222222 [E1]"
        with self.assertRaises(ValueError):
            audit._check_scored(raw, bad, labels, ["q1"], ("k1",))
        bad = deepcopy(scored)
        bad[0]["strict_task_success"] = False
        with self.assertRaises(ValueError):
            audit._check_scored(raw, bad, labels, ["q1"], ("k1",))


if __name__ == "__main__":
    unittest.main()
