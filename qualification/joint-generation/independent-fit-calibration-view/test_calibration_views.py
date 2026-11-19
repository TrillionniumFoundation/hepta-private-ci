import itertools,unittest
import numpy as np
from calibration_views import calibration_view_dataset

def ids():
    names=[':'.join(map(str,g)) for g in itertools.islice(itertools.product(range(12),range(4),range(3),range(3)),130)]
    return [g for g in names for _ in range(6)]
def renderer(scene):return np.full((8,8,3),.2+.05*(scene%5))
class CalibrationViewTests(unittest.TestCase):
    def test_seed_determinism_distinct_branch_and_readonly(self):
        groups=ids();before=groups.copy();a=calibration_view_dataset(groups,0,5701,renderer);b=calibration_view_dataset(groups,0,5701,renderer);c=calibration_view_dataset(groups,1,5702,renderer)
        self.assertEqual(a['input_hashes'],b['input_hashes']);self.assertFalse(set(a['input_hashes'])&set(c['input_hashes']));self.assertEqual(groups,before)
        for key in ('full','low','labels'):
            np.testing.assert_array_equal(a[key],b[key])
            with self.assertRaises(ValueError):a[key].flags.writeable=True
    def test_all_130groups_six_targets_instructions_and_lowview(self):
        groups=ids();calls=[]
        def stub(scene):calls.append(scene);return renderer(scene)
        data=calibration_view_dataset(groups,0,5701,stub);self.assertEqual(len(calls),780);self.assertEqual(data['groups'],tuple(groups));self.assertEqual((data['observations'],data['view_rows'],data['normal_scalars'],data['cache_payload_bytes']),(780,1560,149760,2527200))
        for row,group in enumerate(groups):
            scene,c,s,p=map(int,group.split(':'));expected=((scene//4 if c==0 else c-1)*2+((scene//2)%2 if s==0 else s-1))*2+(scene%2 if p==0 else p-1);self.assertEqual(data['labels'][row],expected)
            instruction=np.concatenate((np.eye(4)[c],np.eye(3)[s],np.eye(3)[p]));np.testing.assert_array_equal(data['full'][row,-10:],instruction);np.testing.assert_array_equal(data['low'][row,-10:],instruction)
        for row in range(780):
            expected=data['full'][row,:192].reshape(4,2,4,2,3).mean(axis=(1,3)).repeat(2,axis=0).repeat(2,axis=1).reshape(-1);np.testing.assert_array_equal(data['low'][row,:192],expected)
        self.assertTrue(np.all((data['full'][:,:192]>=0)&(data['full'][:,:192]<=1)))
    def test_invalid_request_before_renderer(self):
        groups=ids()
        def never(scene):raise AssertionError('invalidrequest mustreject before renderer')
        for gi,fold,seed in ((groups,True,5701),(groups,0,5702),(groups,0,5701.),(groups,1,1702),(groups[:-1],0,5701),(['bad']*780,0,5701)):
            with self.assertRaises(ValueError):calibration_view_dataset(gi,fold,seed,never)
        with self.assertRaises(ValueError):calibration_view_dataset(groups,0,5701,lambda scene:np.zeros((8,8)))
