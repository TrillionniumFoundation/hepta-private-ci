import unittest,itertools,json
from dataclasses import FrozenInstanceError
import numpy as np
from control import Command,ControlProfile,MODE as CONTROL_MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE,sample_joint
from normalized import NormalizedCouplingProfile,MODE as BASE_MODE
from calibration import TemperatureProfile,MODE as GENERATION_MODE,apply_batch as reference
from cached import CompiledTemperatureProfile,IMPLEMENTATION,apply_batch
SHA='a'*64;MEASUREMENTS={}
def fixture(n=1008,temperatures=(.5,2.)):
    ts=tuple((i+3)%12 for i in range(12));ims=tuple((i+7)%12 for i in range(12))
    base=NormalizedCouplingProfile(CouplingProfile(TransportProfile(ControlProfile(SHA,ts,ims,CONTROL_MODE),TRANSPORT_MODE),COUPLING_MODE),BASE_MODE)
    profile=TemperatureProfile(base,*temperatures,GENERATION_MODE)
    all_commands=tuple(Command(*c) for c in itertools.product(range(4),range(3),range(3)));commands=tuple(all_commands[i%36] for i in range(n))
    p=np.arange(1,13,dtype=float);p/=p.sum();q=np.arange(12,0,-1,dtype=float)**2;q/=q.sum()
    return profile,np.tile(p,(n,1)),np.tile(q,(n,1)),commands

def compare(a,b):
    for key in ('text','image','joint','cdf_total'):np.testing.assert_array_equal(a[key],b[key])
    assert a['profile_key']==b['profile_key'] and a['commands']==b['commands']

class CachedTests(unittest.TestCase):
    def test_allcommands_and_sizes_are_bitwise_identical(self):
        rows=0
        for n in (1,36,1008):
            for temperatures in ((1.,1.),(.125,8.),(8.,.125)):
                profile,p,q,commands=fixture(n,temperatures);cache=CompiledTemperatureProfile(profile,IMPLEMENTATION)
                a=reference(profile,p,q,commands,observed_model_sha256=SHA);b=apply_batch(cache,p,q,commands,observed_model_sha256=SHA);compare(a,b);rows+=n
        MEASUREMENTS['bitwise_literal_output_rows']=rows;MEASUREMENTS['maximum_table_difference']=0.

    def test_same_supplied_uniform_draws(self):
        profile,p,q,commands=fixture(36);cache=CompiledTemperatureProfile(profile,IMPLEMENTATION)
        a=reference(profile,p,q,commands,observed_model_sha256=SHA);b=apply_batch(cache,p,q,commands,observed_model_sha256=SHA);count=0
        for row in (0,17,35):
            for u in (0.,.25,.5,.9,float(np.nextafter(1.,0.))):
                aa=tuple(map(tuple,a['joint'][row].tolist()));bb=tuple(map(tuple,b['joint'][row].tolist()))
                self.assertEqual(sample_joint(aa,u),sample_joint(bb,u));count+=1
        MEASUREMENTS['literal_paired_sampler_checks']=count

    def test_roundtrip_distinct_cache_identity_and_tamper_refusal(self):
        profile,p,q,commands=fixture(1);cache=CompiledTemperatureProfile(profile,IMPLEMENTATION)
        loaded=CompiledTemperatureProfile.loads(cache.dumps(),expected_model_sha256=SHA,expected_generation_mode=GENERATION_MODE,expected_implementation=IMPLEMENTATION)
        self.assertEqual(loaded.dumps(),cache.dumps());self.assertEqual(cache.generation_key,profile.key);self.assertNotEqual(cache.key,profile.key)
        for field in ('text_maps','command_order'):
            doc=json.loads(cache.dumps());doc['cache'][field][0][0]=11
            with self.assertRaises(ValueError):CompiledTemperatureProfile.loads(json.dumps(doc),expected_model_sha256=SHA,expected_generation_mode=GENERATION_MODE,expected_implementation=IMPLEMENTATION)
        with self.assertRaises(ValueError):CompiledTemperatureProfile.loads(cache.dumps(),expected_model_sha256='b'*64,expected_generation_mode=GENERATION_MODE,expected_implementation=IMPLEMENTATION)
        with self.assertRaises(ValueError):CompiledTemperatureProfile.loads(cache.dumps(),expected_model_sha256=SHA,expected_generation_mode=BASE_MODE,expected_implementation=IMPLEMENTATION)
        with self.assertRaises(ValueError):CompiledTemperatureProfile.loads(profile.dumps(),expected_model_sha256=SHA,expected_generation_mode=GENERATION_MODE,expected_implementation=IMPLEMENTATION)
        with self.assertRaises(ValueError):TemperatureProfile.loads(cache.dumps(),expected_model_sha256=SHA,expected_mode=GENERATION_MODE)

    def test_cache_buffers_and_inputs_immutable(self):
        profile,p,q,commands=fixture(36);cache=CompiledTemperatureProfile(profile,IMPLEMENTATION);pc,qc=p.copy(),q.copy()
        apply_batch(cache,p,q,commands,observed_model_sha256=SHA);np.testing.assert_array_equal(p,pc);np.testing.assert_array_equal(q,qc)
        with self.assertRaises(FrozenInstanceError):cache.text_maps=()
        for raw in (cache._text_bytes,cache._image_bytes):
            view=np.frombuffer(raw,dtype='<i8')
            with self.assertRaises(ValueError):view.flags.writeable=True

    def test_invalid_binding_inputs_and_profile_mixing(self):
        profile,p,q,commands=fixture(1);cache=CompiledTemperatureProfile(profile,IMPLEMENTATION)
        with self.assertRaises(ValueError):apply_batch(cache,p,q,commands,observed_model_sha256='b'*64)
        with self.assertRaises(ValueError):apply_batch(profile,p,q,commands,observed_model_sha256=SHA)
        with self.assertRaises(ValueError):apply_batch(cache,p,q,list(commands),observed_model_sha256=SHA)
        with self.assertRaises(ValueError):apply_batch(cache,p*np.nan,q,commands,observed_model_sha256=SHA)
        with self.assertRaises(ValueError):CompiledTemperatureProfile(profile,'wrong')

    def test_same_numerical_support_loss_refusal(self):
        profile,p,q,commands=fixture(1,(8.,1.));p=np.full((1,12),1e-50);p[0,0]=1.-11e-50
        cache=CompiledTemperatureProfile(profile,IMPLEMENTATION)
        for function,argument in ((reference,profile),(apply_batch,cache)):
            with self.assertRaisesRegex(ValueError,'support/argmax/marginal'):function(argument,p,q,commands,observed_model_sha256=SHA)
if __name__=='__main__':unittest.main()
