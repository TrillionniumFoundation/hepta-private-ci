"""Actual Torch CPU mechanism checks; no pretrained model or general reasoning claim."""
import unittest
import torch

from group_terminal_evidence import terminal_label_eligibility, guarded_terminal_cross_entropy


class TerminalEvidenceTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(123)
        torch.set_num_threads(1)

    @staticmethod
    def masks():
        # Two examples: evidence at stages 0 and 2, or only stage 0.
        # Two simultaneous operations at stage 2 cannot be silently dropped.
        out = torch.zeros(2, 4, 2, 5, dtype=torch.float32)
        out[0, 0, 0, 0] = 1.
        out[0, 2, 0, 2] = 1.
        out[0, 2, 1, 4] = 1.
        out[1, 0, 0, 1] = 1.
        return out

    def test_completion_requires_terminal_and_all_coalesced_facts(self):
        states = terminal_label_eligibility(self.masks())
        self.assertEqual(states.tolist(), [[False, False, True, True],
                                          [True, True, True, True]])
        self.assertFalse(states.requires_grad)

    def test_masked_cross_entropy_never_updates_unfinished_example(self):
        logits = torch.randn(2, 8, requires_grad=True)
        labels = torch.tensor([2, 4], dtype=torch.long)
        complete = terminal_label_eligibility(self.masks())[:, 0]
        loss, count = guarded_terminal_cross_entropy(logits, labels, complete)
        self.assertEqual(count, 1)
        loss.backward()
        self.assertEqual(logits.grad[0].abs().sum().item(), 0.)
        self.assertGreater(logits.grad[1].abs().sum().item(), 0.)
        torch.testing.assert_close(loss, torch.nn.functional.cross_entropy(
            logits.detach()[1:2], labels[1:2]), atol=0, rtol=0)

    def test_all_unfinished_has_exact_zero_gradient(self):
        logits = torch.randn(2, 8, requires_grad=True)
        labels = torch.tensor([0, 7])
        loss, count = guarded_terminal_cross_entropy(
            logits, labels, torch.tensor([False, False]))
        self.assertEqual(count, 0)
        self.assertEqual(loss.item(), 0.)
        loss.backward()
        self.assertEqual(logits.grad.abs().sum().item(), 0.)

    def test_all_completed_equals_normal_cross_entropy(self):
        logits = torch.randn(3, 8, requires_grad=True)
        labels = torch.tensor([1, 3, 5])
        loss, count = guarded_terminal_cross_entropy(logits, labels,
                                                     torch.tensor([True, True, True]))
        self.assertEqual(count, 3)
        torch.testing.assert_close(loss, torch.nn.functional.cross_entropy(logits, labels),
                                   atol=1e-7, rtol=1e-7)

    def test_tampered_or_empty_teachers_rejected(self):
        x = self.masks()
        bad = [x.clone().requires_grad_(), x.half(), x[:, :, :0],
               x.clone().fill_(0), x.clone().fill_(.5)]
        for masks in bad:
            with self.subTest(shape=tuple(masks.shape)), self.assertRaises(ValueError):
                terminal_label_eligibility(masks)
        x[0, 2, 1, 4] = float("nan")
        with self.assertRaises(ValueError):
            terminal_label_eligibility(x)

    def test_labels_and_inference_authority_not_accepted(self):
        logits = torch.randn(2, 8)
        bad = ((torch.tensor([0, 8]), torch.tensor([True, True])),
               (torch.tensor([0, 2]), torch.tensor([1, 1])),
               (torch.tensor([0., 2.]), torch.tensor([True, True])))
        for labels, complete in bad:
            with self.subTest(labels=labels.tolist()), self.assertRaises(ValueError):
                guarded_terminal_cross_entropy(logits, labels, complete)

    def test_train_only_differential_optimizer_observation(self):
        # A small real optimization step: premature label updates one model,
        # prefix-guarded update leaves the first case's gradient absent.
        x = torch.eye(2)
        targets = torch.tensor([0, 1])
        teacher = self.masks()
        linear_a = torch.nn.Linear(2, 2, bias=False)
        linear_b = torch.nn.Linear(2, 2, bias=False)
        linear_b.load_state_dict(linear_a.state_dict())
        a_loss = torch.nn.functional.cross_entropy(linear_a(x), targets)
        a_loss.backward()
        b_loss, n = guarded_terminal_cross_entropy(
            linear_b(x), targets, terminal_label_eligibility(teacher)[:, 0])
        b_loss.backward()
        self.assertEqual(n, 1)
        self.assertEqual(linear_b.weight.grad[:, 0].abs().sum().item(), 0.)
        self.assertGreater(linear_a.weight.grad[:, 0].abs().sum().item(), 0.)


if __name__ == "__main__":
    unittest.main()
