"""Synthetic mechanics only; no benchmark/model/signer evidence is minted."""

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_ai_qualification as ai

P = Path(__file__).with_name("memory_ai_protocol_v1.json")


def sample():
    protocol = json.loads(P.read_text())
    groups = {"train": ["t1"], "calibration": ["c1"],
              "future_a": ["a1", "a2"], "future_b": ["b1", "b2"]}
    all_groups = sum(groups.values(), [])
    inventory = {name: [name + ":turn1", name + ":turn2"] for name in all_groups}
    gold, queries = {}, []
    for window in ai.WINDOWS:
        for group in groups[window]:
            for suffix in ("answerable", "adversarial"):
                qid = group + ":" + suffix
                queries.append({"query_id": qid, "family": group, "window": window,
                                "source_cut_sha256": ai.sha((group + ":source").encode()),
                                "forget_frontier_sha256": ai.sha((group + ":forget").encode())})
                gold[qid] = {"answerable": suffix == "answerable",
                             "support_ids": [inventory[group][0]] if suffix == "answerable" else []}
    plan = {"schema_version": 1, "protocol_sha256": ai.sha(ai.canonical(protocol)),
            "gold_sha256": ai.sha(ai.canonical(gold)),
            "source_dataset_sha256": ai.sha(b"synthetic-corpus"),
            "reader_sha256": ai.sha(b"synthetic-reader"),
            "tokenizer_sha256": ai.sha(b"synthetic-tokenizer"),
            "prompt_sha256": ai.sha(b"synthetic-prompt"),
            "decoding_sha256": ai.sha(b"synthetic-decoder"),
            "frozen_utc": "2026-10-23T00:00:00Z",
            "window_open_utc": {"future_a": "2026-11-01T00:00:00Z",
                                "future_b": "2026-12-01T00:00:00Z"},
            "families": groups, "source_inventory": inventory, "queries": queries}
    profiles = {}
    trained = {"E", "F", "G", "H", "I", "F_SWAPPED", "G_FIXED", "H_PERMUTED", "I_STATIC"}
    for arm in ai.ARMS + ai.CONTROLS:
        has_trained = arm in trained
        profiles[arm] = {
            "artifact_sha256": ai.sha((arm + ":artifact").encode()),
            "encoder_sha256": ai.sha(b"synthetic-shared-encoder") if arm in trained | {"E_FROZEN"} else None,
            "parameter_bytes": 6144 if has_trained else 0,
            "optimizer_steps": 100 if has_trained else 0,
            "training_examples": 64 if has_trained else 0,
            "router_steps": 20 if arm in {"G", "H", "I", "G_FIXED", "H_PERMUTED", "I_STATIC"} else 0,
            "router_parameter_bytes": 256 if arm in {"G", "H", "I", "G_FIXED", "H_PERMUTED", "I_STATIC"} else 0,
            "router_training_examples": 64 if arm in {"G", "H", "I", "G_FIXED", "H_PERMUTED", "I_STATIC"} else 0,
            "graph_edges": 3 if arm in {"C", "H", "H_PERMUTED", "I", "I_STATIC"} else 0,
            "training_source_closure_sha256": ai.sha(b"synthetic-ancestors"),
            "training_families": ["t1"] if has_trained else [],
        }
    rows, judged = [], []
    for q in queries:
        qid = q["query_id"]
        answerable = gold[qid]["answerable"]
        for arm in ai.ARMS + ai.CONTROLS:
            status = "answered" if answerable else "abstained"
            answer = ai.sha((qid + ":" + arm).encode()) if answerable else ai.sha(b"")
            selected = gold[qid]["support_ids"] if answerable else []
            rows.append({"query_id": qid, "arm": arm, "status": status,
                         "answer_sha256": answer,
                         "context_sha256": ai.sha((qid + ":context").encode()),
                         "source_cut_sha256": q["source_cut_sha256"],
                         "forget_frontier_sha256": q["forget_frontier_sha256"],
                         "reader_sha256": plan["reader_sha256"],
                         "tokenizer_sha256": plan["tokenizer_sha256"],
                         "prompt_sha256": plan["prompt_sha256"],
                         "decoding_sha256": plan["decoding_sha256"],
                         "selected_source_ids": selected,
                         "costs": {"context_bytes": 200, "output_tokens": 8 if answerable else 0,
                                   "wall_ms": 10, "peak_rss_bytes": 10000, "cpu_ms": 9,
                                   "gpu_ms": 0, "storage_bytes": 100,
                                   "encoder_forwards": 1 if arm in trained else 0,
                                   "head_forwards": 1 if arm in trained else 0}})
            judged.append({"query_id": qid, "arm": arm, "answer_sha256": answer,
                           "task_success": True,
                           "citation_supported": answerable,
                           "support_complete": answerable})
    predictions = {"schema_version": 1, "plan_sha256": ai.sha(ai.canonical(plan)),
                   "profiles": profiles, "rows": rows}
    judgments = {"schema_version": 1,
                 "predictions_sha256": ai.sha(ai.canonical(predictions)),
                 "assessor_id": "synthetic-independent-fixture",
                 "assessor_artifact_sha256": ai.sha(b"synthetic-assessor"),
                 "rows": judged}
    return protocol, plan, gold, predictions, judgments


