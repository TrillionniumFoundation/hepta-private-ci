"""Sanitized post-run scoring derivative.

No sources or gold are loaded by this module. Callers supply reviewed inputs.
Exact-span and complete-support checks do not establish semantic truth or
answer correctness. Included tests use invented inputs only.
"""
from __future__ import annotations

import hashlib
import math

from retrieval import BYTE_CAP, serialize_parent


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_gold_task(task, parents, raw_sources):
    """Validate reviewed task, exact source spans, and complete coverage mapping.

    raw_sources maps (source,path) to pinned bytes. parents maps parent ID to
    parser dataclass or a dictionary with identical provenance fields.
    """
    _require(isinstance(task.get("eligible"), bool), "Missing eligibility decision")
    if not task["eligible"]:
        _require(bool(task.get("exclusion_reason")), "Excluded task needs a reason")
        return {"eligible": False, "budget_feasible": False}
    _require(task.get("review_decision") == "approved", "Gold not independently approved")
    _require(task.get("semantic_review_complete") is True, "Semantic review attestation missing")
    _require(task.get("representation_review_complete") is True, "Representation review missing")
    for key in ("id", "question", "intended_action", "source_anchor_file"):
        _require(isinstance(task.get(key), str) and bool(task[key]), f"Missing {key}")
    _require(task.get("stratum") in ("direct", "reference", "condition"), "Invalid stratum")
    obligations = task.get("semantic_obligations", [])
    _require(bool(obligations), "No semantic obligations")
    obligation_ids = [obligation["id"] for obligation in obligations]
    _require(all(isinstance(i, str) and i for i in obligation_ids), "Empty or invalid obligation ID")
    _require(len(obligation_ids) == len(set(obligation_ids)), "Duplicate obligation IDs")
    _require(all(isinstance(o.get("statement"), str) and o["statement"] for o in obligations),
             "Semantic obligation needs a factual statement including conditions/exceptions")
    alternatives = task.get("sufficient_support_alternatives", [])
    _require(bool(alternatives), "No sufficient support alternatives")
    feasible = False
    for alternative in alternatives:
        ids = alternative["parent_ids"]
        _require(bool(ids) and len(ids) == len(set(ids)), "Invalid sufficient parent set")
        _require(all(i in parents for i in ids), "Gold references an absent parent")
        coverage = alternative["coverage"]
        _require({c["obligation_id"] for c in coverage} == set(obligation_ids), "Incomplete obligation coverage")
        covered_parents = set()
        for evidence in coverage:
            i = evidence["parent_id"]
            _require(i in ids, "Evidence parent absent from sufficient set")
            covered_parents.add(i)
            parent = parents[i]
            get = parent.get if isinstance(parent, dict) else lambda key: getattr(parent, key)
            key = (evidence["source"], evidence["path"])
            _require(key in raw_sources, "Missing raw source")
            raw = raw_sources[key]
            _require(hashlib.sha256(raw).hexdigest() == evidence["file_sha256"], "Evidence source hash mismatch")
            _require(get("sha256") == evidence["file_sha256"], "Parent source hash mismatch")
            _require((get("source"), get("path")) == key, "Wrong parent source")
            lines = raw.decode("utf-8", "strict").splitlines(keepends=True)
            start, end = evidence["start_line"], evidence["end_line"]
            _require(isinstance(start, int) and not isinstance(start, bool) and
                     isinstance(end, int) and not isinstance(end, bool), "Noninteger line span")
            _require(1 <= get("start_line") <= start <= end <= get("end_line") <= len(lines),
                     "Evidence outside parent span")
            _require("".join(lines[get("start_line") - 1:get("end_line")]) == get("text"),
                     "Canonical parent is not its exact contiguous raw span")
            exact_text = "".join(lines[start - 1:end])
            _require(bool(exact_text) and evidence["exact_text"] == exact_text, "Evidence text mismatch")
            _require(exact_text in get("text"), "Evidence not visibly preserved in parent")
        _require(covered_parents == set(ids), "Unexplained parent in sufficient support set")
        size = 0
        for i in ids:
            p = parents[i]
            get = p.get if isinstance(p, dict) else lambda key: getattr(p, key)
            size += len(serialize_parent({k: get(k) for k in ("citation", "title", "text")}).encode("utf-8"))
        feasible |= len(ids) <= 4 and size <= BYTE_CAP
    return {"eligible": True, "budget_feasible": feasible}


def verify_emitted_pack(pack, docs, arm):
    expected_cap = 8 if arm == "bm25_top8" else 4
    ids = pack["ids"]
    _require(len(ids) == len(set(ids)) and len(ids) <= expected_cap, "Invalid pack parent count")
    _require(all(i in docs for i in ids), "Unknown emitted parent")
    payloads = [serialize_parent(docs[i]) for i in ids]
    _require(pack["payloads"] == payloads, "Pack altered or omitted canonical text/citation")
    byte_count = sum(len(payload.encode("utf-8")) for payload in payloads)
    _require(pack["bytes"] == byte_count and byte_count <= BYTE_CAP, "Invalid serialized byte count")
    _require(pack["parent_cap"] == expected_cap and pack["byte_cap"] == BYTE_CAP, "Wrong frozen budget")
    return set(ids)


