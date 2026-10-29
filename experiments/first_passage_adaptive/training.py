"""Joint physical mu/sigma/cancellation training on expected hard-event loss.

There is no trainable readout in this diagnostic: all optimized coefficients
change the event distribution. This finite one-event task does not establish an
unbiased gradient for the preceding sampled multilayer renewal network.
"""

from dataclasses import dataclass
import time

import numpy as np

from .gradients import expected_task_loss, outcome_law


PARAMETER_BOUNDS = np.array([[-1.5,2.5],[.2,1.5],[0.,1.5]])


@dataclass(frozen=True)
class Context:
    distance: float
    drift_offset: float
    horizon: float
    costs: tuple


def make_contexts(seed, count=12, *, configuration=None):
    """Registered synthetic task contexts; seeds designate disjoint splits."""
    rng = np.random.default_rng(seed)
    configuration = configuration or {
        "even_rows":{"distance_uniform":[.65,1.],"drift_offset_uniform":[.8,1.1],
                     "horizon_uniform":[.7,1.2],"costs":[0.,1.2,1.5]},
        "odd_rows":{"distance_uniform":[.9,1.3],"drift_offset_uniform":[-.7,-.3],
                    "horizon_uniform":[.7,1.2],"costs":[2.,0.,.35]},
    }
    result = []
    for index in range(count):
        spec = configuration["even_rows" if index % 2 == 0 else "odd_rows"]
        result.append(Context(float(rng.uniform(*spec["distance_uniform"])),
                              float(rng.uniform(*spec["drift_offset_uniform"])),
                              float(rng.uniform(*spec["horizon_uniform"])),tuple(spec["costs"])))
    return result


def objective(parameters, contexts, *, derivatives=1):
    """Average true E[conditional outcome loss] and physical derivatives."""
    parameters = np.asarray(parameters,dtype=float)
    contexts = tuple(contexts)
    if parameters.shape != (3,) or not contexts:
        raise ValueError("Three physical parameters and nonempty contexts are required")
    total,gradient,hessian = 0.0,np.zeros(3),np.zeros((3,3))
    for context in contexts:
        law = outcome_law(context.distance,parameters[0]+context.drift_offset,
                          parameters[1],parameters[2],context.horizon,derivatives=derivatives)
        loss,jacobian,curvature = expected_task_loss(law,context.costs)
        total += loss
        gradient += jacobian[1:]
        hessian += curvature[1:,1:]
    return total/len(contexts),gradient/len(contexts),hessian/len(contexts)


def fit_joint(contexts, *, initial=(.2,.8,.4), steps=40, learning_rate=.35):
    """Bounded true-gradient descent with retained physical update evidence."""
    if steps < 0 or learning_rate <= 0:
        raise ValueError("Expected nonnegative steps and positive learning rate")
    parameters = np.asarray(initial,dtype=float).copy()
    lower,upper = PARAMETER_BOUNDS.T
    if parameters.shape != (3,) or not np.isfinite(parameters).all() or np.any(parameters < lower) or np.any(parameters > upper):
        raise ValueError("Initial physical parameters are outside the registered domain")
    contexts = tuple(contexts)
    started = time.perf_counter()
    original = parameters.copy()
    first_loss,_,_ = objective(parameters,contexts,derivatives=0)
    history = []
    evaluations,gradient_evaluations = 1,0
    for index in range(steps):
        loss,gradient,_ = objective(parameters,contexts)
        evaluations += 1
        gradient_evaluations += 1
        rate = learning_rate
        accepted = False
        for _ in range(16):
            candidate = np.clip(parameters-rate*gradient,lower,upper)
            candidate_loss,_,_ = objective(candidate,contexts,derivatives=0)
            evaluations += 1
            delta = candidate-parameters
            if candidate_loss <= loss + 1e-4*float(gradient@delta) + 1e-14:
                accepted = True
                break
            rate *= .5
        if not accepted:
            raise ArithmeticError("True-gradient line search failed")
        history.append({"step":index+1,"parameters_before":parameters.tolist(),
                        "gradient":gradient.tolist(),"parameters_after":candidate.tolist(),
                        "physical_delta":delta.tolist(),"loss_before":loss,
                        "loss_after":candidate_loss,"accepted_learning_rate":rate})
        parameters = candidate
    final_loss,_,_ = objective(parameters,contexts,derivatives=0)
    evaluations += 1
    return {"method":"joint_physical_true_expected_gradient","initial":original.tolist(),
            "final":parameters.tolist(),"physical_delta":(parameters-original).tolist(),
            "train_initial":first_loss,"train_final":final_loss,"steps":steps,
            "history":history,"objective_evaluations":evaluations,
            "gradient_evaluations":gradient_evaluations,
            "kernel_evaluations":evaluations*len(contexts),
            "first_derivative_kernel_evaluations":gradient_evaluations*len(contexts),
            "elapsed_seconds":time.perf_counter()-started,
            "scope":"one active-cell finite-horizon three-outcome expected task loss"}
