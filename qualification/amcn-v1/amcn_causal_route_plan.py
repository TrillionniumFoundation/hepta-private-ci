"""Source-first nine-arm route construction from immutable original Head scores.

Cannot independently authenticate an original strong-RAG selector, source owner,
trained graph weights, or physical pretrained Encoder. Those prerequisites must
arrive from separately pinned external artifacts. No publisher labels permitted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
from math import isfinite, log
import re

from amcn_causal_task_audit import (
    ALLOWED_TYPES, ARMS, MAX_SOURCES, PROFILE, Refused, bytes_sha, canonical, digest,
    is_sha, pinned_json, request_digest, require, validate_plan, paired_components,
)

SOURCE_PROFILE = "hepta.amcn.source-first-original-nine-arm-input.v1"
RAG_PROFILE = "hepta.amcn.external-original-strong-rag-route.v1"
GRAPH_PROFILE = "hepta.amcn.frozen-edges-trained-relation-coefficients.v1"
PROTOCOL = "hepta.amcn.source-first-nine-arm-plan-builder.shadow.v1"
TOKENS = re.compile(r"\w+", re.UNICODE)
MAX_ELIGIBLE = 8192
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_CANDIDATE = 16
RELATIONS = ("supports", "temporal", "causal_candidate", "procedural", "associative", "contradicts")
GRAPH_ARMS = ("typed_fixed_graph", "typed_learned_graph", "typed_graph_lesion", "unsplit_equal_graph")


def _keys(obj, needed, context):
    require(isinstance(obj, dict) and set(obj) == set(needed), context)


def source_first(question, sources):
    """Physically rescore entire eligible inventory with original AMCN BM25.

    Keep original lexical tie-break: score descending then source ID ascending.
    A top-16 list supplied by a model is NOT enough to certify retrieval.
    """
    require(isinstance(question, str) and 1 <= len(question.encode()) <= 8192,
            "source-first question size")
    words = TOKENS.findall(question.casefold())
    require(0 < len(words) <= 256 and len(sources) <= MAX_ELIGIBLE,
            "unbounded or empty lexical work")
    ordered = sorted(sources, key=lambda r: r["source_id"])
    terms = sorted(set(words))
    document_frequency = Counter()
    bags, lengths = [], []
    for source in ordered:
        tokens = TOKENS.findall(source["text"].casefold())
        require(len(tokens) <= 8192, "unbounded lexical document")
        counts = Counter(tokens)
        bags.append(counts)
        lengths.append(len(tokens))
        for term in terms:
            document_frequency[term] += int(term in counts)
    n, average = len(ordered), max(1.0, sum(lengths) / len(lengths))
    ranked = []
    for source, counts, length in zip(ordered, bags, lengths):
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf:
                df = document_frequency[term]
                score += log(1 + (n - df + 0.5) / (df + 0.5)) * (
                    2.2 * tf / (tf + 1.2 * (0.25 + 0.75 * length / average)))
        require(isfinite(score) and score >= 0, "nonfinite lexical rank")
        ranked.append((source["source_id"], score))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return [sid for sid, _ in ranked[:MAX_CANDIDATE]]


def feature_input_digest(scope, question, row):
    # Reconstruct original amcn_native.build_inputs + Case.input_digest, without
    # importing torch or trusting a producer-supplied per-row digest.
    exposed = canonical({"question": question, "source_id": row["source_id"],
                         "source_revision": row["revision"],
                         "source_content_sha256": row["content_sha256"],
                         "evidence": row["text"]}).decode("utf-8")
    return sha256(canonical([scope, exposed])).hexdigest()


def _stable_rank(ids, scores, k):
    require(1 <= k <= len(ids), "unavailable final evidence budget")
    return sorted(ids, key=lambda sid: (-scores[sid], ids.index(sid)))[:k]


def _admit_graph(graph, case, candidates, full_snapshot_sha256):
    """Rebuild original fixed, learned and lesioned graph digests from edges."""
    _keys(graph, ("profile", "question_id", "original_source_frontier_sha256",
                  "edges", "lesion_edge", "trained_relation_weights",
                  "training_receipt"), "graph route must have original edges and receipt")
    require(graph["profile"] == GRAPH_PROFILE
            and graph["question_id"] == case["question_id"]
            and graph["original_source_frontier_sha256"] == full_snapshot_sha256,
            "graph snapshot/source frontier mismatch")
    edges = graph["edges"]
    require(isinstance(edges, list) and 1 <= len(edges) <= 32768,
            "graph edge census missing or oversized")
    vertices = set(candidates)
    registered = set()
    ordered = []
    for edge in edges:
        _keys(edge, ("source_id", "target_id", "relation", "support_sha256"),
              "unregistered graph edge fields")
        a, b = edge["source_id"], edge["target_id"]
        key = (a, b, edge["relation"])
        require(a != b
                and edge["relation"] in RELATIONS and is_sha(edge["support_sha256"])
                and key not in registered,
                "fabricated, repeated or out-of-inventory graph relation")
        # This bounded pilot may associate admitted candidates only.
        # It cannot discover sources absent from the actual original shortlist.
        registered.add(key)
        ordered.append(edge)
    ordered.sort(key=lambda e: (e["source_id"], e["target_id"], e["relation"]))
    lesion = graph["lesion_edge"]
    require(isinstance(lesion, list) and len(lesion) == 3 and tuple(lesion) in registered,
            "lesion must remove exactly one registered edge")
    weights = graph["trained_relation_weights"]
    require(isinstance(weights, dict) and set(weights) == set(RELATIONS)
            and all(type(v) in (int, float) and isfinite(v) and -8 <= v <= 8
                    for v in weights.values()), "unqualified graph relation coefficients")
    receipt = graph["training_receipt"]
    _keys(receipt, ("graph_sha256", "candidate_weights_sha256", "optimizer_steps",
                    "source_training_split", "training_source_digest",
                    "original_parameter_sha256"), "missing physical graph training lineage")
    fixed_sha = digest({"source": full_snapshot_sha256, "edges": ordered})
    require(receipt["graph_sha256"] == fixed_sha
            and receipt["candidate_weights_sha256"] == digest(weights)
            and receipt["source_training_split"] == "train"
            and type(receipt["optimizer_steps"]) is int
            and 1 <= receipt["optimizer_steps"] <= 1000
            and is_sha(receipt["training_source_digest"])
            and is_sha(receipt["original_parameter_sha256"]),
            "actual trained graph coefficients not tied to original fixed topology")
    # Differs from source truth: weights are applicability/route priors only.
    learned_sha = digest({"fixed": fixed_sha, "weights": weights,
                          "training": receipt})
    lesioned = [e for e in ordered if (e["source_id"], e["target_id"], e["relation"]) != tuple(lesion)
                and e["source_id"] in vertices and e["target_id"] in vertices]
    lesion_sha = digest({"learned": learned_sha, "lesion": lesion,
                         "remaining": lesioned})
    require(len({fixed_sha, learned_sha, lesion_sha}) == 3,
            "graph interventions not distinct")
    return ordered, lesioned, weights, {
        "typed_fixed_graph": fixed_sha, "typed_learned_graph": learned_sha,
        "typed_graph_lesion": lesion_sha, "unsplit_equal_graph": learned_sha,
    }


def graph_rank(candidates, base_scores, edges, weights, k):
    """Bounded fixed-topology additive association; no evidence authority."""
    scores = {key: float(value) for key, value in base_scores.items()}
    seeds = _stable_rank(candidates, scores, min(2, len(candidates)))
    boost = defaultdict(float)
    for edge in edges:
        a, b = edge["source_id"], edge["target_id"]
        if a in seeds:
            weight = weights[edge["relation"]]
            # Learned negative/inhibitory connections can suppress candidates.
            boost[b] += max(-1.0, min(1.0, weight)) * max(0.0, scores[a])
    final = {sid: scores[sid] + boost[sid] for sid in candidates}
    return _stable_rank(candidates, final, k)


def build_original_plan(source_packet, original_predictions, bank, rag_receipt,
                        graph_receipts, reader_binding, *, final_k=4):
    """Produce all nine immutable final evidence arms or refuse the whole study.

    Outputs are only label-blind route candidates. A SHA pin authenticates bytes
    only; model, strong-RAG execution, HNMF source and graph issuer authority
    remain independent scientific prerequisites.
    """
    _keys(source_packet, ("profile", "source_snapshot_sha256", "cases",
                          "lineage_alias_edges"), "source-first input schema")
    require(source_packet["profile"] == SOURCE_PROFILE
            and is_sha(source_packet["source_snapshot_sha256"]),
            "original source packet not pinned")
    _keys(bank, ("profile", "original_bank_manifest_sha256",
                 "original_source_binding_sha256", "original_predictions_sha256",
                 "original_training_receipt_sha256", "types", "capacity",
                 "frozen_head_sha256", "single_head_sha256",
                 "physical_head_forward_replay",
                 "real_pretrained_encoder_origin_independently_authenticated",
                 "future_reader_answers_generated", "original_rag_and_graph_routes_verified",
                 "original_publisher_truth_or_entailment_verified",
                 "real_future_calendar_windows", "production_accepted",
                 "superiority_claim"),
          "complete ORIGINAL #1968 six-Head physical bridge receipt required")
    replay = bank["physical_head_forward_replay"]
    _keys(replay, ("verified_predictions", "physical_model_forward_calls",
                   "maximum_absolute_probability_error", "original_predictions_sha256",
                   "no_label_scores_opened", "production_accepted"),
          "original saved Head not physically replayed")
    require(bank["profile"] == "hepta.amcn.original-typed-six-head-bridge.shadow.v1"
            and all(is_sha(bank[k]) for k in (
                "original_bank_manifest_sha256", "original_source_binding_sha256",
                "original_predictions_sha256", "original_training_receipt_sha256",
                "frozen_head_sha256", "single_head_sha256"))
            and isinstance(bank["types"], list)
            and bank["types"] == sorted(set(bank["types"]))
            and len(bank["types"]) == 2
            and set(bank["types"]) <= ALLOWED_TYPES
            and replay["no_label_scores_opened"] is True
            and replay["production_accepted"] is False
            and replay["verified_predictions"] == len(original_predictions)
            and replay["physical_model_forward_calls"] == len(original_predictions) * 5
            and type(replay["maximum_absolute_probability_error"]) in (float, int)
            and isfinite(replay["maximum_absolute_probability_error"])
            and 0 <= replay["maximum_absolute_probability_error"] <= 1e-6
            and replay["original_predictions_sha256"] == bank["original_predictions_sha256"]
            and bank["original_predictions_sha256"] == digest(original_predictions)
            and bank["real_pretrained_encoder_origin_independently_authenticated"] is False
            and bank["future_reader_answers_generated"] == 0
            and bank["original_rag_and_graph_routes_verified"] is False
            and bank["original_publisher_truth_or_entailment_verified"] is False
            and bank["real_future_calendar_windows"] == 0
            and bank["production_accepted"] is False
            and bank["superiority_claim"] is False,
            "original six-Head physical replay/negative-capability identity missing")
    _keys(rag_receipt, ("profile", "source_snapshot_sha256", "candidate_policy_sha256",
                        "original_retrieval_receipt_sha256", "routes"),
          "original strong RAG route receipt is mandatory")
    require(rag_receipt["profile"] == RAG_PROFILE
            and rag_receipt["source_snapshot_sha256"] == source_packet["source_snapshot_sha256"]
            and all(is_sha(rag_receipt[k]) for k in (
                "candidate_policy_sha256", "original_retrieval_receipt_sha256")),
            "strong RAG must bind the same original source and retrieval policy")
    _keys(reader_binding, ("reader_sha256", "tokenizer_sha256", "prompt_sha256",
                           "encoder_receipt_sha256", "max_input_tokens",
                           "max_output_tokens"), "exact fixed Reader tuple")
    require(all(is_sha(reader_binding[k]) for k in (
        "reader_sha256", "tokenizer_sha256", "prompt_sha256", "encoder_receipt_sha256")),
        "reader/model/Encoder material origins missing")
    require(type(final_k) is int and 1 <= final_k <= MAX_CANDIDATE,
            "invalid fixed final evidence count")
    cases = source_packet["cases"]
    require(isinstance(cases, list) and 1 <= len(cases) <= 8192,
            "original query inventory unavailable")
    require(isinstance(original_predictions, list), "original physical Head answers absent")
    predictions = {}
    for row in original_predictions:
        _keys(row, ("row_id", "family", "split", "input_sha256",
                    "memory_type", "probabilities"), "original saved physical Head row")
        require(isinstance(row["row_id"], str) and row["row_id"] not in predictions,
                "duplicate physical model prediction")
        predictions[row["row_id"]] = row
    require(isinstance(graph_receipts, dict) and isinstance(rag_receipt["routes"], dict),
            "missing original retrieval/graph route census")
    require(set(graph_receipts) == set(rag_receipt["routes"]) == {
        c["question_id"] for c in cases}, "missing/extra graph or RAG question")
    output_cases, consumed = [], set()
    exposed_roots = defaultdict(set)
    for item in cases:
        _keys(item, ("question_id", "family", "source_root", "memory_type",
                     "split", "scope", "generation", "question",
                     "eligible_sources"), "original query/source schema drift")
        require(item["split"] in ("select", "future_a", "future_b", "retention")
                and item["memory_type"] in bank["types"],
                "query type/split not frozen in physical Head pilot")
        original = item["eligible_sources"]
        require(isinstance(original, list) and 1 <= len(original) <= MAX_ELIGIBLE
                and sum(len(s["text"].encode("utf-8")) for s in original) <= MAX_TOTAL_BYTES,
                "source corpus not fully admitted under bounded inventory")
        seen = set()
        for source in original:
            _keys(source, ("source_id", "source_root", "scope", "generation",
                           "revoked", "revision", "content_sha256", "text",
                           "row_id", "input_sha256"), "incomplete eligible source")
            sid = source["source_id"]
            require(isinstance(sid, str) and sid not in seen
                    and isinstance(source["source_root"], str) and source["source_root"]
                    and source["scope"] == item["scope"]
                    and source["generation"] == item["generation"]
                    and source["revoked"] is False
                    and type(source["revision"]) is int and source["revision"] > 0
                    and source["content_sha256"] == bytes_sha(source["text"].encode())
                    and source["input_sha256"] == feature_input_digest(
                        item["scope"], item["question"], source),
                    "source-first input is not exact original Encoder input")
            seen.add(sid)
            # Source-family clustering must include all actual eligible
            # evidence origins, not just the question's single root label.
            exposed_roots[source["source_root"]].add(item["source_root"])
        lexical = source_first(item["question"], original)
        ordered_sources = {s["source_id"]: s for s in original}
        original_inventory_sha = digest(sorted(
            [(s["source_id"], s["source_root"], s["revision"], s["content_sha256"])
             for s in original]))
        final_count = min(final_k, len(lexical))
        rag_row = rag_receipt["routes"][item["question_id"]]
        _keys(rag_row, ("original_question_sha256", "full_source_inventory_sha256",
                        "final_source_ids", "original_retrieval_execution_sha256"),
              "missing original strong-RAG source selection")
        require(rag_row["original_question_sha256"] == digest(item["question"])
                and rag_row["full_source_inventory_sha256"] == original_inventory_sha
                and is_sha(rag_row["original_retrieval_execution_sha256"])
                and isinstance(rag_row["final_source_ids"], list)
                and len(rag_row["final_source_ids"]) == final_count
                and len(set(rag_row["final_source_ids"])) == final_count
                and set(rag_row["final_source_ids"]) <= set(ordered_sources),
                "strong-RAG original output changed or outside admitted source inventory")
        graph = graph_receipts[item["question_id"]]
        _keys(graph, ("profile", "question_id", "original_source_frontier_sha256",
                      "edges", "lesion_edge", "trained_relation_weights",
                      "training_receipt"), "graph original topology required")
        require(graph["profile"] == GRAPH_PROFILE
                and graph["original_source_frontier_sha256"] == original_inventory_sha,
                "graph must bind the FULL original inventory, not a selected shortlist")
        # Build a common final candidate frontier from BM25, original strong
        # hybrid RAG and graph-admitted neighbors. Neither RAG nor graph may
        # be handicapped to lexical Top-16; no gold influences this union.
        frontier = set(lexical) | set(rag_row["final_source_ids"])
        for edge in graph["edges"]:
            require(isinstance(edge, dict) and set(edge) == {
                "source_id", "target_id", "relation", "support_sha256"},
                "graph relation has malformed source IDs")
            require(edge["source_id"] in ordered_sources
                    and edge["target_id"] in ordered_sources,
                    "graph expansion targets source absent from original inventory")
            if edge["source_id"] in lexical:
                frontier.add(edge["target_id"])
        require(len(frontier) <= MAX_SOURCES,
                "expanded common candidate frontier exceeds Reader/Head source budget")
        source_ids = [sid for sid in lexical if sid in frontier]
        source_ids += sorted(frontier - set(source_ids))
        # Every arm will see the same fully eligible candidate frontier. New
        # RAG/graph discoveries require physical Encoder/Head forwards as well;
        # NEVER silently discard extra strong-RAG IDs to reuse old Top-16 scores.
        by_id = {}
        for sid in source_ids:
            record = ordered_sources[sid]
            row_id = record["row_id"]
            prediction = predictions.get(row_id)
            require(prediction is not None and row_id not in consumed
                    and prediction["input_sha256"] == record["input_sha256"]
                    and prediction["memory_type"] == item["memory_type"]
                    and prediction["family"] == item["family"]
                    and prediction["split"] == item["split"],
                    "source-first physical Head prediction missing or relabelled; re-encode RAG/graph union")
            probabilities = prediction["probabilities"]
            require(isinstance(probabilities, dict) and set(probabilities) == {
                "frozen", "single_shared", "untyped_equal_budget",
                "typed_equal_budget", "typed_swapped_negative"}
                and all(type(v) in (float, int) and isfinite(v) and 0 <= v <= 1
                        for v in probabilities.values()), "physical score census changed")
            consumed.add(row_id)
            by_id[sid] = probabilities
        case = {
            "question_id": item["question_id"], "family": item["family"],
            "source_root": item["source_root"], "memory_type": item["memory_type"],
            "split": item["split"], "scope": item["scope"],
            "generation": item["generation"], "question": item["question"],
            "sources": [{"source_id": sid, "revision": ordered_sources[sid]["revision"],
                         "content_sha256": ordered_sources[sid]["content_sha256"],
                         "text": ordered_sources[sid]["text"]} for sid in source_ids],
            "arm_plans": {},
        }
        case["source_frontier_sha256"] = digest(sorted(
            case["sources"], key=lambda s: s["source_id"]))
        _, lesioned, weights, graphs = _admit_graph(
            graph, case, source_ids, original_inventory_sha)
        edges = [e for e in graph["edges"] if
                 e["source_id"] in frontier and e["target_id"] in frontier]
        graph_fixed = {kind: 0.5 for kind in RELATIONS}
        typed_scores = {sid: by_id[sid]["typed_equal_budget"] for sid in source_ids}
        shared_scores = {sid: by_id[sid]["untyped_equal_budget"] for sid in source_ids}
        selected = {
            "frozen_shared": _stable_rank(source_ids, {s: by_id[s]["frozen"]
                                                        for s in source_ids}, final_count),
            "learned_shared": _stable_rank(source_ids, shared_scores, final_count),
            "learned_typed": _stable_rank(source_ids, typed_scores, final_count),
            "typed_swapped": _stable_rank(source_ids, {s: by_id[s]["typed_swapped_negative"]
                                                         for s in source_ids}, final_count),
            "typed_fixed_graph": graph_rank(source_ids, typed_scores, edges, graph_fixed, final_count),
            "typed_learned_graph": graph_rank(source_ids, typed_scores, edges, weights, final_count),
            "typed_graph_lesion": graph_rank(source_ids, typed_scores, lesioned, weights, final_count),
            "unsplit_equal_graph": graph_rank(source_ids, shared_scores, edges, weights, final_count),
        }
        selected["strong_hybrid_rag"] = rag_row["final_source_ids"]
        kind = item["memory_type"]
        alternate = next(t for t in bank["types"] if t != kind)
        typed_bank = bank["capacity"]["typed"]["head_sha256_by_type"]
        pooled_bank = bank["capacity"]["shared"]["head_sha256_by_type"]
        for arm in ARMS:
            head = (None if arm == "strong_hybrid_rag" else
                    bank["frozen_head_sha256"] if arm == "frozen_shared" else
                    pooled_bank[kind] if arm in ("learned_shared", "unsplit_equal_graph") else
                    typed_bank[alternate] if arm == "typed_swapped" else typed_bank[kind])
            route = (alternate if arm == "typed_swapped" else
                     kind if arm.startswith("typed_") or arm == "learned_typed" else None)
            choice = {
                "source_ids": selected[arm], "head_sha256": head,
                "graph_sha256": graphs[arm] if arm in GRAPH_ARMS else None,
                "route_type": route, "planned_request_sha256": "",
            }
            case["arm_plans"][arm] = choice
        output_cases.append(case)
    require(set(predictions) == consumed, "original physical Head predictions not fully accounted")
    provided_aliases = source_packet["lineage_alias_edges"]
    require(isinstance(provided_aliases, list)
            and all(isinstance(x, list) and len(x) == 2 for x in provided_aliases),
            "original owner lineage aliases required")
    alias = {tuple(sorted(x)) for x in provided_aliases}
    for exposures in exposed_roots.values():
        linked = sorted(exposures)
        for other in linked[1:]:
            alias.add((linked[0], other))
    plan = {"profile": PROFILE, **reader_binding, "capacity": bank["capacity"],
            "cases": output_cases,
            "lineage_alias_edges": [list(p) for p in sorted(alias)],
            "future_calendar_verified": False, "production_accepted": False}
    for case in plan["cases"]:
        for arm in ARMS:
            case["arm_plans"][arm]["planned_request_sha256"] = request_digest(
                plan, case, arm, {source["source_id"]: source for source in case["sources"]})
    validate_plan(plan)
    paired_components(plan)
    return {"plan": plan, "source_snapshot_sha256": source_packet["source_snapshot_sha256"],
            "original_predictions_sha256": bank["original_predictions_sha256"],
            "rag_receipt_sha256": digest(rag_receipt),
            "graph_receipts_sha256": digest(graph_receipts),
            "query_count": len(output_cases), "executed_reader_answers": 0,
            "rag_original_execution_externally_authenticated": False,
            "trained_graph_issuer_authenticated": False,
            "real_future_calendar_windows": 0, "production_accepted": False,
            "superiority_claim": False}


def build_from_original_physical_bank(source_packet, matrix, type_by_row,
                                      original_training_receipt, original_predictions,
                                      bank_directory, rag_receipt, graph_receipts,
                                      reader_binding, *, expected_manifest_sha256,
                                      expected_source_binding_sha256,
                                      expected_predictions_sha256, final_k=4):
    """Physically replay original #1968 safetensors and then freeze nine arms.

    There is no mock fallback, alternate trainer, gold ingestion or authority.
    The existing owner library raises if any required actual Head is missing.
    """
    from amcn_causal_physical_bank_bridge import replay_and_bind_original_bank

    observed = replay_and_bind_original_bank(
        matrix, type_by_row, original_training_receipt,
        original_predictions, bank_directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_source_binding_sha256=expected_source_binding_sha256,
        expected_predictions_sha256=expected_predictions_sha256,
    )
    return build_original_plan(source_packet, original_predictions,
                               observed, rag_receipt, graph_receipts,
                               reader_binding, final_k=final_k)


def main(argv=None):
    """Create the exact nine-arm Reader plan only from externally pinned inputs.

    The files carry original source/Head and route declarations; no gold labels,
    free-form output rewriting, model downloading or authority is available.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "predictions", "bank", "rag", "graph", "reader"):
        parser.add_argument("--" + key, type=Path, required=True)
        parser.add_argument("--" + key + "-sha256", required=True)
    parser.add_argument("--final-k", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = [pinned_json(getattr(args, key), getattr(args, key + "_sha256"))
              for key in ("source", "predictions", "bank", "rag", "graph", "reader")]
    receipt = build_original_plan(*inputs, final_k=args.final_k)
    output = args.output
    require(not output.exists() and not output.is_symlink(),
            "original nine-arm source plan already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = canonical(receipt) + b"\n"
    with output.open("xb") as writer:
        writer.write(content)
        writer.flush()
        os.fsync(writer.fileno())
    return {"plan_sha256": digest(receipt["plan"]),
            "source_plan_file_sha256": bytes_sha(content),
            "original_cases": receipt["query_count"],
            "original_reader_calls": 0,
            "independent_source_and_model_authority": False,
            "production_accepted": False}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
