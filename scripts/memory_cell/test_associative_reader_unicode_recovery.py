"""Immutable original-source Unicode recovery: contract tests, never model scores."""
from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
import unittest

from associative_locomo_shadow import canonical, strict_json, read_regular
import associative_reader_unicode_recovery as recover

ROOT = os.environ.get("HEPTA_ASSOC_UNICODE_FIXTURE")


class ReadPlanContractTests(unittest.TestCase):
    def test_reject_nonexistent_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            with self.assertRaisesRegex(ValueError,"two-file"):
                recover.read_plan(p)
            (p/"private.json").write_text("{}")
            with self.assertRaisesRegex(ValueError,"two-file"):
                recover.read_plan(p)

    def test_lesion_order_is_stable_and_keeps_others(self):
        ids=["D3:3","D5:5","D23:15","D22:12"]
        removed=recover._lesion("conv-49/q0014",ids)
        self.assertIn(removed,ids)
        self.assertEqual(removed,recover._lesion("conv-49/q0014",list(ids)))
        self.assertEqual(len([x for x in ids if x != removed]),3)

    def test_reject_extra_or_duplicate_pair(self):
        data=dict(schema=recover.SCHEMA,original_plan_sha256=recover.PINNED_V1_PLAN_SHA256,
                  public_sha256=recover.PINNED_PUBLIC_SHA256,dataset_sha256=recover.DATASET_SHA256,
                  planned_questions=20,planned_attempts=40,recovered_questions=["conv-49/q0014"],
                  recovered_source_ids=["D22:12","D23:15"],arms=list(recover.ARMS),
                  raw_gold_answers_included=False,production_accepted=False,entries=[])
        with self.assertRaisesRegex(ValueError,"incomplete"):
            recover._validate_plan(data)
        data["recovered_source_ids"]=["forged"]
        with self.assertRaisesRegex(ValueError,"invalid or unregistered"):
            recover._validate_plan(data)


@unittest.skipUnless(ROOT and Path(ROOT).is_dir(), "pinned dataset/old plan/source view not staged")
class RegisteredOriginalSourceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(ROOT)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        self.original=self.root/"locomo.json"
        self.v1=self.root/"v1plan"
        self.public=self.root/"public.json"

    def plan(self):
        target=self.work/"plan"
        receipt=recover.produce(self.original,self.v1,self.public,target)
        return receipt,target

    def test_exact_unicode_source_recovery_and_no_gold_fields(self):
        receipt,path=self.plan()
        self.assertEqual(receipt["annotated_sources_available"],20)
        self.assertEqual(receipt["recovered_source_ids"],["D22:12","D23:15"])
        self.assertFalse(receipt["production_accepted"])
        doc,seal=recover.read_plan(path)
        self.assertEqual(seal["plan_sha256"],receipt["plan_sha256"])
        changed=[x for x in doc["entries"] if x["question_id"]=="conv-49/q0014"]
        self.assertEqual(len(changed),2)
        self.assertEqual(len(changed[0]["evidence"]),4)
        self.assertEqual(len(changed[1]["evidence"]),3)
        texts=" ".join(d["text"] for d in changed[0]["evidence"])
        self.assertIn("—",texts)
        self.assertIn("’",texts)
        self.assertNotIn('"answer":',read_regular(path/"plan.json").decode())
        self.assertFalse(doc["independently_verified_semantic_sufficiency"])
        self.assertFalse(doc["retriever_or_memory_utility_comparison"])

    def test_existing_19_source_views_byte_for_byte(self):
        _,path=self.plan()
        doc,_=recover.read_plan(path)
        old,_=recover.read_v1_plan(self.v1)
        oldmap={(q["question_id"],q["arm"]):q for q in old["entries"]}
        for row in doc["entries"]:
            if row["question_id"]!="conv-49/q0014":
                self.assertEqual(row,oldmap[row["question_id"],row["arm"]])

    def test_no_relabel_or_silent_original_overwrite(self):
        receipt,path=self.plan()
        raw=(path/"plan.json").read_bytes()
        (path/"plan.json").write_bytes(raw+b" ")
        with self.assertRaisesRegex(ValueError,"unsealed"):
            recover.read_plan(path)

    def test_reject_extra_hidden_file_next_to_reader_input(self):
        _,path=self.plan()
        (path/"private.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError,"two-file"):
            recover.read_plan(path)

    def test_reject_replaced_original_dataset_before_plan_creation(self):
        p=self.work/"forged.json"
        p.write_bytes(self.original.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"digest changed"):
            recover.produce(p,self.v1,self.public,self.work/"plan")

    def test_reproducible_plan_byte_identity(self):
        receipt,_=self.plan()
        dest=self.work/"second"
        other=recover.produce(self.original,self.v1,self.public,dest)
        self.assertEqual(receipt["plan_sha256"],other["plan_sha256"])

    def test_review_mechanics_preserve_failed_reader_attempts(self):
        _,plan_path=self.plan()
        plan,seal=recover.read_plan(plan_path)
        rows=[dict(question_id=e["question_id"],family=e["family"],arm=e["arm"],
              evidence_ids=[x["source_id"] for x in e["evidence"]],
              result=dict(status="failed",reason="synthetic-mechanics",answer=None))
              for e in plan["entries"]]
        dest=self.work/"fake_reader";dest.mkdir()
        sha=recover.exclusive(dest/"reader-journal.json",rows)
        recover.exclusive(dest/"reader-seal.json",dict(schema=recover.READER_SCHEMA,
            journal_sha256=sha,plan_sha256=seal["plan_sha256"],planned=40,
            labels_visible=False,reader_identity=recover.REGISTERED_READER_IDENTITY,
            production_accepted=False))
        report=recover.review(self.original,self.v1,self.public,plan_path,dest,self.work/"report.json")
        self.assertEqual(report["source_supported_questions"],20)
        self.assertEqual(report["by_arm"]["annotated_all"]["statuses"]["failed"],20)
        self.assertIsNone(report["by_arm"]["annotated_all"]["mean_token_f1"])
        self.assertFalse(report["memorycell_gain_claim"])

    def test_forged_reader_source_ids_rejected(self):
        _,path=self.plan()
        plan,seal=recover.read_plan(path)
        rows=[dict(question_id=e["question_id"],family=e["family"],arm=e["arm"],
              evidence_ids=[x["source_id"] for x in e["evidence"]],
              result=dict(status="failed",reason="fixture",answer=None))
              for e in plan["entries"]]
        rows[0]["evidence_ids"]=["forged:1"]
        dest=self.work/"forged_reader";dest.mkdir()
        sha=recover.exclusive(dest/"reader-journal.json",rows)
        recover.exclusive(dest/"reader-seal.json",dict(schema=recover.READER_SCHEMA,
            journal_sha256=sha,plan_sha256=seal["plan_sha256"],planned=40,
            labels_visible=False,reader_identity=recover.REGISTERED_READER_IDENTITY,
            production_accepted=False))
        with self.assertRaisesRegex(ValueError,"unregistered evidence"):
            recover.review(self.original,self.v1,self.public,path,dest,self.work/"report.json")


if __name__=="__main__":
    unittest.main()
