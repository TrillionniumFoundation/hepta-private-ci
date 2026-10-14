"""Versioned strong controls and generation-local cost attribution for #1526.

No CLI or alternative reviewer. The canonical reviewer calls these checks for
plan.v2. Original-byte pins and caller observations do not authenticate truth.
"""
from collections import Counter
import math

from four_gate_common import COST_AXES, PHASES, costs, digest, integer, lifecycle, number, require, sha, timestamp

V2 = "hepta.four-gate.plan.v2"
DEPTHS = (1, 2, 4, 8, 12, 16)
REASON_CONTROLS = ("fixed_12", "best_fixed", "nonrecursive", "exact_algorithm")
NDU_CONTROLS = ("fixed_12", "best_fixed", "cost_aware_exit", "stopping_router", "generic_nested_risk")


def arms_for(plan, gate, original):
    if plan["schema"] != V2:
        return original
    if gate == "reasoning":
        cfg = plan[gate]
        require(type(cfg["exact_algorithm_applicable"]) is bool, "explicit exact-comparator applicability")
        if not cfg["exact_algorithm_applicable"]:
            sha(cfg["exact_algorithm_assessment_sha256"])
            reason = cfg["exact_algorithm_inapplicability_reason"]
            require(type(reason) is str and 0 < len(reason) <= 2048, "preregistered inapplicability reason")
            return original + REASON_CONTROLS[:-1]
        return original + REASON_CONTROLS
    return original + NDU_CONTROLS


def validate_control_plan(plan):
    for gate in ("reasoning", "ndu"):
        cfg = plan[gate]
        sha(cfg["validation_sha256"])
        require(cfg["validation_depths"] == list(DEPTHS) and
                all(type(d) is int for d in cfg["validation_depths"]), "complete preregistered fixed-depth grid")
        weights = cfg["selection_cost_weights"]
        require(type(weights) is dict and set(weights) <= set(plan["required_cost_axes"]) - {"wall_ns"},
                "selection cost must use measured additive axes")
        for value in weights.values():
            number(value, "selection cost weight")
    arms_for(plan, "reasoning", ())


