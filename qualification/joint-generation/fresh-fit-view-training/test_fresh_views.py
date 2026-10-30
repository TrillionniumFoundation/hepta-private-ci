import itertools,unittest
import numpy as np
from grouped_training import group_schedule
from fresh_views import build_fresh_stream,stream_digest

def fixture():
    names=[':'.join(map(str,g)) for g in itertools.islice(itertools.product(range(12),range(4),range(3),range(3)),130)]
    ids=[name for name in names for _ in range(6)];schedule=group_schedule(ids,9103,steps=2)
    return ids,schedule

def stub(scene):return np.full((8,8,3),.2+.05*(scene%5))
class FreshViewTests(unittest.TestCase):
    def test_deterministic_distinct_seed_and_immutable(self):
        ids,schedule=fixture();old=ids.copy();a=build_fresh_stream(ids,schedule,19103,stub);b=build_fresh_stream(ids,schedule,19103,stub);c=build_fresh_stream(ids,schedule,19107,stub)
        self.assertEqual(a['sha256'],b['sha256']);np.testing.assert_array_equal(a['inputs'],b['inputs']);self.assertFalse(np.array_equal(a['inputs'],c['inputs']));self.assertEqual(ids,old);self.assertEqual(stream_digest(a),a['sha256'])
        for v in (a['inputs'],a['labels']):
            with self.assertRaises(ValueError):v.flags.writeable=True
    def test_pairs_range_instruction_targets_and_counts(self):
        ids,schedule=fixture();calls=[]
        def renderer(scene):calls.append(scene);return stub(scene)
        out=build_fresh_stream(ids,schedule,19103,renderer);self.assertEqual(len(calls),64);self.assertEqual(out['normal_scalars'],12288);self.assertEqual(out['paired_view_rows'],128)
        for step,(rows,full,groups) in enumerate(schedule):
            self.assertEqual(len({ids[r] for r in rows}),8)
            for pair in range(32):
                a,b=out['inputs'][step,2*pair:2*pair+2];scene,c,s,p=map(int,ids[rows[2*pair]].split(':'));target=((scene//4 if c==0 else c-1)*2+((scene//2)%2 if s==0 else s-1))*2+(scene%2 if p==0 else p-1)
                expected=np.concatenate((np.eye(4)[c],np.eye(3)[s],np.eye(3)[p]));np.testing.assert_array_equal(a[-10:],expected);np.testing.assert_array_equal(b[-10:],expected);np.testing.assert_array_equal(out['labels'][step,2*pair:2*pair+2],[target,target])
                self.assertTrue(np.all((a[:192]>=0)&(a[:192]<=1)))
                low=a[:192].reshape(4,2,4,2,3).mean(axis=(1,3)).repeat(2,axis=0).repeat(2,axis=1).reshape(-1);np.testing.assert_array_equal(b[:192],low)
    def test_invalid_admission_before_renderer(self):
        ids,schedule=fixture()
        def never(scene):raise AssertionError('must reject before renderer')
        for badids,badschedule,seed in ((ids,schedule,True),(ids,schedule,19103.),(ids,schedule,999),(ids[:-1],schedule,19103),(['bad']*780,schedule,19103),(ids,(),19103),(ids,((schedule[0][0][:-1],schedule[0][1],schedule[0][2]),),19103)):
            with self.assertRaises(ValueError):build_fresh_stream(badids,badschedule,seed,never)
        with self.assertRaises(ValueError):build_fresh_stream(ids,schedule,19103,lambda scene:np.zeros((8,8)))
        with self.assertRaises(ValueError):build_fresh_stream(ids,schedule,19103,lambda scene:np.full((8,8,3),np.nan))
