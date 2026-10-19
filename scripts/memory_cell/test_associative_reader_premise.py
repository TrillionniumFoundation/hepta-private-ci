"""No-LLM contract tests for the privileged Reader premise diagnostic."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

import test_associative_question_conditioned as fixture
import associative_question_conditioned as q
import associative_reader_premise as premise


class PremiseTests(unittest.TestCase):
    def setUp(self):
        fixture.ContractTests.setUp(self)
        self.plan_dir=self.root/"plan"

    def create(self):
        return premise.make_plan(self.prepared,self.run,self.plan_dir)

    def fake_response(self, *, strip_last=False, bad_source=False):
        plan,_=premise._read_plan(self.plan_dir)
        output=self.root/"results";output.mkdir()
        rows=[]
        for e in plan["entries"]:
            ids=[s["source_id"] for s in e["evidence"]]
            if bad_source and not rows: ids=["D999:1"]
            rows.append(dict(question_id=e["question_id"], arm=e["arm"],family=e["family"],
                  evidence_ids=ids,
                  result=dict(status="succeeded",answer="event 1",reader_identity=premise.REGISTERED_READER_IDENTITY) if e["source_support_complete"]
                         else dict(status="unavailable",reason="missing-annotated-source",answer=None)))
        if strip_last: rows.pop()
        record_sha=q.exclusive(output/"reader-journal.json",rows)
        q.exclusive(output/"reader-seal.json",dict(schema=premise.READER_SCHEMA,
            plan_sha256=premise._read_plan(self.plan_dir)[1]["plan_sha256"],
            source_journal_sha256=self.seal["journal_sha256"],
            reader_journal_sha256=record_sha,planned=40,
            frozen_reader_identity=premise.REGISTERED_READER_IDENTITY,
            gold_answer_bytes_visible=False,production_accepted=False))
        return output

    def test_plan_exact_census_and_no_gold_answer(self):
        r=self.create()
        self.assertEqual(r["planned_questions"],20)
        self.assertEqual(r["planned_attempts"],40)
        self.assertEqual(r["source_supported_questions"],20)
        raw=(self.plan_dir/"plan.json").read_text()
        self.assertNotIn('"answer":',raw)
        plan,seal=premise._read_plan(self.plan_dir)
        self.assertEqual(seal["plan_sha256"],q.sha256((self.plan_dir/"plan.json").read_bytes()))
        self.assertTrue(plan["gold_selected_source_ids_used"])
        self.assertFalse(plan["independently_verified_sufficiency"])

    def test_each_supported_case_removes_exactly_one_source(self):
        self.create()
        plan,_=premise._read_plan(self.plan_dir)
        for i in range(0,40,2):
            all_ids={x["source_id"] for x in plan["entries"][i]["evidence"]}
            missing_ids={x["source_id"] for x in plan["entries"][i+1]["evidence"]}
            self.assertEqual(len(all_ids-missing_ids),1)
            self.assertEqual(len(missing_ids-all_ids),0)

    def test_plan_denies_hidden_file_same_dir(self):
        self.create()
        (self.plan_dir/"private.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"two-file"):
            premise._read_plan(self.plan_dir)

    def test_plan_sha_tamper_rejected(self):
        self.create()
        with (self.plan_dir/"plan.json").open("ab") as s: s.write(b" ")
        with self.assertRaisesRegex(ValueError,"unsealed"):
            premise._read_plan(self.plan_dir)

    def test_plan_forged_duplicate_question_rejected_even_if_resealed(self):
        self.create()
        plan=json.loads((self.plan_dir/"plan.json").read_text())
        plan["entries"][1]=plan["entries"][0]
        sha=q.sha256(q.canonical(plan))
        (self.plan_dir/"plan.json").write_bytes(q.canonical(plan))
        seal=json.loads((self.plan_dir/"seal.json").read_text())
        seal["plan_sha256"]=sha
        (self.plan_dir/"seal.json").write_bytes(q.canonical(seal))
        with self.assertRaisesRegex(ValueError,"duplicate privileged"):
            premise._read_plan(self.plan_dir)

    def test_private_reference_drift_fails_closed(self):
        (self.prepared/"private.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            self.create()

    def test_missing_ancestor_is_reported_not_substituted(self):
        qid=sorted(q._select_reader_questions(self.record, 2))[0]
        self.hidden["annotations"][qid]["evidence"]=["D999:1"]
        private_sha=q.sha256(q.canonical(self.hidden))
        (self.prepared/"private.json").write_bytes(q.canonical(self.hidden))
        self.meta["private_sha256"]=private_sha
        (self.prepared/"manifest.json").write_bytes(q.canonical(self.meta))
        (self.public/"manifest.json").write_bytes(q.canonical(self.meta))
        p=self.create()
        self.assertEqual(p["source_supported_questions"],19)
        plan,_=premise._read_plan(self.plan_dir)
        for arm in premise.ARMS:
            entry=next(i for i in plan["entries"] if i["question_id"]==qid and i["arm"]==arm) if any(i["question_id"]==qid for i in plan["entries"]) else None
            # A given fixture question may not be among hashed selections;
            # in that case the generated plan still has a valid complete census.
            if entry is not None:
                self.assertFalse(entry["evidence"])

    def test_review_tracks_all_attempts_and_nonindependent_score(self):
        self.create();o=self.fake_response()
        report=premise.review(self.prepared,self.public,self.run,self.plan_dir,o,self.root/"review.json")
        self.assertEqual(report["by_arm"]["annotated_all"]["planned"],20)
        self.assertEqual(report["by_arm"]["annotated_all"]["scored_answers"],20)
        self.assertFalse(report["semantic_sufficiency_certified"])
        self.assertFalse(report["production_accepted"])
        self.assertEqual(report["paired_scored_count"],20)

    def test_review_rejects_missing_one_arm(self):
        self.create();o=self.fake_response(strip_last=True)
        with self.assertRaisesRegex(ValueError,"incomplete"):
            premise.review(self.prepared,self.public,self.run,self.plan_dir,o,self.root/"report.json")

    def test_review_rejects_source_identity_substitution(self):
        self.create();o=self.fake_response(bad_source=True)
        with self.assertRaisesRegex(ValueError,"source-payload"):
            premise.review(self.prepared,self.public,self.run,self.plan_dir,o,self.root/"report.json")

    def test_review_rejects_hidden_reference_mutation_after_plan(self):
        self.create();o=self.fake_response()
        self.hidden["annotations"][next(iter(self.hidden["annotations"]))]["evidence"]=["D999:1"]
        (self.prepared/"private.json").write_bytes(q.canonical(self.hidden))
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            premise.review(self.prepared,self.public,self.run,self.plan_dir,o,self.root/"report.json")

    def test_real_source_paired_plan_when_staged(self):
        source=os.environ.get("HEPTA_ASSOC_FULLSOURCE_PREPARED")
        ranked=os.environ.get("HEPTA_ASSOC_FULLSOURCE_RANK")
        if not source or not ranked:
            self.skipTest("pinned original reference not staged")
        with tempfile.TemporaryDirectory() as temp:
            info=premise.make_plan(source,ranked,Path(temp)/"plan")
            self.assertEqual(info["source_supported_questions"],19)
            self.assertEqual(info["planned_questions"],20)

if __name__=="__main__":
    unittest.main()
