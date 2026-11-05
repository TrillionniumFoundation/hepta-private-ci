#!/usr/bin/env python3
"""Offline attribution of recorded routing traces; never a promotion decision.

Schema hepta.memory.routing-traces.v1 has common identities, a common budget,
an arms map (model/scorer/router SHA256), and queries. Every query contains id,
input {query, payload}, input_sha256, answerable, expected_output, support_sets,
records, cells, and traces by arm. input_sha256 must equal digest(input): UTF-8
JSON with sorted object keys, compact separators, preserved string contents,
and no nonfinite numbers. The input digest is part of dataset_sha256 and every
trace context; a query ID alone cannot bind the actual input. This checks the
producer's supplied input record, not authentication of a real model dispatch.
Support sets are OR alternatives of AND-required immutable record-version IDs.
Records contain content_sha256, authorized and current (trusted producer claims,
not authorization established by this analyzer). Each cell has available IDs
and a candidate pool; all arms reference these exact common pools.

A trace binds context_sha256 = digest({identities, query-without-traces,
arm_name, arm_identity}), then
records local_selected for EVERY cell, routed_cells, and reader {evidence,
output, abstained, error}. Missing shadow traces cannot be reconstructed from
final answers. Shadow scoring is diagnostic work whose cost must be counted by
the experiment. No-answer queries have empty support_sets and null gold output;
successful abstention requires abstained=true, output=null, error=null.

identities.dataset_sha256 hashes the ordered query projections GOLD; the pools
digest hashes ordered projections POOLS; budget_sha256 hashes the common budget.
The CLI additionally requires the independently frozen input file SHA256.
Hashes identify supplied bytes; they do not prove those models actually ran.
CLI exit 0 means a report was generated (including unavailable); it is not a
qualification pass. Invalid input exits 2.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from typed_json import equal_json


MAX_BYTES = 16 * 1024 * 1024
MAX_QUERIES, MAX_ARMS, MAX_CELLS, MAX_RECORDS = 4096, 32, 128, 8192
SCHEMA = "hepta.memory.routing-traces.v1"
GOLD = ("id", "input_sha256", "answerable", "expected_output", "support_sets")
POOLS = ("id", "records", "cells")
IDENTITIES = ("source_commit", "memory_sha256", "policy_sha256", "executor_sha256",
              "dataset_sha256", "candidate_pools_sha256", "budget_sha256")
BUDGET = ("max_candidates_per_cell", "max_local_per_cell", "max_routed_cells",
          "max_executor_evidence")
STAGES = ("eligible_memory", "candidate_coverage", "local_scoring_all_cells",
          "cross_expert_routing", "executor_input", "grounded_executor_success")


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), label + ":fields")


def identifier(value):
    require(type(value) is str and 0 < len(value) <= 256, "invalid_identifier")


def sha(value, length=64):
    require(type(value) is str and re.fullmatch("[0-9a-f]{%d}" % length, value),
            "invalid_sha")


def refs(value, allowed, limit, label):
    require(type(value) is list and len(value) <= limit, label + ":missing_or_over_limit")
    for item in value:
        identifier(item)
    result = set(value)
    require(result <= set(allowed), label + ":unknown_or_outside_pool")
    return result


def project(queries, fields):
    return [{key: query[key] for key in fields} for query in queries]


def context_digest(identities, query, arm_name, arm_identity):
    return digest({"identities": identities,
                   "arm_name": arm_name, "arm_identity": arm_identity,
                   "query": {k: v for k, v in query.items() if k != "traces"}})


def analyze(document):
    """Freeze a caller's JSON value and return descriptive nested-event counts."""
    raw = canonical(document)
    require(len(raw) <= MAX_BYTES, "input_over_limit")
    data = json.loads(raw)
    keys(data, ("schema", "identities", "budget", "arms", "queries"), "document")
    require(data["schema"] == SCHEMA, "unsupported_schema")
    identities, budget, arms, queries = (data[k] for k in ("identities", "budget", "arms", "queries"))
    keys(identities, IDENTITIES, "identities")
    for name, value in identities.items():
        sha(value, 40 if name == "source_commit" else 64)
    keys(budget, BUDGET, "budget")
    require(all(type(v) is int and 0 <= v <= MAX_RECORDS for v in budget.values()), "invalid_budget")
    require(type(arms) is dict and 1 <= len(arms) <= MAX_ARMS, "invalid_arms")
    for name, arm in arms.items():
        identifier(name)
        keys(arm, ("model_sha256", "scorer_sha256", "router_sha256"), "arm_identity")
        for value in arm.values():
            sha(value)
    require(type(queries) is list and 1 <= len(queries) <= MAX_QUERIES, "invalid_queries")
    seen_queries, record_hashes = set(), {}
    for query in queries:
        keys(query, (*GOLD, "input", "records", "cells", "traces"), "query")
        identifier(query["id"])
        require(query["id"] not in seen_queries, "duplicate_query_id")
        seen_queries.add(query["id"])
        keys(query["input"], ("query", "payload"), "query_input")
        sha(query["input_sha256"])
        require(query["input_sha256"] == digest(query["input"]), "query_input_identity_mismatch")
        require(type(query["answerable"]) is bool, "invalid_answerable")
        records, cells, supports = query["records"], query["cells"], query["support_sets"]
        require(type(records) is dict and len(records) <= MAX_RECORDS, "invalid_records")
        for rid, record in records.items():
            identifier(rid)
            keys(record, ("content_sha256", "authorized", "current"), "record")
            sha(record["content_sha256"])
            require(type(record["authorized"]) is bool and type(record["current"]) is bool,
                    "invalid_eligibility")
            require(record_hashes.get(rid, record["content_sha256"]) == record["content_sha256"],
                    "immutable_record_identity_conflict")
            record_hashes[rid] = record["content_sha256"]
        require(type(supports) is list and len(supports) <= MAX_CELLS, "invalid_support_sets")
        require(bool(supports) == query["answerable"], "answerability_support_mismatch")
        for support in supports:
            require(refs(support, records, MAX_RECORDS, "support"), "empty_support")
        require(query["answerable"] or query["expected_output"] is None, "no_answer_gold_not_null")
        require(type(cells) is dict and len(cells) <= MAX_CELLS, "invalid_cells")
        for cell, pool in cells.items():
            identifier(cell)
            keys(pool, ("available", "candidates"), "cell")
            available = refs(pool["available"], records, MAX_RECORDS, "available")
            refs(pool["candidates"], available, budget["max_candidates_per_cell"], "candidates")
        require(type(query["traces"]) is dict and set(query["traces"]) <= set(arms), "unknown_trace_arm")
    require(identities["budget_sha256"] == digest(budget), "budget_identity_mismatch")
    require(identities["dataset_sha256"] == digest(project(queries, GOLD)), "dataset_identity_mismatch")
    require(identities["candidate_pools_sha256"] == digest(project(queries, POOLS)), "pool_identity_mismatch")
    results = {}
    for arm in arms:
        rows = []
        for query in queries:
            try:
                rows.append(analyze_query(query, arm, arms[arm], identities, budget))
            except (ValueError, KeyError, TypeError) as error:
                rows.append({"id": query["id"], "answerable": query["answerable"],
                             "status": "unavailable", "reason": str(error)[:256]})
        complete = [r for r in rows if r["status"] == "complete"]
        answered = [r for r in complete if r["answerable"]]
        counts = [sum(r["events"][stage] for r in answered) for stage in STAGES]
        denominators = [len(answered), *counts[:-1]]
        unknown, total = len(rows) - len(complete), len(rows)
        correct = sum(r["actual_correct"] for r in complete)
        grounded = sum(r["grounded_correct"] for r in complete)
        results[arm] = {
            "expected_queries": total, "complete_traces": len(complete), "unavailable_traces": unknown,
            "answerable_complete": len(answered),
            "answerable_unavailable": sum(r["answerable"] for r in rows if r["status"] == "unavailable"),
            "no_answer_complete": len(complete) - len(answered),
            "no_answer_correct": sum(r["actual_correct"] for r in complete if not r["answerable"]),
            "accuracy_bounds_all_expected": [correct / total, (correct + unknown) / total],
            "grounded_accuracy_bounds_all_expected": [grounded / total, (grounded + unknown) / total],
            "correct_without_complete_support": sum(r["actual_correct"] and not r["grounded_correct"] for r in answered),
            "reader_ineligible_traces": sum(bool(r["ineligible_references"]["reader"]) for r in complete),
            "nested_events": {stage: {"count": count, "conditional_denominator": denominator,
                "conditional_rate": count / denominator if denominator else None}
                for stage, count, denominator in zip(STAGES, counts, denominators)}, "rows": rows}
    return {"schema": "hepta.memory.routing-diagnostic.v1", "status": "diagnostic_incomplete"
            if any(r["unavailable_traces"] for r in results.values()) else "diagnostic_complete",
            "input_canonical_sha256": hashlib.sha256(raw).hexdigest(), "identities": identities,
            "arm_identities": arms, "budget": budget, "arms": results,
            "qualification": "not_evaluated", "production_activation_allowed": False,
            "all_cells_upper_bound_is_deployable": False, "new_model_runs": 0,
            "scope": "Nested descriptive events on complete traces; no multiplication of marginal rates. "
                     "Unknown traces remain in accuracy bounds. All-cell local scoring is a diagnostic upper "
                     "bound, not a budget-feasible oracle deployment. Producer claims are not authenticated "
                     "here. No full-cost, causal-improvement, independent-generalization or promotion claim."}


