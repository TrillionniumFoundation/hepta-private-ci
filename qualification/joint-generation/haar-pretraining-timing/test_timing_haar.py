import unittest
import numpy as np
from matched_haar import MatchedHaarModel,MODE as MATCHED_MODE
from timing_haar import clone_to_coordinate,MODE,PATHS
from test_matched_haar import source,inputs,gradients
MEASUREMENTS={}
class TimingHaarTests(unittest.TestCase):
    def test_initial_function_and_shared_decoder_pretraining(self):
        original=source();raw=MatchedHaarModel.from_source(original,representation='raw',mode=MATCHED_MODE);haar=MatchedHaarModel.from_source(original,representation='haar',mode=MATCHED_MODE)
        for model in (raw,haar):
            for a,b in zip(original._forward(inputs())[1:],model._forward(inputs())[1:]):np.testing.assert_allclose(a,b,rtol=0,atol=3e-15)
            for k in ('decoder','decoder_bias','text','text_bias','image','image_bias','bias'):np.testing.assert_array_equal(original.params[k],model.params[k])
        # Literal Source and matched raw have exactly the same first CE update.
        reference=original.clone();reference.supervised_step(inputs(),np.array([1,5]));raw.supervised_step(inputs(),np.array([1,5]))
        for k in raw.params:np.testing.assert_array_equal(reference.params[k],raw.params[k])
    def test_three_clone_paths_forward_update_and_reset(self):
        original=source();bases={r:MatchedHaarModel.from_source(original,representation=r,mode=MATCHED_MODE) for r in ('raw','haar')};work=[]
        for base in bases.values():base.supervised_step(inputs(),np.array([1,5]))
        for path in PATHS:
            base=bases[path[0]];new=clone_to_coordinate(base,coordinate_path=path,mode=MODE)
            self.assertEqual(new.updates,0);self.assertEqual(new._moments,{});self.assertEqual(new.conversion_source_digest,base.digest());work.append(new.coordinate_work.copy())
            for k in base.params:self.assertFalse(np.shares_memory(new.params[k],base.params[k]))
            for a,b in zip(base._forward(inputs())[1:],new._forward(inputs())[1:]):np.testing.assert_allclose(a,b,rtol=0,atol=3e-15)
            if path[0]=='raw':
                # Exact same tensors and one aligned A+anchor update as old conversion.
                bridge=source();bridge.params={k:v.copy() for k,v in base.params.items()};ref=MatchedHaarModel.from_source(bridge,representation=path[1],mode=MATCHED_MODE)
            else:ref=base.clone()
            a,b=gradients(ref),gradients(new)
            for k in a:np.testing.assert_array_equal(a[k],b[k])
            ref.apply_gradients(a,.003);new.apply_gradients(b,.003)
            for k in new.params:np.testing.assert_array_equal(ref.params[k],new.params[k])
            self.assertEqual(ref.digest(),new.digest())
        self.assertTrue(all(w==work[0] for w in work));MEASUREMENTS['paths_qualified']=3
    def test_refuse_wrong_path_source_mode_and_checkpoint(self):
        original=source();raw=MatchedHaarModel.from_source(original,representation='raw',mode=MATCHED_MODE)
        for path in [('haar','raw'),('haar','haar'),['raw','raw'],('raw','other')]:
            with self.assertRaises(ValueError):clone_to_coordinate(raw,coordinate_path=path,mode=MODE)
        with self.assertRaises(ValueError):clone_to_coordinate(original,coordinate_path=('raw','raw'),mode=MODE)
        with self.assertRaises(ValueError):clone_to_coordinate(raw,coordinate_path=('raw','raw'),mode='old')
        raw.params['encoder'][0,0]=np.inf
        with self.assertRaises(ValueError):clone_to_coordinate(raw,coordinate_path=('raw','raw'),mode=MODE)
        for f in (raw.save,MatchedHaarModel.load):
            with self.assertRaises(ValueError):f(object())
