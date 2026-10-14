"""Synthetic mechanism tests, never task-quality or independent evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn
from safetensors.torch import save_file, load_file

import five_causal_experiments as c
import shared_question_gate as g
from experiments.shared_stem_cell.execution import parameters, tensor_digest


def inputs():
    def plan(split, schema):
        evidence = [{"id": "S1", "modality": "text", "text": split + " original source and date 2020-01-01",
                     "asset_sha256": None, "position": 0}]
        request = {"question": split + " matched question?", "options": [], "evidence": evidence}
        other = deepcopy(request); other["question"] = split + " different question?"
        available = {"question_id": c.digest(split + "q"), "family": split + ":r", "donor_family": split + ":d",
                     "split": split, "status": "available", "matched_request": request,
                     "mismatched_request": other, "donor_response": "SECRET TARGET NOT PUBLIC"}
        missing = {"question_id": c.digest(split + "missing"), "family": split + ":r", "split": split,
                   "status": "unavailable_donor" if split == "train" else "unavailable_reference_or_donor",
                   "matched_request": None, "mismatched_request": None}
        return {"schema": schema, "units": [available, missing]}
    return plan("train", "hepta.reader.train-question-relevance.v1"), plan("select", "hepta.reader.select-same-source-question.v1")


class Tokenizer:
    def __call__(self, text, **kwargs):
        assert kwargs["truncation"] is False
        return {"input_ids": [1] + [ord(x) % 251 + 2 for x in text] + [2]}


class EncoderFixture:
    def __init__(self):
        self.loaded = nn.Linear(8, 8, bias=False).eval().requires_grad_(False)
        self.tokenizer = Tokenizer()
        self.calls = []
    def encode(self, texts):
        self.calls.append(texts[:])
        with torch.no_grad():
            return self.loaded(torch.stack([torch.arange(1, 9, dtype=torch.float32)*(1+len(t)/100) for t in texts]))
    def close(self):
        pass


class PublicPlanTests(unittest.TestCase):
    def test_exact_source_shared_between_questions(self):
        plan = g.public_plan(*inputs())
        for unit in plan["units"]:
            if unit["status"] == "available":
                a, b = unit["variants"]
                self.assertEqual(a["evidence_key"], b["evidence_key"])
                self.assertNotEqual(a["question_key"], b["question_key"])
        self.assertEqual(len(plan["features"]), 6)

    def test_answer_and_scopes_not_neural_fields(self):
        plan = g.public_plan(*inputs())
        for row in plan["features"]:
            self.assertNotIn("SECRET TARGET", row["text"])
            self.assertIn(set(json.loads(row["text"])), ({"question", "options"}, {"evidence"}))

    def test_input_not_changed(self):
        a, b = inputs(); before = c.digest([a, b])
        g.public_plan(a, b)
        self.assertEqual(c.digest([a, b]), before)

    def test_missing_pairs_are_retained(self):
        plan = g.public_plan(*inputs())
        self.assertEqual(len(plan["units"]), 4)
        self.assertEqual(sum(not u["variants"] for u in plan["units"]), 2)

    def test_family_overlap_rejected(self):
        a, b = inputs(); b["units"][0]["donor_family"] = "train:d"
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_source_overlap_rejected(self):
        a, b = inputs()
        for name in ("matched_request", "mismatched_request"):
            b["units"][0][name]["evidence"] = deepcopy(a["units"][0][name]["evidence"])
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_same_question_rejected(self):
        a, b = inputs(); a["units"][0]["mismatched_request"] = deepcopy(a["units"][0]["matched_request"])
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_changed_evidence_rejected(self):
        a, b = inputs(); a["units"][0]["mismatched_request"]["evidence"][0]["text"] = "changed"
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_test_partition_rejected(self):
        a, b = inputs(); b["units"][0]["split"] = "test"
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_duplicate_question_rejected(self):
        a, b = inputs(); a["units"].append(deepcopy(a["units"][0]))
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_extra_public_answer_field_rejected(self):
        a, b = inputs(); a["units"][0]["matched_request"]["answer"] = "hidden"
        with self.assertRaises(c.Invalid): g.public_plan(a, b)

    def test_overlong_text_not_truncated(self):
        plan = g.public_plan(*inputs())
        census = g.token_preflight(Tokenizer(), plan, 8)
        self.assertFalse(census["all_within_cap"])
        self.assertFalse(census["truncated"])
        self.assertEqual(len(census["rows"]), 6)


class EncoderTests(unittest.TestCase):
    def test_one_encode_per_unique_scope_text(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture()
        preflight = g.token_preflight(backend.tokenizer, plan)
        values, result = g.encode_once(backend, plan, preflight)
        self.assertEqual(sum(map(len, backend.calls)), 6)
        self.assertEqual(result["component_requests"], 8)
        self.assertEqual(result["deduplicated_component_requests"], 2)
        self.assertEqual(len(values), 6)
        self.assertTrue(all(torch.allclose(v.norm(), torch.tensor(1.)) for v in values.values()))

    def test_output_rows_have_independent_storage(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture()
        values, _ = g.encode_once(backend, plan, g.token_preflight(backend.tokenizer, plan))
        self.assertEqual(len({v.untyped_storage().data_ptr() for v in values.values()}), len(values))

    def test_preflight_failure_makes_no_encoder_calls(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture()
        with self.assertRaises(c.Invalid): g.encode_once(backend, plan, g.token_preflight(backend.tokenizer, plan, 8))
        self.assertEqual(backend.calls, [])

    def test_feature_text_drift_rejected(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture()
        census = g.token_preflight(backend.tokenizer, plan)
        plan["features"][0]["text"] += " extra"
        with self.assertRaises(c.Invalid): g.encode_once(backend, plan, census)
        self.assertEqual(backend.calls, [])

    def test_nonfinite_backend_result_rejected(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture()
        backend.encode = lambda texts: torch.full((len(texts), 8), float("nan"))
        with self.assertRaises(c.Invalid): g.encode_once(backend, plan, g.token_preflight(backend.tokenizer, plan))

    def test_trainable_encoder_rejected(self):
        plan = g.public_plan(*inputs()); backend = EncoderFixture(); backend.loaded.requires_grad_(True)
        with self.assertRaises(c.Invalid): g.encode_once(backend, plan, g.token_preflight(backend.tokenizer, plan))


class HeadTests(unittest.TestCase):
    def data(self):
        q = torch.zeros(2, 8); q[0, 0] = 1; q[1, 0] = -1
        e = torch.ones(2, 8)/8**0.5
        return q, e, torch.tensor([1., 0.])

    def test_actual_parameter_counts(self):
        self.assertEqual(parameters(g.QuestionGate(384))["parameters"], 6921)
        self.assertEqual(parameters(g.QuestionGate(384, kind="linear"))["parameters"], 769)
        self.assertEqual(parameters(g.QuestionGate(384, kind="evidence"))["parameters"], 385)

    def test_identical_evidence_no_question_control_cannot_rank(self):
        q, e, _ = self.data(); model = g.QuestionGate(8, kind="evidence")
        nn.init.normal_(model.e_read.weight)
        self.assertEqual(*model(q, e).tolist())

    def test_gate_can_reverse_question_ranking_as_evidence_changes(self):
        q, _, _ = self.data(); model = g.QuestionGate(8, rank=2)
        with torch.no_grad():
            model.q_down.weight.zero_(); model.q_down.weight[:, 0] = 1
            model.e_gate.weight.zero_(); model.e_gate.weight[0, 0] = 3; model.e_gate.weight[1, 0] = -3
            model.read.copy_(torch.tensor([1., -1.]))
        e = torch.zeros_like(q); e[:, 0] = 1
        a, b = model(q, e), model(q, -e)
        self.assertGreater(float(a[0]-a[1]), 0)
        self.assertLess(float(b[0]-b[1]), 0)

    def test_optimizer_changes_head_not_features(self):
        q, e, y = self.data(); before = [tensor_digest(x) for x in (q,e,y)]
        model, result = g.fit(q,e,y,arm="gated_aligned",seed=5,steps=32)
        self.assertEqual(result["optimizer_steps"],32)
        self.assertNotEqual(result["initial"]["sha256"], result["saved_model"]["sha256"])
        self.assertEqual(before,[tensor_digest(x) for x in (q,e,y)])
        self.assertFalse(any(p.requires_grad for p in model.parameters()))

    def test_reversed_control_changes_direction(self):
        q,e,y=self.data()
        a,_=g.fit(q,e,y,arm="gated_aligned",seed=5,steps=32)
        b,_=g.fit(q,e,y,arm="gated_reversed",seed=5,steps=32)
        self.assertGreater(float(a(q,e)[0]-a(q,e)[1]),0)
        self.assertLess(float(b(q,e)[0]-b(q,e)[1]),0)

    def test_frozen_head_performs_zero_updates(self):
        q,e,y=self.data(); _, r=g.fit(q,e,y,arm="frozen_gate",seed=5)
        self.assertEqual(r["optimizer_steps"],0)
        self.assertEqual(r["initial"],r["saved_model"])

    def test_select_cannot_enter_optimizer(self):
        with self.assertRaises(c.Invalid): g.fit(*self.data(),arm="gated_aligned",seed=5,split="select")

    def test_initialization_matches_reversed_and_frozen(self):
        hashes=[g.fit(*self.data(),arm=a,seed=7,steps=1)[1]["initial"]["sha256"] for a in ("frozen_gate","gated_aligned","gated_reversed")]
        self.assertEqual(len(set(hashes)),1)

    def test_inference_feature_tensor_is_copied_for_training(self):
        with torch.inference_mode(): q,e,y=self.data()
        _,r=g.fit(q,e,y,arm="linear_aligned",seed=5,steps=1)
        self.assertEqual(r["optimizer_steps"],1)

    def test_safetensor_roundtrip_keeps_scores(self):
        q,e,y=self.data(); m,_=g.fit(q,e,y,arm="gated_aligned",seed=2,steps=2)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"head.safetensors"; save_file(m.state_dict(),str(p))
            n=deepcopy(m); n.load_state_dict(load_file(str(p)))
            self.assertTrue(torch.equal(m(q,e),n(q,e)))

    def test_nonfinite_and_wrong_width_rejected(self):
        m=g.QuestionGate(8)
        for q,e in ((torch.ones(2,7),torch.ones(2,7)), (torch.full((2,8),float("nan")),torch.ones(2,8))):
            with self.assertRaises(c.Invalid):m(q,e)


class ReadoutTests(unittest.TestCase):
    def rows(self, scores):
        plan=g.public_plan(*inputs())
        rows=[{"pair_id":u["pair_id"],"status":"succeeded" if u["variants"] else "unavailable",
               "logits":scores if u["variants"] else None} for u in plan["units"]]
        return plan["units"],rows

    def test_zero_logit_tie_not_selective(self):
        r=g.summarize(*self.rows([0.,0.]))
        self.assertTrue(all(x["joint_weak_direction"]==0 for x in r))

    def test_ranking_alone_not_two_directions(self):
        r=g.summarize(*self.rows([2.,1.]))
        self.assertEqual(r[0]["positive_paired_ranking"],1)
        self.assertEqual(r[0]["joint_weak_direction"],0)

    def test_missing_pair_is_not_zero_effect(self):
        r=g.summarize(*self.rows([1.,-1.]))
        self.assertEqual(r[1]["planned_pairs"],2)
        self.assertEqual(r[1]["scored_pairs"],1)
        self.assertEqual(r[1]["mean_margin"],2.)
        self.assertIsNone(r[1]["semantic_accuracy"])

    def test_duplicate_and_missing_predictions_rejected(self):
        u,r=self.rows([1.,-1.])
        with self.assertRaises(c.Invalid):g.summarize(u,r+r[:1])
        with self.assertRaises(c.Invalid):g.summarize(u,r[:-1])

    def test_nan_cannot_be_imputed_as_success(self):
        with self.assertRaises(c.Invalid):g.summarize(*self.rows([float("nan"),0.]))


if __name__=="__main__":
    unittest.main()