def analyze_query(query, arm, arm_identity, identities, budget):
    trace = query["traces"].get(arm)
    keys(trace, ("context_sha256", "local_selected", "routed_cells", "reader"), "trace")
    require(trace["context_sha256"] == context_digest(identities, query, arm, arm_identity),
            "trace_context_mismatch")
    records, cells = query["records"], query["cells"]
    eligible = {rid for rid, record in records.items() if record["authorized"] and record["current"]}
    local = trace["local_selected"]
    keys(local, cells, "local_selected")
    local_sets = {cell: refs(local[cell], pool["candidates"], budget["max_local_per_cell"], "local")
                  for cell, pool in cells.items()}
    routed = refs(trace["routed_cells"], cells, budget["max_routed_cells"], "routed_cells")
    available = {rid for pool in cells.values() for rid in pool["available"]}
    candidates = {rid for pool in cells.values() for rid in pool["candidates"]}
    all_local = {rid for selected in local_sets.values() for rid in selected}
    route_ids = {rid for cell in routed for rid in local_sets[cell]}
    reader = trace["reader"]
    keys(reader, ("evidence", "output", "abstained", "error"), "reader")
    reader_ids = refs(reader["evidence"], route_ids, budget["max_executor_evidence"], "reader")
    require(type(reader["abstained"]) is bool and (reader["error"] is None or
            (type(reader["error"]) is str and len(reader["error"]) <= 1024)), "invalid_reader_terminal")
    if query["answerable"]:
        correct = reader["error"] is None and not reader["abstained"] and (
            equal_json(reader["output"], query["expected_output"]))
    else:
        correct = reader["error"] is None and reader["abstained"] and reader["output"] is None
    supports = [set(group) for group in query["support_sets"]]
    events, prior = {}, True
    for stage, evidence in zip(STAGES[:-1], (available, candidates, all_local, route_ids, reader_ids)):
        prior = prior and any(support <= (evidence & eligible) for support in supports)
        if stage == "executor_input":
            prior = prior and reader_ids <= eligible
        events[stage] = prior if query["answerable"] else None
    grounded = correct and reader_ids <= eligible and (prior or not query["answerable"])
    events[STAGES[-1]] = grounded if query["answerable"] else None
    return {"id": query["id"], "answerable": query["answerable"], "status": "complete",
            "events": events, "actual_correct": correct, "grounded_correct": grounded,
            "first_failed_event": next((s for s in STAGES if events[s] is False), None),
            "ineligible_references": {name: len(ids - eligible) for name, ids in
                (("candidates", candidates), ("local", all_local), ("routed", route_ids), ("reader", reader_ids))},
            "duplicate_references": {
                "candidates": sum(len(p["candidates"]) - len(set(p["candidates"])) for p in cells.values()),
                "local": sum(len(local[c]) - len(local_sets[c]) for c in cells),
                "routed_cells": len(trace["routed_cells"]) - len(routed),
                "reader": len(reader["evidence"]) - len(reader_ids)}}