def score_tasks(tasks, arm_results, docs, parents, raw_sources):
    """No ID-only shortcut: validate all reviewed spans before matching sets."""
    _require(set(docs) == set(parents), "Adapter and canonical parent inventories differ")
    for i, parent in parents.items():
        get = parent.get if isinstance(parent, dict) else lambda key: getattr(parent, key)
        _require(all(docs[i][key] == get(key) for key in ("source", "title", "text", "citation")),
                 "Adapter text/citation differs from canonical parent")
    result = {"task_results": [], "eligible": 0, "excluded": [], "budget_infeasible": []}
    seen = set()
    for task in tasks:
        _require(task["id"] not in seen, "Duplicate task ID")
        seen.add(task["id"])
        validity = verify_gold_task(task, parents, raw_sources)
        if not validity["eligible"]:
            result["excluded"].append({"id": task["id"], "reason": task["exclusion_reason"]})
            continue
        result["eligible"] += 1
        if not validity["budget_feasible"]:
            result["budget_infeasible"].append(task["id"])
        success = {}
        for arm, outputs in arm_results.items():
            pack = outputs.get(task["id"])
            if pack is None:
                success[arm] = False
                continue
            emitted = verify_emitted_pack(pack, docs, arm)
            success[arm] = any(set(alt["parent_ids"]).issubset(emitted)
                               for alt in task["sufficient_support_alternatives"])
        result["task_results"].append({"id": task["id"], "stratum": task["stratum"], "success": success})
    return result


def screen(scored, runtime, protocol):
    """Use the hash-frozen protocol's structured decision parameters, not fit data."""
    rules = protocol["scoring"]["machine"]
    controls, candidate = rules["controls"], rules["candidate"]
    tie_order = rules["control_tie_order"]
    _require(set(tie_order) == set(controls) and len(tie_order) == len(controls), "Bad control tie order")
    arms = controls + [candidate]
    tasks = scored["task_results"]
    valid = len(tasks)
    planned = rules["planned_tasks"]
    _require(valid + len(scored["excluded"]) == planned, "All planned tasks, including exclusions, must be represented")
    counts = {arm: sum(t["success"].get(arm, False) for t in tasks) for arm in arms}
    direct = [t for t in tasks if t["stratum"] == "direct"]
    direct_losses = [t["id"] for t in direct if not t["success"].get(candidate, False)
                     and any(t["success"].get(arm, False) for arm in controls)]
    problems = []
    if valid < rules["minimum_valid"]:
        problems.append("too_few_valid_tasks")
    if len(direct) < rules["minimum_direct"]:
        problems.append("too_few_direct_tasks")
    for arm in arms:
        cost = runtime.get(arm, {})
        seconds = cost.get("cold_end_to_end_seconds")
        if cost.get("status") != "SUCCESS" or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            problems.append("primary_execution_failure:" + arm)
    strongest = None
    ratio = None
    if not any(p.startswith("primary_execution_failure") for p in problems):
        strongest = min(controls, key=lambda arm: (-counts[arm], runtime[arm]["cold_end_to_end_seconds"], tie_order.index(arm)))
        ratio = runtime[candidate]["cold_end_to_end_seconds"] / runtime[strongest]["cold_end_to_end_seconds"]
    gains = {arm: counts[candidate] - counts[arm] for arm in controls}
    failures = []
    if any(gain < rules["minimum_gain_each"] for gain in gains.values()):
        failures.append("insufficient_gain_over_at_least_one_control")
    if len(direct_losses) > rules["maximum_direct_losses"]:
        failures.append("direct_task_loss")
    if ratio is not None and ratio > rules["maximum_cold_time_ratio"]:
        failures.append("cold_runtime_ratio_exceeded")
    return {"screen": "INCONCLUSIVE" if problems else ("REJECT" if failures else "PASS_SCREEN"),
            "scope": "single_source_development_pilot_not_confirmation",
            "planned": planned, "eligible": valid, "excluded": scored["excluded"],
            "budget_infeasible": scored["budget_infeasible"], "complete_counts": counts,
            "eligible_rates": {arm: counts[arm] / valid if valid else None for arm in arms},
            "planned_denominator_rates": {arm: counts[arm] / planned for arm in arms},
            "direct_count": len(direct), "direct_loss_ids": direct_losses,
            "gains_over_each_control": gains, "strongest_cheap_control": strongest,
            "candidate_cold_time_ratio": ratio, "inconclusive_reasons": problems,
            "rejection_reasons": failures, "publication_or_deployment_authorized": False}
