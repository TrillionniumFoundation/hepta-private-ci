"""Execute the existing terminal control rule over 110 joint evidence branches.

This is a stagewise, supplied-model bridge, not an estimate of future resource
behavior or a general constrained optimum. The separate control workstream can
consume JointObservationLaw.forecast for a richer owner/cost transition graph.
"""

import math

import numpy as np

from ...advance_20261026.control.dynamic import ACQUIRE, confidence, terminal


def plan(utility, strict, prior, evidence, *, acquire_cost, future_resource_rejection,
         emit_cost=.002, minimum_confidence=.75, calibration=None,
         current_actual_mask=None, gamma=2.):
    """Compare emission with acquisition using the same full terminal policy.

    Future rejection probabilities are explicit supplied model inputs. Values
    can differ by observed event and chosen code; costs remain in each branch.
    Alias identity is not an input before acquisition.
    """
    mask = None if current_actual_mask is None else np.asarray(current_actual_mask, bool)
    if mask is not None and mask.shape != (102,):
        raise ValueError("Actual mask must cover 100 emissions, stop and acquisition")
    costs = np.broadcast_to(np.asarray(acquire_cost, float), (110,))
    rejects = np.broadcast_to(np.asarray(future_resource_rejection, float), (110, 100))
    if (not np.isfinite(costs).all() or (costs < 0).any() or not np.isfinite(rejects).all()
            or (rejects < 0).any() or (rejects > 1).any()):
        raise ValueError("Finite joint-event costs and declared future resource law required")
    kwargs = dict(emit_cost=emit_cost, minimum_confidence=minimum_confidence,
                  calibration=calibration, gamma=gamma)
    immediate = terminal(utility, strict, prior, actual_mask=None if mask is None else mask[:101], **kwargs)
    futures, moment, success = [], 0., 0.
    for branch in evidence.forecast(prior):
        event, mass = branch["event"], branch["probability"]
        end = terminal(utility, strict, branch["posterior"],
                       rejection_probability=rejects[event], **kwargs)
        moment += mass * math.exp(gamma * costs[event]) * end["moment"]
        success += mass * end["strict_success_probability"]
        futures.append({**branch, "action": end["action"], "moment": end["moment"],
                        "strict_success_probability": end["strict_success_probability"],
                        "cost": float(costs[event])})
    permitted = bool(confidence(success, "acquire", calibration) >= minimum_confidence)
    if mask is not None:
        permitted &= bool(mask[ACQUIRE])
    choose_acquire = permitted and moment < immediate["moment"]
    return {"action": ACQUIRE if choose_acquire else immediate["action"],
            "moment": moment if choose_acquire else immediate["moment"],
            "strict_success_probability": success if choose_acquire else immediate["strict_success_probability"],
            "acquire_moment": moment, "acquire_success_probability": success,
            "acquire_admitted": permitted, "immediate": immediate, "futures": futures,
            "scope": "supplied joint evidence law and declared stagewise resource/admission model"}
