"""A packed step must attend *every* public operation, not their union."""
import unittest
import torch
from group_attention_coverage import per_operation_mass_loss


class OperationAttentionCoverageTests(unittest.TestCase):
    def test_union_loss_can_cheat_by_attending_only_first_required_fact(self):
        masks = torch.tensor([[[1.,0.,0.,0.],[0.,0.,0.,1.]]])
        ignored = torch.tensor([[.97,.01,.01,.01]])
        balanced = torch.tensor([[.49,.01,.01,.49]])
        union = masks.amax(dim=1)
        old_a = -(ignored * union).sum(-1).clamp_min(1e-8).log()
        old_b = -(balanced * union).sum(-1).clamp_min(1e-8).log()
        torch.testing.assert_close(old_a, old_b)
        self.assertGreater(per_operation_mass_loss(ignored,masks).item(),
                           per_operation_mass_loss(balanced,masks).item()+1.)

    def test_actual_gradients_increase_omitted_evidence_mass(self):
        x = torch.tensor([[4.,-2.,-2.,-3.]], requires_grad=True)
        masks = torch.tensor([[[1.,0.,0.,0.],[0.,0.,0.,1.]]])
        before = x.softmax(-1).detach()[0,3].item()
        loss = per_operation_mass_loss(x.softmax(-1),masks)
        loss.backward()
        self.assertLess(x.grad[0,3].item(), 0.)
        after = (x-.1*x.grad).softmax(-1).detach()[0,3].item()
        self.assertGreater(after,before)

    def test_variable_fact_lengths_have_equal_operation_weight(self):
        masks = torch.tensor([[[1.,1.,1.,0.,0.],[0.,0.,0.,0.,1.]]])
        attn = torch.tensor([[.25,.2,.2,.05,.3]])
        expected = -torch.tensor([.65,.3]).log().mean()
        torch.testing.assert_close(per_operation_mass_loss(attn,masks),expected)

    def test_empty_padded_operation_slots_contribute_no_loss(self):
        masks = torch.tensor([[[1.,0.],[0.,0.]]])
        attn = torch.tensor([[.8,.2]])
        torch.testing.assert_close(per_operation_mass_loss(attn,masks),
                                    -torch.tensor(.8).log())

    def test_reject_tensor_shape_drift(self):
        with self.assertRaises(ValueError):
            per_operation_mass_loss(torch.ones(1,4),torch.ones(1,4))

if __name__=="__main__":
    unittest.main()
