"""Source-time trial input assembly tests: fixtures only, no model claims."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import source_time_evidence as m
import source_time_evidence_trial as t


class TrialProjectionTests(unittest.TestCase):
    def fixtures(self):
        doc=SimpleNamespace(identity="scope/D1",content="A: Next month.",observed_at="20 January, 2023")
        q=SimpleNamespace(identity="scope/q1")
        request={"question":"When?","options":[],"evidence":[
            {"id":m.source_id(doc.identity),"modality":"text","text":doc.content,
             "asset_sha256":None,"position":0}]}
        row={"id":"answer","question_id":m.digest(q.identity),"family":"scope","split":"train",
             "request":request,"response":"February [source]","kind":"annotated_answer",
             "source_sha256":"a"*64}
        return q,doc,row

    def test_target_kind_and_split_are_unchanged(self):
        q,doc,row=self.fixtures();original=deepcopy(row)
        out,receipts=t.project_examples([row],[q],lambda query:[doc],m.SOURCE_TIME)
        self.assertEqual(row,original)
        for name in row:
            if name!="request":self.assertEqual(out[0][name],row[name])
        self.assertEqual(receipts[0]["split"],"train")

    def test_select_stays_select_and_test_is_rejected(self):
        q,doc,row=self.fixtures();row["split"]="select"
        out,_=t.project_examples([row],[q],lambda query:[doc],m.SOURCE_TIME)
        self.assertEqual(out[0]["split"],"select")
        row["split"]="test"
        with self.assertRaises(ValueError):t.project_examples([row],[q],lambda query:[doc],m.SOURCE_TIME)

    def test_no_benchmark_target_interface_is_needed(self):
        q,doc,row=self.fixtures()
        out,_=t.project_examples([row],[q],lambda query:[doc],m.CONTENT_ONLY)
        self.assertEqual(out,[row])

    def test_unavailable_cases_keep_planned_denominator(self):
        q,doc,row=self.fixtures()
        cases=[{"question_id":q.identity,"split":"select","condition":"support_only","request":None},
               {"question_id":q.identity,"split":"select","condition":"no_evidence",
                "request":row["request"]|{"evidence":[]}}]
        out,receipts=t.project_cases(cases,[q],lambda query:[doc],m.SOURCE_TIME)
        self.assertEqual(out,cases);self.assertEqual(len(out),2);self.assertEqual(len(receipts),1)

    def test_unknown_question_cannot_borrow_a_date(self):
        q,doc,row=self.fixtures();row["question_id"]="unknown"
        with self.assertRaises(ValueError):t.project_examples([row],[q],lambda query:[doc],m.SOURCE_TIME)

    def test_retrieved_ids_and_order_do_not_change(self):
        q,doc,row=self.fixtures()
        cases=[{"question_id":q.identity,"split":"select","condition":"support_only","request":row["request"]}]
        out,_=t.project_cases(cases,[q],lambda query:[doc],m.SOURCE_TIME)
        self.assertEqual(out[0]["request"]["evidence"][0]["id"],cases[0]["request"]["evidence"][0]["id"])
        self.assertEqual(out[0]["request"]["evidence"][0]["position"],0)

    def test_four_cells_not_an_architecture_grid(self):
        self.assertEqual(len(t.ARMS),4)
        self.assertEqual({(profile,trained) for _,profile,trained in t.ARMS},
                         {(profile,trained) for profile in m.PROFILES for trained in (True,False)})
        self.assertFalse(t.PLAN["test_readout"])
        self.assertFalse(t.PLAN["automatic_selection"])
        self.assertFalse(t.PLAN["compute_matched"])


if __name__=="__main__":
    unittest.main()