def validate_selection(plan, evidence, gate, episodes):
    """Recompute the fixed-depth choice from original historical validation rows."""
    cfg = plan[gate]
    validation = evidence["fixed_depth_validation"]
    require(type(validation) is dict and set(validation) == {"schema", "job_id", "rows"}, "validation envelope")
    require(validation["schema"] == "hepta.fixed-depth.validation.v1", "validation schema")
    require(digest(validation) == cfg["validation_sha256"], "validation changed after registration")
    rows = validation["rows"]
    require(type(rows) is list and 0 < len(rows) <= 100_000, "bounded validation inventory")
    held_inputs = {c["input_sha256"] for c in evidence["cases"]}
    held_groups = {c["source_cluster"] for c in evidence["cases"]}
    training_inputs = set(evidence["training_input_sha256s"])
    training_groups = set(evidence["training_source_clusters"])
    validation_input_owner = {}
    cases, scores, groups = {}, {d: {} for d in DEPTHS}, {}
    for row in rows:
        cid, depth = row["case_id"], row["depth"]
        require(isinstance(cid, str) and 0 < len(cid) <= 256 and type(depth) is int and depth in DEPTHS,
                "validation case/depth")
        require(cid not in scores[depth], "duplicate validation exposure")
        require(row["input_sha256"] not in held_inputs and row["source_cluster"] not in held_groups,
                "held-out information used to select fixed depth")
        sha(row["input_sha256"])
        require(row["input_sha256"] not in training_inputs and
                row["source_cluster"] not in training_groups, "training information used as validation")
        require(validation_input_owner.setdefault(row["input_sha256"], cid) == cid,
                "same validation input repeated as another case")
        require(all(type(row[k]) is str and 0 < len(row[k]) <= 256
                    for k in ("source_cluster", "producer_id", "observer_id")),
                "validation source/producer/observer identity required")
        require(timestamp(row["observed_at"]) <= timestamp(plan["selection_cutoff"]),
                "future outcome used in depth selection")
        require(row["objective_sha256"] == plan["objective_sha256"], "selection objective drift")
        require(row["observer_id"] != row["producer_id"], "selection self-labelled")
        sha(row["outcome_receipt_sha256"])
        identity = (row["input_sha256"], row["source_cluster"])
        require(cases.setdefault(cid, identity) == identity, "unpaired validation inputs")
        require(0 <= number(row["score"], "validation score") <= 1, "validation score range")
        measured = costs(row["cost"], plan["required_cost_axes"])
        scores[depth][cid] = row["score"] - sum(weight * measured[axis]
            for axis, weight in cfg["selection_cost_weights"].items())
        groups[cid] = row["source_cluster"]
    require(all(set(values) == set(cases) for values in scores.values()), "missing validation depth arm")
    cluster_scores = {}
    for depth in DEPTHS:
        by_group = {}
        for cid, score in scores[depth].items():
            by_group.setdefault(groups[cid], []).append(score)
        cluster_scores[depth] = sum(sum(v) / len(v) for v in by_group.values()) / len(by_group)
    # The actual grid execution is preparation, not free information for best_fixed.
    job = evidence["arms"]["best_fixed"]["lifecycle"]["search"]
    require(validation["job_id"] == job["job_id"], "unbound fixed-depth preparation job")
    for axis in set(plan["required_cost_axes"]) - {"wall_ns"}:
        require(job["cost"][axis] >= sum(r["cost"][axis] for r in rows),
                "unpaid fixed-depth validation compute")
    selected = max(DEPTHS, key=lambda d: (cluster_scores[d], -d))
    for (_, arm), item in episodes.items():
        row = item["row"]
        require(row["stop_reason"] in ("fixed_limit", "evidence_sufficient", "budget_exhausted",
                "abstained", "exact_algorithm_complete", "failed"), "explicit stop reason required")
        depth = item["depth"]["learned_depth"]
        if arm == "fixed_12":
            require(depth == 12, "fixed-12 comparator did not execute 12 rounds")
        elif arm == "best_fixed":
            require(depth == selected, "best fixed depth differs from historical selection")
        elif arm == "nonrecursive":
            require(depth == 1, "nonrecursive comparator has recursive learned depth")
        elif arm == "exact_algorithm":
            require(depth == 0 and row["stop_reason"] == "exact_algorithm_complete",
                    "deterministic comparator cannot manufacture learned depth")
    return {"selected_best_fixed_depth": selected, "validation_groups": len(set(groups.values())),
            "validation_cases": len(cases), "validation_scores": cluster_scores,
            "validation_sha256": digest(validation), "selection_authenticated": False}


def depth_distribution(episodes):
    by_arm = {}
    for (_, arm), item in episodes.items():
        by_arm.setdefault(arm, Counter())[item["depth"]["learned_depth"]] += 1
    return {arm: {"histogram": dict(sorted(values.items())), "constant_depth": len(values) == 1,
                  "input_adaptive_benefit_inferred": False} for arm, values in by_arm.items()}


