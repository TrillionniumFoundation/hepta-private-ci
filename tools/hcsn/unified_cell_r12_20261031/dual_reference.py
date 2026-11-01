"""Development-only dual-head expression references, separate from primary fits.

The public grid and split seed are fixed. Two independent linear heads receive
observable summaries sufficient to specify this deliberately restricted belief
family. Twenty fixed updates, no search or confirmation-data selection. A
margin-only pair matches the exact channels and a local active-policy slope at
one anchor; it cannot change when uncertainty, time or recovery changes alone.
"""
import time

import numpy as np

from .task_value import ExactBeliefDP


FEATURES = ("active_margin", "bit_one", "bit_uncertainty", "recovery_mass",
            "remaining_time", "remaining_steps", "next_dt", "active_variance")


def _belief(centers, margin, bit_one, recovery):
    index = int(np.clip(np.searchsorted(centers, margin)-1, 0, 6))
    fraction = (margin-centers[index])/(centers[index+1]-centers[index])
    if not 0 <= fraction <= 1:
        raise ValueError("Margin must lie between the declared active centers")
    phases, derivative = np.zeros(10), np.zeros(10)
    phases[index:index+2] = (1-recovery)*np.array([1-fraction, fraction])
    phases[8] = recovery
    derivative[index:index+2] = (1-recovery)*np.array([-1., 1.])/(centers[index+1]-centers[index])
    bits = np.array([1-bit_one, bit_one])
    return np.outer(phases, bits).ravel(), np.outer(derivative, bits).ravel()


def _features(centers, margin, bit_one, recovery, schedule):
    p, _ = _belief(centers, margin, bit_one, recovery)
    phase = p.reshape(10, 2).sum(1)[:8]/(1-recovery)
    return np.array([margin, bit_one, 4*bit_one*(1-bit_one), recovery,
                     sum(schedule), len(schedule), schedule[0], phase @ (centers-margin)**2])


def _action_alpha(planner, p, schedule, budget, action):
    """Exact alpha vector for the locally selected finite policy tree.

    A selected branch defines an affine function of the initial belief. At
    action ties this is a subgradient; finite differences below diagnose the
    anchor rather than claiming global differentiability.
    """
    if action.startswith("STOP"):
        return planner.reward[:, int(action[-1])].copy()
    dt, rest = schedule[0], schedule[1:]
    matrix = planner._transition(dt)
    def tail(belief, reads):
        return _action_alpha(planner, belief, rest, reads, planner.choose(belief, rest, reads))
    if action == "RESET":
        flow = planner.R @ matrix
        return flow @ tail(p @ flow, budget)-planner.reset_cost-planner.latency_price*dt
    successor = p @ matrix
    if action == "WAIT":
        return matrix @ tail(successor, budget)-planner.latency_price*dt
    alpha = -planner.latency_price*dt-np.array(matrix @ planner.read_cost)*planner.read_multiplier
    for token in range(planner.E.shape[1]):
        joint = successor*planner.E[:, token]
        if joint.sum() > 0:
            alpha += matrix @ (planner.E[:, token]*tail(joint/joint.sum(), budget-1))
    return alpha


