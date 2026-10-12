"""Nonrectangular model uncertainty: exact global/local risk counterexample.

An exogenous public signal precedes the decision; the hidden law is never
revealed. Local conditional worst cases may change laws across signal branches,
which is not the same problem as one globally admissible joint law.
"""
from fractions import Fraction as F
from itertools import product

PRIORS = (
    {(0, 0): F(0), (0, 1): F(1, 2), (1, 0): F(1, 2), (1, 1): F(0)},
    {(0, 0): F(1, 2), (0, 1): F(0), (1, 0): F(0), (1, 1): F(1, 2)},
)
ACTIONS = ("guess0", "guess1", "abstain")
ABSTAIN = F(-1, 4)


def terminal(action, true_label):
    if action == "abstain":
        return ABSTAIN
    if action not in ("guess0", "guess1") or true_label not in (0, 1):
        raise ValueError("invalid terminal action or hidden label")
    return F(1) if int(action[-1]) == true_label else F(-1)


def expected_prior(policy, prior):
    if tuple(sorted(policy)) != (0, 1) or any(a not in ACTIONS for a in policy.values()):
        raise ValueError("policy must act on both public signal outcomes")
    if set(prior) != set(PRIORS[0]) or sum(prior.values()) != 1:
        raise ValueError("invalid joint probability law")
    return sum((mass * terminal(policy[signal], label)
                for (signal, label), mass in prior.items()), F(0))


def exhaustive_global():
    """One shared member of the admissible joint-prior set, not one per branch."""
    candidates = []
    for left, right in product(ACTIONS, repeat=2):
        policy = {0: left, 1: right}
        values = tuple(expected_prior(policy, p) for p in PRIORS)
        candidates.append((min(values), policy, values))
    best = max(candidates, key=lambda x: x[0])
    return {"value": best[0], "policy": best[1], "prior_values": best[2],
            "policy_count": len(candidates)}


def local_rectangular():
    """Solve a DIFFERENT objective allowing a new worst prior at each signal."""
    decisions, worst_posterior, signal_payoffs = {}, {}, {}
    for signal in (0, 1):
        candidates = []
        for action in ACTIONS:
            conditioned = []
            for prior in PRIORS:
                mass = sum(v for (s, _), v in prior.items() if s == signal)
                if mass <= 0:
                    raise ValueError("zero-probability public information state")
                conditioned.append(sum((v * terminal(action, label) / mass
                    for (s, label), v in prior.items() if s == signal), F(0)))
            candidates.append((min(conditioned), action, tuple(conditioned)))
        best = max(candidates, key=lambda x: x[0])
        signal_payoffs[signal], decisions[signal] = best[0], best[1]
        worst_posterior[signal] = best[2]
    return {"value": (signal_payoffs[0] + signal_payoffs[1]) / 2,
            "policy": decisions, "signal_values": signal_payoffs,
            "conditional_outcomes": worst_posterior}


def experiment():
    g, local = exhaustive_global(), local_rectangular()
    assert g["value"] == 0 and local["value"] == ABSTAIN
    return {"schema": "hepta.fbsde.nonrectangular-ambiguity.v1",
            "global_maxmin_value": str(g["value"]),
            "rectangular_local_sweep_value": str(local["value"]),
            "gap": str(g["value"]-local["value"]),
            "global_policy": g["policy"], "local_policy": local["policy"],
            "enumerated_nonanticipative_policies": g["policy_count"],
            "global_models": len(PRIORS),
            "underlying_model_set_is_nonrectangular": True,
            "different_objectives_not_solver_error": True,
            "local_uniqueness_does_not_prove_global_equality": True,
            "independent_future_policy_results_available": False,
            "production_promotion_permitted": False}


if __name__ == "__main__":
    import json
    print(json.dumps(experiment(), sort_keys=True))
