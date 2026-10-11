"""Gates 3/4: causal activation depth and matched external-outcome comparisons.

A recorded DAG is not an autograd tape. A value-head output or BSDE residual is
never used as the outcome. These are read-only, unauthenticated diagnostics.
"""
from collections import defaultdict

from four_gate_controls import V2, arms_for, depth_distribution, generation_overhead, validate_selection

from four_gate_common import (
    costs, grouped_interval, integer, lifecycle, number, require,
    result, sha, text, timestamp,
)

WINDOWS = ("future_1", "future_2")
STRATA = ("new_relations", "temporal_order", "missing_evidence",
          "wrong_initial_hypothesis", "counterfactual")
REASON_ARMS = ("single_step", "fixed_depth", "equal_compute_control")
NDU_ARMS = ("fixed_budget", "confidence", "ndu_deterministic", "ndu_stochastic")


def causal_depth(nodes, root_input):
    """Count sequential learned/Cell depth, not parallel width, waits or retries."""
    require(type(nodes) is list and 0 < len(nodes) <= 4096, "bounded nonempty trace required")
    seen = {}
    known = {root_input}
    for node in nodes:
        require(set(node) == {"id", "kind", "parents", "start_ns", "end_ns",
                              "input_refs", "output_sha256"}, "unknown trace field / label channel")
        ident = text(node["id"], "activation id")
        require(ident not in seen, "duplicate activation cannot manufacture depth")
        kind = node["kind"]
        require(kind in ("cell", "group_reasoning", "guard", "wait", "transport_retry"),
                "unknown activation kind")
        parents = node["parents"]
        require(type(parents) is list and len(parents) == len(set(parents)) and
                all(parent in seen for parent in parents), "cycle, duplicate or unknown causal parent")
        start = integer(node["start_ns"], "activation start", 0, 2**63 - 1)
        end = integer(node["end_ns"], "activation end", start, 2**63 - 1)
        require(all(seen[p]["end_ns"] <= start for p in parents), "noncausal activation timestamps")
        refs = node["input_refs"]
        require(type(refs) is list and refs and all(ref in known for ref in refs),
                "future/terminal outcome or unavailable input entered reasoning trace")
        parent_outputs = {seen[p]["output"] for p in parents}
        require(all(ref == root_input or ref in parent_outputs for ref in refs),
                "input edge missing from observed causal DAG")
        output = sha(node["output_sha256"])
        require(output not in known or kind == "transport_retry", "aliased new activation output")
        if kind == "transport_retry":
            require(parents and output in parent_outputs, "retry must preserve an existing result")
        learned = kind in ("cell", "group_reasoning")
        seen[ident] = {
            "learned": max((seen[p]["learned"] for p in parents), default=0) + learned,
            "cell": max((seen[p]["cell"] for p in parents), default=0) + (kind == "cell"),
            "end_ns": end, "output": output,
        }
        known.add(output)
    return {"learned_depth": max(row["learned"] for row in seen.values()),
            "cell_depth": max(row["cell"] for row in seen.values()),
            "activations": len(nodes),
            "learned_activations": sum(n["kind"] in ("cell", "group_reasoning") for n in nodes),
            "transport_retries": sum(n["kind"] == "transport_retry" for n in nodes)}


