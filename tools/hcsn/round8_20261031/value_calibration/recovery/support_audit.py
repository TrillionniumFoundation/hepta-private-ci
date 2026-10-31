"""Check public-state sufficiency invariants and frozen-domain rejection.

Construct equivalent public inputs by changing absolute clock, sunk cost,
prior/past votes, and the split of action versus latency costs. Check independent
world-enumerated next-input and reward laws, not a fitted model's predictions.
"""

import argparse
from collections import defaultdict
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from scipy.special import expit

from .. import finite
from ..run import MODES, SEEDS, digest, write
from .support import FrozenTrainingSupport, UnsupportedDomain


def law(state):
    result = {}
    for action in finite.task.legal_actions(state):
        grouped = defaultdict(lambda: np.zeros(2))
        for p, successor, reward in finite.execution_branches(state, action):
            # Rounding only coalesces algebraically equivalent next inputs;
            # input equality and branch masses/rewards are checked separately.
            key = None if successor.terminated else tuple(np.round(finite.task.features(successor), 10))
            grouped[key] += (p, p * reward)
        result[action] = grouped
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    support = FrozenTrainingSupport(args.prepared, expected_freeze_sha256=args.freeze_sha256)
    nominal = finite.build_graph(finite.configurations())
    invariants = defaultdict(lambda: {"states_checked": 0, "max_input_error": 0., "max_transition_reward_error": 0.})
    for state in nominal["states"]:
        p = state.parameters
        variants = {
            "absolute_clock_origin": replace(state, tick=state.tick + 7,
                parameters=replace(p, horizon=p.horizon + 7, arrival_tick=p.arrival_tick + 7)),
            "sunk_additive_cost": replace(state, total_cost=3.125),
            "action_latency_cost_split": replace(state, parameters=replace(p,
                latency_cost=p.latency_cost / 2,
                **{name: getattr(p, name) + p.latency_cost / 2 for name in
                    ("read_cost", "wait_cost", "repair_cost", "stop_cost")}))}
        if state.reads:
            votes = state.vote_sum + 2 if state.vote_sum < state.reads else state.vote_sum - 2
            logit = math.log(p.prior_probability / (1 - p.prior_probability))
            logit += (state.vote_sum - votes) * math.log(p.ordinary_reliability / (1 - p.ordinary_reliability))
            variants["prior_and_past_votes_same_posterior"] = replace(state, vote_sum=votes,
                parameters=replace(p, prior_probability=float(expit(logit))))
        original = law(state)
        for name, equivalent in variants.items():
            input_error = float(abs(finite.task.features(state) - finite.task.features(equivalent)).max())
            alternate = law(equivalent)
            if original.keys() != alternate.keys() or any(original[a].keys() != alternate[a].keys() for a in original):
                raise AssertionError(("feature aliases have different successor support", name, state.to_dict()))
            error = max(float(abs(original[a][s] - alternate[a][s]).max()) for a in original for s in original[a])
            if max(input_error, error) > 1e-12:
                raise AssertionError(("public-feature sufficiency invariant", name, input_error, error))
            row = invariants[name]
            row["states_checked"] += 1
            row["max_input_error"] = max(row["max_input_error"], input_error)
            row["max_transition_reward_error"] = max(row["max_transition_reward_error"], error)
    coverage = []
    lower, upper = nominal["x"].min(0), nominal["x"].max(0)
    for regime in ("nominal", "drift", "missing", "cost_shift"):
        graph = finite.build_graph(finite.configurations(regime))
        accepted = sum(support.inspect(s)["supported"] for s in graph["states"])
        if accepted != (len(graph["states"]) if regime == "nominal" else 0):
            raise AssertionError("incorrect domain coverage")
        require_rejects = 0
        for state in graph["states"]:
            try:
                support.require_supported(state)
            except UnsupportedDomain:
                require_rejects += 1
        if require_rejects != len(graph["states"]) - accepted:
            raise AssertionError("unsupported domain did not fail closed")
        outside = (graph["x"] < lower - 1e-12) | (graph["x"] > upper + 1e-12)
        coverage.append({"regime": regime, "public_states": len(graph["states"]), "domain_admitted": accepted,
            "domain_rejected": require_rejects, "business_success_count": 0, "policy_execution_count": 0,
            "features_outside_training_range": [{"name": finite.task.FEATURE_NAMES[i],
                "training": [float(lower[i]), float(upper[i])],
                "shift": [float(graph["x"][:, i].min()), float(graph["x"][:, i].max())]}
                for i in np.flatnonzero(outside.any(0))]})
    with tempfile.TemporaryDirectory(prefix="r8-support-integrity-") as temp:
        temp = Path(temp)
        (temp / "FREEZE.json").write_bytes((args.prepared / "FREEZE.json").read_bytes())
        (temp / "STATE_GRAPH.json").write_bytes((args.prepared / "STATE_GRAPH.json").read_bytes() + b" ")
        try:
            FrozenTrainingSupport(temp, expected_freeze_sha256=args.freeze_sha256)
        except ValueError as error:
            tamper_rejected = str(error) == "training domain bytes differ from preparation"
        else:
            tamper_rejected = False
    if not tamper_rejected:
        raise AssertionError("modified domain manifest was accepted")
    constants = np.flatnonzero(np.ptp(nominal["x"], axis=0) < 1e-12)
    scales = []
    for path in sorted(args.prepared.glob("*.json")):
        if path.name.split("_")[0] not in ("first", "clocked", "direct"):
            continue
        item = json.loads(path.read_text())
        if "weights" not in item:
            continue
        observed = np.asarray(item["weights"]["scale"])[constants]
        if not np.array_equal(observed, np.ones_like(observed)):
            raise AssertionError("constant-feature normalization contract differs")
        scales.append(path.name)
    if set(scales) != {f"{mode}_{seed}.json" for mode in MODES for seed in SEEDS}:
        raise AssertionError("normalization audit is missing frozen heads")
    report = {"schema": "hepta.round8.value-support-audit.v1", "passed": True,
        "scope": "Posthoc contract and implementation diagnosis, not efficacy; domain rejection is not a completed business task.",
        "feature_sufficiency_invariants": dict(invariants), "coverage": coverage,
        "constant_public_features": [finite.task.FEATURE_NAMES[i] for i in constants],
        "heads_checked_for_unit_scale_on_constant_features": scales,
        "tampered_domain_rejected": tamper_rejected,
        "freeze_sha256": args.freeze_sha256, "audit_source_sha256": digest(Path(__file__)),
        "support_source_sha256": digest(Path(__file__).with_name("support.py")),
        "production_activation": False,
        "conclusion": "No missing-public-information, cost-split or zero-scale implementation error found in these finite contracts. Shift failures are extrapolation of continuation Q beyond the frozen training domain. Changed compute/event fees also require a new contract; the source freeze keeps them fixed."}
    write(args.output, report)
    print(json.dumps({"passed": True, "coverage": coverage, "invariants": dict(invariants)}, indent=2))


if __name__ == "__main__":
    main()
