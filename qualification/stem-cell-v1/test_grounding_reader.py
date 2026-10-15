"""Small public-tensor fixtures for V9 Group reuse and learned chain execution."""
import copy
import io
import unittest

import torch
from torch.nn import functional as F

from bridge_reader import build_reader
from grounding_reader import (ARMS,GroundingCore,build_grounding_reader,grounding_identity,
    load_grounding_warmup,restore_grounding_reader)
from token_reader_training import parameter_digest


def fixture():
    generator = torch.Generator().manual_seed(311)
    facts = torch.randn(4,3,4,384,generator=generator)
    facts[1],facts[3] = facts[0].clone(),facts[2].clone()
    mask = torch.ones(4,3,4,dtype=torch.bool)
    mask[:,1,-1] = False
    return (facts,torch.randn(4,2,384,generator=generator),torch.randn(4,3,384,generator=generator),
        mask,torch.ones(4,2,dtype=torch.bool),torch.ones(4,3,dtype=torch.bool))


class GroundingReaderTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.features = fixture()
        self.core = build_reader("bridge",41).eval().requires_grad_(False)
        self.core.training_source_groups = ("tiny-public-fixture",)

    def test_four_arms_have_identical_weights_and_exact_actual_warmup_predictions(self):
        rng = torch.random.get_rng_state().clone()
        models = [load_grounding_warmup(self.core,arm,seed=41) for arm in ARMS]
        self.assertTrue(torch.equal(rng,torch.random.get_rng_state()))
        self.assertEqual(len({parameter_digest(model) for model in models}),1)
        old = self.core(*self.features,steps=3)
        for arm,model in zip(ARMS,models):
            identity = grounding_identity(model)
            self.assertEqual(identity["parameter_count"],42562+2322)
            self.assertEqual(identity["arm"],arm)
            for name,value in self.core.state_dict().items():
                self.assertEqual(value.numpy().tobytes(),model.state_dict()[name].numpy().tobytes(),name)
            self.assertTrue(torch.equal(model(*self.features,steps=3),old))
            self.assertEqual(torch.count_nonzero(model.grounding.head[2].weight).item(),0)
            self.assertEqual(torch.count_nonzero(model.grounding.head[2].bias).item(),0)

    def test_deduplication_reuses_only_fact_computation_and_does_not_cache_across_calls(self):
        model = load_grounding_warmup(self.core,"grounded_chain",seed=41)
        shapes = []
        hook = model.grounding.feature.register_forward_pre_hook(lambda module,args:shapes.append(tuple(args[0].shape)))
        trace = model(*self.features,return_attention=True)
        hook.remove()
        self.assertEqual(trace["graph_grouped_counts"],dict(input_rows=4,unique_fact_groups=2,reused_rows=2))
        self.assertEqual(shapes[0],(2,3,4,32))
        self.assertEqual(len(shapes),3)
        self.assertTrue(torch.equal(trace["graph_slots"][0],trace["graph_slots"][1]))
        self.assertFalse(torch.equal(trace["graph_question"][0],trace["graph_question"][1]))
        with torch.no_grad():
            model.grounding.feature.weight[0,0] += .3
        later = model(*self.features,return_attention=True)
        self.assertFalse(torch.equal(trace["graph_slots"],later["graph_slots"]))

    def test_auxiliary_addresses_are_exactly_the_metric_used_by_the_walk(self):
        model = load_grounding_warmup(self.core,"grounded_chain",seed=41)
        trace = model(*self.features,return_attention=True)
        for address,raw in (("graph_slots","graph_slot_features"),("graph_question","graph_question_features"),
                            ("graph_candidate","graph_candidate_features")):
            torch.testing.assert_close(trace[address],F.normalize(model.grounding.metric(trace[raw]),dim=-1,eps=1e-8))
        state = trace["graph_question"]
        for actual,attention in zip(trace["graph_states"],trace["graph_fact_attentions"]):
            expected = F.normalize((attention[:,:,None]*trace["graph_slots"][:,:,1]).sum(1),dim=-1,eps=1e-8)
            torch.testing.assert_close(actual,expected)
            self.assertLessEqual(actual.abs().max().item(),1.000001)
            state = actual
        self.assertEqual(len(trace["states"]),3)
        self.assertEqual(len(trace["graph_states"]),2)
        self.assertTrue(torch.equal(trace["step_logits"][-1],trace["logits"]))

    def test_padding_and_fact_permutation_preserve_nonzero_graph_outputs(self):
        model = load_grounding_warmup(self.core,"grounded_chain",seed=41)
        with torch.no_grad():
            model.grounding.head[2].weight.fill_(.1)
        original = model(*self.features,return_attention=True)
        changed = list(self.features)
        changed[0] = changed[0].clone()
        changed[0][~changed[3]] = 10000
        torch.testing.assert_close(original["logits"],model(*changed))
        padded = list(self.features)
        padded[0] = torch.cat((padded[0],torch.full((4,1,4,384),10000.)),1)
        padded[3] = torch.cat((padded[3],torch.zeros(4,1,4,dtype=torch.bool)),1)
        result = model(*padded,return_attention=True)
        torch.testing.assert_close(original["logits"],result["logits"])
        torch.testing.assert_close(original["graph_readout_features"][-1],result["graph_readout_features"][-1])
        permutation = torch.tensor([2,0,1])
        permuted = list(self.features)
        permuted[0],permuted[3] = permuted[0][:,permutation],permuted[3][:,permutation]
        torch.testing.assert_close(original["logits"],model(*permuted))
        empty = list(self.features)
        empty[3] = torch.zeros_like(empty[3])
        absent = model(*empty,return_attention=True)
        self.assertTrue(torch.isfinite(absent["logits"]).all())
        self.assertEqual(torch.count_nonzero(absent["graph_states"][-1]).item(),0)

    def test_controlled_chain_reaches_second_destination_and_reset_repeats_first(self):
        core = GroundingCore(8)
        eye = torch.eye(8)
        slots = torch.stack((torch.stack((eye[0],eye[1])),torch.stack((eye[1],eye[2])))).unsqueeze(0)
        question,candidate,present = eye[0:1],eye[2:3],torch.ones(1,2,dtype=torch.bool)
        chain = core.walk(slots,question,candidate,present,depth=2)
        reset = core.walk(slots,question,candidate,present,depth=2,reset=True)
        one = core.walk(slots,question,candidate,present,depth=1)
        self.assertGreater((chain["graph_states"][-1]*candidate).sum().item(),.99)
        self.assertLess((reset["graph_states"][-1]*candidate).sum().item(),.1)
        self.assertTrue(torch.equal(one["graph_states"][0],reset["graph_states"][-1]))
        broken = core.walk(slots,question,candidate,present,value_permutation=torch.tensor([[1,0]]))
        self.assertFalse(torch.equal(chain["graph_states"][-1],broken["graph_states"][-1]))
        with self.assertRaisesRegex(ValueError,"unit-bounded"):
            core.walk(slots,question*2,candidate,present)

    def test_added_parameters_and_graph_states_receive_real_gradients_after_updates(self):
        for arm in ("grounded_chain","grounded_reset"):
            model = load_grounding_warmup(self.core,arm,seed=41).train().requires_grad_(True)
            initial = copy.deepcopy(model.state_dict())
            optimizer = torch.optim.SGD(model.parameters(),lr=.1)
            for _ in range(3):
                optimizer.zero_grad()
                trace = model(*self.features,return_attention=True)
                for state in trace["graph_states"]:
                    state.retain_grad()
                F.cross_entropy(trace["logits"],torch.tensor([0,1,1,0])).backward()
                optimizer.step()
            for name,value in model.named_parameters():
                if name.startswith("grounding."):
                    self.assertTrue(torch.isfinite(value.grad).all(),name)
                    self.assertGreater(value.grad.abs().sum().item(),0,name)
                    self.assertFalse(torch.equal(initial[name],value),name)
            self.assertGreater(trace["graph_states"][-1].grad.abs().sum().item(),0)
            if arm.endswith("reset"):
                self.assertIsNone(trace["graph_states"][0].grad)
            else:
                self.assertGreater(trace["graph_states"][0].grad.abs().sum().item(),0)

    def test_prepared_steps_and_strict_serialized_restore_include_the_graph_residual(self):
        model = load_grounding_warmup(self.core,"grounded_chain",seed=41)
        with torch.no_grad():
            model.grounding.head[2].weight.fill_(.07)
        prepared,state = model.prepare(*self.features),None
        for _ in range(3):
            state,logits,_,_ = model.step_prepared(prepared,state)
        self.assertTrue(torch.equal(logits,model(*self.features)))
        stream = io.BytesIO()
        torch.save(model.state_dict(),stream)
        stream.seek(0)
        restored = restore_grounding_reader("grounded_chain",7,torch.load(stream,weights_only=True),
                                            training_source_groups=model.training_source_groups)
        self.assertEqual(grounding_identity(restored),grounding_identity(model))
        self.assertTrue(torch.equal(logits,restored(*self.features)))
        with self.assertRaisesRegex(ValueError,"bounded graph"):
            model(*self.features,graph_depth=0)
        with self.assertRaisesRegex(ValueError,"bounded old"):
            model(*self.features,steps=0)
        with self.assertRaisesRegex(ValueError,"valid facts"):
            model(*self.features,value_permutation=torch.zeros(4,3,dtype=torch.long))


if __name__ == "__main__":
    unittest.main()
