"""Independent whole-objective perturbations retained with fitted checkpoints."""

import numpy as np

from .meta import meta_objective
from .training import objective


def _finite_difference(value, parameters):
    parameters = np.asarray(parameters,dtype=float)
    answer = []
    evaluations = 0
    for index in range(3):
        h = 2e-5
        delta = np.eye(3)[index]*h
        if index == 2 and parameters[index] < h:
            answer.append((-3*value(parameters)+4*value(parameters+delta)-value(parameters+2*delta))/(2*h))
            evaluations += 3
        else:
            answer.append((value(parameters+delta)-value(parameters-delta))/(2*h))
            evaluations += 2
    return np.asarray(answer),evaluations


def physical_check(parameters, contexts):
    _,gradient,_ = objective(parameters,contexts)
    numerical,evaluations = _finite_difference(
        lambda candidate:objective(candidate,contexts,derivatives=0)[0],parameters)
    return {"parameters":list(parameters),"gradient":gradient.tolist(),
            "whole_task_finite_difference":numerical.tolist(),
            "maximum_absolute_error":float(np.max(np.abs(gradient-numerical))),
            "objective_evaluations":evaluations+1,
            "kernel_evaluations":(evaluations+1)*len(contexts)}


def meta_check(parameters, inner, outer, tree_contract):
    analytic = meta_objective(parameters,inner,outer,**tree_contract)
    spent = [analytic.kernel_evaluations]
    def value(candidate):
        result = meta_objective(candidate,inner,outer,derivatives=False,**tree_contract)
        spent.append(result.kernel_evaluations)
        return result.objective
    numerical,evaluations = _finite_difference(value,parameters)
    return {"parameters":list(parameters),"hypergradient":analytic.hypergradient.tolist(),
            "whole_tree_finite_difference":numerical.tolist(),
            "pathwise_component":analytic.pathwise_component.tolist(),
            "score_component":analytic.score_component.tolist(),
            "maximum_absolute_error":float(np.max(np.abs(analytic.hypergradient-numerical))),
            "error_if_score_omitted":float(np.max(np.abs(analytic.pathwise_component-numerical))),
            "objective_evaluations":evaluations+1,"kernel_evaluations":sum(spent)}
