"""Hermetic tests; tiny random Llama weights are fixtures, not model evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import torch
from transformers import LlamaConfig, LlamaForCausalLM

import five_causal_experiments as c
import five_reader_response_learning as l
import five_reader_response_trial as t
from five_native_historical_smoke import prepare_materials


class Tokenizer:
    chat_template = "fixture-template"
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is True
        if add_generation_prompt:
            return [1, 2, 3]
        return [1, 2, 3] + [4 + ord(x) % 64 for x in messages[-1]["content"]] + [2]


def examples():
    result = []
    for i, answer in enumerate(("Alpha", "Beta")):
        request = {"question": "Fixture?", "options": [], "evidence": [
            {"id": "E1", "modality": "text", "text": "fixture source", "asset_sha256": None, "position": 0}]}
        for kind in ("annotated_answer", "empty_refusal"):
            r = deepcopy(request)
            if kind == "empty_refusal":
                r["evidence"] = []
            result.append({"id": str(i)+":"+kind, "question_id": "q"+str(i), "family": "family"+str(i),
                "split": "train", "request": r, "response": answer if kind == "annotated_answer" else l.REFUSAL,
                "kind": kind, "source_sha256": "a"*64})
    return result


def benchmark():
    qs = [SimpleNamespace(identity="q"+str(i), family="f"+str(i), content="where fixture") for i in range(4)]
    docs = [SimpleNamespace(identity="d"+str(i), root="root"+str(i), content="fixture") for i in range(4)]
    return SimpleNamespace(questions=qs, families={q.family:q.family for q in qs},
        partition=lambda q: "train" if q.identity in ("q0", "q1") else "test",
        history=lambda q: [docs[int(q.identity[1:])]],
        targets={q.identity:SimpleNamespace(answer="Alpha", evidence=(docs[i].identity,), unresolved_evidence=(),
                                           unanswerable=False) for i,q in enumerate(qs)})


class SupervisionTests(unittest.TestCase):
    def test_prompt_tokens_are_masked_and_answer_tokens_remain(self):
        batch, receipt = l.compile_supervision(Tokenizer(), examples()[0], input_cap=8, response_cap=64, position_cap=128)
        self.assertEqual(batch["labels"][0,:3].tolist(), [-100]*3)
        self.assertTrue(torch.equal(batch["labels"][0,3:], batch["input_ids"][0,3:]))
        self.assertEqual(receipt["prefix_tokens"],3)
        self.assertTrue(receipt["response_only_loss"])

    def test_different_full_template_prefix_fails(self):
        class Bad(Tokenizer):
            def apply_chat_template(self, messages, **kwargs):
                ids = super().apply_chat_template(messages, **kwargs)
                if not kwargs["add_generation_prompt"]:
                    ids[0] = 99
                return ids
        with self.assertRaises(c.Invalid):
            l.compile_supervision(Bad(), examples()[0], input_cap=8, response_cap=64, position_cap=128)

    def test_no_response_or_prompt_truncation(self):
        for caps in ((2,64,128),(8,1,128),(8,64,4)):
            with self.assertRaises(c.Invalid):
                l.compile_supervision(Tokenizer(),examples()[0],input_cap=caps[0],response_cap=caps[1],position_cap=caps[2])

    def test_train_only_and_family_disjoint(self):
        for split in ("test","validation","confirmation"):
            rows=examples(); rows[0]["split"]=split
            with self.assertRaises(c.Invalid): l.validate_examples(rows)
        with self.assertRaises(c.Invalid): l.validate_examples(examples(), ["family0"])

    def test_duplicate_and_extra_fields_rejected(self):
        rows=examples(); rows.append(deepcopy(rows[0]))
        with self.assertRaises(c.Invalid): l.validate_examples(rows)
        rows=examples(); rows[0]["gold_for_evaluation"]="hidden"
        with self.assertRaises(c.Invalid): l.validate_examples(rows)

    def test_all_refusal_training_rejected(self):
        with self.assertRaises(c.Invalid):
            l.validate_examples([r for r in examples() if r["kind"]=="empty_refusal"])

    def test_empty_negative_really_empty(self):
        rows=examples(); rows[1]["request"]["evidence"]=deepcopy(rows[0]["request"]["evidence"])
        with self.assertRaises(c.Invalid): l.validate_examples(rows)

    def test_shuffle_preserves_refusal_control_and_target_multiset(self):
        rows=examples(); before=deepcopy(rows); swapped=l.permuted_positive_targets(rows)
        self.assertEqual(rows,before)
        self.assertEqual(sorted(r["response"] for r in rows),sorted(r["response"] for r in swapped))
        self.assertNotEqual(rows[0]["response"],swapped[0]["response"])
        for a,b in zip(rows,swapped):
            self.assertEqual(a["request"],b["request"])
            if a["kind"]=="empty_refusal": self.assertEqual(a,b)

    def test_degenerate_shuffle_rejected(self):
        rows=examples(); rows[2]["response"]=rows[0]["response"]
        with self.assertRaises(c.Invalid): l.permuted_positive_targets(rows)


class NativeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def backend(self):
        with torch.random.fork_rng():
            torch.manual_seed(19)
            config=LlamaConfig(vocab_size=128,hidden_size=16,intermediate_size=32,num_hidden_layers=1,
                               num_attention_heads=2,num_key_value_heads=2,max_position_embeddings=128,
                               bos_token_id=1,eos_token_id=2,pad_token_id=2,attention_dropout=0.0)
            model=LlamaForCausalLM(config).eval().requires_grad_(False)
        return SimpleNamespace(loaded=model,tokenizer=Tokenizer(),close=lambda:None)

    def test_real_adapter_optimizer_mask_and_saved_reload(self):
        backend=self.backend(); original=l.state_digest(backend.loaded.state_dict())
        with tempfile.TemporaryDirectory() as folder:
            receipt=l.fit_response_adapter(backend,examples(),Path(folder)/"candidate",epochs=1)
            self.assertTrue(receipt["base_unchanged"])
            self.assertEqual(receipt["base_tensor_sha256"],original)
            self.assertEqual(receipt["optimizer_steps"],4)
            self.assertEqual(receipt["training_forwards"],4)
            self.assertNotEqual(receipt["initial_adapter_sha256"],receipt["adapter_tensor_sha256"])
            self.assertTrue(receipt["checkpoint_reload_equal"])
            self.assertTrue(all(not p.requires_grad for p in backend.loaded.parameters()))
            self.assertTrue((Path(folder)/"candidate/adapter/adapter_model.safetensors").is_file())
            self.assertFalse(receipt["production_accepted"])
            self.assertFalse(receipt["independent_semantic_sufficiency"])

    def test_rejected_family_before_model_wrapping_or_output(self):
        backend=self.backend()
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"candidate"
            with self.assertRaises(c.Invalid): l.fit_response_adapter(backend,examples(),out,forbidden_families=["family0"])
            self.assertFalse(out.exists())
            self.assertFalse(hasattr(backend.loaded,"peft_config"))

    def test_no_overwrite_and_no_trainable_base(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError): l.fit_response_adapter(self.backend(),examples(),Path(folder),epochs=1)
            backend=self.backend(); backend.loaded.requires_grad_(True)
            with self.assertRaises(c.Invalid): l.fit_response_adapter(backend,examples(),Path(folder)/"next",epochs=1)


class StudyTests(unittest.TestCase):
    def test_selection_does_not_read_target_labels(self):
        b=benchmark()
        class Forbidden:
            def __getitem__(self,key): raise AssertionError("target reached during selection")
        b.targets=Forbidden()
        result=t.choose_questions(b)
        self.assertEqual({q.identity for q in result["train"]},{"q0","q1"})
        self.assertEqual({q.identity for q in result["test"]},{"q2","q3"})

    def test_source_roots_cannot_cross_split(self):
        b=benchmark(); b.history=lambda q:[SimpleNamespace(root="same-root")]
        with self.assertRaises(c.Invalid): t.choose_questions(b)

    def test_support_removal_keeps_distractor_identity_position_text(self):
        b=benchmark(); q=b.questions[0]
        docs=[SimpleNamespace(identity="d0",content="known"),SimpleNamespace(identity="other",content="where fixture")]
        b.history=lambda query: docs
        cases, support, usable=t.cases_for(b,q)
        self.assertTrue(usable); self.assertEqual(len(support),1)
        self.assertEqual(cases["support_removed"]["evidence"],cases["oracle_plus_distractors"]["evidence"][1:])
        self.assertFalse(cases["no_evidence"]["evidence"])

    def test_missing_support_does_not_fabricate_sufficiency(self):
        b=benchmark(); q=b.questions[0]
        b.targets[q.identity].unresolved_evidence=("missing",)
        cases,_,usable=t.cases_for(b,q)
        self.assertFalse(usable)
        self.assertIsNone(cases["oracle_plus_distractors"])
        self.assertIsNone(cases["support_removed"])

    def test_failed_rows_and_refusal_collapse_remain_visible(self):
        b=benchmark()
        raw=[dict(trial_id="a",question_id="q2",family="f2",arm="aligned_lora",condition="no_evidence",
                  status="succeeded",answer=l.REFUSAL,evidence_ids=[]),
             dict(trial_id="b",question_id="q2",family="f2",arm="aligned_lora",condition="oracle_plus_distractors",
                  status="failed",answer="Alpha",evidence_ids=["E1"])]
        scores=t.score_rows(raw,b)
        self.assertTrue(scores[0]["exact_refusal"])
        self.assertFalse(scores[0]["benchmark_exact_body"])
        self.assertFalse(scores[1]["benchmark_exact_body"])
        summary=t.summarize(scores)["aligned_lora"]["oracle_plus_distractors"]
        self.assertEqual(summary["planned"],1); self.assertEqual(summary["succeeded"],0)
        self.assertIsNone(scores[1]["grounded_and_cited_semantics"])

    def test_no_bag_of_words_exact_match(self):
        b=benchmark(); b.targets["q2"].answer="A before B"
        row=dict(trial_id="a",question_id="q2",family="f2",arm="frozen_reader",condition="lexical_retrieval",
                 status="succeeded",answer="B before A [E1]",evidence_ids=["E1"])
        score=t.score_rows([row],b)[0]
        self.assertFalse(score["benchmark_exact_body"])
        self.assertTrue(score["citation_syntax_valid"])
        self.assertIsNone(score["grounded_and_cited_semantics"])

    def test_clean_staging_uses_existing_verified_copy_not_loader_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); original=root/"original-models"
            with patch("five_native_historical_smoke.extract",return_value=original), \
                 patch("five_archived_torch_reference.stage_clean",return_value={"fixture":True}) as copy, \
                 patch("five_native_historical_smoke.snapshot",return_value={}) as verify:
                src,clean,receipt=prepare_materials(root/"archive.zip",root/"work")
                self.assertEqual(src,original)
                self.assertEqual(copy.call_count,2); self.assertEqual(verify.call_count,2)
                self.assertEqual(clean,root/"work/clean")
                self.assertTrue(receipt["official_loader_requirements_unchanged"])


class ReadoutContentPreservationTests(unittest.TestCase):
    def row(self, answer, ids=("E1",)):
        return dict(trial_id="r", question_id="q2", family="f2", arm="aligned_lora",
                    condition="oracle_plus_distractors", status="succeeded",
                    answer=answer, evidence_ids=list(ids))

    def score(self, answer, ids=("E1",), expected="Alpha"):
        b = benchmark(); b.targets["q2"].answer = expected
        return t.score_rows([self.row(answer, ids)], b)[0]

    def test_bracketed_negation_is_not_erased(self):
        self.assertFalse(self.score("Alpha [not]")["benchmark_exact_body"])

    def test_bracketed_numbers_are_not_erased(self):
        self.assertFalse(self.score("Alpha [2026]")["benchmark_exact_body"])

    def test_unknown_source_label_is_not_removed(self):
        score = self.score("Alpha [E2]")
        self.assertFalse(score["benchmark_exact_body"])
        self.assertFalse(score["citation_syntax_valid"])

    def test_delivered_source_label_can_be_removed(self):
        score = self.score("Alpha [E1]")
        self.assertTrue(score["benchmark_exact_body"])
        self.assertTrue(score["citation_syntax_valid"])
        self.assertIsNone(score["grounded_and_cited_semantics"])

    def test_empty_evidence_does_not_supply_any_strip_allowance(self):
        self.assertFalse(self.score("Alpha [E1]", ids=())["benchmark_exact_body"])

    def test_mixed_valid_and_invalid_citations_preserve_invalid_content(self):
        score = self.score("Alpha [E1] [not]")
        self.assertFalse(score["benchmark_exact_body"])
        self.assertFalse(score["citation_syntax_valid"])

    def test_raw_answer_and_evidence_ids_are_not_mutated(self):
        rows = [self.row("Alpha [E1] [not]")]; before = deepcopy(rows)
        t.score_rows(rows, benchmark())
        self.assertEqual(rows, before)

    def test_real_bracketed_target_content_remains_comparable(self):
        score = self.score("Alpha [not] [E1]", expected="Alpha [not]")
        self.assertTrue(score["benchmark_exact_body"])
        self.assertFalse(score["citation_syntax_valid"])

    def test_changed_readout_profile_is_explicit_in_plan_and_rows(self):
        self.assertEqual(t.PLAN["readout_profile"], "registered-citation-only-exact-body-v2")
        self.assertEqual(self.score("Alpha")["readout_profile"], t.PLAN["readout_profile"])


if __name__ == "__main__":
    unittest.main()
