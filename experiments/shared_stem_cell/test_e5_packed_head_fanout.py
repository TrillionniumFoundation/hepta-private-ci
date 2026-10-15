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
    def test_packed_sgd_equals_isolated_per_cell_sgd(self):
        torch.manual_seed(38)
        heads=[seq.make_head(torch) for _ in range(3)]
        packed={key:torch.stack([h.state_dict()[key].detach().clone() for h in heads]).requires_grad_(True)
                for key in heads[0].state_dict()}
        feature=torch.randn((3,384))
        states=torch.randn((3,64));labels=torch.tensor([1,2,3])
        before={key:val.detach().clone() for key,val in packed.items()}
        loss=torch.nn.functional.cross_entropy(m.packed_forward(torch,packed,feature,states),labels,reduction='sum')
        loss.backward()
        with torch.no_grad():
            for value in packed.values():
                self.assertTrue(bool(torch.isfinite(value.grad).all()))
                value.add_(value.grad,alpha=-0.01)
        for i,head in enumerate(heads):
            head.zero_grad(set_to_none=True)
            alone=torch.nn.functional.cross_entropy(head(feature[i:i+1],states[i:i+1]),labels[i:i+1])
            alone.backward()
            with torch.no_grad():
                for value in head.parameters():value.add_(value.grad,alpha=-0.01)
            for key,val in head.state_dict().items():
                self.assertTrue(torch.allclose(val,packed[key][i],rtol=1e-5,atol=1e-6),key)
        self.assertFalse(torch.equal(before['output.weight'],packed['output.weight'].detach()))

    def test_shared_encoder_gradient_never_receives_packed_head_update(self):
        weights={name:t.requires_grad_(True) for name,t in m.parameterize(torch,3,4).items()}
        feature=torch.randn((3,384),requires_grad=True)
        states=torch.randn((3,64),requires_grad=True)
        logits=m.packed_forward(torch,weights,feature,states)
        torch.nn.functional.cross_entropy(logits,torch.tensor([0,1,2])).backward()
        self.assertIsNone(feature.grad)
        self.assertIsNone(states.grad)
        self.assertIsNotNone(weights['output.weight'].grad)

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
