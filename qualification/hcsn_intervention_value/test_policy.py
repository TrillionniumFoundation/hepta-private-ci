import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from . import policy,run,independent


def synthetic(groups=8,offset='train'):
    rng=np.random.default_rng(434); n=groups*4; h=6
    g=np.repeat(np.arange(groups),4); target=(np.arange(n)%2).astype(int)
    # Observable cue modifies whether audio can be trusted; paid truth is used for
    # training/evaluation only. No synthetic trajectory is used for corpus metrics.
    cue=rng.normal(size=(n,1)); x=rng.normal(size=(n,h,3)); x[...,0]=cue
    free=(rng.normal(size=(n,h))+.6*(2*target[:,None]-1)*(cue>.1))
    paid=rng.normal(size=(n,h))+(2*target[:,None]-1)*(.3+1.1*(cue<.1))
    return dict(x=x,scores=np.stack((-free,free),-1),read_scores=np.stack((-paid,paid),-1),
        dt=np.full((n,h),.48),target=target,class_id=target.copy(),group=np.array([offset+'-g'+str(v) for v in g]),
        source=np.array([offset+'-rec'+str(v//2) for v in range(n)]),query_id=np.array([offset+str(i) for i in range(n)]))


def fake_front(data):
    # Isolated generated fixtures only; real data must pass the parent's opportunity gate.
    for k in ('front_weights','chooser'): run.write(data/(k+'.json'),{'synthetic_fixture':True})
    run.write(data/'panels.json',{'synthetic_fixture':{n:{'paid_gate_pass':True} for n in ('train','dev')}})
    names=['train.npz','dev.npz','retain.npz','front_weights.json','chooser.json','panels.json']
    run.write(data/'frontend_seal.json',{'selected':'synthetic_fixture','heldout_opened':False,'sha256':{n:run.sha(data/n) for n in names}})


class TestPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls): torch.set_num_threads(1)

    def test_held_source_exclusion_and_noread(self):
        s=synthetic(); policy.validate(s); f=policy.fold_ids(s); self.assertEqual(len(np.unique(f)),5)
        for k in ('source','group'):
            for v in s[k]: self.assertEqual(len(set(f[s[k]==v])),1)
        a=policy.fit_teacher(s,True); no=policy.fit_teacher(s,False)
        self.assertEqual(a['targets'].shape,(32,6,3)); self.assertTrue(np.isfinite(a['held']).all())
        mutated=copy.deepcopy(s); touched=f==f[0]; mutated['read_scores'][touched]=mutated['read_scores'][touched,:,::-1]
        mutated['target'][touched]=1-mutated['target'][touched]
        b=policy.fit_teacher(mutated,True)
        np.testing.assert_array_equal(np.asarray(a['held'])[touched],np.asarray(b['held'])[touched]); self.assertFalse(np.array_equal(a['targets'][touched],b['targets'][touched]))
        mutated=copy.deepcopy(s); mutated['read_scores']*=-1
        n2=policy.fit_teacher(mutated,False)
        for key in ('held','targets'): np.testing.assert_array_equal(no[key],n2[key]); self.assertTrue(np.isfinite(no[key]).all())
        self.assertEqual(no['models'],n2['models'])

    def test_prefix_causality_and_external_threshold(self):
        s=synthetic(3); z=policy.free_state(s['x'],s['scores'],s['dt']); x=torch.from_numpy(z[:3])
        dt=torch.from_numpy(s['dt'][:3]); q=torch.zeros((3,6,3),dtype=torch.float64)
        q[...,0]=1; low=q.clone(); low[:,:3,0]=-1; low[:,:3,1]=-1
        model=policy.representation('external',1,x.shape[-1]); zero=model.initial_edit_vector()
        self.assertTrue(torch.all(model.task_boundaries(q,True)[:,:3]>model.task_boundaries(low,True)[:,:3]))
        h=model.edited(zero,x,dt,q,True)
        truncated=model.edited(zero,x[:,:3],dt[:,:3],q[:,:3],True)
        torch.testing.assert_close(h[:,:3],truncated,rtol=1e-11,atol=1e-12)
        self.assertGreater(float((h-model.edited(zero,x,dt,low,True)).abs().detach().max()),1e-5)
        raw=policy.free_state(s['x'][:,:3],s['scores'][:,:3],s['dt'][:,:3]); np.testing.assert_array_equal(raw,z[:,:3])

    def test_policy_trace_matches_independent_law(self):
        s=synthetic(3); rng=np.random.default_rng(22); q=rng.normal(size=(12,6,3)); q[:,-1,policy.WAIT]=99
        for can_read in (False,True):
            a=run.score(q,s,can_read); b=independent.outcome(s,np.array(a['exit_prefix']),np.array(a['terminal_action']))
            self.assertEqual(a['episode_hit'],b['episode_hit']); np.testing.assert_allclose(a['episode_utility'],b['episode_utility'],atol=1e-14,rtol=0)
            self.assertAlmostEqual(a['r1'],b['r1']); self.assertAlmostEqual(a['utility'],b['utility']); self.assertEqual(a['per_source'].keys(),b['per_source'].keys())
            self.assertTrue(all(p<=5 for p in a['exit_prefix']))
            if not can_read: self.assertEqual(a['reads'],0)

    def test_train_phase_and_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); data=p/'data'; out=p/'evidence'; data.mkdir()
            for k in ('train','dev','retain'): np.savez(data/(k+'.npz'),**synthetic(2,offset=k))
            fake_front(data)
            run.prepare_fit(data,out)
            self.assertTrue((out/'prepare/read.json').exists())
            with self.assertRaises(FileNotFoundError): run.check_seal(out)
            self.assertFalse((data/'test.npz').exists())


if __name__=='__main__': unittest.main()
