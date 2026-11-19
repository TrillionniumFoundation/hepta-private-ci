import json
from pathlib import Path
import unittest
from ood_forward_audit import audit, AuditError

HERE=Path(__file__).parent
PLAN=(HERE/"HPCA_V2_OOD_PLAN.json").read_bytes()
RESULT=(HERE/"ACTUAL_OOD_FORWARD_RESULT.json").read_bytes()


def mutate_result(transform):
    j=json.loads(RESULT)
    transform(j)
    return json.dumps(j).encode()


class FrozenForwardAuditTests(unittest.TestCase):
    def test_real_operator_forward_216_rows(self):
        r=audit(PLAN,RESULT)
        self.assertEqual(r["original_forward_rows_verified"],216)
        self.assertEqual(r["paired_mean_bursty_minus_interleaved_accuracy"],0)
        self.assertEqual(len(r["four_seed_pairs"]),4)
        self.assertEqual(r["status"],"HOLD_NO_GO_OPERATOR_ONLY")

    def test_plan_changed_after_run_refused(self):
        j=json.loads(PLAN)
        j["tasks"][0]["question"]="Hindsight modified"
        with self.assertRaisesRegex(AuditError,"plan digest"):
            audit(json.dumps(j).encode(),RESULT)

    def test_predicted_label_tamper_refused(self):
        raw=mutate_result(lambda j:j["runs"][0]["predictions"][0].update(prediction="no"))
        with self.assertRaisesRegex(AuditError,"decision"):
            audit(PLAN,raw)

    def test_malformed_probability_refused(self):
        raw=mutate_result(lambda j:j["runs"][0]["predictions"][0].update(p_yes=0.0))
        with self.assertRaisesRegex(AuditError,"probability"):
            audit(PLAN,raw)

    def test_missing_row_refused(self):
        raw=mutate_result(lambda j:j["runs"][5]["predictions"].pop())
        with self.assertRaisesRegex(AuditError,"prediction count"):
            audit(PLAN,raw)

    def test_prompt_changed_between_arms_refused(self):
        raw=mutate_result(lambda j:j["runs"][8]["predictions"][0].update(prompt_sha256="a"*64))
        with self.assertRaisesRegex(AuditError,"unmatched prompt"):
            audit(PLAN,raw)

    def test_false_summary_refused(self):
        raw=mutate_result(lambda j:j["runs"][0]["scores"]["overall"].update(accuracy=0.99))
        with self.assertRaisesRegex(AuditError,"scored mean"):
            audit(PLAN,raw)

    def test_false_paired_metric_refused(self):
        raw=mutate_result(lambda j:j["paired"][0].update(bursty_minus_interleaved_accuracy=0.5))
        with self.assertRaisesRegex(AuditError,"claimed seed pair"):
            audit(PLAN,raw)

    def test_duplicate_json_key_refused(self):
        with self.assertRaisesRegex(AuditError,"duplicate JSON key"):
            audit(PLAN, RESULT.replace(b'"authority":',b'"authority":"DENY_ALL_HOLD_NO_GO","authority":',1))

    def test_nonfinite_json_refused(self):
        with self.assertRaises(AuditError):
            audit(PLAN,RESULT.replace(b'"p_yes": 0.580846488',b'"p_yes": NaN',1))

    def test_bad_cost_refused(self):
        raw=mutate_result(lambda j:j["runs"][0]["cost"].update(load_wall_seconds=-1))
        with self.assertRaisesRegex(AuditError,"invalid run cost"):
            audit(PLAN,raw)


if __name__=="__main__":unittest.main()
