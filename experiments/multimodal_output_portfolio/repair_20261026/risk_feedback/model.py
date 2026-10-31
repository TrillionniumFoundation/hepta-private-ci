"""Small fitted models and finite-control diagnostics; no media or private truth IO."""
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from ...advance_20261026.control.bellman import Branch, State, solve


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def softmax(x):
    z = np.exp(x - x.max(axis=-1, keepdims=True))
    return z / z.sum(axis=-1, keepdims=True)


@dataclass(frozen=True)
class PublicTask:
    cue: int

    def __post_init__(self):
        if type(self.cue) is not int or not 0 <= self.cue < 4:
            raise ValueError("A public cue only; no target or fault field is accepted")


def fit_posterior(spec):
    rng = np.random.default_rng(spec["posterior_seed"])
    cues = rng.choice(4, spec["posterior_training_rows"], p=spec["cue_probabilities"])
    law = np.array(spec["target_law_by_cue"])
    targets = np.array([rng.choice(3, p=law[c]) for c in cues])
    counts = np.zeros((4, 3))
    np.add.at(counts, (cues, targets), 1)
    weights = np.zeros((4, 3))
    before = digest(weights.tolist())
    losses = []
    for step in range(spec["training_steps"]):
        q = softmax(weights)
        if step in (0, spec["training_steps"] - 1):
            losses.append(float(-(counts * np.log(q)).sum() / counts.sum()))
        weights -= spec["learning_rate"] * (q * counts.sum(1, keepdims=True) - counts) / counts.sum()
    return weights, {"initial_parameter_sha256": before, "final_parameter_sha256": digest(weights.tolist()),
        "gradient_updates": spec["training_steps"], "rows": len(cues), "nll_before_and_last_update": losses,
        "training_data_sha256": digest({"cues": cues.tolist(), "targets": targets.tolist()}),
        "observed_counts": counts.astype(int).tolist(), "model": "categorical softmax, twelve trainable logits"}


def fit_feedback(feedback, labels, spec):
    x = np.column_stack((np.ones(len(feedback)), feedback))
    w = np.zeros(2)
    before = digest(w.tolist())
    losses = []
    for step in range(spec["training_steps"]):
        logits = x @ w
        p = 1 / (1 + np.exp(-logits))
        if step in (0, spec["training_steps"] - 1):
            losses.append(float(np.mean(np.logaddexp(0, logits) - labels * logits)))
        w -= spec["learning_rate"] * x.T @ (p - labels) / len(labels)
    return w, {"initial_parameter_sha256": before, "final_parameter_sha256": digest(w.tolist()),
        "gradient_updates": spec["training_steps"], "rows": len(labels),
        "logloss_before_and_last_update": losses, "model": "two-parameter logistic repair policy"}


def choose_initial(task, parameters, profile, spec):
    if type(task) is not PublicTask:
        raise TypeError("Online policy accepts only PublicTask")
    law = softmax(parameters)[task.cue]
    returns = np.array(spec["semantic_utility_action_by_target"]) - np.array(spec["initial_action_cost"])[:, None]
    if profile == "mean":
        values = returns @ law
        action = int(values.argmax())
    elif profile == "risk":
        values = np.exp(-spec["gamma"] * returns) @ law
        action = int(values.argmin())
    else:
        raise ValueError("Unknown objective")
    return action, law.tolist(), values.tolist()


def choose_continuation(arm, observed, feedback, parameters, spec):
    # All arms receive exactly the same public readback. Numeric ablations
    # change the chosen computational pathway, not access to private truth.
    if arm == "risk_history":
        return "repair" if spec["terminal_mismatch_penalty"][observed["fault_class"]] > spec["repair_cost"] else "stop"
    if arm == "risk_always_repair":
        return "repair"
    if arm == "risk_static_stop":
        return "stop"
    return "repair" if parameters @ np.array([1.0, feedback]) >= 0 else "stop"


def exact_diagnostic(spec, law):
    """Old solver reused on an observable tree, without revealing target branches."""
    states, policies = {}, []
    gamma = spec["gamma"]
    for a in range(4):
        for fault in range(3):
            # Hidden target is integrated at the terminal, not added to policy state.
            actions = {}
            for option in ("retain", "repair"):
                cost = spec["repair_cost"] if option == "repair" else 0.0
                penalty = 0.0 if option == "repair" else spec["terminal_mismatch_penalty"][fault]
                actions[option] = tuple(Branch(float(p), cost, terminal_utility=u - penalty)
                    for p, u in zip(law, spec["semantic_utility_action_by_target"][a]))
            states[f"{a}:{fault}"] = State(1, actions)
        root_branches = tuple(Branch(p, spec["initial_action_cost"][a] + spec["channel_cost_by_fault"][f]
            + spec["irreversible_first_delivery_damage"][f], next_state=f"{a}:{f}")
            for f, p in enumerate(spec["fault_probabilities"]))
        for mask in range(8):
            terms = []
            for f, branch in enumerate(root_branches):
                terminal = states[branch.next_state].actions["repair" if mask & (1 << f) else "retain"]
                terms.append(branch.probability * math.exp(gamma * branch.cost) * sum(
                    b.probability * math.exp(-gamma * (b.terminal_utility - b.cost)) for b in terminal))
            policies.append((sum(terms), a, mask))
        states.setdefault("root", State(2, {})).actions[str(a)] = root_branches
    result = solve(states, "root", gamma)
    best = min(policies)
    return {"bellman_moment": result.root_moment, "enumerated_moment": best[0],
        "bellman_action": result.actions["root"], "enumerated_action": best[1],
        "nonanticipating_policies_enumerated": len(policies),
        "absolute_error": abs(result.root_moment - best[0]),
        "scope": "Exact only for the supplied synthetic joint law and twelve observable continuation states"}


def certainty_equivalent(values, gamma):
    x = -gamma * np.asarray(values)
    high = x.max(axis=-1, keepdims=True)
    return -(high.squeeze(-1) + np.log(np.exp(x - high).mean(axis=-1))) / gamma
