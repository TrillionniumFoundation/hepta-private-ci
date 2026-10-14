"""Physical packed tensor CPU tests, never model task learning evidence."""
import unittest
import torch
import e5_packed_head_fanout as m
import e5_physical_head_fanout as seq

class Tests(unittest.TestCase):
    def test_exact_packed_weight_geometry(self):
        w=m.parameterize(torch,64,7)
        self.assertEqual(sum(v.numel() for v in w.values()),64*9744)
        self.assertEqual(len(w),6)
    def test_genuine_batched_pytorch_forward(self):
        r=m.run(64,8,repeats=3)
        self.assertTrue(r['real_cpu_pytorch_batched_forward'])
        self.assertEqual(r['physical_input_feature_buffers'],1)
        self.assertEqual(r['complete_head_parameters'],64*9744)
        self.assertFalse(r['pretrained_encoder_executed'])
        self.assertFalse(r['production_promotion_permitted'])
    def test_not_a_forged_batch(self):
        w=m.parameterize(torch,2,7)
        out=m.packed_forward(torch,w,torch.ones((2,384)),torch.ones((2,64)))
        self.assertEqual(tuple(out.shape),(2,8))
        self.assertTrue(bool(torch.isfinite(out).all()))
    def test_equivalent_to_unpacked_head(self):
        torch.manual_seed(123)
        heads=[seq.make_head(torch) for _ in range(3)]
        w={key:torch.stack([h.state_dict()[key].detach() for h in heads]) for key in heads[0].state_dict()}
        feature=torch.randn(1,384)
        state=torch.randn(3,64)
        expected=torch.cat([h(feature,state[i:i+1]) for i,h in enumerate(heads)],0)
        actual=m.packed_forward(torch,w,feature.expand(3,-1),state)
        self.assertTrue(torch.allclose(expected,actual,rtol=1e-5,atol=1e-6),torch.max(abs(expected-actual)))
    def test_shape_tampering_denied(self):
        w=m.parameterize(torch,3,7);w['gate.bias']=w['gate.bias'][:2]
        with self.assertRaises(m.Invalid):m.packed_forward(torch,w,torch.ones((3,384)),torch.ones((3,64)))
    def test_bad_scale_denied(self):
        with self.assertRaises(m.Invalid):m.run(65,8)
    def test_no_fake_p99_certification(self):
        r=m.run(64,8,repeats=2)
        self.assertEqual(r['batch_forward_samples'],2)
        self.assertFalse(r['p99_independently_qualified'])

if __name__=='__main__':unittest.main()
