"""Synthetic integrity failures; not a substituted Qwen inference run."""

from copy import deepcopy
import unittest
import tempfile
from pathlib import Path

from event_citation_delivery_gap import (
    ARMS, KINDS, _one, reconcile,
)


def fixture():
    raw, cases = [], []
    for kind in KINDS:
        for ix in range(2):
            qid = f"controlled-{kind}-{ix}"
            required = [f"{qid}-prerequisite", f"{qid}-answer"] if kind in (
                "composition", "procedure"
            ) else [f"{qid}-answer"]
            for arm in ARMS:
                evid = [dict(label=f"E{j}",original_id=src)
                        for j,src in enumerate(required,1)]
                answer = f"fixture [E{len(required)}]"
                raw.append(dict(
                    question_id=qid,kind=kind,arm=arm,selected=list(required),
                    status="succeeded",answer=answer,
                    receipt=dict(delivered_evidence=evid,
                                 semantic_citation_precision=None,
                                 answer_postprocessed=False,production_accepted=False,
                                 trainable_parameters=0,input_ids_digest="f"*64),
                ))
                cases.append(dict(
                    question_id=qid,kind=kind,arm=arm,answer=answer,
                    generation_status="succeeded",strict_task_success=True,
                    cited_source_ids=[required[-1]],
                    missing_program_declared_support=required[:-1],
                    program_declared_support_cited=len(required)==1,
                ))
    report=dict(formal_citation_chain=dict(cases=cases,by_arm={
        arm:dict(attempted=8,strict_task_success=8,
                 correct_with_full_program_declared_citations=4)
        for arm in ARMS
    }))
    return raw,report


class DeliveredCitationGapTests(unittest.TestCase):
    def test_incomplete_citations_on_complete_two_source_delivery(self):
        source,score=fixture()
        receipt=reconcile(source,score)
        self.assertEqual(receipt["original_total_model_calls"],72)
        self.assertEqual(receipt["program_support_multistep"]["strictly_correct_answers"],4)
        self.assertEqual(receipt["program_support_multistep"]["both_declared_sources_delivered"],4)
        self.assertEqual(receipt["program_support_multistep"]["complete_delivery_but_incomplete_citation"],4)
        self.assertEqual(receipt["program_support_multistep"]["full_declared_chain_cited"],0)
        self.assertFalse(receipt["production_accepted"])

    def test_delivery_gap_not_confused_with_reader_citation_omission(self):
        src,score=fixture()
        row=next(x for x in src if x["kind"]=="composition" and x["arm"]=="hybrid_k4")
        row["selected"] = row["selected"][1:]
        row["receipt"]["delivered_evidence"] = [dict(label="E1",original_id=row["selected"][0])]
        case=next(x for x in score["formal_citation_chain"]["cases"]
                  if x["question_id"]==row["question_id"] and x["arm"]==row["arm"])
        case["answer"]=row["answer"]="fixture [E1]"
        x=_one(row,case,[f"{row['question_id']}-prerequisite",row["selected"][0]])
        self.assertEqual(x["shortfall"],"necessary-source-not-delivered")
        self.assertEqual(len(x["required_delivered_but_uncited_source_ids"]),0)

    def test_unbound_citation_marker_cannot_fill_declared_chain(self):
        src,score=fixture()
        row=src[0];case=score["formal_citation_chain"]["cases"][0]
        row["answer"]=case["answer"]="fixture [E999]"
        case["cited_source_ids"]=[]
        case["missing_program_declared_support"]=[row["selected"][0]]
        case["program_declared_support_cited"]=False
        item=_one(row,case,row["selected"])
        self.assertEqual(item["unbound_output_labels"],["E999"])
        self.assertEqual(item["actually_cited_required_sources"],0)

    def test_forged_official_citation_result_rejected(self):
        src,score=fixture()
        score["formal_citation_chain"]["cases"][0]["cited_source_ids"] = ["forged"]
        with self.assertRaisesRegex(ValueError,"official citations disagree"):
            reconcile(src,score)

    def test_modified_model_output_not_accepted_as_original_answer(self):
        src,score=fixture()
        src[0]["answer"]="changed model result"
        with self.assertRaisesRegex(ValueError,"mismatched raw answer"):
            reconcile(src,score)

    def test_missing_duplicate_or_wrong_kind_rejected(self):
        src,score=fixture()
        for mode in ("missing","duplicate","kind"):
            a,b=deepcopy(src),deepcopy(score)
            if mode=="missing":a.pop()
            elif mode=="duplicate":a[-1]=a[0]
            else:a[0]["kind"]="wrong"
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                reconcile(a,b)

    def test_postrun_semantic_or_weight_promotions_rejected(self):
        for field,value in (("semantic_citation_precision",1.0),
                            ("answer_postprocessed",True),
                            ("production_accepted",True),
                            ("trainable_parameters",1)):
            a,b=fixture();a[0]["receipt"][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,"promoted"):
                reconcile(a,b)

    def test_old_python_streaming_sha_checks_bytes_before_zip_open(self):
        # Python 3.10 has no hashlib.file_digest. Wrong transport bytes must
        # fail by SHA instead of an AttributeError or a ZIP parser traceback.
        from event_citation_delivery_gap import audit_archive
        with tempfile.TemporaryDirectory() as temp:
            tampered = Path(temp) / "untrusted.zip"
            tampered.write_bytes(b"not the pinned original Qwen artifact")
            with self.assertRaisesRegex(ValueError,"transport SHA256 differs"):
                audit_archive(tampered)

    def test_raw_selected_must_equal_delivered_original_source_order(self):
        a,b=fixture();a[0]["selected"]=["another-source"]
        with self.assertRaisesRegex(ValueError,"selected and delivered"):
            reconcile(a,b)


if __name__=="__main__":
    unittest.main()
