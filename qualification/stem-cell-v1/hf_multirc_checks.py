"""Real installed stock Transformers architecture; random-weight CHECK, not efficacy."""
import unittest
from hf_profile_checks import InstalledHFTests
from multirc_reader_study import safe_encoder,train_then_predict,score_sealed
from test_multirc_real_study import fixture_rows
from multirc_materials import prepare_panels
from next_round_matrix import _digest


class StockHFMultiRCTest(unittest.TestCase):
    def test_real_stock_full_checkpoint_and_two_question_reader(self):
        sample=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        sample.setUp()
        self.addCleanup(sample.tmp.cleanup)
        evidence,query,verify,ckpt,full,loading=safe_encoder(sample.root)
        train,heldout,labels=prepare_panels(fixture_rows(5),fixture_rows(4,'val'),
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64,train_passages=3,val_passages=2)
        observation,readers=train_then_predict(train,lambda:heldout,encoder=evidence,
            question_encoder=query,checkpoint_sha256=ckpt,steps=2)
        verify()
        self.assertEqual((observation['actual_train_encoder_calls'],observation['actual_eval_encoder_calls']),(3,2))
        self.assertEqual(observation['eval_examples'],4)
        self.assertEqual(len(set(observation['arm_parameter_counts'].values())),1)
        score=score_sealed(observation,labels,expected_observation_id=observation['observation_id'],
                           expected_label_sha256=_digest(labels))
        self.assertEqual(score['results']['conditioned']['total'],4)
        self.assertFalse(score['resource_efficiency_established'])


class StockHFBlindEvidenceStressTests(unittest.TestCase):
    def test_real_architecture_sealed_reader_evidence_interventions(self):
        # Randomly initialized stock ModernBERT: compatibility, NOT public
        # pretrained model accuracy or answer grounding.
        from multirc_evidence_stress import audit_evidence
        from matrix_bank import state_digest
        sample=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        sample.setUp()
        self.addCleanup(sample.tmp.cleanup)
        evidence,query,verify,ckpt,full,loading=safe_encoder(sample.root)
        tr,ev,labels=prepare_panels(fixture_rows(5),fixture_rows(4,'val'),
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64,train_passages=3,val_passages=2)
        obs,readers=train_then_predict(tr,lambda:ev,encoder=evidence,
            question_encoder=query,checkpoint_sha256=ckpt,steps=2)
        owner=state_digest(readers['conditioned'])
        report=audit_evidence(tr,ev,obs,readers['conditioned'],encoder=evidence,
            question_encoder=query,checkpoint_sha256=ckpt)
        verify()
        self.assertEqual(report['passage_count'],2)
        self.assertEqual(report['encoder_calls'],3)
        self.assertEqual(report['conditioned_reader_calls'],16)
        self.assertEqual(report['stress_work']['unknown_operators'],{})
        self.assertEqual(state_digest(readers['conditioned']),owner)
        self.assertFalse(report['missing_premise_correctness_certified'])


if __name__=='__main__':unittest.main()


class StockHFQuestionAnswerFactorialTests(unittest.TestCase):
    def test_trained_stock_reader_separates_question_from_candidate_answer(self):
        # Real stock Transformer architecture, RANDOM weights: compatible
        # execution only, not an independent public MultiRC quality result.
        from multirc_evidence_stress import audit_evidence
        from multirc_query_factorial import audit_question_answer_factors
        from matrix_bank import state_digest
        sample=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        sample.setUp()
        self.addCleanup(sample.tmp.cleanup)
        evidence,query,verify,ckpt,full,loading=safe_encoder(sample.root)
        tr,ev,_=prepare_panels(fixture_rows(5),fixture_rows(4,'val'),
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64,
            train_passages=3,val_passages=2)
        obs,readers=train_then_predict(tr,lambda:ev,encoder=evidence,
            question_encoder=query,checkpoint_sha256=ckpt,steps=2)
        prior=audit_evidence(tr,ev,obs,readers['conditioned'],encoder=evidence,
            question_encoder=query,checkpoint_sha256=ckpt)
        original=state_digest(readers['conditioned'])
        r=audit_question_answer_factors(tr,ev,obs,readers['conditioned'],
            encoder=evidence,question_encoder=query,checkpoint_sha256=ckpt,
            original_stress=prior)
        verify()
        self.assertEqual((r['passage_count'],r['question_count']),(2,4))
        self.assertEqual((r['physical_encoder_calls'],r['newly_computed_question_embeddings'],
                          r['conditioned_reader_calls']),(2,8,8))
        self.assertEqual(r['work_observation']['unknown_operators'],{})
        self.assertEqual(state_digest(readers['conditioned']),original)
        self.assertIsNone(r['counterfactual_accuracy'])
