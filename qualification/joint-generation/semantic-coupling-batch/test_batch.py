import itertools,unittest
import numpy as np
from control import Command,ControlProfile,MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE,sample_joint
from batch import apply_batch

SHA='a'*64

def fixture(n=36,permuted=False):
    sem=tuple((i+4)%12 for i in range(12)) if permuted else tuple(range(12))
    profile=CouplingProfile(TransportProfile(ControlProfile(SHA,tuple(range(12)),sem,MODE),TRANSPORT_MODE),COUPLING_MODE)
    commands=tuple(Command(*v) for v in itertools.product(range(4),range(3),range(3)))
    commands=tuple(commands[i%36] for i in range(n))
    p=(np.arange(n*12).reshape(n,12)%17+1).astype(float);q=(np.arange(n*12).reshape(n,12)%13+1).astype(float)[:,::-1].copy()
    p/=p.sum(1,keepdims=True);q/=q.sum(1,keepdims=True)
    for i in range(n):
        if i%4==0:q[i]=p[i]
        if i%7==0:p[i]=np.eye(12)[0];q[i]=np.eye(12)[1]
    return profile,p,q,commands


class BatchTests(unittest.TestCase):
    def test_all36_commands_scalar_parity_both_semantic_maps(self):
        for permuted in (False,True):
            profile,p,q,commands=fixture(permuted=permuted);batch=apply_batch(profile,p,q,commands,observed_model_sha256=SHA)
            for i,c in enumerate(commands):
                scalar=profile.apply(tuple(p[i].tolist()),tuple(q[i].tolist()),c,observed_model_sha256=SHA)
                for key in ('text','image','joint'):np.testing.assert_allclose(batch[key][i],scalar[key],rtol=0,atol=1e-12)
                self.assertEqual(batch['profile_key'],scalar['profile_key'])

    def test_zero_residual_diagonal_exact(self):
        profile,p,q,commands=fixture(1);p=np.zeros((1,12));p[0,3]=1
        r=apply_batch(profile,p,p,(Command(0,0,0),),observed_model_sha256=SHA)
        self.assertEqual(r['joint'][0,3,3],1);self.assertEqual(r['joint'].sum(),1)

    def test_input_immutability_and_normalized_marginals(self):
        profile,p,q,commands=fixture();before=(p.copy(),q.copy())
        r=apply_batch(profile,p,q,commands,observed_model_sha256=SHA);normalized=r['joint']/r['cdf_total'][:,None,None]
        np.testing.assert_array_equal(p,before[0]);np.testing.assert_array_equal(q,before[1])
        np.testing.assert_allclose(normalized.sum(2),r['text'],rtol=0,atol=1e-12)
        np.testing.assert_allclose(normalized.sum(1),r['image'],rtol=0,atol=1e-12)

    def test_near_normalized_counterexample_rejects(self):
        profile,p,q,commands=fixture(1);p=np.zeros((1,12));p[0,0]=1+5e-11
        with self.assertRaises(ValueError):apply_batch(profile,p,p,(Command(0,0,0),),observed_model_sha256=SHA)

    def test_explicit_binding_shapes_commands_and_probabilities_reject(self):
        profile,p,q,commands=fixture(1)
        for pp,qq,cc,digest in ((p,q,commands,'b'*64),(p,q,list(commands),SHA),(p[:,:11],q,commands,SHA),(p*2,q,commands,SHA),(p*np.nan,q,commands,SHA),(p[:0],q[:0],(),SHA)):
            with self.assertRaises(ValueError):apply_batch(profile,pp,qq,cc,observed_model_sha256=digest)

    def test_cdf_draw_parity(self):
        profile,p,q,commands=fixture();b=apply_batch(profile,p,q,commands,observed_model_sha256=SHA)
        for i in range(len(p)):
            s=profile.apply(tuple(p[i].tolist()),tuple(q[i].tolist()),commands[i],observed_model_sha256=SHA)
            joint=tuple(map(tuple,b['joint'][i].tolist()))
            for u in (0.,.37,.999999):self.assertEqual(sample_joint(joint,u),sample_joint(s['joint'],u))


if __name__=='__main__':unittest.main()
