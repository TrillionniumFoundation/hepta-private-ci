import copy
import unittest
from teacher_distillation import cases,labels,fit,predict,evaluate_after_seal,_digest,_params_digest,initialize

class DistillationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=cases('train',7347,320)
        cls.future=cases('future',7348,160)
        cls.labels=labels(cls.train)
        cls.candidate=fit(cls.train,cls.labels,steps=300)
        cls.seal=predict(cls.candidate,cls.future)
    def test_real_head_parameter_updates(self):
        c=self.candidate
        self.assertNotEqual(c.initial_digest,c.trained_digest)
        self.assertGreater(c.observed_parameters_changed,100)
        self.assertEqual(self.seal['head_parameters'],9744)
        self.assertFalse(self.seal['pretrained_encoder_executed'])
    def test_teacher_future_agreement_is_measured_after_seal(self):
        report=evaluate_after_seal(self.seal,self.future,expected_digest=_digest(self.seal))
        print('Synthetic Teacher Future Agreement:',report)
        self.assertGreater(report['teacher_agreement'],.7)
        self.assertFalse(report['external_natural_success'])
    def test_no_future_targets_in_predictor(self):
        future=list(self.future)
        future[0]={**future[0],'label':1}
        with self.assertRaises(ValueError):predict(self.candidate,future)
    def test_tampered_prediction_denied(self):
        s=copy.deepcopy(self.seal)
        s['case_predictions'][self.future[0]['case_id']]=4
        with self.assertRaises(ValueError):evaluate_after_seal(s,self.future,expected_digest=_digest(self.seal))
    def test_future_inputs_changed_after_seal_denied(self):
        future=list(self.future)
        future[0]={**future[0],'case_id':'tampered'}
        with self.assertRaises(ValueError):evaluate_after_seal(self.seal,future,expected_digest=_digest(self.seal))
    def test_initial_weights_never_rewritten(self):
        self.assertEqual(_params_digest(self.candidate.initial_weights),self.candidate.initial_digest)
        self.assertEqual(_params_digest(initialize(19)),self.candidate.initial_digest)
    def test_frozen_no_change_differs(self):
        c=self.candidate
        self.assertNotEqual(_params_digest(c.weights),_params_digest(c.initial_weights))
    def test_invalid_provenance_rejected(self):
        future=list(self.future)
        future[0]={**future[0],'group_id':'0'*64}
        with self.assertRaises(ValueError): predict(self.candidate,future)
    def test_future_label_smuggling_in_train_rows_rejected(self):
        train=list(self.train)
        train[0]={**train[0],'model_predicted_label':1}
        with self.assertRaises(ValueError):fit(train,self.labels,steps=1)

if __name__=='__main__':unittest.main()

class ThreeArmControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from teacher_distillation import (fit_cheap_linear,cheap_linear_predictions,
                                          frozen_control_predictions)
        c=DistillationTests.candidate
        cls.rows=DistillationTests.future
        w,cls.linear_cpu=fit_cheap_linear(DistillationTests.train,DistillationTests.labels,steps=300)
        cls.seals={
            'learned_gate':DistillationTests.seal['case_predictions'],
            'frozen_gate':frozen_control_predictions(c,cls.rows),
            'cheap_linear':cheap_linear_predictions(w,cls.rows)
        }
    def test_sealed_all_controls(self):
        from teacher_distillation import evaluate_controls_after_seal
        x=evaluate_controls_after_seal(self.seals,self.rows,_digest(self.seals))
        print('Three-arm teacher study:',x)
        self.assertGreater(x['teacher_agreement_by_arm']['learned_gate'],.9)
        self.assertLess(x['teacher_agreement_by_arm']['frozen_gate'],.9)
        self.assertFalse(x['production_accepted'])
    def test_refuses_best_arm_posthoc_mutation(self):
        from teacher_distillation import evaluate_controls_after_seal
        d=_digest(self.seals)
        changed=copy.deepcopy(self.seals)
        changed['learned_gate'].pop(self.rows[0]['case_id'])
        with self.assertRaises(ValueError):evaluate_controls_after_seal(changed,self.rows,d)
    def test_cheap_linear_not_falsely_equal_compute(self):
        self.assertNotEqual(self.linear_cpu,DistillationTests.candidate.training_cpu_ns)
