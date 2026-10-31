"""Direct expected task-value fitting, with exact full-trajectory gradients."""
import hashlib
import math
import time

import numpy as np

from .model import Model, softmax_policy


def fit_region(contract, seed, updates=600, learning_rate=1., optimizer="mirror"):
    """Fit tabular randomized stopping decisions, then report hard deployment.

    The complete objective includes actual query/wait/recovery costs and next-job
    continuation. No observation-likelihood loss or teacher labels are used.
    This fits one public contract; cross-contract amortization is not claimed.
    """
    wall, cpu = time.perf_counter(), time.process_time()
    if optimizer not in ("mirror", "adam"):
        raise ValueError("Use explicit mirror or adam optimization")
    if type(updates) is not int or updates < 1 or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("Positive finite fixed training budget and step size required")
    model = Model(contract)
    rng = np.random.default_rng(seed)
    logits = rng.normal(0., .01, model.valid.shape)
    initial = logits.copy()
    first, second = np.zeros_like(logits), np.zeros_like(logits)
    trace = []
    for update in range(1, updates+1):
        evaluated = model.solve(softmax_policy(model, logits))
        gradient = evaluated["logit_gradient"]
        if not np.all(np.isfinite(gradient)) or not np.isfinite(evaluated["initial_value"]):
            raise FloatingPointError("Direct task gradient failed")
        if optimizer == "adam":
            first = .9*first+.1*gradient
            second = .999*second+.001*gradient*gradient
            logits += learning_rate*(first/(1-.9**update))/(np.sqrt(second/(1-.999**update))+1e-8)
        else:
            # Model-based mirror policy improvement uses the CURRENT policy's
            # Q values. It is not supervision by the optimal QVI solution.
            # Updating all finite states includes counterfactual states; it is
            # explicitly a planning-aware boundary fit, not model-free learning.
            advantage = np.where(model.valid, evaluated["q"]-evaluated["value"][:, None], 0.)
            logits += learning_rate*advantage
        trace.append(dict(update=update-1, value=evaluated["initial_value"],
                          loss=-evaluated["initial_value"],
                          maximum_gradient=float(np.max(np.abs(gradient)))))
    probabilities = softmax_policy(model, logits)
    soft = model.solve(probabilities)
    trace.append(dict(update=updates, value=soft["initial_value"], loss=-soft["initial_value"],
                      maximum_gradient=float(np.max(np.abs(soft["logit_gradient"])))))
    hard_actions = np.argmax(probabilities, axis=1)
    hard = model.solve(model.deterministic(hard_actions))
    optimal = model.solve()
    uniform = model.valid/model.valid.sum(1, keepdims=True)
    legal_reachable = model.solve(uniform)["occupation"] > 0
    policy_reachable = hard["occupation"] > 0
    residual = np.max(hard["q"], axis=1)-hard["value"]
    gap = optimal["value"]-hard["value"]
    return dict(schema="hcsn.regenerative-evidence.direct-task-fit.v1",
        contract=contract.serializable(), states=[list(s) for s in model.states],
        seed=seed, updates=updates, learning_rate=learning_rate, optimizer=optimizer,
        objective="exact expected task return including post-FIRE continuation",
        gradient="full discounted occupation times policy advantage; mirror preconditioning uses current-policy Q, no optimal teacher labels",
        initial_sha256=hashlib.sha256(initial.astype("<f8").tobytes()).hexdigest(),
        logits=logits.tolist(), probabilities=probabilities.tolist(),
        hard_actions=hard_actions.tolist(), trace=trace,
        soft_value=soft["initial_value"], hard_value=hard["initial_value"],
        hard_minus_soft=hard["initial_value"]-soft["initial_value"],
        optimal_reference_value=optimal["initial_value"],
        hard_optimality_gap=optimal["initial_value"]-hard["initial_value"],
        hard_maximum_state_gap=float(np.max(optimal["value"]-hard["value"])),
        hard_bellman_residual=float(np.max(residual)),
        hard_initial_bellman_residual=float(residual[model.start]),
        hard_legal_reachable_bellman_residual=float(np.max(residual[legal_reachable])),
        hard_policy_reachable_bellman_residual=float(np.max(residual[policy_reachable])),
        hard_maximum_legal_reachable_gap=float(np.max(gap[legal_reachable])),
        hard_maximum_policy_reachable_gap=float(np.max(gap[policy_reachable])),
        state_counts=dict(envelope=len(model.states), legal_reachable=int(legal_reachable.sum()),
                          hard_policy_reachable=int(policy_reachable.sum())),
        soft_maximum_gradient=float(np.max(np.abs(soft["logit_gradient"]))),
        converged_gradient=bool(np.max(np.abs(soft["logit_gradient"])) < 1e-7),
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        scope="One finite public contract; deterministic deployment is separately evaluated")
