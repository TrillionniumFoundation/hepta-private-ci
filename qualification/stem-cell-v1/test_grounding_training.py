"""Small deterministic V9 fixtures; no Encoder, official data or campaign runs."""
import copy
from dataclasses import replace
from hashlib import sha256
import math
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from binding_training import BindingTrainingFailure, paired_margin_loss, world_pairs
from grounding_reader import GroundingReader
from grounding_spans import make_grounding_targets
from grounding_training import (ARMS, _Targets, _auxiliary, auxiliary_observation, auxiliary_panel,
    continue_grounding, mention_contrastive)
from retention_v7_training import make_retention_plan
from token_protocol import build_binding_cases
from token_reader_training import TokenBatch, parameter_digest


class OffsetTokenizer:
    is_fast = True

    def __call__(self,text,**kwargs):
        ids,offsets = [],[]
        for match in re.finditer(r"[A-Za-z]+|[.?]",text):
            left,right = match.span()
            pieces = [(left,right)] if right-left < 5 else [(left,right-2),(right-2,right)]
            for start,end in pieces:
                ids.append(int(sha256(text[start:end].encode()).hexdigest()[:8],16))
                offsets.append((start,end))
        return dict(input_ids=ids,offset_mapping=offsets)


def fixture(cases):
    tokenizer = OffsetTokenizer()
    texts = {text for c in cases for text in (*c.facts,c.question,c.candidate)}
    tokens = {text:tokenizer(text)["input_ids"] for text in texts}
    values = {text:torch.randn(len(tokens[text]),8,generator=torch.Generator().manual_seed(
        int(sha256(text.encode()).hexdigest()[:8],16))) for text in texts}
    size = len(cases)
    width = max(len(tokens[t]) for c in cases for t in c.facts)
    qwidth = max(len(tokens[c.question]) for c in cases)
    cwidth = max(1,max(len(tokens[c.candidate]) for c in cases))
    facts,question,candidate = torch.zeros(size,4,width,8),torch.zeros(size,qwidth,8),torch.zeros(size,cwidth,8)
    fmask,qmask,cmask = torch.zeros(size,4,width,dtype=torch.bool),torch.zeros(size,qwidth,dtype=torch.bool),torch.zeros(size,cwidth,dtype=torch.bool)
    for i,case in enumerate(cases):
        for j,text in enumerate(case.facts):
            n = len(tokens[text]);facts[i,j,:n],fmask[i,j,:n] = values[text],True
        for output,mask,text in ((question,qmask,case.question),(candidate,cmask,case.candidate)):
            n = len(tokens[text]);output[i,:n],mask[i,:n] = values[text],True
    data = TokenBatch(facts,question,candidate,fmask,qmask,cmask,torch.tensor([c.label for c in cases]),
        tuple(c.source_hash for c in cases))
    return data,make_grounding_targets(cases,tokens,tokenizer)


class GroundingTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.old = build_binding_cases("train",groups=4,seed=41)
        self.new = tuple(replace(c,paragraph_id=c.paragraph_id.replace("binding-v4/train/47/",
            "binding-v5/retention-v7-augmentation-0/1701/")) for c in build_binding_cases("train",groups=4,seed=47))
        self.natural = tuple(replace(c,paragraph_id="natural-"+c.paragraph_id,segmentation="natural-fixture",
            source_hash=sha256(("natural-"+c.source_hash).encode()).hexdigest()) for c in self.old)
        self.binding,self.old_targets = fixture(self.old)
        self.augmentation,self.new_targets = fixture(self.new)
        self.natural_data,self.natural_targets = fixture(self.natural)
        self.targets = dict(binding=self.old_targets,augmentation=self.new_targets)
        self.plan = make_retention_plan(self.natural,self.old,self.new,seed=41,updates=2)

    def model(self,arm="grounded_chain"):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(31)
            model = GroundingReader(8,8,max_hops=3,arm=arm,residual_seed=19,grounding_seed=23)
        model.training_source_groups = tuple(sorted(set(self.binding.source_groups)))
        return model.eval().requires_grad_(False)

    def fit(self,arm="grounded_chain",**changes):
        arguments = dict(arm=arm,plan=self.plan,natural_cases=self.natural,grounding_targets=self.targets,
            diagnostic_interval=1,wall_time_ns=60_000_000_000)
        arguments.update(changes)
        return continue_grounding(self.model(arm),self.natural_data,self.binding,self.augmentation,self.old,self.new,**arguments)

    def test_multi_positive_mass_deduplicates_contexts_and_has_real_gradients(self):
        vectors = torch.tensor([[1.,0.],[.8,.2],[0.,1.],[.2,.8]],requires_grad=True)
        entities = ["object:bead","object:bead","person:Ada","person:Ada"]
        contexts = [sha256(str(i).encode()).hexdigest() for i in range(4)]
        loss,record = mention_contrastive(vectors,entities,contexts,full=True)
        normalized = F.normalize(vectors,dim=-1)
        scores = normalized@normalized.T/.1
        expected = torch.stack([torch.logsumexp(scores[i,torch.arange(4)!=i],0)-scores[i,i^1] for i in range(4)]).mean()
        torch.testing.assert_close(loss,expected)
        duplicated,duplicate_record = mention_contrastive(torch.cat((vectors,vectors[:1])),entities+entities[:1],contexts+contexts[:1])
        torch.testing.assert_close(loss,duplicated)
        self.assertEqual(record["retrieval_queries"],4)
        self.assertEqual(duplicate_record["duplicate_mentions"],1)
        loss.backward()
        self.assertTrue(torch.isfinite(vectors.grad).all())
        self.assertGreater(vectors.grad.abs().sum().item(),0)
        with self.assertRaisesRegex(ValueError,"one canonical"):
            mention_contrastive(vectors,["object:bead","person:Ada",*entities[2:]],[contexts[0],contexts[0],*contexts[2:]])

    def test_no_cross_context_positive_or_negative_is_finite_zero(self):
        for entities,contexts in ((["object:a","person:b"],["a","b"]),(["object:a"]*2,["a","b"]),(["object:a"]*2,["a","a"])):
            vectors = torch.randn(2,3,requires_grad=True)
            loss,record = mention_contrastive(vectors,entities,contexts)
            self.assertEqual(loss.item(),0.)
            self.assertEqual(record["retrieval_queries"],0)
            loss.backward()
            self.assertTrue(torch.equal(vectors.grad,torch.zeros_like(vectors)))

    def test_span_selected_probabilities_replay_ce_and_supervise_metric_without_answer_input(self):
        model = self.model().requires_grad_(True)
        table = _Targets(self.old_targets,self.old,self.binding)
        targets = table.take(list(range(16)),self.binding)
        trace = model(*self.binding.features(),steps=3,graph_depth=2,return_attention=True)
        span,alignment,record = _auxiliary(trace,targets,full=True)
        replay = [-sum(math.log(max(p,1e-9)) for p in probabilities)/count for probabilities,count in
                  zip(record["span_selected_probabilities"],record["span_token_counts"])]
        self.assertAlmostEqual(span.item(),sum(replay)/len(replay),places=5)
        self.assertEqual(record["span_count"],160)
        self.assertEqual(len(record["slot_addresses"]),160)
        (span+.1*alignment).backward()
        self.assertGreater(model.grounding.queries.grad.abs().sum().item(),0)
        self.assertGreater(model.grounding.metric.weight.grad.abs().sum().item(),0)
        changed = tuple(replace(c,label=1-c.label,evidence_sentence_indices=()) for c in self.old)
        tokenizer = OffsetTokenizer()
        cache = {t:tokenizer(t)["input_ids"] for c in changed for t in (*c.facts,c.question,c.candidate)}
        self.assertEqual(make_grounding_targets(changed,cache,tokenizer),self.old_targets)

    def test_four_arms_preserve_all_streams_fixed_budget_and_original_model(self):
        receipts = {}
        for arm in ARMS:
            original = self.model(arm)
            original_sha = parameter_digest(original)
            trained,receipt = continue_grounding(original,self.natural_data,self.binding,self.augmentation,self.old,self.new,
                arm=arm,plan=self.plan,natural_cases=self.natural,grounding_targets=self.targets,diagnostic_interval=1)
            receipts[arm] = receipt
            self.assertEqual((receipt["status"],receipt["completed_steps"],len(receipt["updates"]),receipt["actual_total_exposures"]),
                             ("completed",2,6,96))
            self.assertEqual(parameter_digest(original),original_sha)
            self.assertNotEqual(parameter_digest(trained),original_sha)
            self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
            self.assertEqual([r["stream"] for r in receipt["updates"]],["natural","transfer","retention"]*2)
            self.assertEqual([r["logical_step"] for r in receipt["diagnostics"]],[0,1,2])
            self.assertEqual(receipt["actual_auxiliary_diagnostic_forwards"],6)
            for row in receipt["updates"]:
                supervised = row["stream"]!="natural"
                self.assertEqual(row["span_weight"],float(supervised and arm.startswith("grounded_")))
                self.assertEqual(row["identity_weight"],.1 if supervised and arm.startswith("grounded_") else 0.)
                self.assertEqual(row["auxiliary"]["span_count"],160 if supervised else 0)
                self.assertEqual((len(row["hop_state_gradient_l2"]),len(row["graph_state_gradient_l2"])),(3,2))
                self.assertEqual(row["graph_reset"],arm.endswith("_reset"))
                self.assertGreater(row["common_parameter_update_l2"],0)
                self.assertGreaterEqual(row["graph_parameter_update_l2"],0)
                self.assertGreater(row["cpu_ns"],0)
                cases = self.natural if not supervised else self.new if row["stream"]=="transfer" else self.old
                selected = [cases[i] for i in row["indices"]]
                logits = torch.tensor(row["logits"])
                ce = F.cross_entropy(logits,torch.tensor([c.label for c in selected]))
                pair = paired_margin_loss(logits,torch.tensor([c.label for c in selected]),world_pairs(selected)) if supervised else ce*0
                replay = ce.item()+row["pair_weight"]*pair.item()+row["span_weight"]*row["auxiliary"]["span_loss"]+row["identity_weight"]*row["auxiliary"]["contrastive"]["loss"]
                self.assertAlmostEqual(row["total_loss"],replay,places=5)
        for key in ("plan_sha256","natural_sequence_sha256","binding_sequence_sha256","augmentation_sequence_sha256","initial_model_sha256"):
            self.assertEqual(len({r[key] for r in receipts.values()}),1)

    def test_invalid_target_plan_or_mode_refuses_before_copy_and_optimizer(self):
        invalid = copy.deepcopy(self.targets)
        invalid["binding"]["fact_attention_targets"][0][0][0][0] += .5
        diagnostic = copy.deepcopy(self.targets)
        diagnostic["binding"].update(role="frozen_diagnostic",trainer_only=False)
        wrong_order = copy.deepcopy(self.targets)
        wrong_order["augmentation"]["case_ids"].reverse()
        with patch("grounding_training._train_copy") as copied,patch("grounding_training.torch.optim.Adam") as optimizer:
            for changes in (dict(grounding_targets=invalid),dict(grounding_targets=diagnostic),
                            dict(grounding_targets=wrong_order),dict(graph_depth=1),dict(plan={**self.plan,"updates":1})):
                with self.assertRaises(BindingTrainingFailure) as caught:
                    self.fit(**changes)
                self.assertEqual(caught.exception.receipt["updates"],[])
            copied.assert_not_called();optimizer.assert_not_called()

    def test_auxiliary_panel_reuses_one_table_and_forward_probabilities(self):
        model = self.model()
        bank = SimpleNamespace(dataset=lambda cases:self.binding)
        observed = auxiliary_observation(model,self.old,bank,self.old_targets)
        expected = model(*self.binding.features(),steps=3).softmax(-1)[:,1].tolist()
        self.assertEqual(observed["probabilities"],expected)
        self.assertEqual((observed["physical_forward_calls"],len(observed["logits"])),(1,16))
        with patch("grounding_training._Targets",wraps=_Targets) as table:
            panel = auxiliary_panel(model,self.old,bank,self.old_targets)
            self.assertEqual(table.call_count,1)
        self.assertEqual(panel["probabilities"],expected)
        natural_bank = SimpleNamespace(dataset=lambda cases:self.natural_data)
        natural = auxiliary_observation(model,self.natural,natural_bank,self.natural_targets)
        self.assertEqual((natural["span_count"],natural["contrastive"]["retrieval_queries"]),(0,0))
        frozen_targets = copy.deepcopy(self.old_targets)
        frozen_targets.update(role="frozen_diagnostic",trainer_only=False)
        self.assertEqual(auxiliary_panel(model,self.old,bank,frozen_targets)["probabilities"],expected)
        with self.assertRaisesRegex(ValueError,"frozen diagnostic"):
            auxiliary_panel(model.train(),self.old,bank,frozen_targets)

    def test_failure_preserves_completed_work_and_original_model(self):
        original = self.model()
        original_sha,persisted = parameter_digest(original),[]
        with patch("grounding_training._step",side_effect=RuntimeError("controlled update interruption")):
            with self.assertRaises(BindingTrainingFailure) as caught:
                continue_grounding(original,self.natural_data,self.binding,self.augmentation,self.old,self.new,
                    plan=self.plan,natural_cases=self.natural,grounding_targets=self.targets,failure_receipt_fn=persisted.append)
        self.assertEqual(persisted,[caught.exception.receipt])
        self.assertEqual(len(persisted[0]["diagnostics"]),1)
        self.assertEqual(persisted[0]["updates"],[])
        self.assertGreater(persisted[0]["cpu_ns"],0)
        self.assertTrue(persisted[0]["failed_attempt_time_included"])
        self.assertEqual(parameter_digest(original),original_sha)


if __name__ == "__main__":
    unittest.main()
