"""No SDK or model required; exercises safety and provenance of the reader harness."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from hepta_sngr_reader_eval import (
    ARM_NAMES,
    BackendUnavailable,
    FROZEN_CASE_SHA256,
    ReaderBenchError,
    checkpoint_fingerprint,
    construct_request,
    evidence_for,
    git_blob_sha1,
    injection_target,
    load_cases,
    load_local_laya,
    main,
    option_presentation,
    parse_answer,
    reject_sdk_checkpoint_mutation,
    run_reader,
    verify_checkout,
)

CASES = Path(__file__).with_name("hepta_sngr_reader_cases.json")


class SpyTypedAgent:
    """A pure TEST STUB, not a trained model, not valid effectiveness evidence."""

    def __init__(self, task_to_quote_and_gold=()):
        self.calls = []
        self.reference = list(task_to_quote_and_gold)

    def predict(self, state, questions):
        self.calls.append((state, questions))
        evidence = state["source_excerpt_untrusted"]
        matched = [gold for quote, gold in self.reference if quote in evidence]
        # This is an artificial fixed-key oracle for testing treatment plumbing.
        # It must never be used as an experimental results backend.
        result = matched[0] if matched else "UNKNOWN"
        probs = dict.fromkeys(("A", "B", "C", "D", "UNKNOWN"), 0.0)
        probs[result] = 1.0
        return {"answers": {"answer": {"choice": result, "confidence": 1.0,
                                          "probabilities": probs}},
                "usage": {"input_tokens": len(evidence.split()), "output_tokens": 0}}


class CorpusValidityTests(unittest.TestCase):
    def setUp(self):
        self.corpus = load_cases(CASES)

    def test_frozen_repo_snapshot_and_balanced_golds(self):
        self.assertEqual(len(self.corpus["tasks"]), 16)
        self.assertEqual(self.corpus["base_commit"], "f8c9419df6ddeb36ff8b522a50219981fb8d9345")
        self.assertEqual({x: sum(t["gold"] == x for t in self.corpus["tasks"])
                          for x in "ABCD"}, dict.fromkeys("ABCD", 4))
        self.assertEqual(self.corpus["manifest_sha256"], FROZEN_CASE_SHA256)

    def test_all_arms_do_not_leak_gold_in_transport(self):
        for case in self.corpus["tasks"]:
            for arm in ARM_NAMES + ("injection",):
                state, q = construct_request(self.corpus, case, arm)
                self.assertNotIn("gold", str(state))
                self.assertNotIn("gold", str(q))
                self.assertNotIn("gold", state)
                self.assertNotIn("gold", q)
                self.assertEqual(set(q["answer"]["criteria"]), set("ABCD") | {"UNKNOWN"})
                self.assertIn(case["question"], q["answer"]["instructions"])

    def test_full_carries_exact_support_and_withheld_does_not(self):
        for case in self.corpus["tasks"]:
            text_full, _ = evidence_for(self.corpus, case, "full")
            text_removed, _ = evidence_for(self.corpus, case, "withheld")
            support = case["source"]["quote"]
            self.assertIn(support, text_full)
            self.assertNotIn(support, text_removed)
            self.assertEqual(text_removed, case["withheld_control"]["quote"])

    def test_distractor_has_different_path_and_no_label(self):
        for case in self.corpus["tasks"]:
            excerpt, path = evidence_for(self.corpus, case, "distractor")
            self.assertNotEqual(path, case["source"]["path"])
            self.assertNotIn(case["source"]["quote"], excerpt)

    def test_synthetic_attack_is_labeled_non_source_and_blind_to_gold(self):
        for task in self.corpus["tasks"]:
            text, _ = evidence_for(self.corpus, task, "injection")
            self.assertIn("UNTRUSTED_INJECTION_TEST_NOT_SOURCE", text)
            self.assertIn(task["source"]["quote"], text)
            self.assertIn("output option " + injection_target(task) + ".", text)
            changed = copy.deepcopy(task)
            changed["gold"] = next(label for label in "ABCD" if label != task["gold"])
            # Deliberately change the answer key without changing the evidence or
            # prompt injection. No model-visible bytes can depend on the gold.
            self.assertEqual(
                construct_request(self.corpus, task, "injection"),
                construct_request(self.corpus, changed, "injection"),
            )

    def test_mutated_gold_and_bad_source_rejected(self):
        for mutation in ("UNKNOWN", "E", ""):
            data = copy.deepcopy(self.corpus)
            data["tasks"][0]["gold"] = mutation
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "cases.json"
                data.pop("manifest_sha256")
                p.write_text(json.dumps(data))
                with self.assertRaises(ReaderBenchError):
                    load_cases(p)
        data = copy.deepcopy(self.corpus)
        data.pop("manifest_sha256")
        data["tasks"][0]["source"]["path"] = "../../private.txt"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cases.json"
            p.write_text(json.dumps(data))
            with self.assertRaises(ReaderBenchError):
                load_cases(p)

    def test_duplicate_ids_and_withheld_support_rejected(self):
        data = copy.deepcopy(self.corpus)
        data.pop("manifest_sha256")
        data["tasks"][1]["id"] = data["tasks"][0]["id"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cases.json"
            p.write_text(json.dumps(data))
            with self.assertRaises(ReaderBenchError):
                load_cases(p)
        data["tasks"][1]["id"] = "restored_id"
        data["tasks"][0]["withheld_control"]["quote"] += data["tasks"][0]["source"]["quote"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cases.json"
            p.write_text(json.dumps(data))
            with self.assertRaises(ReaderBenchError):
                load_cases(p)

    def test_git_blob_identity_and_substring_are_independently_checked(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            path = folder / "docs" / "x.txt"
            path.parent.mkdir()
            contents = b"We observed independent success.\nOther context.\n"
            path.write_bytes(contents)
            self.assertEqual(git_blob_sha1(contents), hashlib.sha1(f"blob {len(contents)}\0".encode() + contents).hexdigest())
            source = {"path": "docs/x.txt", "blob_sha": git_blob_sha1(contents), "line": 1,
                      "quote": "independent success"}
            context = {**source, "line": 2, "quote": "Other context"}
            corpus = {"tasks": [{"source": source, "withheld_control": context}]}
            self.assertEqual(verify_checkout(corpus, folder), {"docs/x.txt": source["blob_sha"]})
            # Entire blob and quotation can both match while the declared line
            # number is false; this must not be accepted as cited evidence.
            mislocated = copy.deepcopy(corpus)
            mislocated["tasks"][0]["source"]["line"] = 2
            with self.assertRaisesRegex(ReaderBenchError, "line mismatch"):
                verify_checkout(mislocated, folder)
            path.write_text("We observed different success.\nOther context.\n")
            with self.assertRaisesRegex(ReaderBenchError, "mismatch"):
                verify_checkout(corpus, folder)

    def test_checkout_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            outside = root / "other.txt"
            outside.write_text("test test test")
            link = root / "s.txt"
            link.symlink_to(outside)
            src = {"path": "s.txt", "blob_sha": git_blob_sha1(outside.read_bytes()),
                   "line": 1, "quote": "test test test"}
            with self.assertRaisesRegex(ReaderBenchError, "symlinked"):
                verify_checkout({"tasks": [{"source": src, "withheld_control": src}]}, root)


class ChoiceParsingTests(unittest.TestCase):
    @staticmethod
    def response(choice="A", confidence=0.8, probabilities=None, tokens=42):
        if probabilities is None:
            probabilities = {"A": 0.8, "B": 0.05, "C": 0.05, "D": 0.05, "UNKNOWN": 0.05}
        return {"answers": {"answer": {"choice": choice, "confidence": confidence,
                                           "probabilities": probabilities}},
                "usage": {"input_tokens": tokens, "output_tokens": 0}}

    def test_actual_laya_sdk_result_shape(self):
        self.assertEqual(parse_answer(self.response()), ("A", 0.8, 42))

    def test_unsupported_shapes_fail_closed(self):
        invalid = [
            {}, {"answers": {}}, self.response(choice="EXFILTRATE"),
            self.response(confidence=float("nan")), self.response(confidence=2.0),
            self.response(probabilities={"A": 0.7, "B": 0.2, "C": 0.1}),
            {"answers": {"answer": {"choice": "A", "confidence": 0.8}}},
            self.response(choice="A", probabilities={"A": 0.1, "B": 0.75, "C": 0.05, "D": 0.05, "UNKNOWN": 0.05}),
            self.response(tokens=-1), self.response(confidence=True),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ReaderBenchError):
                parse_answer(value)


class ProtocolAndCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_cases(CASES)

    def test_mock_backend_validates_all_four_arms_without_claiming_efficacy(self):
        refs = [(t["source"]["quote"], t["gold"]) for t in self.corpus["tasks"]]
        agent = SpyTypedAgent(refs)
        result = run_reader(self.corpus, agent, "a" * 64, seed=71, max_calls=64)
        self.assertEqual(result["model_calls"], 64)
        self.assertEqual(result["calls_per_case"], 4)
        self.assertEqual(result["summaries"]["full"]["top1_gold_fraction"], 1.0)
        self.assertEqual(result["summaries"]["none"]["abstention_fraction"], 1.0)
        self.assertEqual(result["summaries"]["withheld"]["abstention_fraction"], 1.0)
        for arm in ("none", "withheld", "full"):
            self.assertEqual(result["summaries"][arm]["evidence_condition_accuracy"], 1.0)
            self.assertEqual(result["summaries"][arm]["multiclass_brier_evidence_target"], 0.0)
        self.assertEqual(result["production_selection_authority"], False)
        for state, q in agent.calls:
            self.assertNotIn("gold", state)
            self.assertNotIn("gold", q)

    def test_attack_arm_and_equal_budget(self):
        refs = [(t["source"]["quote"], t["gold"]) for t in self.corpus["tasks"]]
        agent = SpyTypedAgent(refs)
        report = run_reader(self.corpus, agent, "b" * 64, include_injection=True, max_calls=80)
        self.assertEqual(report["model_calls"], 80)
        self.assertEqual(report["summaries"]["injection"]["top1_gold_fraction"], 1.0)
        self.assertEqual(sum(1 for r in report["rows"] if r["arm"] == "injection"), 16)
        attacks = [r for r in report["rows"] if r["arm"] == "injection"]
        self.assertEqual(report["summaries"]["injection"]["opposed_gold_cases"],
                         sum(injection_target(task) != task["gold"] for task in self.corpus["tasks"]))
        self.assertEqual(report["summaries"]["injection"]["attack_success_fraction_when_opposed"], 0.0)
        self.assertEqual(report["injection_target_policy"], "sha256(task_id)_mod_4_gold_blind")
        self.assertTrue(all(row["injection_target"] == injection_target(next(t for t in self.corpus["tasks"] if t["id"] == row["task_id"])) for row in attacks))

    def test_fixed_seed_assignment_and_document_provenance(self):
        a, b = SpyTypedAgent(), SpyTypedAgent()
        run_reader(self.corpus, a, "c" * 64, seed=45, max_calls=64)
        run_reader(self.corpus, b, "c" * 64, seed=45, max_calls=64)
        self.assertEqual(a.calls, b.calls)
        self.assertTrue(all(r["source_blob_sha"] in {t["source"]["blob_sha"] for t in self.corpus["tasks"]}
                            for r in run_reader(self.corpus, SpyTypedAgent(), "c" * 64, max_calls=64)["rows"]))

    def test_unsupported_guess_never_counts_as_evidence_condition_success(self):
        class ConstantGuessAgent:
            def predict(self, state, questions):
                probs = dict.fromkeys(("A", "B", "C", "D", "UNKNOWN"), 0.0)
                probs["A"] = 1.0
                return {"answers": {"answer": {"choice": "A", "confidence": 1.0,
                                                  "probabilities": probs}},
                        "usage": {"input_tokens": 1, "output_tokens": 0}}

        result = run_reader(self.corpus, ConstantGuessAgent(), "d" * 64, seed=17)
        self.assertEqual(result["schema"], "hepta.sngr.reader-diagnostic.shadow.v2")
        self.assertEqual(result["summaries"]["none"]["top1_gold_fraction"], 0.25)
        self.assertEqual(result["summaries"]["none"]["evidence_condition_accuracy"], 0.0)
        self.assertEqual(result["summaries"]["none"]["unsupported_assertion_fraction"], 1.0)
        self.assertEqual(result["summaries"]["none"]["multiclass_brier_evidence_target"], 2.0)

    def test_probability_vector_must_support_reported_choice(self):
        bad = {"answers": {"answer": {"choice": "A", "confidence": 0.8,
                                      "probabilities": {"A": 0.10, "B": 0.70, "C": 0.10,
                                                        "D": 0.05, "UNKNOWN": 0.05}}},
               "usage": {"input_tokens": 5}}
        with self.assertRaisesRegex(ReaderBenchError, "inconsistent"):
            parse_answer(bad)

    def test_real_model_needs_source_checkout_even_with_checkpoint_path(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            fake_ckpt = Path(d) / "checkpoint"
            fake_ckpt.mkdir()
            with self.assertRaisesRegex(ReaderBenchError, "source checkout required"):
                main(["--checkpoint-dir", str(fake_ckpt), "--output", str(out)])
            self.assertFalse(out.exists())

    def test_attack_targets_cover_real_opposed_cases_without_label_dependency(self):
        targets = [(t["gold"], injection_target(t)) for t in self.corpus["tasks"]]
        self.assertEqual(len(targets), 16)
        self.assertGreater(sum(g != a for g, a in targets), 0)
        for task in self.corpus["tasks"]:
            modified = copy.deepcopy(task)
            modified["gold"] = next(label for label in "ABCD" if label != task["gold"])
            self.assertEqual(evidence_for(self.corpus, task, "injection"),
                             evidence_for(self.corpus, modified, "injection"))

    def test_model_digest_and_budget_guard(self):
        for model_digest in ("", "bad", "a" * 63):
            with self.subTest(model_digest=model_digest), self.assertRaises(ReaderBenchError):
                run_reader(self.corpus, SpyTypedAgent(), model_digest)
        with self.assertRaisesRegex(ReaderBenchError, "budget"):
            run_reader(self.corpus, SpyTypedAgent(), "f" * 64, max_calls=63)

    def test_counterbalance_is_gold_blind_and_each_answer_occupies_each_slot(self):
        for task in self.corpus["tasks"]:
            modified = copy.deepcopy(task)
            modified["gold"] = next(k for k in "ABCD" if k != task["gold"])
            positions = set()
            for variant in range(4):
                choices, shift = option_presentation(task, 7, variant, presentations=4)
                other, other_shift = option_presentation(modified, 7, variant, presentations=4)
                self.assertEqual((choices, shift), (other, other_shift))
                self.assertEqual(set(choices.values()), set(task["choices"].values()))
                gold_position = "ABCD"[("ABCD".index(task["gold"]) + shift) % 4]
                self.assertEqual(choices[gold_position], task["choices"][task["gold"]])
                positions.add(gold_position)
                for arm in ARM_NAMES + ("injection",):
                    state, questions = construct_request(self.corpus, task, arm,
                                                         choices_override=choices)
                    self.assertEqual(questions["answer"]["criteria"][gold_position],
                                     task["choices"][task["gold"]])
                    self.assertNotIn("gold", state)
                    self.assertNotIn("gold", questions)
            self.assertEqual(positions, set("ABCD"))

    def test_counterbalanced_four_arm_budget_and_paired_task_cluster_diagnostics(self):
        class AlwaysAAuditStub:
            def predict(self, state, questions):
                # Deliberately biased TEST STUB, not a real reader result.
                probs = {label: float(label == "A") for label in (*"ABCD", "UNKNOWN")}
                return {"answers": {"answer": {"choice": "A", "confidence": 1.0,
                                                   "probabilities": probs}},
                        "usage": {"input_tokens": 32, "output_tokens": 0}}

        audit = run_reader(self.corpus, AlwaysAAuditStub(), "e" * 64,
                           seed=19, presentations=4, max_calls=256, max_input_tokens=128)
        self.assertEqual(audit["model_calls"], 256)
        self.assertEqual(audit["calls_per_case"], 16)
        self.assertEqual(audit["answer_order_presentations"], 4)
        self.assertEqual(audit["summaries"]["full"]["top1_gold_fraction"], 0.25)
        self.assertEqual(audit["summaries"]["full"]["mean_reported_input_tokens"], 32)
        self.assertEqual(audit["position_diagnostics"]["full_gold_accuracy_by_position"],
                         {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0})
        self.assertEqual(audit["position_diagnostics"]["dependence_warning"],
                         "repeated_presentations_same_task_not_independent_episodes")
        self.assertEqual(set(audit["position_diagnostics"]["per_task_full_gold_accuracy"].values()),
                         {0.25})
        self.assertEqual(set(audit["paired_gold_fraction_differences"].values()), {0.0})
        for t in self.corpus["tasks"]:
            for variant in range(4):
                rows = [r for r in audit["rows"]
                        if r["task_id"] == t["id"] and r["presentation"] == variant]
                self.assertEqual(len(rows), 4)
                self.assertEqual(len({r["gold"] for r in rows}), 1)
                self.assertEqual(len({r["option_shift"] for r in rows}), 1)

    def test_maximum_five_arm_latin_square_fits_exact_320_call_ceiling(self):
        audit = run_reader(self.corpus, SpyTypedAgent(), "f" * 64, seed=17,
                           include_injection=True, presentations=4, max_calls=320)
        self.assertEqual(audit["model_calls"], 320)
        self.assertEqual(audit["summaries"]["injection"]["opposed_gold_cases"], 48)
        with self.assertRaisesRegex(ReaderBenchError, "budget"):
            run_reader(self.corpus, SpyTypedAgent(), "f" * 64, seed=17,
                       include_injection=True, presentations=4, max_calls=319)
        for presentations in (0, 2, 3, 5):
            with self.assertRaisesRegex(ReaderBenchError, "single order"):
                run_reader(self.corpus, SpyTypedAgent(), "f" * 64,
                           presentations=presentations)

    def test_same_seed_reproducible_different_seeds_change_presentation_order(self):
        agent_a = SpyTypedAgent()
        agent_b = SpyTypedAgent()
        run_reader(self.corpus, agent_a, "f" * 64, seed=5,
                   presentations=4, max_calls=256)
        run_reader(self.corpus, agent_b, "f" * 64, seed=5,
                   presentations=4, max_calls=256)
        self.assertEqual(agent_a.calls, agent_b.calls)
        agent_c = SpyTypedAgent()
        run_reader(self.corpus, agent_c, "f" * 64, seed=6,
                   presentations=4, max_calls=256)
        self.assertNotEqual(agent_a.calls, agent_c.calls)

    def test_missing_or_saturated_model_token_count_rejects_ambiguous_truncation(self):
        class TokenAuditStub:
            def __init__(self, tokens):
                self.tokens = tokens

            def predict(self, state, questions):
                probabilities = {label: float(label == "UNKNOWN")
                                 for label in (*"ABCD", "UNKNOWN")}
                return {"answers": {"answer": {"choice": "UNKNOWN", "confidence": 1.0,
                                                   "probabilities": probabilities}},
                        "usage": {"input_tokens": self.tokens}}

        for reported in (None, 128, 129):
            with self.subTest(reported=reported), self.assertRaisesRegex(
                    ReaderBenchError, "possible evidence truncation"):
                run_reader(self.corpus, TokenAuditStub(reported), "f" * 64,
                           max_input_tokens=128)
        for invalid_limit in (0, 2.5, True, 8193):
            with self.assertRaisesRegex(ReaderBenchError, "token limit"):
                run_reader(self.corpus, TokenAuditStub(32), "f" * 64,
                           max_input_tokens=invalid_limit)

    def test_no_weights_does_not_claim_success_or_create_output(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.json"
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                status = main(["--manifest", str(CASES), "--output", str(out)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(console.getvalue())["status"], "unavailable")
            self.assertFalse(out.exists())

    def test_missing_local_sdk_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(BackendUnavailable):
                load_local_laya(Path(d) / "missing")

    def test_laya_preflight_rejects_mutating_tokenizer_without_loading_sdk(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cfg = folder / "tokenizer" / "tokenizer_config.json"
            cfg.parent.mkdir()
            cfg.write_text('{"tokenizer_class": "TokenizersBackend", "extra_special_tokens": []}')
            with self.assertRaisesRegex(BackendUnavailable, "rewriting"):
                reject_sdk_checkpoint_mutation(folder)
            cfg.write_text('{"tokenizer_class": "PreTrainedTokenizerFast", "extra_special_tokens": {}}')
            reject_sdk_checkpoint_mutation(folder)

    def test_local_model_fingerprint_binds_bytes_and_fails_without_weights(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "rl_agent_config.json"
            weight = root / "model.safetensors"
            cfg.write_text('{"encoder":"stub","head_layers":1}')
            with self.assertRaises(BackendUnavailable):
                checkpoint_fingerprint(root)
            weight.write_bytes(b"fake test-only weights")
            one = checkpoint_fingerprint(root)
            weight.write_bytes(b"fake test-only updated weights")
            two = checkpoint_fingerprint(root)
            self.assertNotEqual(one, two)
            self.assertEqual(len(two), 64)


if __name__ == "__main__":
    unittest.main()
