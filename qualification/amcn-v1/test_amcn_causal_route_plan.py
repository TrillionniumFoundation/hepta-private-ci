"""Source-first, label-free *mock score* protocol tests (not pretrained results)."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

import amcn_causal_route_plan as route
from amcn_causal_task_audit import ARMS, Refused, bytes_sha, digest, validate_plan
from amcn_causal_reader_generation import PROMPT_SHA


def pin(x):
    return sha256(x.encode()).hexdigest()


def setup():
    types = ("episodic", "semantic")
    capacity = {
        kind: {
            "total_trainable_parameters": 2200,
            "optimizer_steps": 48, "minibatch_examples": 192,
            "artifact_sha256": pin("bank"), "training_receipt_sha256": pin("actual training"),
            "head_sha256_by_type": {t: pin(kind + t) for t in types},
            "trainable_head_count": 2, "active_heads_per_query": 1}
        for kind in ("shared", "typed")}
    bank = {
        "profile": "hepta.amcn.original-typed-six-head-bridge.shadow.v1",
        "types": list(types), "capacity": capacity,
        "frozen_head_sha256": pin("frozen-head"),
        "single_head_sha256": pin("trained shared control"),
        "original_bank_manifest_sha256": pin("original bank physical manifest"),
        "original_source_binding_sha256": pin("original source manifest"),
        "original_training_receipt_sha256": pin("physical TRAIN-only SGD"),
        "real_pretrained_encoder_origin_independently_authenticated": False,
        "future_reader_answers_generated": 0,
        "original_rag_and_graph_routes_verified": False,
        "original_publisher_truth_or_entailment_verified": False,
        "real_future_calendar_windows": 0,
        "production_accepted": False, "superiority_claim": False,
        "original_predictions_sha256": "",
        "physical_head_forward_replay": {"no_label_scores_opened": True,
                                         "production_accepted": False,
                                         "maximum_absolute_probability_error": 0.0,
                                         "physical_model_forward_calls": 0,
                                         "original_predictions_sha256": "",
                                         "verified_predictions": 0},
    }
    packet = {"profile": route.SOURCE_PROFILE,
              "source_snapshot_sha256": pin("original source owned externally"),
              "lineage_alias_edges": [], "cases": []}
    rag = {"profile": route.RAG_PROFILE,
           "source_snapshot_sha256": packet["source_snapshot_sha256"],
           "candidate_policy_sha256": pin("independently tuned hybrid policy"),
           "original_retrieval_receipt_sha256": pin("original retrieval receipt"),
           "routes": {}}
    graphs = {}
    predictions = []
    for i, (split, kind) in enumerate([
        ("select", "episodic"), ("retention", "semantic"),
        ("future_a", "episodic"), ("future_a", "semantic"),
        ("future_b", "episodic"), ("future_b", "semantic")]):
        qid = f"question-{i}"
        question = f"What was the command for delta error {i}?"
        sources = []
        for j in range(5):
            text = f"The delta error {i} command is command-{j}." if j < 3 else f"unrelated token {i}-{j}"
            row = {"source_id": f"event-{i}-{j}", "source_root": f"root-{i}",
                   "scope": "research", "generation": "g1", "revoked": False,
                   "revision": 1, "content_sha256": bytes_sha(text.encode()),
                   "text": text, "row_id": f"row-{i}-{j}"}
            row["input_sha256"] = route.feature_input_digest("research", question, row)
            sources.append(row)
        item = {"question_id": qid, "family": f"family-{i}",
                "source_root": f"root-{i}", "memory_type": kind,
                "split": split, "scope": "research", "generation": "g1",
                "question": question, "eligible_sources": sources}
        packet["cases"].append(item)
        lexical = route.source_first(question, sources)
        for pos, sid in enumerate(lexical):
            row = next(s for s in sources if s["source_id"] == sid)
            p = (len(lexical)-pos) / (len(lexical)+2)
            predictions.append({"row_id": row["row_id"], "family": item["family"],
                                "split": split, "input_sha256": row["input_sha256"],
                                "memory_type": kind,
                                "probabilities": {"frozen": p, "single_shared": 1-p,
                                                  "untyped_equal_budget": 1-p,
                                                  "typed_equal_budget": p,
                                                  "typed_swapped_negative": 1-p}})
        source_fields = [{k: s[k] for k in ("source_id", "revision", "content_sha256", "text")}
                         for s in sources if s["source_id"] in lexical]
        frontier = digest(sorted(source_fields, key=lambda s: s["source_id"]))
        edges = [{"source_id": lexical[0], "target_id": lexical[-1],
                  "relation": "associative", "support_sha256": pin("graph witness")},
                 {"source_id": lexical[0], "target_id": lexical[1],
                  "relation": "temporal", "support_sha256": pin("temporal link") }]
        original_sha = digest(sorted(
            [(x["source_id"], x["source_root"], x["revision"], x["content_sha256"])
             for x in sources]))
        fixed_sha = digest({"source": original_sha, "edges": sorted(edges,
                         key=lambda e: (e["source_id"], e["target_id"], e["relation"]))})
        weights = {r: 0.1 for r in route.RELATIONS}
        weights["associative"] = 0.9
        graphs[qid] = {
            "profile": route.GRAPH_PROFILE, "question_id": qid,
            "original_source_frontier_sha256": original_sha, "edges": edges,
            "lesion_edge": [lexical[0], lexical[-1], "associative"],
            "trained_relation_weights": weights,
            "training_receipt": {
                "graph_sha256": fixed_sha,
                "candidate_weights_sha256": digest(weights),
                "optimizer_steps": 40, "source_training_split": "train",
                "training_source_digest": pin("external TRAIN groups"),
                "original_parameter_sha256": pin("route tensor")}}
        rag["routes"][qid] = {
            "original_question_sha256": digest(question),
            "full_source_inventory_sha256": digest(sorted(
                [(s["source_id"], s["source_root"], s["revision"], s["content_sha256"])
                 for s in sources])),
            "final_source_ids": lexical[:2],
            "original_retrieval_execution_sha256": pin("independently executed strong RAG"+qid)}
    bank["original_predictions_sha256"] = digest(predictions)
    bank["physical_head_forward_replay"]["original_predictions_sha256"] = digest(predictions)
    bank["physical_head_forward_replay"]["physical_model_forward_calls"] = 5 * len(predictions)
    bank["physical_head_forward_replay"]["verified_predictions"] = len(predictions)
    reader = {"reader_sha256": pin("same pretrained Reader"),
              "tokenizer_sha256": pin("unchanged tokenizer"),
              "prompt_sha256": PROMPT_SHA,
              "encoder_receipt_sha256": pin("frozen pretrained feature identity"),
              "max_input_tokens": 1024, "max_output_tokens": 64}
    return packet, predictions, bank, rag, graphs, reader


class OriginalRouteBuilder(unittest.TestCase):
    def setUp(self):
        (self.packet, self.predictions, self.bank, self.rag,
         self.graphs, self.reader) = setup()

    def run_plan(self):
        return route.build_original_plan(self.packet, self.predictions,
                  self.bank, self.rag, self.graphs, self.reader, final_k=2)

    def test_builds_original_whole_question_nine_arm_pairs(self):
        result = self.run_plan()
        self.assertEqual(result["query_count"], 6)
        self.assertEqual(set(result["plan"]["cases"][0]["arm_plans"]), set(ARMS))
        self.assertEqual(len(result["plan"]["cases"][0]["arm_plans"]["learned_typed"]["source_ids"]), 2)
        self.assertEqual(len(validate_plan(result["plan"])), 54)
        self.assertEqual(result["executed_reader_answers"], 0)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["superiority_claim"])

    def test_missing_strong_rag_receipt_blocks_every_arm(self):
        self.rag["routes"].pop("question-2")
        with self.assertRaisesRegex(Refused, "RAG"):
            self.run_plan()

    def test_hidden_gold_cannot_enter_original_source(self):
        self.packet["cases"][0]["publisher_support"] = ["event-0-0"]
        with self.assertRaisesRegex(Refused, "schema"):
            self.run_plan()

    def test_physical_head_prediction_missing_blocks_plan(self):
        self.predictions.pop()
        self.bank["original_predictions_sha256"] = digest(self.predictions)
        self.bank["physical_head_forward_replay"]["original_predictions_sha256"] = digest(self.predictions)
        self.bank["physical_head_forward_replay"]["physical_model_forward_calls"] = 5 * len(self.predictions)
        self.bank["physical_head_forward_replay"]["verified_predictions"] = len(self.predictions)
        with self.assertRaisesRegex(Refused, "physical Head prediction missing"):
            self.run_plan()

    def test_truncated_eligible_source_collection_rejected_by_prediction_inventory(self):
        self.packet["cases"][0]["eligible_sources"] = self.packet["cases"][0]["eligible_sources"][:2]
        with self.assertRaises(Refused):
            self.run_plan()

    def test_same_source_but_modified_content_denied(self):
        self.packet["cases"][0]["eligible_sources"][0]["text"] += " changed"
        with self.assertRaisesRegex(Refused, "source-first input"):
            self.run_plan()

    def test_graph_coefficients_not_training_bound_denied(self):
        self.graphs["question-0"]["trained_relation_weights"]["associative"] = 8
        with self.assertRaisesRegex(Refused, "trained graph coefficients"):
            self.run_plan()

    def test_lesion_edge_must_be_original(self):
        self.graphs["question-0"]["lesion_edge"] = ["fake", "invented", "supports"]
        with self.assertRaisesRegex(Refused, "lesion"):
            self.run_plan()

    def test_wrong_executed_rag_source_denied(self):
        self.rag["routes"]["question-0"]["final_source_ids"][0] = "fake"
        with self.assertRaisesRegex(Refused, "strong-RAG"):
            self.run_plan()

    def test_reader_swap_prevents_generation_identity(self):
        result = self.run_plan()
        changed = deepcopy(result["plan"])
        changed["reader_sha256"] = pin("another Reader")
        with self.assertRaisesRegex(Refused, "request"):
            validate_plan(changed)

    def test_foreign_scope_and_revoked_source_refused(self):
        src = self.packet["cases"][0]["eligible_sources"][0]
        src["scope"] = "other-principal"
        with self.assertRaisesRegex(Refused, "source-first input"):
            self.run_plan()
        src["scope"] = "research"
        src["revoked"] = True
        with self.assertRaisesRegex(Refused, "source-first input"):
            self.run_plan()

    def test_original_epoch_drift_denied(self):
        self.packet["cases"][0]["eligible_sources"][0]["generation"] = "future"
        with self.assertRaisesRegex(Refused, "source-first input"):
            self.run_plan()

    def test_physical_replay_count_cannot_be_claimed_without_forwards(self):
        self.bank["physical_head_forward_replay"]["physical_model_forward_calls"] -= 1
        with self.assertRaisesRegex(Refused, "physical replay"):
            self.run_plan()

    def test_wrapper_requires_existing_physical_head_bank(self):
        from unittest.mock import patch
        with patch("amcn_causal_physical_bank_bridge.replay_and_bind_original_bank",
                   side_effect=ValueError("missing actual physical weights")) as physical:
            with self.assertRaisesRegex(ValueError, "actual physical weights"):
                route.build_from_original_physical_bank(
                    self.packet, object(), {}, {}, self.predictions,
                    "/missing/original-bank", self.rag, self.graphs,
                    self.reader,
                    expected_manifest_sha256=pin("model"),
                    expected_source_binding_sha256=pin("source"),
                    expected_predictions_sha256=self.bank["original_predictions_sha256"])
            physical.assert_called_once()

    def test_invented_partial_bank_receipt_refused(self):
        self.bank.pop("original_bank_manifest_sha256")
        with self.assertRaisesRegex(Refused, "six-Head physical bridge"):
            self.run_plan()

    def test_balanced_predictor_capacity_required(self):
        self.bank["capacity"]["typed"]["total_trainable_parameters"] += 1
        with self.assertRaisesRegex(Refused, "capacity"):
            self.run_plan()

    def test_classification_proxy_is_not_answer_success(self):
        result = self.run_plan()
        self.assertIsNotNone(result["rag_receipt_sha256"])
        self.assertFalse(result["rag_original_execution_externally_authenticated"])
        self.assertEqual(result["real_future_calendar_windows"], 0)


if __name__ == "__main__":
    unittest.main()

class OriginalRouteMaterialization(unittest.TestCase):
    def setUp(self):
        (self.packet, self.predictions, self.bank, self.rag,
         self.graphs, self.reader) = setup()

    def _add_original_sources_outside_lexical_top16(self):
        item = self.packet["cases"][0]
        for i in range(11):
            sid = f"extra-{i:02d}"
            text = f"neutral passage with no query words {i}"
            row = {"source_id": sid, "source_root": item["source_root"],
                   "scope": "research", "generation": "g1", "revoked": False,
                   "revision": 1, "content_sha256": bytes_sha(text.encode()),
                   "text": text, "row_id": "row-extra-" + str(i)}
            row["input_sha256"] = route.feature_input_digest(item["scope"], item["question"], row)
            item["eligible_sources"].append(row)
        # Now 16 top lexical candidates and one independently retrieved
        # extra source not in the Top-16. No fake Encoder forward is added yet.
        outside = "zz-original-hybrid-only"
        text = "entirely unrelated raincloud conifer resin"
        row = {"source_id": outside, "source_root": item["source_root"],
               "scope": "research", "generation": "g1", "revoked": False,
                   "revision": 1, "content_sha256": bytes_sha(text.encode()),
               "text": text, "row_id": "row-outside"}
        row["input_sha256"] = route.feature_input_digest(item["scope"], item["question"], row)
        item["eligible_sources"].append(row)
        lexical = route.source_first(item["question"], item["eligible_sources"])
        self.assertEqual(len(lexical), 16)
        self.assertNotIn(outside, lexical)
        seen = {x["row_id"] for x in self.predictions}
        for x in item["eligible_sources"]:
            if x["source_id"] in lexical and x["row_id"] not in seen:
                self.predictions.append({"row_id": x["row_id"],
                    "family": item["family"], "split": item["split"],
                    "input_sha256": x["input_sha256"], "memory_type": item["memory_type"],
                    "probabilities": {k: 0.4 for k in (
                        "frozen", "single_shared", "untyped_equal_budget",
                        "typed_equal_budget", "typed_swapped_negative")}})
        full_inventory_sha = digest(sorted((x["source_id"],x["source_root"],
            x["revision"],x["content_sha256"]) for x in item["eligible_sources"]))
        self.rag["routes"][item["question_id"]]["full_source_inventory_sha256"] = full_inventory_sha
        self.rag["routes"][item["question_id"]]["final_source_ids"] = [outside, lexical[0]]
        graph = self.graphs[item["question_id"]]
        graph["original_source_frontier_sha256"] = full_inventory_sha
        ordered = sorted(graph["edges"], key=lambda e: (e["source_id"], e["target_id"], e["relation"]))
        graph["training_receipt"]["graph_sha256"] = digest({"source": full_inventory_sha, "edges":ordered})
        self._refresh_bank()
        return row

    def _refresh_bank(self):
        self.bank["original_predictions_sha256"] = digest(self.predictions)
        self.bank["physical_head_forward_replay"]["original_predictions_sha256"] = digest(self.predictions)
        self.bank["physical_head_forward_replay"]["physical_model_forward_calls"] = 5 * len(self.predictions)
        self.bank["physical_head_forward_replay"]["verified_predictions"] = len(self.predictions)

    def build(self):
        return route.build_original_plan(self.packet, self.predictions,
                  self.bank, self.rag, self.graphs, self.reader, final_k=2)

    def test_hybrid_sources_outside_bm25_are_not_silently_dropped(self):
        self._add_original_sources_outside_lexical_top16()
        with self.assertRaisesRegex(Refused, "re-encode RAG/graph union"):
            self.build()

    def test_graph_expansion_outside_lexical_requires_unseen_encoder_forward(self):
        extra = self._add_original_sources_outside_lexical_top16()
        qid = self.packet["cases"][0]["question_id"]
        self.rag["routes"][qid]["final_source_ids"] = route.source_first(
            self.packet["cases"][0]["question"],
            self.packet["cases"][0]["eligible_sources"])[:2]
        graph = self.graphs[qid]
        lexical = route.source_first(self.packet["cases"][0]["question"],
                   self.packet["cases"][0]["eligible_sources"])
        graph["edges"].append({"source_id": lexical[0],
                     "target_id": extra["source_id"], "relation": "supports",
                     "support_sha256": pin("observed source relation")})
        ordered = sorted(graph["edges"], key=lambda e: (e["source_id"],e["target_id"],e["relation"]))
        graph["training_receipt"]["graph_sha256"] = digest({
            "source": graph["original_source_frontier_sha256"], "edges": ordered})
        with self.assertRaisesRegex(Refused, "re-encode RAG/graph union"):
            self.build()

    def test_original_hybrid_discovered_source_requires_real_head_candidate(self):
        extra = self._add_original_sources_outside_lexical_top16()
        # A synthetic score row only tests protocol mechanics, not a real
        # additional Encoder forward or learned-memory achievement.
        self.predictions.append({"row_id": extra["row_id"],
            "family": self.packet["cases"][0]["family"], "split": "select",
            "input_sha256": extra["input_sha256"], "memory_type": "episodic",
            "probabilities": {k: 0.6 for k in (
                "frozen", "single_shared", "untyped_equal_budget",
                "typed_equal_budget", "typed_swapped_negative")}})
        self._refresh_bank()
        plan = self.build()["plan"]
        case = plan["cases"][0]
        self.assertIn(extra["source_id"], {s["source_id"] for s in case["sources"]})
        self.assertIn(extra["source_id"], case["arm_plans"]["strong_hybrid_rag"]["source_ids"])
        self.assertEqual(len(validate_plan(plan)), 54)

    def test_shared_evidence_root_auto_clusters_future_families(self):
        left = self.packet["cases"][2]
        right = self.packet["cases"][3]
        # Neither case's own case.source_root is shared. Both nevertheless
        # expose one same evidence source family; they are one sampling unit.
        left["eligible_sources"][0]["source_root"] = "shared-derived-source"
        right["eligible_sources"][0]["source_root"] = "shared-derived-source"
        for item in (left, right):
            original_sha = digest(sorted((z["source_id"], z["source_root"],
                z["revision"], z["content_sha256"]) for z in item["eligible_sources"]))
            qid = item["question_id"]
            self.rag["routes"][qid]["full_source_inventory_sha256"] = original_sha
            graph = self.graphs[qid]
            graph["original_source_frontier_sha256"] = original_sha
            ordered = sorted(graph["edges"], key=lambda e: (
                e["source_id"], e["target_id"], e["relation"]))
            graph["training_receipt"]["graph_sha256"] = digest({
                "source": original_sha, "edges": ordered})
        self.assertIn(["root-2", "root-3"], self.build()["plan"]["lineage_alias_edges"])

    def test_cli_rechecks_all_pinned_inputs_before_writing(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            args = []
            for name, value in (("source", self.packet), ("predictions", self.predictions),
                                ("bank", self.bank), ("rag", self.rag),
                                ("graph", self.graphs), ("reader", self.reader)):
                target = directory / (name + ".json")
                content = route.canonical(value) + b"\n"
                target.write_bytes(content)
                args += ["--" + name, str(target), "--" + name + "-sha256",
                         bytes_sha(content)]
            args += ["--output", str(directory / "original-nine-arm-plan.json"),
                     "--final-k", "2"]
            report = route.main(args)
            self.assertEqual(report["original_cases"], 6)
            self.assertEqual(report["original_reader_calls"], 0)
            with self.assertRaisesRegex(Refused, "already exists"):
                route.main(args)
            (directory / "source.json").write_bytes(b'{}')
            with self.assertRaisesRegex(Refused, "original material changed"):
                route.main(args[:-4]+["--output", str(directory / "second-plan.json")])