def generation_overhead(plan, evidence, cases, episodes):
    """Amortize only over actual uses of each immutable generation, never future volume.

Per-arm lifecycle entries are summaries of disjoint generation job rows, not
additional physical charges. A shared job requires an explicit disjoint allocation
outside this profile; repeating its full job identity in two arms is rejected.
"""
    weights = plan["ndu"]["cost_weights"]
    overhead, seen_jobs = {}, set()
    for arm, meta in evidence["arms"].items():
        generations = meta["lifecycle_generations"]
        require(type(generations) is list and 0 < len(generations) <= len(cases), "generation inventory")
        covered = set()
        phase_sums = {p: {a: 0 for a in COST_AXES} for p in PHASES}
        for entry in generations:
            require(set(entry) == {"binding", "case_ids", "lifecycle"}, "generation fields / imaginary uses")
            binding = entry["binding"]
            require(set(binding) == {"model_sha256", "critic_sha256", "objective_sha256", "scope", "generation"},
                    "complete cache generation binding")
            require(binding["objective_sha256"] == plan["objective_sha256"], "cached objective changed")
            sha(binding["model_sha256"])
            require(binding["model_sha256"] == meta["stem_sha256"], "cache model differs from loaded Stem")
            if binding["critic_sha256"] is not None:
                sha(binding["critic_sha256"])
            require(isinstance(binding["scope"], str) and 0 < len(binding["scope"]) <= 256, "cache scope")
            integer(binding["generation"], "cache generation", 1, 2**63 - 1)
            ids = entry["case_ids"]
            require(type(ids) is list and ids and len(ids) == len(set(ids)) and
                    set(ids) <= set(cases) and not covered.intersection(ids), "duplicate/missing observed uses")
            covered.update(ids)
            sums = lifecycle(entry["lifecycle"], plan["required_cost_axes"])
            for phase, job in entry["lifecycle"].items():
                require(job["job_id"] not in seen_jobs, "physical job double charged across generations/arms")
                seen_jobs.add(job["job_id"])
                for axis in COST_AXES:
                    value = job["cost"][axis]
                    phase_sums[phase][axis] = (None if value is None or phase_sums[phase][axis] is None
                                               else phase_sums[phase][axis] + value)
            for cid in ids:
                row = episodes[(cid, arm)]["row"]
                require(row["cache_binding_sha256"] == digest(binding), "stale model/critic/objective/scope cache")
                require(cases[cid]["scope"] == binding["scope"], "cross-scope amortization")
                overhead[(cid, arm)] = sum(weight * (sums[axis] - entry["lifecycle"]["inference"]["cost"][axis]) / len(ids)
                                            for axis, weight in weights.items())
            for axis in set(plan["required_cost_axes"]) - {"wall_ns"}:
                measured = entry["lifecycle"]["inference"]["cost"][axis]
                observed = sum(episodes[(cid, arm)]["row"]["cost"][axis] for cid in ids)
                require(math.isclose(measured, observed, rel_tol=1e-9, abs_tol=1), "generation inference mismatch")
        require(covered == set(cases), "unaccounted generation / future amortization")
        for phase in PHASES:
            for axis in COST_AXES:
                a, b = phase_sums[phase][axis], meta["lifecycle"][phase]["cost"][axis]
                require(a is None and b is None or a is not None and b is not None and
                        math.isclose(a, b, rel_tol=1e-9, abs_tol=1), "generation lifecycle summary mismatch")
    return overhead


def capture_exact_reachability(node_count, edges, source, target, *, edge_inventory_complete):
    """Execute the bounded cheap graph comparator, not an independent outcome judge.

    A found path certifies reachability under the supplied graph. Absence of a
    path in an explicitly incomplete graph returns abstention, not a false label.
    The one guard activation has zero learned depth regardless of visited nodes.
    """
    from collections import deque
    import time

    integer(node_count, "graph nodes", 1, 4096)
    integer(source, "source node", 0, node_count - 1)
    integer(target, "target node", 0, node_count - 1)
    require(type(edge_inventory_complete) is bool, "explicit graph completeness")
    require(type(edges) is list and len(edges) <= 65536, "bounded graph edges")
    begin, cpu = time.perf_counter_ns(), time.process_time_ns()
    adjacency = [set() for _ in range(node_count)]
    for edge in edges:
        require(type(edge) in (list, tuple) and len(edge) == 2, "directed edge shape")
        a = integer(edge[0], "edge source", 0, node_count - 1)
        b = integer(edge[1], "edge target", 0, node_count - 1)
        require(b not in adjacency[a], "duplicate edge")
        adjacency[a].add(b)
    payload = {"nodes": node_count, "edges": sorted([a, b] for a in range(node_count)
                for b in adjacency[a]), "source": source, "target": target,
               "complete": edge_inventory_complete}
    seen, queue = {source}, deque([source])
    while queue and target not in seen:
        for successor in sorted(adjacency[queue.popleft()]):
            if successor not in seen:
                seen.add(successor)
                queue.append(successor)
    answer = True if target in seen else False if edge_inventory_complete else None
    output = digest({"algorithm": "bounded_bfs_v1", "input": digest(payload), "answer": answer})
    end, elapsed_cpu = time.perf_counter_ns(), time.process_time_ns() - cpu
    return {"input_sha256": digest(payload), "prediction": answer,
            "prediction_sha256": output, "visited_nodes": len(seen),
            "stop_reason": "exact_algorithm_complete", "abstained": answer is None,
            "cost": {"cpu_ns": elapsed_cpu, "wall_ns": end - begin,
                     "gpu_ns": 0, "energy_uj": None},
            "trace": [{"id": "exact-bfs", "kind": "guard", "parents": [],
                       "start_ns": begin, "end_ns": end, "input_refs": [digest(payload)],
                       "output_sha256": output}],
            "external_outcome_observed": False, "production_promotion_permitted": False}
