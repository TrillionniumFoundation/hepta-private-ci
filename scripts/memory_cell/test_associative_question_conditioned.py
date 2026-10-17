"""Pre-registered question-conditioned MemoryCell study: adversarial contract tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

import associative_question_conditioned as q


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.prepared=self.root/"prepared"
        self.public=self.root/"public"
        self.run=self.root/"run"
        self.prepared.mkdir();self.public.mkdir();self.run.mkdir()
        groups=[]
        private={}
        for i in range(10):
            family=f"conv-{i+1}"
            docs=[dict(id=f"D{i+1}:{j+1}",speaker="Alice",text=f"event {j} scheduled for Sunday",
                       session="session_1",seq=j+1,kind="semantic") for j in range(128)]
            queries=[dict(id=f"{family}/q{j:04d}",text=f"What was discussed about event {j}?",
                          kind=q.kind_of(f"What was discussed about event {j}?"))
                     for j in range(24)]
            for j,query in enumerate(queries):
                private[query["id"]]=dict(evidence=[docs[j]["id"]],
                                         unresolved_reference=False,category=1,
                                         answer_available=True,answer=f"event {j}")
            groups.append(dict(family=family,sources=docs,questions=queries))
        self.record=dict(schema=q.SCHEMA,dataset_sha256=q.DATASET_SHA256,
                         policy=dict(source_policy="all-eligible-ascii",source_max=q.SOURCES_MAX,
                                     question_limit=24,train_prefix=128),families=groups)
        self.hidden=dict(schema=q.SCHEMA,annotations=private)
        pub_hash=q.exclusive(self.prepared/"public.json",self.record)
        private_hash=q.exclusive(self.prepared/"private.json",self.hidden)
        self.meta=dict(schema=q.SCHEMA,dataset_sha256=q.DATASET_SHA256,
                       public_sha256=pub_hash,private_sha256=private_hash,
                       family_count=10,source_count=1280,question_count=240,
                       labels_used_for_training=False,production_accepted=False)
        q.exclusive(self.prepared/"manifest.json",self.meta)
        (self.public/"public.json").write_bytes((self.prepared/"public.json").read_bytes())
        (self.public/"manifest.json").write_bytes((self.prepared/"manifest.json").read_bytes())
        self.journal=[]
        for group in groups:
            identifiers=[d["id"] for d in group["sources"][:8]]
            for question in group["questions"]:
                self.journal.append(dict(question_id=question["id"],family=group["family"],
                                         kind=question["kind"],predictions={
                                           arm:list(identifiers) for arm in q.ARMS}))
        digest=q.exclusive(self.run/"journal.json",self.journal)
        self.seal=dict(schema=q.SCHEMA,public_sha256=pub_hash,journal_sha256=digest,
                       complete_count=240,arms=list(q.ARMS),training_question_labels_accessed=False)
        q.exclusive(self.run/"seal.json",self.seal)

    def test_verified_public_and_private_are_physically_separated(self):
        record,manifest=q._read_public(self.public)
        self.assertEqual(len(record["families"]),10)
        self.assertNotIn("answer",(self.public/"public.json").read_text())
        self.assertEqual(manifest["public_sha256"],q.sha256((self.public/"public.json").read_bytes()))

    def test_hidden_source_poison_rejected(self):
        (self.public/"private.json").write_text("{}");
        with self.assertRaisesRegex(ValueError,"hidden labels"):
            q._read_public(self.public)

    def test_test_answer_exposure_rejected(self):
        self.record["families"][0]["questions"][0]["answer"]="leak"
        with self.assertRaisesRegex(ValueError,"labels"):
            q._check_public(self.record)

    def test_invalid_source_order_rejected(self):
        self.record["families"][0]["sources"][0]["seq"]=777
        with self.assertRaisesRegex(ValueError,"chronology"):
            q._check_public(self.record)

    def test_duplicate_original_source_rejected(self):
        docs=self.record["families"][0]["sources"]
        docs[1]["id"]=docs[0]["id"]
        with self.assertRaisesRegex(ValueError,"duplicated identity"):
            q._check_public(self.record)

    def test_question_probes_have_no_reference_annotations(self):
        doc=self.record["families"][0]["sources"][1]
        self.assertIn("What did Alice say about",q.pseudo_question(doc))
        doc["answer"]="injected"
        with self.assertRaisesRegex(ValueError,"synthetic question"):
            q.pseudo_question(doc)

    def test_no_answer_labels_pass_into_reader(self):
        rows=list(q.reader_inputs(self.public,self.run,per_family=2))
        self.assertEqual(len(rows),100)
        self.assertEqual({r["arm"] for r in rows},set(q.READER_ARMS))
        for row in rows:
            self.assertNotIn("answer",json.dumps(row))
            if row["arm"]=="empty":
                self.assertFalse(row["evidence"])
            else:
                self.assertEqual(len(row["evidence"]),8)
                self.assertEqual([e["label"] for e in row["evidence"]],
                                 [f"E{i}" for i in range(1,9)])

    def test_query_budget_census_is_deterministic(self):
        public,_=q._read_public(self.public)
        ids=q._select_reader_questions(public,3)
        self.assertEqual(ids,q._select_reader_questions(public,3))
        self.assertEqual(len(ids),30)
        with self.assertRaisesRegex(ValueError,"pre-registered"):
            q._select_reader_questions(public,20)

    def test_source_id_forgery_rejected_before_review(self):
        self.journal[0]["predictions"]["rrf"][0]="D12345:1"
        (self.run/"journal.json").write_bytes(q.canonical(self.journal))
        self.seal["journal_sha256"]=q.sha256((self.run/"journal.json").read_bytes())
        (self.run/"seal.json").write_bytes(q.canonical(self.seal))
        with self.assertRaisesRegex(ValueError,"non-source"):
            q._checked_run(self.public,self.run)

    def test_unsealed_prediction_mutation_rejected(self):
        self.journal[0]["predictions"]["bm25"].reverse()
        (self.run/"journal.json").write_bytes(q.canonical(self.journal))
        with self.assertRaisesRegex(ValueError,"unsealed"):
            q._checked_run(self.public,self.run)

    def test_duplicate_query_rejected_even_with_new_valid_seal(self):
        self.journal[1]=self.journal[0]
        (self.run/"journal.json").write_bytes(q.canonical(self.journal))
        self.seal["journal_sha256"]=q.sha256((self.run/"journal.json").read_bytes())
        (self.run/"seal.json").write_bytes(q.canonical(self.seal))
        with self.assertRaisesRegex(ValueError,"duplicate inference"):
            q._checked_run(self.public,self.run)

    def test_review_only_reads_pinned_hidden_after_seal(self):
        result=q.review(self.prepared,self.run,self.root/"review.json")
        self.assertEqual(result["planned_questions"],240)
        self.assertEqual(result["reference_positive"],240)
        self.assertEqual(result["reference_eligible"],240)
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["semantic_citation_precision"])

    def test_reference_modification_fails(self):
        (self.prepared/"private.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            q.review(self.prepared,self.run,self.root/"review.json")

    def test_reader_review_all_planned_or_fail(self):
        public,_=q._read_public(self.public)
        chosen=q._select_reader_questions(public,1)
        output=self.root/"reader";output.mkdir()
        records=[]
        for row in q.reader_inputs(self.public,self.run,per_family=1):
            records.append(dict(question_id=row["question_id"],family=row["family"],
                                arm=row["arm"],evidence_ids=[s["source_id"] for s in row["evidence"]],
                                result=dict(status="succeeded",answer="event 1")))
        digest=q.exclusive(output/"reader-journal.json",records)
        q.exclusive(output/"reader-seal.json",dict(schema=q.READER_SCHEMA,
            source_journal_sha256=self.seal["journal_sha256"],reader_journal_sha256=digest,
            per_family=1,labels_visible=False))
        report=q.review_reader(self.prepared,self.run,output,self.root/"reader-review.json")
        self.assertEqual(report["by_arm"]["rrf"]["planned"],10)
        self.assertFalse(report["statistically_significant_superiority"])

    def test_reader_missing_arm_fails(self):
        output=self.root/"reader";output.mkdir()
        records=[]
        for row in q.reader_inputs(self.public,self.run,per_family=1):
            if row["arm"]=="empty":continue
            records.append(dict(question_id=row["question_id"],family=row["family"],
                                arm=row["arm"],evidence_ids=[x["source_id"] for x in row["evidence"]],result=dict(status="failed")))
        digest=q.exclusive(output/"reader-journal.json",records)
        q.exclusive(output/"reader-seal.json",dict(schema=q.READER_SCHEMA,
            source_journal_sha256=self.seal["journal_sha256"],reader_journal_sha256=digest,
            per_family=1,labels_visible=False))
        with self.assertRaisesRegex(ValueError,"incomplete"):
            q.review_reader(self.prepared,self.run,output,self.root/"reader-review.json")

    def test_unsupervised_training_budget_is_fixed(self):
        self.assertEqual(q.RANK,8)
        self.assertEqual(q.TRAIN_STEPS,128)
        self.assertEqual(q.TRAIN_PREFIX,128)
        self.assertEqual(q.RRF_K,60)
        self.assertEqual(q.ARMS[0],"frozen")


class RealCorpusTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HEPTA_ASSOC_LOCOMO_FILE"),"pinned source file not staged")
    def test_full_source_prefix_and_size(self):
        path=Path(os.environ["HEPTA_ASSOC_LOCOMO_FILE"])
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/"prepared"
            meta=q.prepare_full(path,folder)
            self.assertEqual(meta["source_count"],5804)
            public=q.strict_json(q.read_regular(folder/"public.json"))
            self.assertEqual(sum(len(g["questions"]) for g in public["families"]),240)
            self.assertFalse(meta["independently_admitted"])


if __name__=="__main__":
    unittest.main()
