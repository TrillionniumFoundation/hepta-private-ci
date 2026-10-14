"""Pure generation assembly: no model outputs or hidden targets in requests."""
from copy import deepcopy
import unittest
import five_causal_experiments as c
import question_evidence_relevance as rel
import question_relevance_trial as trial
from test_question_evidence_relevance import examples


def fixture(count=4):
    data=examples()[:count*2]
    rows=[]
    for i in range(count):
        for j,condition in ((0,"support_only"),(1,"no_evidence")):
            a=data[2*i+j]
            rows.append({"question_id":f"raw{i}","family":a["family"],"split":"train",
                         "condition":condition,"request":deepcopy(a["request"])})
    names=[{"question_id":c.digest(f"raw{i}"),"original_question_id":f"raw{i}"} for i in range(count)]
    return rows,rel.build_plan(data),names


class CasesTests(unittest.TestCase):
    def test_all_old_recipients_and_four_contexts_retained(self):
        result=trial.train_cases(*fixture())
        self.assertEqual(len(result),16)
        self.assertEqual({r["condition"] for r in result},{"own_sources","empty","donor_sources","matched_donor_question"})

    def test_mismatched_and_matched_have_identical_evidence(self):
        result=trial.train_cases(*fixture())
        for i in range(0,len(result),4):
            self.assertEqual(result[i+2]["request"]["evidence"],result[i+3]["request"]["evidence"])
            self.assertNotEqual(result[i+2]["request"]["question"],result[i+3]["request"]["question"])
            self.assertNotEqual(result[i+2]["question_id"],result[i+3]["question_id"])

    def test_unavailable_extra_does_not_delete_original(self):
        result=trial.train_cases(*fixture(1))
        self.assertEqual(len(result),4)
        self.assertIsNotNone(result[0]["request"])
        self.assertEqual(result[1]["request"]["evidence"],[])
        self.assertIsNone(result[2]["request"]);self.assertIsNone(result[3]["request"])

    def test_target_values_never_enter_generation(self):
        for row in trial.train_cases(*fixture()):
            self.assertEqual(set(row),{"question_id","family","split","condition","request"})
            c.validate_public(row["request"])

    def test_input_plan_not_mutated(self):
        args=fixture();before=deepcopy(args);trial.train_cases(*args)
        self.assertEqual(args,before)

    def test_no_new_train_calls_from_select(self):
        args=fixture()
        for row in args[0]:row["split"]="select"
        with self.assertRaises(c.Invalid):trial.train_cases(*args)


if __name__=="__main__":unittest.main()
