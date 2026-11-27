import itertools
import json
import math
import unittest
from control import Command,ControlProfile,MODE
from transport import TransportProfile,TRANSPORT_MODE

SHA='a'*64
SEM=tuple(range(12))
P=tuple((i+1)/78 for i in range(12))

def profile(image=SEM):return TransportProfile(ControlProfile(SHA,SEM,image,MODE),TRANSPORT_MODE)

class TransportTests(unittest.TestCase):
    def test_all_keep_exact(self):
        result=profile().apply(P,P,Command(0,0,0),observed_model_sha256=SHA)
        self.assertIs(result['text'],P);self.assertIs(result['image'],P)

    def test_complete_command_lattice_preserves_free_joint_distribution(self):
        semantics=tuple((i+4)%12 for i in SEM);state=profile(semantics)
        for words in itertools.product(range(4),range(3),range(3)):
            command=Command(*words);out=state.apply(P,P,command,observed_model_sha256=SHA)['image']
            before={};after={}
            for k,p,q in zip(semantics,P,out):
                attrs=(k//4,(k//2)%2,k%2);free=tuple(a for a,w in zip(attrs,words) if w==0)
                before[free]=before.get(free,0)+p;after[free]=after.get(free,0)+q
                if not command.permits(k):self.assertEqual(q,0)
            for key in before:self.assertAlmostEqual(before[key],after[key],places=14)
            self.assertAlmostEqual(math.fsum(out),1,places=14)

    def test_mass_can_move_to_zero_prior_destination(self):
        p=(1.,)+(0.,)*11
        out=profile().apply(p,p,Command(3,0,0),observed_model_sha256=SHA)['image']
        self.assertEqual(out,(0.,)*8+(1.,)+(0.,)*3)

    def test_permuted_decoder_uses_observed_semantics(self):
        p=(1.,)+(0.,)*11
        out=profile(tuple((i+4)%12 for i in SEM)).apply(p,p,Command(3,0,0),observed_model_sha256=SHA)['image']
        self.assertEqual(out,(0.,)*4+(1.,)+(0.,)*7)

    def test_missing_duplicate_semantics_rejects(self):
        with self.assertRaises(ValueError):profile((0,)*12)

    def test_keep_does_not_repair_old_wrong_attributes(self):
        p=(1.,)+(0.,)*11
        out=profile().apply(p,p,Command(2,0,0),observed_model_sha256=SHA)['image']
        self.assertEqual(out[4],1.) # Existing left/square attributes remain, right is not invented.
        self.assertEqual(out[5],0.)

    def test_explicit_roundtrip_and_mode_separation(self):
        p=profile();restored=TransportProfile.loads(p.dumps(),expected_model_sha256=SHA,expected_mode=TRANSPORT_MODE)
        self.assertEqual(p,restored);self.assertEqual(p.key,restored.key)
        with self.assertRaises(ValueError):TransportProfile.loads(p.dumps(),expected_model_sha256=SHA,expected_mode=MODE)
        with self.assertRaises(ValueError):ControlProfile.loads(p.dumps(),expected_model_sha256=SHA,expected_mode=MODE)

    def test_wrong_binding_or_tamper_rejects(self):
        p=profile();obj=json.loads(p.dumps());obj['profile_key']='b'*64
        with self.assertRaises(ValueError):TransportProfile.loads(json.dumps(obj),expected_model_sha256=SHA,expected_mode=TRANSPORT_MODE)
        with self.assertRaises(ValueError):p.apply(P,P,Command(1,1,1),observed_model_sha256='b'*64)

    def test_full_command_point_mass_is_structural_not_learned(self):
        for color,shape,position in itertools.product(range(1,4),range(1,3),range(1,3)):
            out=profile().apply(P,P,Command(color,shape,position),observed_model_sha256=SHA)['text']
            target=((color-1)*2+shape-1)*2+position-1
            self.assertAlmostEqual(out[target],math.fsum(P),places=14);self.assertEqual(sum(x>0 for x in out),1)

if __name__=='__main__':unittest.main()
