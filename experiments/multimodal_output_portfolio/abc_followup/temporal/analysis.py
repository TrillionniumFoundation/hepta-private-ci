"""Frozen source-cluster inference using quality and cost from identical outputs."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from .state import GAMMA, PRICE, PRICE_GRID
from .tasks import manifest


POLICIES = ("fixed", "initial", "feedback")
BOOTSTRAPS = 4000
BOOTSTRAP_SEED = 20261025044
PRIMARY_CONFIDENCE = 1 - .05 / 3


def ce(values, axis=None):
    # Utilities/costs are bounded in these executions; retain stable log sum.
    scaled = -GAMMA * np.asarray(values)
    maximum = np.max(scaled, axis=axis, keepdims=True)
    log_mean = np.log(np.mean(np.exp(scaled - maximum), axis=axis))
    return -(log_mean + np.squeeze(maximum, axis=axis)) / GAMMA


def interval(values, confidence):
    alpha = (1 - confidence) / 2
    return np.quantile(values, [alpha, 1 - alpha]).tolist()


def cvar(loss, fraction=.1):
    ordered = np.sort(np.asarray(loss).ravel())[::-1]
    count = fraction * len(ordered)
    full = int(np.floor(count))
    total = ordered[:full].sum()
    if full < len(ordered):
        total += (count - full) * ordered[full]
    return float(total / count)


def analyze(args):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    from .registration import verify
    protocol = verify(args.protocol, args.policies)
    generation = json.loads((args.run / "complete.json").read_text())
    scoring = json.loads((args.scores / "complete.json").read_text())
    if not scoring["complete"] or scoring["scored_requests"] != 768:
        raise ValueError("All final requests must have independent offline observations")
    if scoring["generation_complete_sha256"] != sha256(args.run / "complete.json") or scoring["scores_sha256"] != sha256(args.scores / "scores.jsonl"):
        raise ValueError("Complete generation/scoring identities differ")
    source_ids = [r["source_id"] for r in manifest()["roles"]["evaluation"]]
    source_map = {source: i for i, source in enumerate(source_ids)}
    arrays = {name: np.full((64, 4, 3), np.nan) for name in
              ("utility", "seconds", "cpu_seconds", "success", "completion", "physical", "agreement", "queries", "first_query", "second_query")}
    seen = set()
    decision_errors = []
    from .value import Policy
    from .state import Frame
    policy = Policy.load(args.policies)
    for line in (args.scores / "scores.jsonl").read_text().splitlines():
        item = json.loads(line)
        if sha256(item["case"]) != item["sha256"]:
            raise ValueError("Executed case identity changed")
        row = json.loads(Path(item["case"]).read_text())
        if row["template"] not in (0, 1) or row["scenario"] not in (0, 1):
            raise ValueError("Final template/scenario is outside the frozen domain")
        if any(row[name] != item[name] for name in ("source_id", "template", "scenario")):
            raise ValueError("Score index and actual-generation role identities differ")
        key = (row["source_id"], row["template"], row["scenario"], item["policy"])
        if key in seen:
            raise ValueError("Repeated final observation")
        seen.add(key)
        i, j, k = source_map[row["source_id"]], 2 * row["template"] + row["scenario"], POLICIES.index(item["policy"])
        if item["wave_sha256"] != row["verification"]["wave_sha256"]:
            raise ValueError("Quality and timed-output identities differ")
        observation_file = args.scores / "observations" / f"{item['wave_sha256']}.json"
        if sha256(observation_file) != item["observation_sha256"]:
            raise ValueError("Independent observation changed")
        if item["policy"] == "feedback":
            expected = [policy.feedback_action(Frame(**f)) for f in row["frames"]]
        elif item["policy"] == "initial":
            expected = list(policy.initial_route(Frame(**row["frames"][0])))
        else:
            expected = policy.payload["selected_fixed_route"]
        if expected != row["route"]:
            decision_errors.append(key)
        for stage, decision in enumerate(row["decisions"]):
            if decision["optional_cue_exists"]:
                raise ValueError("Unreleased optional cue was present at decision")
            matching = [a for a in row["acquisitions"] if a["cue_index"] == stage + 2]
            if bool(matching) != bool(row["route"][stage]):
                raise ValueError("Acquisition differs from closed action")
            if matching and matching[0]["released_ns"] <= decision["decision_ns"]:
                raise ValueError("Cue was released before the decision")
        m = item["metrics"]
        values = {"utility": m["utility"], "seconds": row["generation_cost"]["wall_ns"] / 1e9,
                  "cpu_seconds": row["generation_cost"]["cpu_ns"] / 1e9,
                  "success": m["success"], "completion": m["semantic_complete"],
                  "physical": m["physical_complete"], "agreement": m["agreement"],
                  "queries": sum(row["route"]), "first_query": row["route"][0], "second_query": row["route"][1]}
        for name, value in values.items():
            arrays[name][i, j, k] = value
    if len(seen) != 768 or any(not np.isfinite(a).all() for a in arrays.values()) or decision_errors:
        raise ValueError("Incomplete census or policy replay mismatch")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(64, size=(BOOTSTRAPS, 64))
    utility, seconds = arrays["utility"], arrays["seconds"]
    summary = {}
    for k, name in enumerate(POLICIES):
        summary[name] = {"raw_ce": float(ce(utility[:, :, k])),
                         "priced_ce": float(ce(utility[:, :, k] - PRICE * seconds[:, :, k])),
                         "success": float(arrays["success"][:, :, k].mean()),
                         "semantic_completion": float(arrays["completion"][:, :, k].mean()),
                         "physical_completion": float(arrays["physical"][:, :, k].mean()),
                         "fact_agreement": float(arrays["agreement"][:, :, k].mean()),
                         "mean_loss": float((1 - utility[:, :, k]).mean()),
                         "output_cvar90_loss": cvar(1 - utility[:, :, k]),
                         "source_mean_cvar90_loss": cvar((1 - utility[:, :, k]).mean(axis=1)),
                         "wall_mean_seconds": float(seconds[:, :, k].mean()),
                         "wall_p50_seconds": float(np.quantile(seconds[:, :, k], .5)),
                         "wall_p95_seconds": float(np.quantile(seconds[:, :, k], .95)),
                         "cpu_mean_seconds": float(arrays["cpu_seconds"][:, :, k].mean()),
                         "mean_optional_queries": float(arrays["queries"][:, :, k].mean()),
                         "first_query_rate": float(arrays["first_query"][:, :, k].mean()),
                         "second_query_rate": float(arrays["second_query"][:, :, k].mean())}
    primary, descriptive = [], []
    uboot, tboot = utility[draws], seconds[draws]
    bootstrap_ce = ce(uboot - PRICE * tboot, axis=(1, 2))
    point_ce = ce(utility - PRICE * seconds, axis=(0, 1))
    for reference in (0, 1):
        samples = bootstrap_ce[:, 2] - bootstrap_ce[:, reference]
        bounds = interval(samples, PRIMARY_CONFIDENCE)
        primary.append({"id": f"priced_ce_feedback_minus_{POLICIES[reference]}",
                        "estimate": float(point_ce[2] - point_ce[reference]),
                        "interval": bounds, "confidence": PRIMARY_CONFIDENCE,
                        "passed": bounds[0] > 0})
        time_differences = seconds[:, :, 2] - seconds[:, :, reference]
        raw_differences = ce(uboot, axis=(1, 2))[:, 2] - ce(uboot, axis=(1, 2))[:, reference]
        descriptive.append({"reference": POLICIES[reference],
                            "mean_wall_seconds_difference": float(time_differences.mean()),
                            "mean_wall_seconds_interval95": interval(time_differences[draws].mean(axis=(1, 2)), .95),
                            "raw_ce_difference": summary["feedback"]["raw_ce"] - summary[POLICIES[reference]]["raw_ce"],
                            "raw_ce_interval95": interval(raw_differences, .95)})
    success_delta = arrays["success"][:, :, 2] - arrays["success"][:, :, 0]
    success_bounds = interval(success_delta[draws].mean(axis=(1, 2)), PRIMARY_CONFIDENCE)
    primary.append({"id": "strict_success_retention_feedback_minus_fixed", "margin": 0.,
                    "estimate": float(success_delta.mean()), "interval": success_bounds,
                    "confidence": PRIMARY_CONFIDENCE, "passed": success_bounds[0] >= 0})
    prices = []
    for price in PRICE_GRID:
        boot = ce(uboot - price * tboot, axis=(1, 2))
        point = ce(utility - price * seconds, axis=(0, 1))
        for reference in (0, 1):
            prices.append({"price_utility_per_wall_second": price, "reference": POLICIES[reference],
                           "difference": float(point[2] - point[reference]),
                           "nominal_family10_interval": interval(boot[:, 2] - boot[:, reference], .995)})
    scan = []
    for price in np.linspace(0, .2, 41):
        values = ce(utility - price * seconds, axis=(0, 1))
        scan.append({"price": float(price), "feedback_minus_fixed": float(values[2] - values[0]),
                     "feedback_minus_initial": float(values[2] - values[1])})
    result = {"schema": "hepta.abc4.temporal-main-results.v1", "complete": True,
              "primary_family_all_passed": all(r["passed"] for r in primary),
              "policies": summary, "primary": primary, "descriptive": descriptive,
              "price_grid": prices, "break_even_scan": scan,
              "price_interpretation": "Research utility price .05 per actual wall-second; not an externally calibrated willingness-to-pay. References frozen at .05, not reselected at other prices.",
              "source_groups": 64, "templates": 2, "scenarios": 2, "requests": 768,
              "trained_policy": "three-seed ensemble; uncertainty conditional on fitted ensemble, not independent critic-seed population",
              "bootstrap": {"draws": BOOTSTRAPS, "seed": BOOTSTRAP_SEED, "unit": "underlying fact group; retain all templates/scenarios/policies", "primary_confidence": PRIMARY_CONFIDENCE,
                            "qualification": "nominal percentile/Bonferroni intervals; no exact finite-sample or project-wide coverage claim"},
              "generation_receipt": generation, "scoring_receipt": scoring,
              "policy_sha256": sha256(args.policies), "protocol_sha256": sha256(args.protocol),
              "quality_cost_same_actual_output": True, "policy_replay_errors": decision_errors,
              "source_means": {name: arrays[name].mean(axis=1).tolist() for name in arrays},
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}
    write_json(args.output, result)
    print(json.dumps({"complete": True, "primary": primary, "result_sha256": sha256(args.output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "scores", "policies", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
