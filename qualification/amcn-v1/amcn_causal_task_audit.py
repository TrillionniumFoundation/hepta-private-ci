"""Fail-closed, task-level paired AMCN audit for three distinct causal questions.

Reads externally sealed ORIGINAL Reader answers and separate judgments. It never
loads a model, fabricates Reader calls, opens training labels, publishes a Cell,
or grants qualification. Test fixtures are mechanism tests, not model results.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite, log, sqrt
import os
import re
from pathlib import Path

PROFILE = "hepta.amcn.causal-three-axis.task.v1"
ARMS = (
    "strong_hybrid_rag", "frozen_shared", "learned_shared", "learned_typed",
    "typed_swapped", "typed_fixed_graph", "typed_learned_graph",
    "typed_graph_lesion", "unsplit_equal_graph",
)
CONTRASTS = {
    "parameter_vs_frozen": ("learned_shared", "frozen_shared"),
    "type_vs_unspecialized": ("learned_typed", "learned_shared"),
    "type_swap_control": ("learned_typed", "typed_swapped"),
    "fixed_graph_vs_local": ("typed_fixed_graph", "learned_typed"),
    "learned_graph_vs_fixed": ("typed_learned_graph", "typed_fixed_graph"),
    "graph_lesion": ("typed_learned_graph", "typed_graph_lesion"),
    "typed_vs_equal_unsplit_graph": ("typed_learned_graph", "unsplit_equal_graph"),
    "graph_vs_strong_rag": ("typed_learned_graph", "strong_hybrid_rag"),
}
HELDOUT = {"select", "future_a", "future_b", "retention"}
MAX_CASES = 8192
MAX_SOURCES = 512
MAX_SOURCE_BYTES = 8192
MAX_FILE_BYTES = 32 * 1024 * 1024
# Original LoCoMo pilot used (episodic, semantic); the original 1968
# matched physical training fixture also uses (procedural, semantic).
# Actual two-type identity must come from the frozen Head-bank inventory.
TYPES = ("episodic", "semantic")
ALLOWED_TYPES = frozenset({"sensory", "episodic", "semantic", "procedural",
                           "predictive", "salience", "meta_memory"})


class Refused(ValueError):
    """Experiment violates its frozen shape or source/answer identity."""


def require(ok, message):
    if not ok:
        raise Refused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def bytes_sha(value):
    return sha256(value).hexdigest()


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value)


def exact(record, names, context):
    require(isinstance(record, dict) and set(record) == set(names), context)


def require_string(value, description):
    require(isinstance(value, str) and bool(value.strip())
            and len(value.encode("utf-8")) <= MAX_SOURCE_BYTES, description)



# Match every bracketed citation-like span, including malformed tokens.
# Deliberately surface invalid numbers instead of silently deleting evidence.
CITATION_MARKER = re.compile(r"\[[Ee]([^\]\r\n]*)\]")


def original_emitted_sources(answer, source_ids):
    """Reconstruct citations from unchanged answer bytes, not producer metadata.

    This verifies citation *structure*, never semantic entailment or truth.
    Keep out-of-range labels visible as unmatched references.
    """
    if answer is None:
        return []
    sources = []
    for match in CITATION_MARKER.finditer(answer):
        digits = match.group(1)
        if (match.group().startswith("[E")
                and re.fullmatch(r"[1-9][0-9]{0,3}", digits)):
            number = int(digits)
            if number <= len(source_ids):
                sources.append(source_ids[number - 1])
                continue
        sources.append("UNDELIVERED:" + match.group())
    return sources


def request_digest(plan, case, arm, source_by_id):
    """Bind exact visible request evidence; a digest alone proves no dispatch."""
    choice = case["arm_plans"][arm]
    return digest({
        "profile": PROFILE, "question_id": case["question_id"],
        "question": case["question"], "scope": case["scope"],
        "generation": case["generation"], "reader": plan["reader_sha256"],
        "tokenizer": plan["tokenizer_sha256"],
        "prompt": plan["prompt_sha256"],
        "input_limit": plan["max_input_tokens"],
        "output_limit": plan["max_output_tokens"],
        "arm": arm, "selected_sources": [source_by_id[s]
                                            for s in choice["source_ids"]],
        "head": choice["head_sha256"], "graph": choice["graph_sha256"],
    })


def validate_plan(plan):
    exact(plan, {"profile", "reader_sha256", "tokenizer_sha256", "prompt_sha256",
                 "encoder_receipt_sha256", "max_input_tokens", "max_output_tokens",
                 "capacity", "cases", "lineage_alias_edges", "future_calendar_verified",
                 "production_accepted"}, "unexpected experiment plan fields")
    require(plan["profile"] == PROFILE and plan["production_accepted"] is False
            and plan["future_calendar_verified"] is False,
            "this research profile cannot pre-claim authority or future time")
    require(all(is_sha(plan[k]) for k in ("reader_sha256", "tokenizer_sha256",
                                           "prompt_sha256", "encoder_receipt_sha256")),
            "missing bound Reader/Encoder identity")
    require(type(plan["max_input_tokens"]) is int
            and 16 <= plan["max_input_tokens"] <= 32768
            and type(plan["max_output_tokens"]) is int
            and 1 <= plan["max_output_tokens"] <= 2048,
            "invalid equal Reader budget")
    capacity = plan["capacity"]
    exact(capacity, {"shared", "typed"}, "missing equal-capacity control")
    typed_keys = capacity["typed"].get("head_sha256_by_type") if isinstance(
        capacity["typed"], dict) else None
    require(isinstance(typed_keys, dict) and len(typed_keys) == 2
            and set(typed_keys) <= ALLOWED_TYPES,
            "Head bank must precommit two permitted original HNMF types")
    committed_types = set(typed_keys)
    for item in capacity.values():
        exact(item, {"total_trainable_parameters", "optimizer_steps",
                     "minibatch_examples", "artifact_sha256", "training_receipt_sha256",
                     "head_sha256_by_type", "trainable_head_count",
                     "active_heads_per_query"},
              "incomplete physical training meter")
        require(all(type(item[k]) is int and item[k] > 0 for k in (
            "total_trainable_parameters", "optimizer_steps", "minibatch_examples")),
            "unverified parameter/training work meter")
        require(is_sha(item["artifact_sha256"])
                and is_sha(item["training_receipt_sha256"]), "missing Head origin")
        # Two real, distinct trainable Head tensors per arm are mandatory.
        # The unspecialized control trains each bank member on pooled TRAIN
        # families rather than gaining a free additional parameter or call.
        bank = item["head_sha256_by_type"]
        require(isinstance(bank, dict) and set(bank) == committed_types
                and all(is_sha(v) for v in bank.values())
                and len(set(bank.values())) == len(TYPES)
                and item["trainable_head_count"] == 2
                and type(item["trainable_head_count"]) is int
                and item["active_heads_per_query"] == 1
                and type(item["active_heads_per_query"]) is int,
                "two independent physical Heads and one read per query required")
    require(all(capacity["shared"][k] == capacity["typed"][k] for k in (
        "total_trainable_parameters", "optimizer_steps", "minibatch_examples")),
        "typed Head wins cannot buy additional training/capacity")
    cases = plan["cases"]
    require(isinstance(cases, list) and 1 <= len(cases) <= MAX_CASES,
            "invalid question census")
    seen, roots, types = set(), set(), set()
    expected = {}
    for case in cases:
        exact(case, {"question_id", "family", "source_root", "memory_type",
                     "split", "scope", "generation", "question", "sources",
                     "source_frontier_sha256", "arm_plans"},
              "a question must be complete before gold is opened")
        for k in ("question_id", "family", "source_root", "scope",
                  "generation", "question"):
            require_string(case[k], "empty/oversize case identity")
        require(case["question_id"] not in seen and case["split"] in HELDOUT,
                "duplicate question or TRAIN truth in Reader trial")
        seen.add(case["question_id"])
        require(case["memory_type"] in committed_types,
                "types are predeclared HNMF kinds, not inferred from gold")
        types.add(case["memory_type"])
        roots.add(case["source_root"])
        source_by_id = {}
        require(isinstance(case["sources"], list)
                and 1 <= len(case["sources"]) <= MAX_SOURCES,
                "unbounded original source candidates")
        for source in case["sources"]:
            exact(source, {"source_id", "revision", "content_sha256", "text"},
                  "source identifier/revision/content required")
            require_string(source["source_id"], "missing source ID")
            require_string(source["text"], "source text missing or oversized")
            require(type(source["revision"]) is int and source["revision"] > 0
                    and source["source_id"] not in source_by_id
                    and source["content_sha256"] == bytes_sha(source["text"].encode("utf-8")),
                    "duplicate or fabricated source content SHA")
            source_by_id[source["source_id"]] = source
        require(case["source_frontier_sha256"] == digest(sorted(
            case["sources"], key=lambda s: s["source_id"])),
            "source frontier drift")
        choices = case["arm_plans"]
        require(isinstance(choices, dict) and set(choices) == set(ARMS),
                "missing/extra case-level comparison arm")
        for arm, choice in choices.items():
            exact(choice, {"source_ids", "head_sha256", "graph_sha256",
                           "route_type", "planned_request_sha256"},
                  "incomplete label-blind arm recipe")
            selected = choice["source_ids"]
            require(isinstance(selected, list) and len(selected) <= 16
                    and len(selected) == len(set(selected))
                    and all(s in source_by_id for s in selected),
                    "source not in original eligible snapshot or Top-16 exceeded")
            if arm == "strong_hybrid_rag":
                require(choice["head_sha256"] is None, "RAG must not borrow learned Head")
            else:
                require(is_sha(choice["head_sha256"]), "unidentified model Head")
            is_graph = arm in ("typed_fixed_graph", "typed_learned_graph",
                               "typed_graph_lesion", "unsplit_equal_graph")
            require((is_sha(choice["graph_sha256"]) if is_graph
                     else choice["graph_sha256"] is None),
                    "graph/non-graph intervention not bound")
            if arm == "typed_swapped":
                require(choice["route_type"] != case["memory_type"]
                        and choice["route_type"] in committed_types,
                        "swapped-type must really route to the other type")
            elif arm in ("strong_hybrid_rag", "frozen_shared", "learned_shared",
                         "unsplit_equal_graph"):
                require(choice["route_type"] is None, "untyped arm uses hidden type")
            else:
                require(choice["route_type"] == case["memory_type"],
                        "type reassigned after original plan")
            require(choice["planned_request_sha256"] == request_digest(
                plan, case, arm, source_by_id), "source/Reader request changed")
            expected[(case["question_id"], arm)] = (case, choice)
        get = choices.__getitem__
        typed_bank = capacity["typed"]["head_sha256_by_type"]
        shared_bank = capacity["shared"]["head_sha256_by_type"]
        kind = case["memory_type"]
        opposite = next(t for t in committed_types if t != kind)
        require(get("learned_shared")["head_sha256"] == shared_bank[kind]
                and get("learned_typed")["head_sha256"] == typed_bank[kind]
                and get("typed_swapped")["head_sha256"] == typed_bank[opposite],
                "changed/missing unspecialized or typed physical Head bank")
        typed = get("learned_typed")["head_sha256"]
        for arm in ("typed_fixed_graph", "typed_learned_graph", "typed_graph_lesion"):
            require(get(arm)["head_sha256"] == typed,
                    "graph arm changed learned typed Head")
        require(get("typed_swapped")["head_sha256"] != typed,
                "swapped-type negative equals correct Head")
        require(get("unsplit_equal_graph")["head_sha256"] == get("learned_shared")["head_sha256"],
                "unsplit-graph control changed frozen shared Head")
        require(get("unsplit_equal_graph")["graph_sha256"] ==
                get("typed_learned_graph")["graph_sha256"],
                "graph capacity control must use same topology")
        require(len({get(arm)["graph_sha256"] for arm in (
            "typed_fixed_graph", "typed_learned_graph", "typed_graph_lesion")}) == 3,
            "fixed, learned, and lesioned graph must be distinct interventions")
    require(types == committed_types,
            "both functional types required for specialization contrast")
    alias = plan["lineage_alias_edges"]
    require(isinstance(alias, list) and len(alias) <= MAX_CASES * 2,
            "unbounded lineage aliases")
    for edge in alias:
        require(isinstance(edge, list) and len(edge) == 2
                and all(isinstance(root, str) and root in roots for root in edge),
                "alias references unknown original source root")
    return expected


def paired_components(plan):
    """Iterative transitive root+family connectivity; never count alias rows as n."""
    parent = {}

    def find(value):
        parent.setdefault(value, value)
        root = value
        while parent[root] != root:
            root = parent[root]
        while parent[value] != value:
            item = parent[value]
            parent[value] = root
            value = item
        return root

    def union(a, b):
        parent[find(a)] = find(b)

    for case in plan["cases"]:
        union("r:" + case["source_root"], "f:" + case["family"])
    for a, b in plan["lineage_alias_edges"]:
        union("r:" + a, "r:" + b)
    components = defaultdict(list)
    for case in plan["cases"]:
        components[find("r:" + case["source_root"])].append(case)
    for cases in components.values():
        partitions = {c["split"] for c in cases}
        require(len(partitions & {"select", "future_a", "future_b"}) <= 1
                and not ("retention" in partitions
                         and partitions & {"select", "future_a", "future_b"}),
                "transitive leakage across heldout prospective partitions or retention")
    return list(components.values())


def audit(plan, answers, judgments):
    expected = validate_plan(plan)
    components = paired_components(plan)
    require(isinstance(answers, list) and len(answers) == len(expected),
            "a real Reader answer or explicit failure is required for every arm")
    original = {}
    resource = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0,
                                    "wall_ms": 0, "failures": 0,
                                    "undelivered_citation_ids": 0})
    for row in answers:
        exact(row, {"question_id", "arm", "request_sha256", "status", "raw_answer",
                    "raw_answer_sha256", "input_tokens", "output_tokens", "wall_ms",
                    "emitted_source_ids", "reader_execution_receipt_sha256"},
              "inference journal is not exact original wire shape")
        key = (row["question_id"], row["arm"])
        require(key in expected and key not in original, "unknown/duplicate Reader answer")
        case, choice = expected[key]
        require(row["request_sha256"] == choice["planned_request_sha256"],
                "original Reader request/source/prompt drift")
        require(row["status"] in ("ok", "failed"), "unknown original completion")
        if row["status"] == "ok":
            require_string(row["raw_answer"], "missing original generated answer")
            require(row["raw_answer_sha256"] == bytes_sha(row["raw_answer"].encode("utf-8"))
                    and is_sha(row["reader_execution_receipt_sha256"]),
                    "modified answer or absent physical inference receipt")
        else:
            require(row["raw_answer"] is None and row["raw_answer_sha256"] is None,
                    "a failed generation cannot have a reconstructed answer")
            require(row["reader_execution_receipt_sha256"] is None
                    or is_sha(row["reader_execution_receipt_sha256"]),
                    "bad failure evidence")
        for name, maximum in (("input_tokens", plan["max_input_tokens"]),
                              ("output_tokens", plan["max_output_tokens"]),
                              ("wall_ms", 3_600_000)):
            require(type(row[name]) is int and 0 <= row[name] <= maximum,
                    "Reader tokens/latency exceed registered bound")
        if row["status"] == "ok":
            require(row["input_tokens"] > 0 and row["output_tokens"] > 0,
                    "claimed model answer without tokens")
        cite = row["emitted_source_ids"]
        require(isinstance(cite, list) and len(cite) <= 64
                and all(isinstance(v, str) and len(v) < 256 for v in cite),
                "unbounded citation output")
        actual_citations = original_emitted_sources(row["raw_answer"],
                                                     choice["source_ids"])
        require(cite == actual_citations,
                "submitted citation labels disagree with raw model output")
        resource[row["arm"]]["input_tokens"] += row["input_tokens"]
        resource[row["arm"]]["output_tokens"] += row["output_tokens"]
        resource[row["arm"]]["wall_ms"] += row["wall_ms"]
        resource[row["arm"]]["failures"] += int(row["status"] != "ok")
        resource[row["arm"]]["undelivered_citation_ids"] += sum(
            v not in choice["source_ids"] for v in cite)
        original[key] = row
    require(set(original) == set(expected), "missing original Reader condition")
    require(isinstance(judgments, list) and len(judgments) == len(expected),
            "no incomplete/blinded task judgments")
    scores = {}
    for row in judgments:
        exact(row, {"question_id", "arm", "raw_answer_sha256", "correctness",
                    "citation_entailment", "review_receipt_sha256"},
              "modified external scoring schema")
        key = (row["question_id"], row["arm"])
        require(key in original and key not in scores, "unmatched/duplicated judgment")
        answer = original[key]
        require(row["raw_answer_sha256"] == answer["raw_answer_sha256"]
                and is_sha(row["review_receipt_sha256"]),
                "external judgment not bound to original answer")
        value = row["correctness"]
        require(type(value) in (int, float) and isfinite(value)
                and 0 <= value <= 1, "not a bounded independent task score")
        require(row["citation_entailment"] is None
                or type(row["citation_entailment"]) is bool,
                "citation not independently adjudicated")
        require(answer["status"] == "ok" or value == 0,
                "failed model generation relabelled a success")
        scores[key] = float(value)
    require(set(scores) == set(expected), "judgments cannot omit failed/hard cases")
    comparisons = {}
    future_cases = [c for c in components if any(
        q["split"] in ("future_a", "future_b") for q in c)]
    for label, (candidate, control) in CONTRASTS.items():
        paired = []
        for component in future_cases:
            values = [scores[(case["question_id"], candidate)] -
                      scores[(case["question_id"], control)]
                      for case in component if case["split"] in ("future_a", "future_b")]
            if values:
                paired.append(sum(values) / len(values))
        require(paired, "two future partitions must have outcomes")
        mean = sum(paired) / len(paired)
        radius = sqrt(2 * log(2 * len(CONTRASTS) / 0.05) / len(paired))
        comparisons[label] = {
            "future_independent_root_family_components_upper_bound": len(paired),
            "mean_paired_success_delta": mean,
            "simultaneous_95pct_lower_bound": max(-1.0, mean - radius),
            "simultaneous_95pct_upper_bound": min(1.0, mean + radius),
            "component_wins": sum(x > 0 for x in paired),
            "component_losses": sum(x < 0 for x in paired),
            "component_ties": sum(x == 0 for x in paired),
        }
    splits = {c["split"] for c in plan["cases"]}
    require({"future_a", "future_b", "select", "retention"} <= splits,
            "complete select/future/retention census missing")
    results = {}
    for arm in ARMS:
        scored = [scores[(case["question_id"], arm)] for case in plan["cases"]]
        results[arm] = {"questions": len(scored), "mean_task_score": sum(scored) / len(scored),
                        "failed_generations": resource[arm]["failures"]}
    return {
        "profile": PROFILE + ".review.v1", "original_plan_sha256": digest(plan),
        "original_answers_sha256": digest(answers),
        "external_judgments_sha256": digest(judgments),
        "question_count": len(plan["cases"]), "original_answer_attempts": len(answers),
        "original_judgment_rows": len(judgments),
        "all_original_questions_and_failures_retained": True,
        "transitive_source_family_groups_upper_bound": len(components),
        "future_group_count_upper_bound": len(future_cases),
        "scores": results, "matched_resource_observations": dict(resource),
        "paired_causal_diagnostics": comparisons,
        "real_reader_dispatch_externally_authenticated": False,
        "external_reviewer_independence_verified": False,
        "pretrained_model_origin_verified": False,
        "real_prospective_calendar_windows_verified": False,
        "strong_rag_original_generation_independently_attested": False,
        "parametric_unlearning_verified": False,
        "citation_precision": None,
        "compression_net_savings_verified": False,
        "production_accepted": False, "selected_model": None,
        "superiority_claim": False,
    }


def _duplicate_reject(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise Refused("duplicate JSON object key")
        out[k] = v
    return out


def pinned_json(path, pin):
    require(is_sha(pin), "missing external SHA256 pin")
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= MAX_FILE_BYTES, "unsafe audit input")
    raw = path.read_bytes()
    require(bytes_sha(raw) == pin, "original material changed since external seal")
    try:
        return json.loads(raw, object_pairs_hook=_duplicate_reject,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              Refused("nonfinite JSON value")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refused("invalid original JSON material") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "answers", "judgments"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(pinned_json(args.plan, args.plan_sha256),
                   pinned_json(args.answers, args.answers_sha256),
                   pinned_json(args.judgments, args.judgments_sha256))
    require(not args.output.exists() and not args.output.is_symlink(),
            "cannot overwrite original output or prior review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(canonical(result) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


if __name__ == "__main__":
    result = main()
    print(json.dumps({"questions": result["question_count"],
                      "accepted": result["production_accepted"]}))