def reseal(t):
    protocol, plan, gold, pred, judgment = t
    plan["protocol_sha256"] = ai.sha(ai.canonical(protocol))
    plan["gold_sha256"] = ai.sha(ai.canonical(gold))
    pred["plan_sha256"] = ai.sha(ai.canonical(plan))
    judgment["predictions_sha256"] = ai.sha(ai.canonical(pred))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.t = sample()

    def check_reject(self, words):
        with self.assertRaisesRegex(ai.QualificationError, words):
            ai.qualify(*self.t)

    def test_valid_mechanism_fixture_stays_hold_no_go(self):
        report = ai.qualify(*self.t)
        self.assertEqual(report["status"], "SHADOW_ONLY / DENY_ALL / HOLD_NO_GO")
        self.assertEqual(report["arms"], list(ai.ARMS))
        self.assertEqual(len(report["comparisons"]), 22)
        self.assertEqual(report["windows"]["future_a"]["independent_families"], 2)
        self.assertFalse(report["descriptive_gates_passed"])
        self.assertFalse(report["scientific_superiority_qualified"])
        self.assertFalse(report["production_activation_allowed"])

    def test_reject_missing_arm_result(self):
        self.t[3]["rows"].pop()
        self.check_reject("incomplete nine-arm")

    def test_reject_extra_duplicate_result(self):
        self.t[3]["rows"].append(copy.deepcopy(self.t[3]["rows"][0]))
        self.check_reject("duplicate")

    def test_reject_missing_judgment(self):
        self.t[4]["rows"].pop()
        reseal(self.t)
        self.check_reject("missing independently judged")

    def test_reject_gold_commitment_change(self):
        self.t[2]["a1:answerable"]["support_ids"] = ["a1:turn2"]
        self.check_reject("gold commitment")

    def test_reject_answerability_forgery(self):
        self.t[2]["a1:answerable"]["answerable"] = False
        reseal(self.t)
        self.check_reject("answerable question lacks")

    def test_reject_gold_source_not_in_corpus(self):
        self.t[2]["a1:answerable"]["support_ids"] = ["c1:turn1"]
        reseal(self.t)
        self.check_reject("original support source")

    def test_reject_overlapping_future_window(self):
        self.t[1]["families"]["future_b"].append("a1")
        reseal(self.t)
        self.check_reject("source family leaks")

    def test_reject_future_preceding_freeze(self):
        self.t[1]["window_open_utc"]["future_a"] = "2026-10-22T00:00:00Z"
        reseal(self.t)
        self.check_reject("future window not later")

    def test_reject_wrong_source_cut(self):
        self.t[3]["rows"][0]["source_cut_sha256"] = ai.sha(b"wrong")
        reseal(self.t)
        self.check_reject("stale source/forget")

    def test_reject_reader_drift(self):
        self.t[3]["rows"][0]["reader_sha256"] = ai.sha(b"other")
        reseal(self.t)
        self.check_reject("Reader or decoding drift")

    def test_reject_foreign_source(self):
        self.t[3]["rows"][0]["selected_source_ids"] = ["t1:turn1"]
        reseal(self.t)
        self.check_reject("foreign source")

    def test_reject_duplicate_selected_source(self):
        s = self.t[3]["rows"][0]["selected_source_ids"][0]
        self.t[3]["rows"][0]["selected_source_ids"] = [s, s]
        reseal(self.t)
        self.check_reject("duplicate or foreign source")

    def test_reject_forged_success_of_failed(self):
        row = self.t[3]["rows"][0]
        row["status"] = "failed"
        row["answer_sha256"] = ai.sha(b"")
        self.t[4]["rows"][0]["answer_sha256"] = ai.sha(b"")
        reseal(self.t)
        self.check_reject("failed execution scored successful")

    def test_reject_forged_judgment_answer(self):
        self.t[4]["rows"][0]["answer_sha256"] = ai.sha(b"made-up")
        self.check_reject("judgment answer not source-bound")

    def test_reject_unsupported_gold_coverage_claim(self):
        q = self.t[3]["rows"][0]
        q["selected_source_ids"] = ["a1:turn2"]
        reseal(self.t)
        self.check_reject("evidence completeness")

    def test_reject_illegal_adversarial_success(self):
        row = self.t[3]["rows"][14]  # second question, A
        self.assertEqual(row["status"], "abstained")
        self.t[4]["rows"][14]["task_success"] = False
        self.check_reject("adversarial answerability")

    def test_reject_false_citation_after_abstain(self):
        self.t[4]["rows"][14]["citation_supported"] = True
        self.check_reject("unavailable citation fabricated")

    def test_reject_nan_cost(self):
        self.t[3]["rows"][0]["costs"]["wall_ms"] = float("nan")
        # Seal will reject NaN; if bypassed, row still rejects it.
        with self.assertRaises(ValueError):
            reseal(self.t)

    def test_reject_boolean_resource_count(self):
        self.t[3]["rows"][0]["costs"]["head_forwards"] = True
        reseal(self.t)
        self.check_reject("invalid resources")

    def test_reject_token_budget_violation(self):
        self.t[3]["rows"][0]["costs"]["output_tokens"] = 65
        reseal(self.t)
        self.check_reject("runtime budget")

    def test_reject_dense_head_execution(self):
        row = next(r for r in self.t[3]["rows"] if r["arm"] == "G")
        row["costs"]["head_forwards"] = 3
        reseal(self.t)
        self.check_reject("duplicate shared-Encoder")

    def test_reject_training_source_leakage(self):
        self.t[3]["profiles"]["E"]["training_families"] = ["a1"]
        reseal(self.t)
        self.check_reject("training source leakage")

    def test_reject_equal_budget_cheating(self):
        self.t[3]["profiles"]["I_STATIC"]["parameter_bytes"] = 1
        reseal(self.t)
        self.check_reject("unmatched Head training budget")

    def test_reject_untrained_head_claim(self):
        self.t[3]["profiles"]["E"]["optimizer_steps"] = 0
        reseal(self.t)
        self.check_reject("no real trained model declared")

    def test_reject_mismatched_stem(self):
        self.t[3]["profiles"]["H"]["encoder_sha256"] = ai.sha(b"different")
        reseal(self.t)
        self.check_reject("shared Encoder")

    def test_reject_missing_control(self):
        self.t[0]["controls"].pop("I_STATIC")
        reseal(self.t)
        self.check_reject("complete ordered")

    def test_reject_unsafe_promotion(self):
        self.t[0]["production_activation_allowed"] = True
        reseal(self.t)
        self.check_reject("unsafe activation")

    def test_reject_subtle_posthoc_metric_edit(self):
        self.t[0]["comparisons"][-1]["min_gain"] = 0.0
        reseal(self.t)
        self.check_reject("frozen protocol digest changed")

    def test_reject_router_budget_drift(self):
        self.t[3]["profiles"]["G_FIXED"]["router_steps"] = 1
        reseal(self.t)
        self.check_reject("unmatched router budget")

    def test_reject_graph_budget_drift(self):
        self.t[3]["profiles"]["H_PERMUTED"]["graph_edges"] = 1
        reseal(self.t)
        self.check_reject("unmatched graph budget")

    def test_reject_training_ancestor_drift(self):
        self.t[3]["profiles"]["I_STATIC"]["training_source_closure_sha256"] = ai.sha(b"other")
        reseal(self.t)
        self.check_reject("unmatched training ancestor")

    def test_reject_duplicate_json_key(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "json"
            path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ai.QualificationError, "duplicate JSON member"):
                ai.read_json(path)

    def test_reject_invalid_json_nan(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "json"
            path.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ai.QualificationError, "non-JSON numeric"):
                ai.read_json(path)

    def test_cli_creates_only_negative_receipt(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            files = []
            for name, value in zip(("protocol", "plan", "gold", "predictions", "judgments"), self.t):
                path = Path(tmp) / (name + ".json")
                path.write_bytes(ai.canonical(value))
                files.extend(["--" + name, str(path)])
            output = Path(tmp) / "report.json"
            from contextlib import redirect_stdout
            import io
            with redirect_stdout(io.StringIO()):
                result = ai.main(files + ["--output", str(output)])
            self.assertEqual(result, 2)
            report = json.loads(output.read_bytes())
            self.assertEqual(report["status"], "SHADOW_ONLY / DENY_ALL / HOLD_NO_GO")
            self.assertTrue(any("insufficient independent families" in blocker for blocker in report["blockers"]))
            with self.assertRaises(FileExistsError), redirect_stdout(io.StringIO()):
                ai.main(files + ["--output", str(output)])

    def test_family_bootstrap_is_deterministic(self):
        x = {"a": 1.0, "b": 1.0, "c": 1.0}
        y = {"a": 0.0, "b": 0.0, "c": 0.0}
        self.assertEqual(ai.lower_bound(x, y, alpha=0.05, replicates=1000, seed=1), 1.0)
        with self.assertRaisesRegex(ai.QualificationError, "family set mismatch"):
            ai.lower_bound(x, {"a": 0.0}, alpha=0.05, replicates=1000, seed=1)


if __name__ == "__main__":
    unittest.main()
