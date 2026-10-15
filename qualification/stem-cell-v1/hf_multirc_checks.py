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

class StockHFAllGenuineCandidatesTests(unittest.TestCase):
    """Actual stock Model/Tokenizer, native candidate slates, frozen V1 banks."""

    def test_real_stock_encoder_scores_all_original_answer_candidates(self):
        from multirc_candidate_slate import prepare_candidate_slate
        from multirc_candidate_audit import run_slate_audit,score_candidate_slate
        import copy
        sample=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        sample.setUp()
        self.addCleanup(sample.tmp.cleanup)
        encoder,query,verify,ckpt,full,receipt=safe_encoder(sample.root)
        source=fixture_rows(3,'val')
        train,eval_bundle,orig_labels=prepare_panels(
            fixture_rows(4),source,train_passages=2,val_passages=2,
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)
        slate,labels=prepare_candidate_slate(train,eval_bundle,source,
                                             original_label_receipt=orig_labels)
        obs,banks=train_then_predict(train,lambda:copy.deepcopy(eval_bundle),
            encoder=encoder,question_encoder=query,checkpoint_sha256=ckpt,steps=2)
        measured=run_slate_audit(train,eval_bundle,slate,obs,banks,
            encoder=encoder,question_encoder=query,checkpoint_sha256=ckpt)
        verify()
        scores=score_candidate_slate(measured,slate,labels,
            expected_observation_id=measured['observation_id'],
            expected_labels_sha256=_digest(labels))
        self.assertEqual((measured['passage_count'],measured['question_count'],
                          measured['actual_candidate_count']),(2,4,8))
        self.assertEqual(measured['original_v1_anchors_replayed'],4)
        self.assertEqual(scores['results']['conditioned']['total'],8)
        self.assertFalse(scores['official_multirc_score_established'])


class StockHFMatchedNativeTrainingTests(unittest.TestCase):
    def test_stock_transformers_all_native_train_vs_first_candidate(self):
        """Installed random stock checkpoint; architecture only, no efficacy."""
        from multirc_native_training import prepare_train_slate,fit_and_evaluate,score_native_training
        from multirc_candidate_slate import prepare_candidate_slate
        sample=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        sample.setUp()
        self.addCleanup(sample.tmp.cleanup)
        encoder,query,verify,ckpt,full,_=safe_encoder(sample.root)
        train_source=fixture_rows(4); eval_source=fixture_rows(3,'val')
        train,eval_bundle,owner=prepare_panels(train_source,eval_source,
            train_passages=2,val_passages=2,
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)
        native=prepare_train_slate(train,train_source)
        slate,labels=prepare_candidate_slate(train,eval_bundle,eval_source,
            original_label_receipt=owner)
        obs,_=fit_and_evaluate(train,native,lambda:(eval_bundle,slate),
            encoder=encoder,question_encoder=query,checkpoint_sha256=ckpt,steps=2)
        verify()
        result=score_native_training(obs,slate,labels,
            expected_observation_id=obs['observation_id'],
            expected_label_digest=_digest(labels))
        self.assertEqual(len(result['results']),4)
        self.assertEqual(obs['shared_train_encoder_calls'],2)
        self.assertEqual(obs['train_question_encoder_calls'],8)
        self.assertEqual(result['results']['all_native_conditioned']['total'],8)
        self.assertFalse(result['training_all_native_superiority_established'])
