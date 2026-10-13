"""Pure Torch projection/gradient tests. Random fixtures are not model evidence."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import torch
from torch.nn import functional as F
import assistant_projection as p


class CausalFixture(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = torch.nn.Embedding(17, 9)
        self.mix = torch.nn.Linear(9, 9)
        self.lm_head = torch.nn.Linear(9, 17, bias=False)
        self.seen = []
    def get_output_embeddings(self):
        return self.lm_head
    def forward(self, input_ids, attention_mask, use_cache, logits_to_keep=0):
        self.seen.append(input_ids.detach().clone())
        assert use_cache is False
        hidden = torch.tanh(self.mix(self.embed(input_ids).cumsum(1)))
        index = slice(None) if isinstance(logits_to_keep, int) else logits_to_keep
        return SimpleNamespace(logits=self.lm_head(hidden[:, index]))


def example(length=12, prefix=8):
    ids = torch.arange(length).remainder(17)[None]
    labels = ids.clone(); labels[:, :prefix] = -100
    return dict(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels)


def reference(model, batch):
    output = model(input_ids=batch['input_ids'], attention_mask=batch['attention_mask'], use_cache=False)
    return -F.cross_entropy(output.logits[:, :-1].float().reshape(-1,17),
                            batch['labels'][:, 1:].reshape(-1), ignore_index=-100)


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
    def setUp(self):
        with torch.random.fork_rng():
            torch.manual_seed(314)
            self.model = CausalFixture().eval()
    def test_one_causal_shift_and_eos_position(self):
        positions, labels = p.response_positions(example())
        self.assertEqual(positions.tolist(), [7,8,9,10])
        self.assertEqual(labels.tolist(), [8,9,10,11])
    def test_single_response_token_and_single_prompt_token(self):
        for length,prefix in ((12,11),(2,1),(12,1)):
            batch=example(length,prefix)
            torch.testing.assert_close(reference(self.model,batch), p.sequence_score(self.model,batch))
    def test_exact_score_and_all_parameter_gradients(self):
        other=deepcopy(self.model); batch=example()
        full=reference(self.model,batch); short=p.sequence_score(other,batch)
        full.backward(); short.backward()
        torch.testing.assert_close(full,short,rtol=1e-6,atol=1e-6)
        for a,b in zip(self.model.parameters(),other.parameters()):
            torch.testing.assert_close(a.grad,b.grad,rtol=1e-5,atol=1e-7)
    def test_complete_context_is_retained_and_receives_gradient(self):
        batch=example(); old={k:v.clone() for k,v in batch.items()}
        p.sequence_score(self.model,batch).backward()
        self.assertTrue(torch.equal(self.model.seen[0],batch['input_ids']))
        self.assertGreater(float(self.model.embed.weight.grad[0].abs().sum()),0)
        for k in batch: self.assertTrue(torch.equal(batch[k],old[k]))
    def test_multiple_adam_updates_match(self):
        other=deepcopy(self.model)
        a=torch.optim.AdamW(self.model.parameters(),lr=.002)
        b=torch.optim.AdamW(other.parameters(),lr=.002)
        for _ in range(4):
            for model,optimizer,fn in ((self.model,a,reference),(other,b,p.sequence_score)):
                optimizer.zero_grad(); (-fn(model,example())).backward(); optimizer.step()
        for x,y in zip(self.model.parameters(),other.parameters()):
            torch.testing.assert_close(x,y,rtol=1e-5,atol=1e-6)
    def test_projection_meter_counts_only_produced_tensors(self):
        with p.projection_meter(self.model) as full: reference(self.model,example())
        with p.projection_meter(self.model) as selected: p.sequence_score(self.model,example())
        self.assertEqual(full['projected_positions'],12)
        self.assertEqual(selected['projected_positions'],4)
        self.assertEqual(full['produced_logit_bytes'],12*17*4)
        self.assertEqual(selected['produced_logit_bytes'],4*17*4)
        self.assertFalse(selected['peak_process_memory_measured'])
        self.assertFalse(self.model.lm_head._forward_hooks)
    def test_backend_ignoring_selection_fails_without_retry(self):
        class Ignoring(CausalFixture):
            def forward(self, **kw):
                kw.pop('logits_to_keep',None)
                return super().forward(**kw)
        model=Ignoring()
        with self.assertRaises(ValueError): p.sequence_score(model,example())
        self.assertEqual(len(model.seen),1)
    def test_no_prompt_or_no_response_rejected_before_call(self):
        for prefix in (0,12):
            with self.assertRaises(ValueError): p.sequence_score(self.model,example(prefix=prefix))
        self.assertFalse(self.model.seen)
    def test_noncontiguous_response_mask_rejected(self):
        batch=example(); batch['labels'][0,10]=-100
        with self.assertRaises(ValueError): p.sequence_score(self.model,batch)
    def test_changed_labels_rejected(self):
        batch=example(); batch['labels'][0,8]=1
        with self.assertRaises(ValueError): p.sequence_score(self.model,batch)
    def test_padding_and_multirow_rejected(self):
        batch=example(); batch['attention_mask'][0,0]=0
        with self.assertRaises(ValueError): p.sequence_score(self.model,batch)
        batch={k:v.repeat(2,1) for k,v in example().items()}
        with self.assertRaises(ValueError): p.sequence_score(self.model,batch)
    def test_extra_fields_and_non_tensor_rejected(self):
        for batch in (example()|{'gold':'x'},example()|{'labels':[]},{}):
            with self.assertRaises(ValueError): p.sequence_score(self.model,batch)
    def test_nonfinite_logits_and_bad_vocabulary_rejected(self):
        targets=torch.tensor([1,2]); logits=torch.zeros(1,2,3)
        logits[0,0,0]=float('nan')
        with self.assertRaises(ValueError): p.selected_logp(logits,targets)
        with self.assertRaises(ValueError): p.selected_logp(torch.zeros(1,2,2),targets)
    def test_hook_removed_after_failure(self):
        with self.assertRaises(RuntimeError):
            with p.projection_meter(self.model) as meter:
                reference(self.model,example()); raise RuntimeError('fixture')
        self.assertEqual(meter['head_calls'],1)
        self.assertFalse(self.model.lm_head._forward_hooks)
    def test_no_grad_does_not_enable_grad(self):
        with torch.no_grad(): score=p.sequence_score(self.model,example())
        self.assertFalse(score.requires_grad)


if __name__=='__main__': unittest.main()