def load_json(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input_over_limit")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("nonfinite_json:" + value)

    return raw, json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def audit_historical(directory):
    """Inspect pinned existing V14 receipts, without inventing absent trace fields."""
    from audit_v14 import REF, REPO, RUN, SOURCE, SOURCES

    inputs = []
    for seed in (17, 29, 43):
        name = f"semantic-{seed}.json"
        repo_path, expected_blob = SOURCES[name]
        path = Path(directory) / name
        if not path.is_file():
            path = Path(directory) / repo_path
        raw, data = load_json(path)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(blob == expected_blob, "historical_git_blob_mismatch:" + name)
        require(data.get("schema") == "hepta.semantic.run.v1" and data.get("seed") == seed
                and data.get("github_commit") == SOURCE and data.get("github_run_id") == RUN,
                "historical_run_identity_mismatch")
        inputs.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob,
            "bytes": len(raw), "source_url": f"https://github.com/{REPO}/blob/{REF}/{repo_path}",
            "status": "unavailable", "decomposition": None,
            "observed_fields": {arm: {"holdout_fields": sorted(value["holdout"]),
                "outcome_fields": sorted({k for row in value["holdout"]["outcomes"] for k in row}),
                "outcome_count": len(value["holdout"]["outcomes"]),
                "composition_trace_fields": sorted({k for row in value["compositions"]
                                                    for step in row["trace"] for k in step})}
                for arm, value in data["arms"].items()},
            "missing": ["per_query_normalized_input_and_sha256", "gold_evidence_support_sets", "current_authorized_record_snapshot",
                        "common_per_cell_candidate_pools", "per_cell_local_selections",
                        "routed_cell_set", "executor_evidence_ids"]})
    return {"schema": "hepta.memory.routing-historical-availability.v1", "status": "unavailable",
            "inputs": inputs, "historical_source_commit": SOURCE,
            "pin_registry_sha256": hashlib.sha256(Path(__file__).with_name("audit_v14.py").read_bytes()).hexdigest(),
            "new_model_runs": 0, "new_independent_queries": 0, "production_activation_allowed": False,
            "reason": "Final predicted skill/output and composition execution steps do not bind the actual "
                      "per-query input or identify "
                      "candidate coverage, expert-local scoring or cross-expert routing. No trace was synthesized."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--historical-v14", type=Path)
    parser.add_argument("--output", type=Path, help="new evidence file; existing files are never overwritten")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists; choose a new evidence path")
    try:
        require(bool(args.trace) != bool(args.historical_v14), "choose_trace_or_historical")
        if args.trace:
            sha(args.expected_sha256)
            raw, document = load_json(args.trace)
            require(hashlib.sha256(raw).hexdigest() == args.expected_sha256, "input_file_identity_mismatch")
            require(not args.output or args.output.resolve() != Path(args.trace).resolve(), "output_is_input")
            report = analyze(document)
            report["input_file_sha256"] = args.expected_sha256
        else:
            report = audit_historical(args.historical_v14)
        report["analyzer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["comparator_sha256"] = hashlib.sha256(Path(__file__).with_name("typed_json.py").read_bytes()).hexdigest()
        code = 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        report = {"status": "invalid_input", "reason": str(error)[:512], "production_activation_allowed": False}
        code = 2
    encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output and report.get("reason") != "output_is_input":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as handle:
            handle.write(encoded)
    else:
        print(encoded, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
