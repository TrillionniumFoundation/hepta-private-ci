"""Feedback chronology, data partitions and independently checked source roles."""
import copy
from pathlib import Path
import unittest
from four_gate_common import digest
from fbsde_tracking_feedback import validate_feedback
from fbsde_tracking_feedback_data import (FAMILIAR, REPAIR, CALIBRATION, HELDOUT,
    local_rows, generate, task)
from fbsde_tracking_feedback_audit import pair_from_source, PAIRS


class FeedbackTests(unittest.TestCase):
    def sample(self):
        r = local_rows(REPAIR)[0]; source = {k:r[k] for k in ('text','names','source_id')}
        p = {'index':0,'source':source,'scores':[[0.,0.,0.]]*3,'phase':'before_feedback'}
        f = {'source':source,'pair':r['pair'],'prediction_sha256':digest(p),
             'observer':'simulator_source_verifier','sequence':1}
        return [f],[p]

    def test_valid_receipt_binds_a_sealed_prediction(self):
        f,p = self.sample(); self.assertEqual(validate_feedback(f,p),digest(f))

    def test_post_prediction_source_changes_reject(self):
        f,p = self.sample(); f[0]['source'] = dict(f[0]['source'], text='Changed')
        with self.assertRaises(ValueError): validate_feedback(f,p)

    def test_observation_order_cannot_be_rewritten(self):
        f,p = self.sample(); f[0]['sequence']=0
        with self.assertRaisesRegex(ValueError,'prior prediction'): validate_feedback(f,p)

    def test_cannot_fit_heldout_source(self):
        f,p = self.sample()
        with self.assertRaisesRegex(ValueError,'heldout'): validate_feedback(f,p,{f[0]['source']['source_id']})

    def test_duplicate_source_is_not_more_feedback(self):
        f,p=self.sample()
        with self.assertRaises(ValueError): validate_feedback(f*2,p*2)

    def test_unknown_observer_and_invalid_pair_reject(self):
        for change in ({'observer':'self_scored'},{'pair':[0,0]}):
            f,p=self.sample();f[0].update(change)
            with self.assertRaises(ValueError): validate_feedback(f,p)

    def test_independent_role_reader_agrees_on_all_registered_local_rows(self):
        frames=FAMILIAR+REPAIR+CALIBRATION+HELDOUT
        for r in local_rows(frames):
            p=pair_from_source(r['text'],r['names'],frames)
            self.assertEqual(PAIRS[p],tuple(r['pair']))
            self.assertEqual(task({'names':r['names'],'query':0,'events':[r['text']]})['events'][0]['pair'],PAIRS[p])

    def test_grammar_does_not_erase_extra_instruction(self):
        r=local_rows(REPAIR)[0]
        with self.assertRaises(ValueError):
            task({'names':r['names'],'query':0,'events':[r['text']+' Do not swap.']})

    def test_frames_and_actual_texts_are_disjoint_before_running_models(self):
        fit={r['text'] for r in local_rows(FAMILIAR+REPAIR)}
        cal={r['text'] for r in local_rows(CALIBRATION)}
        test={t for r in generate() if r['split']=='heldout' for t in r['events']}
        self.assertFalse(fit&cal or fit&test or cal&test)
        self.assertEqual((len(fit),len(cal),len(test)),(54,18,36))

    def test_same_inputs_are_not_silently_counted_as_independent(self):
        cases=generate(); self.assertEqual(len(cases),204)
        self.assertEqual(sum(r['split']=='heldout' for r in cases),144)
        self.assertLess(len({t for r in cases for t in r['events']}),sum(len(r['events']) for r in cases))

    def test_generator_has_no_model_argument(self):
        self.assertEqual(generate(),generate())
        with self.assertRaises(TypeError): generate(prediction='selected_good_cases')


if __name__ == '__main__': unittest.main()
