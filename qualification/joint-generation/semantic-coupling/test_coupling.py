import unittest,json,math,itertools
from control import Command,ControlProfile,MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE,sample_joint

SHA='a'*64

def profile(image=tuple(range(12))):
    return CouplingProfile(TransportProfile(ControlProfile(SHA,tuple(range(12)),image,MODE),TRANSPORT_MODE),COUPLING_MODE)


class CouplingTests(unittest.TestCase):
    def test_equal_marginals_diagonal_and_exact_zero_residual(self):
        p=(.5,.5)+(0.,)*10;law=profile().apply(p,p,Command(0,0,0),observed_model_sha256=SHA)
        self.assertEqual(sum(law['joint'][i][i] for i in range(12)),1)
        self.assertEqual(law['joint'][0][0],.5);self.assertEqual(law['joint'][1][1],.5)

    def test_disjoint_support_residual_product(self):
        p=(.25,.75)+(0.,)*10;q=(0.,0.,.6,.4)+(0.,)*8
        law=profile().apply(p,q,Command(0,0,0),observed_model_sha256=SHA)
        for i,j in itertools.product(range(12),repeat=2):self.assertAlmostEqual(law['joint'][i][j],p[i]*q[j],places=15)

    def test_partial_overlap_maximum_agreement_and_marginals(self):
        p=(.4,.3,.3)+(0.,)*9;q=(.2,.5,.3)+(0.,)*9
        law=profile().apply(p,q,Command(0,0,0),observed_model_sha256=SHA);joint=law['joint']
        for i in range(12):
            self.assertAlmostEqual(math.fsum(joint[i]),p[i],places=15)
            self.assertAlmostEqual(math.fsum(row[i] for row in joint),q[i],places=15)
            self.assertAlmostEqual(joint[i][i],min(p[i],q[i]),places=15)
        self.assertAlmostEqual(sum(joint[i][i] for i in range(12)),.8,places=15)

    def test_observed_semantics_not_latent_diagonal(self):
        perm=tuple((i+4)%12 for i in range(12));pr=profile(perm)
        p=(1.,)+(0.,)*11;q=tuple(float(s==0) for s in perm)
        joint=pr.apply(p,q,Command(0,0,0),observed_model_sha256=SHA)['joint']
        self.assertEqual(joint[0][8],1);self.assertEqual(joint[0][0],0)

    def test_all36_commands_preserve_entire_transported_marginals(self):
        p=tuple((i+1)/78 for i in range(12));q=tuple(reversed(p));pr=profile()
        for values in itertools.product(range(4),range(3),range(3)):
            c=Command(*values);law=pr.apply(p,q,c,observed_model_sha256=SHA)
            old=pr.transport.apply(p,q,c,observed_model_sha256=SHA)
            self.assertEqual((law['text'],law['image']),(old['text'],old['image']))
            for i in range(12):
                self.assertAlmostEqual(math.fsum(law['joint'][i]),old['text'][i],places=14)
                self.assertAlmostEqual(math.fsum(row[i] for row in law['joint']),old['image'][i],places=14)
                for j in range(12):
                    if not c.permits(i) or not c.permits(j):self.assertEqual(law['joint'][i][j],0)

    def test_distinct_identity_explicit_load_and_tamper_rejection(self):
        pr=profile();self.assertNotEqual(pr.key,pr.transport.key)
        loaded=CouplingProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=COUPLING_MODE)
        self.assertEqual(loaded,pr)
        for payload,sha,mode in ((pr.dumps(),'b'*64,COUPLING_MODE),(pr.dumps(),SHA,TRANSPORT_MODE),(pr.transport.dumps(),SHA,COUPLING_MODE),(pr.dumps().replace('"schema":','"schema":"wrong","schema":',1),SHA,COUPLING_MODE)):
            with self.assertRaises(ValueError):CouplingProfile.loads(payload,expected_model_sha256=sha,expected_mode=mode)

    def test_sampler_follows_positive_cdf_intervals(self):
        p=(.25,.75)+(0.,)*10;law=profile().apply(p,p,Command(0,0,0),observed_model_sha256=SHA)
        for u in (0,.1,.249999):self.assertEqual(sample_joint(law['joint'],u),(0,0))
        for u in (.25,.5,.999999):self.assertEqual(sample_joint(law['joint'],u),(1,1))

    def test_invalid_policies_modes_and_uniforms_reject(self):
        p=(1.,)+(0.,)*11;pr=profile()
        for bad in ((0.,)*12,(float('nan'),)+(0.,)*11):
            with self.assertRaises(ValueError):pr.apply(bad,p,Command(0,0,0),observed_model_sha256=SHA)
        near=(1+5e-11,)+(0.,)*11
        with self.assertRaises(ValueError):pr.apply(near,near,Command(0,0,0),observed_model_sha256=SHA)
        with self.assertRaises(ValueError):CouplingProfile(pr.transport,TRANSPORT_MODE)
        with self.assertRaises(ValueError):pr.apply(p,p,Command(0,0,0),observed_model_sha256='b'*64)
        joint=pr.apply(p,p,Command(0,0,0),observed_model_sha256=SHA)['joint']
        for u in (-1,1,float('nan')):
            with self.assertRaises(ValueError):sample_joint(joint,u)


if __name__=='__main__':unittest.main()
