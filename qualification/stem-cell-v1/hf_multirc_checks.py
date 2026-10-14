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


if __name__=='__main__':unittest.main()
