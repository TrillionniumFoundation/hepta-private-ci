import unittest
from stem_audit_reader_condition import frozen_condition, PHASES


def fixture():
    plan={'questions':{phase:[f'{phase}-{i}' for i in range(8)] for phase in PHASES}}
    scored=[];oracle=[]
    for phase in PHASES:
        for i in range(8):
            qid=f'{phase}-{i}'
            unanswerable=i==7
            oracle.append(dict(phase=phase,question_id=qid,
                oracle_kind='annotated-unanswerable' if unanswerable else 'no-admitted-literal-reference-span',
                status='succeeded' if unanswerable else 'unavailable',
                policy_comparator=False,semantic_entailment_independently_verified=False))
            scored.append(dict(stage=48,phase=phase,question_id=qid,arm='frozen_rerank',
                status='failed' if i==3 else 'succeeded',
                source_choice_correct=0 if unanswerable or i in (3,4,5,6) else 1,
                selected=0,answer='synthetic Reader response',diagnostic_answer_f1=0.25,receipt={'generator_identity':'pinned'}))
    return plan,scored,oracle


class ConditionalReaderTests(unittest.TestCase):
    def test_complete_final_checkpoint_preserves_all_32(self):
        result=frozen_condition(*fixture())
        assert result['unique_original_questions']==32
        assert result['by_phase']['test']['planned_questions']==8
        assert result['by_phase']['test']['native_answerable_support_selected']==3
        assert result['by_phase']['test']['native_answerable_support_not_selected']==4
        assert result['by_phase']['test']['unanswerable_native_questions']==1
        assert not result['production_accepted']

    def test_score_works_only_from_actual_completed_reader(self):
        p,s,o=fixture();r=frozen_condition(p,s,o)
        failed=r['by_phase']['test']['source_and_answerability_strata']['answerable-native-document/source-or-abstention-incorrect']
        self.assertEqual(failed['original_reader_failed'],1)
        self.assertAlmostEqual(failed['all_planned_answer_token_f1_lower_bound'],0.1875)
        self.assertAlmostEqual(failed['all_planned_answer_token_f1_upper_bound'],0.4375)

    def test_missing_double_and_unknown_oracle_fail_closed(self):
        p,s,o=fixture()
        for altered in [o[:-1],o[:-1]+[o[0]],o[:-1]+[dict(o[-1],oracle_kind='verified-gold-entailment')]]:
            with self.assertRaises(ValueError):frozen_condition(p,s,altered)

    def test_missing_duplicate_or_incompatible_frozen_outcome_reject(self):
        p,s,o=fixture()
        for altered in [s[:-1],s[:-1]+[s[0]],s[:-1]+[dict(s[-1],arm='fake')]]:
            with self.assertRaises(ValueError):frozen_condition(p,altered,o)

    def test_forged_native_abstention_success_rejected(self):
        p,s,o=fixture();s[-1]['source_choice_correct']=1
        with self.assertRaisesRegex(ValueError,'abstention'):frozen_condition(p,s,o)

    def test_successful_unanswerable_without_f1_not_fabricated_as_perfect(self):
        p,s,o=fixture()
        for row in s:
            if row["question_id"].endswith("-7"):
                row["diagnostic_answer_f1"]=None
        result=frozen_condition(p,s,o)
        for phase in PHASES:
            item=result["by_phase"][phase]["source_and_answerability_strata"]["native-unanswerable/source-or-abstention-incorrect"]
            self.assertEqual(item["original_questions"],1)
            self.assertEqual(item["original_reader_success"],1)
            self.assertEqual(item["answer_diagnostic_scored"],0)
            self.assertIsNone(item["observed_answer_token_f1_mean"])
            self.assertEqual(item["all_planned_answer_token_f1_upper_bound"],1)

    def test_oracle_independence_and_unscored_reader_rejected(self):
        p,s,o=fixture();o[0]['semantic_entailment_independently_verified']=True
        with self.assertRaises(ValueError):frozen_condition(p,s,o)
        p,s,o=fixture();s[0]['diagnostic_answer_f1']=float('nan')
        with self.assertRaises(ValueError):frozen_condition(p,s,o)


if __name__=='__main__':unittest.main()