def paired_evidence(plan, evidence, gate, arms):
    require(evidence["schema"] == f"hepta.four-gate.{gate}-traces.v1", "outcome evidence schema")
    cfg = plan[gate]
    metadata = evidence["arms"]
    require(set(metadata) == set(arms), "missing comparator arm")
    require(len({(m["stem_sha256"], m["tokenizer_sha256"], m["training_data_sha256"],
                  m["host_sha256"], m["environment_sha256"]) for m in metadata.values()}) == 1,
            "comparison changed Stem, training data, tokenizer, host or environment")
    totals = {}
    for arm, meta in metadata.items():
        require(meta["source_sha"] == plan["source_sha"] and
                meta["objective_sha256"] == plan["objective_sha256"], "source/objective drift")
        for name in ("stem_sha256", "tokenizer_sha256", "training_data_sha256", "policy_sha256",
                     "host_sha256", "environment_sha256"):
            sha(meta[name])
        require(timestamp(meta["selection_time"]) <= timestamp(plan["selection_cutoff"]),
                "policy selected using future window")
        integer(meta["trainable_parameters"], "trainable tensors", 0, cfg["parameter_ceiling"])
        number(meta["peak_rss_bytes"], "peak RSS", 1)
        require(meta["peak_rss_bytes"] <= cfg["rss_ceiling_bytes"], "RSS budget exceeded")
        totals[arm] = lifecycle(meta["lifecycle"], plan["required_cost_axes"])
        for axis, ceiling in cfg["lifecycle_ceilings"].items():
            require(totals[arm][axis] is not None and totals[arm][axis] <= ceiling,
                    f"lifecycle {axis} budget exceeded")
    cases = {}
    clusters = {}
    input_groups = {}
    structure_windows = {}
    train_groups = set(evidence["training_source_clusters"])
    train_structures = set(evidence["training_structure_sha256s"])
    train_inputs = set(evidence["training_input_sha256s"])
    require(train_groups and train_structures and train_inputs, "missing training split lineage")
    for value in train_structures | train_inputs:
        sha(value)
    require(0 < len(evidence["cases"]) <= 100_000, "bounded case inventory required")
    for case in evidence["cases"]:
        cid = text(case["case_id"], "case id")
        require(cid not in cases, "duplicate evaluation case")
        window = case["window"]
        require(window in WINDOWS, "missing real future window")
        cluster = text(case["source_cluster"], "source cluster")
        require(cluster not in train_groups, "training source leaked into evaluation")
        require(cluster not in clusters or clusters[cluster] == window, "cluster spans future windows")
        clusters[cluster] = window
        sha(case["input_sha256"])
        require(case["input_sha256"] not in train_inputs, "training input reused in evaluation")
        prior = input_groups.setdefault(case["input_sha256"], (cluster, window))
        require(prior == (cluster, window), "same input counted as independent sources/windows")
        sha(case["structure_sha256"])
        prior_window = structure_windows.setdefault(case["structure_sha256"], window)
        require(prior_window == window, "held-out structure spans novelty windows")
        require(case["structure_sha256"] not in train_structures, "training structure reused in novelty test")
        require(case["stratum"] in STRATA, "unsupported held-out task stratum")
        start, end = (timestamp(v) for v in plan["windows"][window])
        require(start <= timestamp(case["event_time"]) <= end, "case outside declared calendar window")
        cases[cid] = case
    require({(c["window"], c["stratum"]) for c in cases.values()} ==
            {(w, s) for w in WINDOWS for s in STRATA}, "complete two-window five-stratum coverage required")
    episodes = {}
    for row in evidence["episodes"]:
        key = (row["case_id"], row["arm"])
        require(key not in episodes and key[0] in cases and key[1] in arms,
                "duplicate or extra episode")
        case = cases[key[0]]
        require(row["input_sha256"] == case["input_sha256"], "unpaired initial information")
        require(row["status"] in ("succeeded", "failed", "cancelled", "indeterminate", "censored"),
                "unknown outcome status")
        require(row["status"] != "censored", "censored outcomes require a registered censoring estimator")
        outcome = row["external_outcome"]
        require(outcome["objective_sha256"] == plan["objective_sha256"], "outcome objective changed")
        text(outcome["observer_id"], "outcome observer")
        text(metadata[key[1]]["producer_id"], "model producer")
        require(outcome["observer_id"] != metadata[key[1]]["producer_id"], "policy self-labelled its outcome")
        sha(outcome["receipt_sha256"])
        require(0 <= number(outcome["score"], "external score") <= 1, "score outside fixed [0,1] objective")
        require(timestamp(outcome["observed_at"]) >= timestamp(case["event_time"]) and
                timestamp(outcome["observed_at"]) <= timestamp(plan["assessment_time"]),
                "outcome not yet observed")
        if row["status"] != "succeeded":
            require(outcome["score"] == 0, "failed/cancelled/unknown outcome cannot be counted as success")
        costs(row["cost"], plan["required_cost_axes"])
        for axis, ceiling in cfg["episode_ceilings"].items():
            require(row["cost"][axis] is not None and row["cost"][axis] <= ceiling,
                    f"episode {axis} budget exceeded")
        depth = causal_depth(row["trace"], case["input_sha256"])
        sha(row["prediction_sha256"])
        require(row["prediction_sha256"] == row["trace"][-1]["output_sha256"],
                "final prediction not bound to trace")
        require(outcome["receipt_sha256"] not in {ref for n in row["trace"] for ref in n["input_refs"]},
                "terminal label leaked into reasoning")
        episodes[key] = {"row": row, "depth": depth, "case": case}
    require(set(episodes) == {(cid, arm) for cid in cases for arm in arms},
            "missing matched episodes; failures and unvisited choices cannot be dropped")
    for arm in arms:
        for axis in set(plan["required_cost_axes"]) - {"wall_ns"}:
            summed = sum(episodes[(cid, arm)]["row"]["cost"][axis] for cid in cases)
            measured = metadata[arm]["lifecycle"]["inference"]["cost"][axis]
            require(abs(summed - measured) <= max(1, measured * 1e-9),
                    "episode attribution omits or double-charges physical inference")
    return cases, episodes, totals