def run_dual_reference(cell):
    started = time.process_time()
    planner, centers = ExactBeliefDP(cell), np.asarray(cell.centers)
    anchor = dict(margin=float(.75*centers[3]+.25*centers[4]), bit_one=.75,
                  recovery=.25, schedule=(.45, .45, .45))
    p, direction = _belief(centers, anchor["margin"], anchor["bit_one"], anchor["recovery"])
    q = planner.action_values(p, anchor["schedule"], 2)
    continue_action = max(("WAIT", "READ"), key=lambda a: q[a])
    alphas = np.stack([_action_alpha(planner, p, anchor["schedule"], 2, a)
                       for a in (continue_action, "RESET")])
    target, slope = np.array([q[continue_action], q["RESET"]]), alphas @ direction
    def exact(margin, confidence, recovery, schedule):
        belief, _ = _belief(centers, margin, confidence, recovery)
        channels = planner.channels(belief, schedule, 2)
        return np.array([channels["A"], channels["B"]]), channels["stop"]
    h = 1e-5*(centers[1]-centers[0])
    numerical_slope = (exact(anchor["margin"]+h, .75, .25, anchor["schedule"])[0]
                       -exact(anchor["margin"]-h, .75, .25, anchor["schedule"])[0])/(2*h)
    x, y, stop, grid = [], [], [], []
    for margin in (float(centers[1]), float(centers[3]), float(centers[6])):
        for confidence in (.5, .75, .9):
            for recovery in (0., .5):
                for steps in (1, 3):
                    for dt in (.15, .45):
                        schedule = (dt,)*steps
                        outputs, terminal = exact(margin, confidence, recovery, schedule)
                        x.append(_features(centers, margin, confidence, recovery, schedule))
                        y.append(outputs); stop.append(terminal)
                        grid.append(dict(margin=margin, bit_one=confidence, recovery=recovery, schedule=list(schedule)))
    x, y, stop = np.array(x), np.array(y), np.array(stop)
    order = np.random.default_rng(311000).permutation(len(x))
    test, train = order[:len(x)//3], order[len(x)//3:]
    mean, scale = x[train].mean(0), np.maximum(x[train].std(0), 1e-8)
    design = np.column_stack(((x-mean)/scale, np.ones(len(x))))
    weights = np.zeros((design.shape[1], 2)); weights[-1] = y[train].mean(0)
    for _ in range(20):
        error = design[train] @ weights-y[train]
        penalty = 1e-4*weights; penalty[-1] = 0.
        weights -= .05*(2*design[train].T @ error/len(train)+penalty)
    ordinary = design @ weights
    matched = target+(x[:, :1]-anchor["margin"])*slope
    def metrics(predicted):
        actions = np.argmax(np.column_stack((stop[test], predicted[test])), axis=1)
        reference = np.argmax(np.column_stack((stop[test], y[test])), axis=1)
        return dict(heldout_channel_mse=np.mean((predicted[test]-y[test])**2, axis=0).tolist(),
                    heldout_three_way_action_disagreement=float(np.mean(actions != reference)),
                    heldout_continue_reset_sign_disagreement=float(np.mean((predicted[test, 0] >= predicted[test, 1])
                                                                           != (y[test, 0] >= y[test, 1]))))
    probes = []
    for confidence, recovery, schedule in ((.5, .25, (.45,)*3), (.9, .25, (.45,)*3),
                                            (.75, 0., (.45,)*3), (.75, .5, (.45,)*3),
                                            (.75, .25, (.15,)), (.75, .25, (1.05,)*3)):
        outputs, terminal = exact(anchor["margin"], confidence, recovery, schedule)
        features = _features(centers, anchor["margin"], confidence, recovery, schedule)
        predicted = np.r_[(features-mean)/scale, 1.] @ weights
        probes.append(dict(margin=anchor["margin"], bit_one=confidence, recovery=recovery,
                           schedule=list(schedule), exact=outputs.tolist(), stop=terminal,
                           slope_matched=target.tolist(), ordinary=predicted.tolist()))
    return dict(schema="hcsn.r12.development-dual-reference.v1", model_identity=planner.model_identity,
        scope="Fixed public development grid; not eight-fit primary performance or an independent confirmation experiment",
        information_scope="Features specify this two-bin/product-content/recovery0 family; not a sufficient statistic for arbitrary joint beliefs",
        anchor={**anchor, "A_B": target.tolist(), "local_alpha_values": (alphas @ p).tolist(),
                "slope": slope.tolist(), "finite_difference_slope": numerical_slope.tolist(),
                "slope_max_error": float(np.max(np.abs(slope-numerical_slope)))},
        feature_names=list(FEATURES), grid=grid, train_indices=train.tolist(), test_indices=test.tolist(),
        split_seed=311000, updates=20, learning_rate=.05, regularization=1e-4,
        ordinary_weights=weights.tolist(), normalization=dict(mean=mean.tolist(), scale=scale.tolist()),
        ordinary_independent_heads=metrics(ordinary), margin_slope_matched=metrics(matched),
        fixed_margin_probes=probes, exact_fixed_margin_channel_range=np.ptp([r["exact"] for r in probes], axis=0).tolist(),
        margin_reference_fixed_margin_channel_range=np.ptp([r["slope_matched"] for r in probes], axis=0).tolist(),
        cpu_seconds=time.process_time()-started)
