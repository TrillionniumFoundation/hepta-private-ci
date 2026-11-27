import hashlib
import json
from pathlib import Path
import sys
import unittest
import numpy as np

from cell_field_fixed_fixture import build_synthetic_references, verify_original_sources
from cell_field_fixed_adapter import fixed_impulse_predictions

class RealClassSyntheticInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs=build_synthetic_references()

    def test_source_freeze_matches_all_dependencies(self):
        self.assertEqual(len(verify_original_sources()['files']),4)
        import tempfile
        from unittest.mock import patch
        import cell_field_fixed_fixture as fixture
        with tempfile.TemporaryDirectory(prefix='fixed-source-rejection-') as directory:
            target=Path(directory)
            contract=json.loads((fixture.ROOT/'cell_field_fixed_sources.json').read_bytes())
            for name in fixture.ORIGINALS:
                (target/name).write_bytes((fixture.ROOT/name).read_bytes())
            name='cell_learning_models.py'
            changed=(target/name).read_bytes()+b'\n# source changed with resealed metadata\n'
            (target/name).write_bytes(changed)
            contract['files'][name]={'bytes':len(changed),'sha256':hashlib.sha256(changed).hexdigest(),
                'git_blob_sha1':hashlib.sha1(b'blob '+str(len(changed)).encode()+b'\0'+changed).hexdigest()}
            (target/'cell_field_fixed_sources.json').write_text(json.dumps(contract,sort_keys=True,indent=2)+'\n')
            with patch.object(fixture,'ROOT',target):
                with self.assertRaisesRegex(ValueError,'pinned source contract changed'):
                    verify_original_sources()

    def test_exact_dimensions_and_all_fixed_actions_first_step(self):
        from cell_field_fixed_actions import fixed_library
        for mode,ref in self.refs.items():
            self.assertEqual(ref.state.parameter_count,36 if mode=='linear' else 52)
            for action,_ in fixed_library(ref.state.parameter_count):
                results=[fixed_impulse_predictions(ref,action,mode=m) for m in ('q4','loss2','full')]
                for result in results:
                    np.testing.assert_allclose(result['fields'][1],results[-1]['fields'][1],atol=1e-14)
                    np.testing.assert_array_equal(result['actions'][1:],0)
                np.testing.assert_array_equal(results[0]['actions'],results[-1]['actions'])

    def test_q4_matches_direct_inherited_projection(self):
        for ref in self.refs.values():
            got=fixed_impulse_predictions(ref,'d2:a1/2:s1')
            _,E=ref.action_matrix('all'); out=np.zeros((4,4))
            for k in range(3):
                F=ref.C[k+1]@ref.A[k]@np.linalg.pinv(ref.C[k],rcond=1e-10)
                D=ref.C[k+1]@E[k]
                out[k+1]=F@out[k]+D@got['actions'][k]
            np.testing.assert_allclose(got['observations'],out,rtol=1e-13,atol=1e-14)
            self.assertEqual(len(got['projection_diagnostics']),4)

    def test_real_observation_jacobian_all_columns(self):
        for ref in self.refs.values():
            x=ref.states[1]; eps=1e-4
            fd=np.zeros_like(ref.C[1])
            for j in range(len(x)):
                d=np.zeros_like(x);d[j]=eps*ref.scales[j]
                fd[:,j]=(ref.observe(x+d)[0]-ref.observe(x-d)[0])/(2*eps)
            np.testing.assert_allclose(ref.C[1],fd,rtol=2e-5,atol=2e-9)
            np.testing.assert_array_equal(ref.C[1,:,2*ref.state.parameter_count:],0)

    def test_real_adam_transition_all_columns(self):
        for ref in self.refs.values():
            x=ref.states[1]; eps=1e-4; fd=np.zeros_like(ref.A[1])
            for j in range(len(x)):
                d=np.zeros_like(x);d[j]=eps*ref.scales[j]
                plus=ref.state.transition_vector(x+d,ref.state.step_count+1,ref.train_features,ref.train_labels)
                minus=ref.state.transition_vector(x-d,ref.state.step_count+1,ref.train_features,ref.train_labels)
                fd[:,j]=(plus-minus)/(2*eps)/ref.scales
            np.testing.assert_allclose(ref.A[1],fd,rtol=3e-5,atol=2e-8)

    def test_zero_action_all_modes_and_reference_not_mutated(self):
        for ref in self.refs.values():
            before=[a.copy() for a in (ref.A,ref.C,ref.scales,ref.states)]
            for mode in ('q4','loss2','full'):
                np.testing.assert_array_equal(fixed_impulse_predictions(ref,'zero',mode=mode)['fields'],0)
            for a,b in zip(before,(ref.A,ref.C,ref.scales,ref.states)):np.testing.assert_array_equal(a,b)

    def test_reject_rescaling_and_changed_anchor(self):
        import copy
        ref=copy.deepcopy(self.refs['linear']);ref.scales*=2
        with self.assertRaises(ValueError):fixed_impulse_predictions(ref,'zero')
        ref=copy.deepcopy(self.refs['linear']);ref.states[0,0]+=.01
        with self.assertRaises(ValueError):fixed_impulse_predictions(ref,'zero')

    def test_reject_unknown_action_mode_and_nonfinite(self):
        import copy
        ref=self.refs['linear']
        with self.assertRaises(ValueError):fixed_impulse_predictions(ref,'learned')
        with self.assertRaises(ValueError):fixed_impulse_predictions(ref,'zero',mode='optimized')
        ref=copy.deepcopy(ref);ref.A[0,0,0]=np.nan
        with self.assertRaises(ValueError):fixed_impulse_predictions(ref,'zero')

if __name__=='__main__':unittest.main()