def compare(plan, deltas, comparisons, seed):
    return grouped_interval(deltas, alpha=plan["alpha"] / comparisons,
                            replicates=plan["bootstrap_replicates"], seed=seed,
                            min_groups=plan["min_groups"])


def review_reasoning(plan, evidence):
    arms = arms_for(plan, "reasoning", REASON_ARMS)
    cases, episodes, totals = paired_evidence(plan, evidence, "reasoning", arms)
    selection = (validate_selection(plan, evidence, "reasoning", episodes)
                 if plan["schema"] == V2 else None)
    controls = tuple(arm for arm in arms if arm != "fixed_depth")
    cfg = plan["reasoning"]
    matched = True
    comparisons = {}
    passes = []
    for axis in cfg["match_axes"]:
        a, b = totals["fixed_depth"][axis], totals["equal_compute_control"][axis]
        require(a is not None and b is not None, "missing equal-lifecycle measurement")
        matched = matched and abs(a - b) <= max(a, b, 1) * cfg["matching_relative_tolerance"]
    for cid in cases:
        single = episodes[(cid, "single_step")]
        candidate = episodes[(cid, "fixed_depth")]
        control = episodes[(cid, "equal_compute_control")]
        require(single["depth"]["learned_depth"] == 1, "single-step comparator is not single-step")
        require(candidate["depth"]["learned_depth"] == cfg["selected_depth"], "fixed depth changed after selection")
        for axis in cfg["match_axes"]:
            a, b = candidate["row"]["cost"][axis], control["row"]["cost"][axis]
            require(a is not None and b is not None, "missing equal-compute measurement")
            matched = matched and abs(a - b) <= max(a, b, 1) * cfg["matching_relative_tolerance"]
    for window in WINDOWS:
        for stratum in STRATA:
            cohort = [c for c in cases.values() if (c["window"], c["stratum"]) == (window, stratum)]
            for control in controls:
                rows = [(c["source_cluster"],
                         episodes[(c["case_id"], "fixed_depth")]["row"]["external_outcome"]["score"] -
                         episodes[(c["case_id"], control)]["row"]["external_outcome"]["score"])
                        for c in cohort]
                interval = compare(plan, rows, len(WINDOWS) * len(STRATA) * len(controls), plan["seed"] + len(comparisons))
                comparisons[f"{window}:{stratum}:{control}"] = interval
                passes.append(interval["enough_groups"] and interval["lcb"] > cfg["minimum_score_gain"])
    return result(matched and all(passes), {"paired_comparisons": comparisons,
                  "equal_compute_matched": matched, "fixed_depth_selection": selection,
                  "depth_distribution": depth_distribution(episodes),
                  "observed_depth": {f"{cid}:{arm}": item["depth"] for (cid, arm), item in episodes.items()}},
                  [] if matched and all(passes) else ["novelty benefit or equal-compute requirement not met"])


