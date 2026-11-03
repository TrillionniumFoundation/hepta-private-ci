"""A-I memory study: source-first, fail-closed independent result qualification.

This is an audit of external ORIGINAL model/retriever/Reader runs, not a model
runner, proof of model execution, proof of source authority, or signer.
Predictions are sealed before separately provided gold/judgments are opened.
No result from this module grants production authority.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

ARMS = tuple("ABCDEFGHI")
CONTROLS = ("E_FROZEN", "F_SWAPPED", "G_FIXED", "H_PERMUTED", "I_STATIC")
WINDOWS = ("future_a", "future_b")
PROFILE_COUNTS = ("parameter_bytes", "optimizer_steps", "training_examples",
                  "router_steps", "router_parameter_bytes", "router_training_examples",
                  "graph_edges")
COST_FIELDS = ("context_bytes", "output_tokens", "wall_ms", "peak_rss_bytes",
               "cpu_ms", "gpu_ms", "storage_bytes", "encoder_forwards", "head_forwards")
HEX = set("0123456789abcdef")
FROZEN_PROTOCOL_SHA256 = "e26d94f92bd42d1e5fcff58454ef55a33fa3394aad2a914d79faea191aa70cf5"


class QualificationError(ValueError):
    pass


def fail(message):
    raise QualificationError(message)


def require(ok, message):
    if not ok:
        fail(message)


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return type(value) is str and len(value) == 64 and all(c in HEX for c in value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def number(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "naive timestamp")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as error:
        fail(f"invalid UTC timestamp: {error}")


def verify_protocol(protocol):
    require(protocol.get("schema_version") == 1 and
            protocol.get("protocol_id") == "hepta-memory-A-I-prospective-v1", "protocol identity")
    require(tuple(protocol["arms"]) == ARMS and tuple(protocol["controls"]) == CONTROLS,
            "complete ordered A-I and negative control census")
    require(tuple(protocol["evaluation_windows"]) == WINDOWS, "future windows")
    require(protocol.get("production_activation_allowed") is False, "unsafe activation policy")
    require(integer(protocol["min_independent_families_per_window"], 200), "family floor")
    require(integer(protocol["bootstrap_replicates"], 1000) and
            integer(protocol["family_bootstrap_seed"]), "bootstrap configuration")
    require(0 < protocol["simultaneous_one_sided_alpha"] <= 0.05,
            "multiple comparisons confidence")
    require(integer(protocol["top_k"], 1) and protocol["top_k"] <= 16 and
            integer(protocol["max_context_bytes"], 1) and
            integer(protocol["max_output_tokens"], 1), "context budgets")
    pairs = [(r["candidate"], r["baseline"], r["mechanism"]) for r in protocol["comparisons"]]
    require(len(pairs) == len(set(pairs)) >= 11, "duplicate or missing planned contrasts")
    required = {("D", "B"), ("E", "E_FROZEN"), ("F", "E"),
                ("F", "F_SWAPPED"), ("G", "G_FIXED"), ("H", "G"),
                ("H", "H_PERMUTED"), ("I", "H"), ("I", "I_STATIC"),
                ("I", "B"), ("I", "C")}
    require({(a, b) for a, b, _ in pairs} == required, "causal contrasts altered")
    for entry in protocol["comparisons"]:
        require(number(entry["min_gain"]) and entry["min_gain"] <= 0.1, "invalid superiority threshold")
    for name in ("max_wall_ms", "max_p95_latency_ratio_vs_B", "max_peak_rss_ratio_vs_B",
                 "min_answerable_coverage", "max_adversarial_false_acceptance",
                 "min_citation_supported", "max_model_trainable_parameter_bytes",
                 "max_model_optimizer_steps", "max_model_training_examples"):
        require(number(protocol[name]), f"invalid protocol bound {name}")
    require(sha(canonical(protocol)) == FROZEN_PROTOCOL_SHA256,
            "frozen protocol digest changed: new independent preregistration required")
    return protocol


def verify_plan(plan, protocol, gold):
    require(plan.get("schema_version") == 1 and
            plan.get("protocol_sha256") == sha(canonical(protocol)), "plan protocol pin")
    require(plan.get("gold_sha256") == sha(canonical(gold)), "heldout gold commitment")
    for field in ("source_dataset_sha256", "reader_sha256", "tokenizer_sha256",
                  "prompt_sha256", "decoding_sha256"):
        require(digest(plan.get(field)), f"plan {field} pin")
    freeze = utc(plan["frozen_utc"])
    groups = {}
    for split in ("train", "calibration") + WINDOWS:
        names = plan["families"][split]
        require(type(names) is list and len(names) == len(set(names)) and
                all(type(g) is str and g for g in names), f"invalid families in {split}")
        for name in names:
            require(name not in groups, "source family leaks across split/window")
            groups[name] = split
    require(plan["families"]["train"], "no training families")
    for window in WINDOWS:
        require(utc(plan["window_open_utc"][window]) > freeze, "future window not later than freeze")
    source_inventory = plan["source_inventory"]
    require(set(source_inventory) == set(groups), "source inventory family census")
    for group, ids in source_inventory.items():
        require(type(ids) is list and len(ids) == len(set(ids)) and
                all(type(x) is str and x for x in ids), f"invalid source inventory {group}")
    queries = {}
    for q in plan["queries"]:
        qid, family, window = q["query_id"], q["family"], q["window"]
        require(type(qid) is str and qid and qid not in queries, "duplicate/invalid question")
        require(window in WINDOWS and groups.get(family) == window, "query split mismatch")
        require(digest(q.get("source_cut_sha256")) and digest(q.get("forget_frontier_sha256")),
                "unbound source cut or forget frontier")
        queries[qid] = q
    require(queries, "no heldout queries")
    require(type(gold) is dict and set(gold) == set(queries),
            "incomplete withheld gold query census")
    for qid, label in gold.items():
        require(type(label) is dict and set(label) == {"answerable", "support_ids"} and
                type(label["answerable"]) is bool, "malformed withheld gold")
        support = label["support_ids"]
        require(type(support) is list and len(support) == len(set(support)) and
                all(type(sid) is str and sid in source_inventory[queries[qid]["family"]]
                    for sid in support), "invalid original support source ID")
        require(bool(support) == label["answerable"],
                "answerable question lacks bounded gold evidence (or unanswerable carries it)")
    for window in WINDOWS:
        require({q["family"] for q in queries.values() if q["window"] == window} ==
                set(plan["families"][window]), "window contains families with no questions")
    return queries, groups


def verify_profiles(profiles, protocol, groups):
    required = set(ARMS + CONTROLS)
    require(type(profiles) is dict and set(profiles) == required, "incomplete model profile census")
    for arm, profile in profiles.items():
        require(digest(profile.get("artifact_sha256")), f"missing model artifact {arm}")
        for key in PROFILE_COUNTS:
            require(integer(profile.get(key)), f"invalid model resources {arm}/{key}")
        require(profile["parameter_bytes"] <= protocol["max_model_trainable_parameter_bytes"] and
                profile["optimizer_steps"] <= protocol["max_model_optimizer_steps"] and
                profile["training_examples"] <= protocol["max_model_training_examples"],
                f"training budget exceeded {arm}")
        require(digest(profile.get("training_source_closure_sha256")),
                f"unbound training ancestor closure {arm}")
        training = profile["training_families"]
        require(type(training) is list and len(training) == len(set(training)) and
                all(groups.get(g) == "train" for g in training), f"training source leakage {arm}")
        if arm in ("E", "F", "G", "H", "I", "I_STATIC", "F_SWAPPED", "G_FIXED", "H_PERMUTED"):
            require(digest(profile.get("encoder_sha256")) and profile["optimizer_steps"] > 0 and
                    profile["training_examples"] > 0 and profile["parameter_bytes"] > 0,
                    f"no real trained model declared for {arm}")
    require(profiles["E_FROZEN"]["optimizer_steps"] == 0 and
            profiles["E_FROZEN"]["training_examples"] == 0, "untrained control actually trained")
    anchor = profiles["F"]["encoder_sha256"]
    for arm in ("E", "E_FROZEN", "G", "H", "I", "F_SWAPPED", "G_FIXED", "H_PERMUTED", "I_STATIC"):
        require(profiles[arm]["encoder_sha256"] == anchor, "shared Encoder identity mismatch")
    for a, b in (("E", "F"), ("F", "F_SWAPPED"), ("F", "G"),
                 ("G", "G_FIXED"), ("G", "H"),
                 ("H", "H_PERMUTED"), ("I", "I_STATIC")):
        # Route/graph/evolution have separate resource metering; controls must
        # hold the SAME underlying trainable Head capacity and training work.
        for field in ("parameter_bytes", "optimizer_steps", "training_examples"):
            require(profiles[a][field] == profiles[b][field],
                    f"unmatched Head training budget {a} vs {b}: {field}")
    for a, b in (("E", "F"), ("F", "F_SWAPPED"), ("F", "G"),
                 ("G", "G_FIXED"), ("H", "H_PERMUTED"), ("I", "I_STATIC")):
        require(profiles[a]["training_families"] == profiles[b]["training_families"] and
                profiles[a]["training_source_closure_sha256"] ==
                profiles[b]["training_source_closure_sha256"],
                f"unmatched training ancestor inventory {a} vs {b}")
    for a, b in (("G", "G_FIXED"), ("H", "H_PERMUTED"), ("I", "I_STATIC")):
        for field in ("router_steps", "router_parameter_bytes", "router_training_examples"):
            require(profiles[a][field] == profiles[b][field],
                    f"unmatched router budget {a} vs {b}: {field}")
    for a, b in (("H", "H_PERMUTED"), ("I", "I_STATIC")):
        require(profiles[a]["graph_edges"] == profiles[b]["graph_edges"],
                f"unmatched graph budget {a} vs {b}")


def verify_predictions(predictions, plan, protocol, queries, groups):
    require(predictions.get("schema_version") == 1 and
            predictions.get("plan_sha256") == sha(canonical(plan)), "prediction plan pin")
    verify_profiles(predictions["profiles"], protocol, groups)
    expected = {(qid, arm) for qid in queries for arm in ARMS + CONTROLS}
    rows = {}
    empty_sha = sha(b"")
    for row in predictions["rows"]:
        key = (row["query_id"], row["arm"])
        require(key in expected and key not in rows, "duplicate, unknown or unregistered result")
        q = queries[key[0]]
        for field in ("source_cut_sha256", "forget_frontier_sha256"):
            require(row.get(field) == q[field], f"stale source/forget frontier: {key}")
        for field in ("reader_sha256", "tokenizer_sha256", "prompt_sha256", "decoding_sha256"):
            require(row.get(field) == plan[field], f"Reader or decoding drift: {key}")
        require(row.get("status") in ("answered", "abstained", "failed", "unavailable"),
                f"invalid execution status: {key}")
        require(digest(row.get("answer_sha256")) and digest(row.get("context_sha256")),
                f"answer/context not sealed: {key}")
        if row["status"] != "answered":
            require(row["answer_sha256"] == empty_sha, f"invented unavailable answer: {key}")
        selected = row["selected_source_ids"]
        require(type(selected) is list and len(selected) == len(set(selected)) and
                len(selected) <= protocol["top_k"] and
                all(type(s) is str and s in plan["source_inventory"][q["family"]] for s in selected),
                f"missing, duplicate or foreign source: {key}")
        costs = row["costs"]
        require(type(costs) is dict and set(costs) == set(COST_FIELDS), f"resource fields missing: {key}")
        require(all(number(costs[name]) for name in COST_FIELDS), f"invalid resources: {key}")
        for name in ("context_bytes", "output_tokens", "encoder_forwards", "head_forwards"):
            require(integer(costs[name]), f"noninteger counter: {key}/{name}")
        require(costs["context_bytes"] <= protocol["max_context_bytes"] and
                costs["output_tokens"] <= protocol["max_output_tokens"] and
                costs["wall_ms"] <= protocol["max_wall_ms"], f"runtime budget exceeded: {key}")
        if key[1] in ("E", "F", "G", "H", "I", "I_STATIC", "F_SWAPPED", "G_FIXED", "H_PERMUTED"):
            require(costs["head_forwards"] <= 1 and costs["encoder_forwards"] <= 1,
                    f"dense or duplicate shared-Encoder/Head execution: {key}")
        rows[key] = row
    require(set(rows) == expected, f"incomplete nine-arm/control census: missing {len(expected - set(rows))}")
    return rows


def verify_judgments(judgments, predictions, queries, gold, rows):
    require(judgments.get("schema_version") == 1 and
            judgments.get("predictions_sha256") == sha(canonical(predictions)),
            "independent judgment predates or differs from original sealed predictions")
    require(type(judgments.get("assessor_id")) is str and judgments["assessor_id"].strip() and
            digest(judgments.get("assessor_artifact_sha256")), "missing independent assessor reference")
    found = set()
    result = {}
    for item in judgments["rows"]:
        key = (item["query_id"], item["arm"])
        require(key in rows and key not in found, "invented/duplicate adjudication row")
        found.add(key)
        require(item.get("answer_sha256") == rows[key]["answer_sha256"], "judgment answer not source-bound")
        require(all(type(item.get(field)) is bool for field in
                    ("task_success", "citation_supported", "support_complete")),
                "malformed task/adjudication outcome")
        if rows[key]["status"] in ("failed", "unavailable"):
            require(not item["task_success"], "failed execution scored successful")
        answerable = gold[key[0]]["answerable"]
        if not answerable:
            require(item["task_success"] == (rows[key]["status"] == "abstained"),
                    "adversarial answerability scorer disagreement")
        if answerable and rows[key]["status"] != "answered":
            require(not item["task_success"], "answerable question without answer scored successful")
        expected_support = (answerable and rows[key]["status"] == "answered" and
                            set(gold[key[0]]["support_ids"]) <=
                            set(rows[key]["selected_source_ids"]))
        require(item["support_complete"] == expected_support,
                "source evidence completeness disagrees with independently committed gold")
        if rows[key]["status"] != "answered":
            require(not item["citation_supported"], "unavailable citation fabricated")
        if item["citation_supported"]:
            require(bool(rows[key]["selected_source_ids"]), "citation support without delivered source")
        result[key] = item
    require(set(result) == set(rows), "missing independently judged arm outcomes")
    return result


def family_means(rows, queries, window, arm, field):
    by_family = defaultdict(list)
    for (qid, name), value in rows.items():
        if name == arm and queries[qid]["window"] == window:
            by_family[queries[qid]["family"]].append(float(value[field]))
    return {k: statistics.fmean(v) for k, v in by_family.items()}


def lower_bound(x, y, *, alpha, replicates, seed):
    require(set(x) == set(y) and bool(x), "paired independent family set mismatch")
    families = sorted(x)
    deltas = [x[f] - y[f] for f in families]
    rng = random.Random(seed)
    sample = [statistics.fmean(deltas[rng.randrange(len(deltas))] for _ in deltas)
              for _ in range(replicates)]
    sample.sort()
    # One-sided percentile family bootstrap, Bonferroni over all contrasts/windows.
    return sample[max(0, math.ceil(alpha * replicates) - 1)]


def ratio(a, b):
    return a / b if b else (1.0 if not a else math.inf)


def p95(numbers):
    ordered = sorted(numbers)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def qualify(protocol, plan, gold, predictions, judgments):
    verify_protocol(protocol)
    queries, groups = verify_plan(plan, protocol, gold)
    rows = verify_predictions(predictions, plan, protocol, queries, groups)
    scores = verify_judgments(judgments, predictions, queries, gold, rows)
    alpha = protocol["simultaneous_one_sided_alpha"] / (
        len(protocol["comparisons"]) * len(WINDOWS))
    windows = {}
    contrasts = []
    blockers = []
    for window in WINDOWS:
        fams = plan["families"][window]
        if len(fams) < protocol["min_independent_families_per_window"]:
            blockers.append(f"{window}: insufficient independent families ({len(fams)})")
        subset_ids = [qid for qid, q in queries.items() if q["window"] == window]
        answerable = [qid for qid in subset_ids if gold[qid]["answerable"]]
        adversarial = [qid for qid in subset_ids if not gold[qid]["answerable"]]
        arm_metrics = {}
        for arm in ARMS + CONTROLS:
            scored = [scores[qid, arm] for qid in subset_ids]
            answered = [rows[qid, arm] for qid in subset_ids]
            arm_metrics[arm] = {
                "task_success": statistics.fmean(int(v["task_success"]) for v in scored),
                "family_macro_task_success": statistics.fmean(
                    family_means(scores, queries, window, arm, "task_success").values()),
                "answerable_coverage": (sum(rows[qid, arm]["status"] == "answered" for qid in answerable) / len(answerable)
                                         if answerable else None),
                "adversarial_false_acceptance": (sum(rows[qid, arm]["status"] == "answered" for qid in adversarial) / len(adversarial)
                                                  if adversarial else None),
                "citation_supported": (sum(scores[qid, arm]["citation_supported"] for qid in answerable) / len(answerable)
                                       if answerable else None),
                "complete_support": (sum(scores[qid, arm]["support_complete"] for qid in answerable) / len(answerable)
                                     if answerable else None),
                "p95_wall_ms": p95([v["costs"]["wall_ms"] for v in answered]),
                "peak_rss_bytes": max(v["costs"]["peak_rss_bytes"] for v in answered),
                "total_storage_bytes": sum(v["costs"]["storage_bytes"] for v in answered),
            }
        windows[window] = {"independent_families": len(fams), "questions": len(subset_ids),
                           "answerable": len(answerable), "adversarial": len(adversarial),
                           "arms": arm_metrics}
        for index, contrast in enumerate(protocol["comparisons"]):
            a, b = contrast["candidate"], contrast["baseline"]
            left = family_means(scores, queries, window, a, "task_success")
            right = family_means(scores, queries, window, b, "task_success")
            lb = lower_bound(left, right, alpha=alpha,
                             replicates=protocol["bootstrap_replicates"],
                             seed=protocol["family_bootstrap_seed"] + index + 1000 * WINDOWS.index(window))
            delta = statistics.fmean(left[g] - right[g] for g in left)
            passed = lb > contrast["min_gain"]
            contrasts.append({"window": window, "mechanism": contrast["mechanism"],
                              "candidate": a, "baseline": b,
                              "family_macro_delta": delta,
                              "simultaneous_one_sided_lower": lb,
                              "preregistered_min_gain": contrast["min_gain"],
                              "passed": passed})
            if not passed:
                blockers.append(f"{window}: {contrast['mechanism']} gain gate failed")
        final = arm_metrics["I"]
        baseline = arm_metrics["B"]
        coverage = final["answerable_coverage"]
        false_accept = final["adversarial_false_acceptance"]
        if coverage is None or coverage < protocol["min_answerable_coverage"]:
            blockers.append(f"{window}: answerable coverage inadequate/unmeasured")
        if false_accept is None or false_accept > protocol["max_adversarial_false_acceptance"]:
            blockers.append(f"{window}: adversarial false acceptance inadequate/unmeasured")
        if (final["citation_supported"] is None or
                final["citation_supported"] < protocol["min_citation_supported"]):
            blockers.append(f"{window}: independently supported citation rate inadequate/unmeasured")
        if ratio(final["p95_wall_ms"], baseline["p95_wall_ms"]) > protocol["max_p95_latency_ratio_vs_B"]:
            blockers.append(f"{window}: latency budget regression")
        if ratio(final["peak_rss_bytes"], baseline["peak_rss_bytes"]) > protocol["max_peak_rss_ratio_vs_B"]:
            blockers.append(f"{window}: memory budget regression")
    # Source/artifact signatures, unseen live calendar status, trained model/Reader
    # inference and full TCO must be independently established by original owners.
    # A caller-provided SHA, id or time string does not attest those facts.
    descriptive_gates_passed = not blockers
    blockers.extend([
        "external_source_authority_and_live_forget_recheck_not_authenticated_here",
        "original_model_training_and_reader_execution_not_independently_attested_here",
        "assessor_independence_and_citation_entailment_not_cryptographically_verified_here",
        "exact_head_CI_architecture_security_and_multihost_deletion_unlearning_not_verified_here",
    ])
    return {
        "protocol_sha256": sha(canonical(protocol)), "plan_sha256": sha(canonical(plan)),
        "predictions_sha256": sha(canonical(predictions)),
        "judgments_sha256": sha(canonical(judgments)),
        "arms": list(ARMS), "controls": list(CONTROLS), "windows": windows,
        "comparisons": contrasts, "blockers": blockers,
        "descriptive_gates_passed": descriptive_gates_passed,
        "scientific_superiority_qualified": False,
        "production_activation_allowed": False,
        "status": "SHADOW_ONLY / DENY_ALL / HOLD_NO_GO",
    }


def read_json(path):
    def unique_pairs(pairs):
        found = {}
        for key, value in pairs:
            require(key not in found, f"duplicate JSON member: {key}")
            found[key] = value
        return found

    def reject_constant(value):
        fail(f"non-JSON numeric constant: {value}")

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--judgments", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    inputs = [read_json(path) for path in
              (args.protocol, args.plan, args.gold, args.predictions, args.judgments)]
    output = qualify(*inputs)
    dest = Path(args.output)
    with dest.open("xb") as fp:
        fp.write(canonical(output) + b"\n")
    print(json.dumps({"status": output["status"], "blockers": output["blockers"]}, indent=2))
    return 2 if output["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