def review_ndu(plan, evidence):
    arms = arms_for(plan, "ndu", NDU_ARMS)
    cases, episodes, totals = paired_evidence(plan, evidence, "ndu", arms)
    selection = (validate_selection(plan, evidence, "ndu", episodes)
                 if plan["schema"] == V2 else None)
    cfg = plan["ndu"]
    require(evidence["utility_profile_sha256"] == sha(cfg["utility_profile_sha256"]), "NDU profile changed")
    require(evidence["utility_profile"] == "registered_linear_external_score_minus_lifecycle_cost",
            "general recursive utility requires a separately conforming evaluator")
    weights = cfg["cost_weights"]
    require(weights and set(weights) <= set(plan["required_cost_axes"]) - {"wall_ns"},
            "NDU cost requires measured additive axes, not summed wall latency")
    for value in weights.values():
        number(value, "fixed external cost weight", 1e-30)
    n = len(cases)
    generation_cost = (generation_overhead(plan, evidence, cases, episodes)
                       if plan["schema"] == V2 else None)
    full_cost = {}
    for (cid, arm), item in episodes.items():
        overhead = {axis: (totals[arm][axis] - evidence["arms"][arm]["lifecycle"]["inference"]["cost"][axis]) / n
                    for axis in weights}
        full_cost[(cid, arm)] = (sum(weights[axis] * item["row"]["cost"][axis] for axis in weights)
                                 + (generation_cost[(cid, arm)] if generation_cost is not None else
                                    sum(weights[axis] * overhead[axis] for axis in weights)))
    comparisons = {}
    passes = []
    pairs = (("ndu_deterministic", "fixed_budget"), ("ndu_deterministic", "confidence"),
             ("ndu_stochastic", "fixed_budget"), ("ndu_stochastic", "confidence"),
             ("ndu_stochastic", "ndu_deterministic"))
    if plan["schema"] == V2:
        pairs += tuple((candidate, control) for candidate in ("ndu_deterministic", "ndu_stochastic")
                       for control in arms if control not in NDU_ARMS)
    family_size = len(WINDOWS) * len(pairs) * (3 + len(STRATA))
    for window in WINDOWS:
        cohort = [c for c in cases.values() if c["window"] == window]
        for candidate, control in pairs:
            quality, cost_delta, net = [], [], []
            for case in cohort:
                cid, group = case["case_id"], case["source_cluster"]
                gain = episodes[(cid, candidate)]["row"]["external_outcome"]["score"] - episodes[(cid, control)]["row"]["external_outcome"]["score"]
                extra = full_cost[(cid, candidate)] - full_cost[(cid, control)]
                quality.append((group, gain))
                cost_delta.append((group, extra))
                net.append((group, gain - extra))
            cis = {name: compare(plan, values, family_size, plan["seed"] + len(comparisons))
                   for name, values in (("quality", quality), ("cost", cost_delta), ("net", net))}
            supported = all(ci["enough_groups"] for ci in cis.values())
            better = (cis["quality"]["lcb"] > 0 and cis["cost"]["ucb"] <= cfg["cost_noninferiority_margin"])
            cheaper = (cis["quality"]["lcb"] >= -cfg["quality_noninferiority_margin"] and cis["cost"]["ucb"] < 0)
            retention = {}
            for stratum in STRATA:
                values = []
                for case in cohort:
                    if case["stratum"] == stratum:
                        cid = case["case_id"]
                        delta = episodes[(cid, candidate)]["row"]["external_outcome"]["score"] - episodes[(cid, control)]["row"]["external_outcome"]["score"]
                        values.append((case["source_cluster"], delta))
                retention[stratum] = compare(plan, values, family_size, plan["seed"] + len(comparisons))
            retained = all(ci["enough_groups"] and ci["lcb"] >= -cfg["quality_noninferiority_margin"]
                           for ci in retention.values())
            passed = supported and retained and (better or cheaper) and cis["net"]["lcb"] > 0
            comparisons[f"{window}:{candidate}:{control}"] = {
                **cis, "per_stratum_retention": retention, "passed": passed}
            passes.append(passed)
    return result(all(passes), {"paired_comparisons": comparisons,
                  "lifecycle_cost": totals, "actual_amortization_episodes": n,
                  "generation_local_amortization": generation_cost is not None,
                  "fixed_depth_selection": selection, "depth_distribution": depth_distribution(episodes),
                  "internal_utility_and_bsde_residual_used_as_outcome": False,
                  "general_fbsde_conformance_established": False},
                  [] if all(passes) else ["cost-adjusted external benefit not established for every registered comparison"])
