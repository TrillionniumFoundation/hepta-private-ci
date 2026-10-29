"""Exact finite-tree outer gradients for a declared hard-event SG algorithm.

Inner updates use hard categorical outcomes and a deliberately biased surrogate
Jacobian. Shape parameters affect only that learning rule; the physical forward
law is held fixed. The outer expectation enumerates every hard outcome and its
probability. Its gradient includes BOTH update sensitivities and changes in path
probability. This is not a fixed-random-mask or straight-through hypergradient.
"""

from dataclasses import dataclass
import time

import numpy as np

from .gradients import outcome_law
from .training import PARAMETER_BOUNDS


@dataclass(frozen=True)
class MetaExample:
    distance: float
    drift_offset: float
    horizon: float
    feature: float
    target: int


@dataclass(frozen=True)
class MetaResult:
    objective: float
    hypergradient: np.ndarray
    pathwise_component: np.ndarray
    score_component: np.ndarray
    probability_mass: float
    probability_mass_gradient: np.ndarray
    leaves: int
    kernel_evaluations: int
    projection_contacts: int
    leaf_records: list

    def receipt(self):
        return {name:value.tolist() if isinstance(value,np.ndarray) else value
                for name,value in self.__dict__.items()}


def make_meta_examples(seed, count=3, *, configuration=None):
    """Registered independent context streams, alternating hit/survive targets."""
    rng = np.random.default_rng(seed)
    configuration = configuration or {
        "even_rows":{"distance_uniform":[.8,1.2],"drift_offset_uniform":[.5,1.],
                     "feature":1.,"target":"hit"},
        "odd_rows":{"distance_uniform":[1.,1.4],"drift_offset_uniform":[-.5,-.2],
                    "feature":-.8,"target":"survive"},"horizon_uniform":[.8,1.2],
    }
    result = []
    for index in range(count):
        spec = configuration["even_rows" if index % 2 == 0 else "odd_rows"]
        result.append(MetaExample(float(rng.uniform(*spec["distance_uniform"])),
                                  float(rng.uniform(*spec["drift_offset_uniform"])),
                                  float(rng.uniform(*configuration["horizon_uniform"])),
                                  float(spec["feature"]),("hit","survive","cancel").index(spec["target"])))
    return result


def _law_at(weight, example, parameters, order):
    return outcome_law(example.distance-example.feature*weight,
                       parameters[0]+example.drift_offset,parameters[1],parameters[2],
                       example.horizon,derivatives=order)


def _outer_loss(weight, examples, physical_parameters, order):
    loss,gradient = 0.0,0.0
    for example in examples:
        law = _law_at(weight,example,physical_parameters,order)
        # Squared loss of a HARD one-hot outcome against a one-hot target.
        costs = np.ones(3)
        costs[example.target] = 0.0
        loss += costs@law.probability
        gradient += costs@(-law.jacobian[:,0])*example.feature
    return float(loss/len(examples)),float(gradient/len(examples))


def meta_objective(shape_parameters, training_examples, outer_examples, *,
                   physical_parameters=(.15,.65,.2), inner_steps=3,
                   inner_learning_rate=.2, initial_weight=0., weight_bounds=(-.45,.45),
                   derivatives=True):
    """E[outer hard-event loss] over all 3**K stochastic inner-training paths.

    The scalar weight controls initial voltage through distance=a-feature*w.
    The physical mu/sigma/cancel law is identical in all comparison arms. The
    three shape coefficients alter only the inner SG Jacobian. Consequently
    there is no direct outer dependence on shape; all adaptation is mediated by
    actual inner updates. The physical path-score term is nevertheless essential.
    """
    training_examples,outer_examples = tuple(training_examples),tuple(outer_examples)
    shape_parameters = np.asarray(shape_parameters,dtype=float)
    physical_parameters = np.asarray(physical_parameters,dtype=float)
    if (not training_examples or not outer_examples or not 0 <= inner_steps <= 6
            or inner_learning_rate <= 0 or len(weight_bounds) != 2
            or not weight_bounds[0] <= initial_weight <= weight_bounds[1]):
        raise ValueError("Invalid finite-tree training contract")
    if shape_parameters.shape != (3,) or physical_parameters.shape != (3,):
        raise ValueError("Expected three shape and three physical coefficients")
    for example in training_examples+outer_examples:
        if example.target not in (0,1,2) or min(example.distance-example.feature*w for w in weight_bounds) <= 0:
            raise ValueError("All projected states must remain strictly below the barrier")
    # weight, derivative of weight, path probability, derivative of probability
    nodes = [(float(initial_weight),np.zeros(3),1.0,np.zeros(3),())]
    evaluations,contacts = 0,0
    for step in range(inner_steps):
        example = training_examples[step % len(training_examples)]
        next_nodes = []
        target = np.eye(3)[example.target]
        for weight,sensitivity,mass,mass_gradient,path in nodes:
            physical = _law_at(weight,example,physical_parameters,1 if derivatives else 0)
            shape = _law_at(weight,example,shape_parameters,2 if derivatives else 1)
            evaluations += 2
            sg = -shape.jacobian[:,0]*example.feature
            physical_weight_gradient = -physical.jacobian[:,0]*example.feature
            for outcome in range(3):
                residual = np.eye(3)[outcome]-target
                update = float(residual@sg)
                proposal = weight-inner_learning_rate*update
                new_weight = float(np.clip(proposal,*weight_bounds))
                interior = weight_bounds[0] < proposal < weight_bounds[1]
                contacts += int(not interior)
                new_sensitivity = np.zeros(3)
                if derivatives and interior:
                    update_weight = float(residual@shape.hessian[:,0,0])*example.feature**2
                    update_shape = residual@(-shape.hessian[:,0,1:])*example.feature
                    new_sensitivity = ((1-inner_learning_rate*update_weight)*sensitivity
                                       -inner_learning_rate*update_shape)
                probability = float(physical.probability[outcome])
                new_mass_gradient = (mass_gradient*probability
                    +mass*physical_weight_gradient[outcome]*sensitivity)
                next_nodes.append((new_weight,new_sensitivity,mass*probability,new_mass_gradient,path+(outcome,)))
        nodes = next_nodes
    objective,pathwise,score = 0.0,np.zeros(3),np.zeros(3)
    total_mass,total_mass_gradient = 0.0,np.zeros(3)
    leaf_records = []
    for weight,sensitivity,mass,mass_gradient,path in nodes:
        loss,loss_weight = _outer_loss(weight,outer_examples,physical_parameters,1 if derivatives else 0)
        evaluations += len(outer_examples)
        objective += mass*loss
        pathwise += mass*loss_weight*sensitivity
        score += loss*mass_gradient
        total_mass += mass
        total_mass_gradient += mass_gradient
        leaf_records.append({"outcome_path":list(path),"weight":weight,
                             "weight_derivative":sensitivity.tolist(),"probability":mass,
                             "probability_derivative":mass_gradient.tolist(),
                             "outer_expected_loss":loss,"outer_weight_gradient":loss_weight})
    if abs(total_mass-1) > 1e-9 or np.max(np.abs(total_mass_gradient)) > 1e-8:
        raise ArithmeticError("Enumerated physical training paths do not conserve mass")
    return MetaResult(float(objective),pathwise+score,pathwise,score,float(total_mass),
                      total_mass_gradient,len(nodes),evaluations,contacts,leaf_records)


def exact_inner_baseline(training_examples, outer_examples, *,
                         physical_parameters=(.15,.65,.2), inner_steps=3,
                         inner_learning_rate=.2, initial_weight=0., weight_bounds=(-.45,.45)):
    """Same law/loss/contexts/K, using the model's true expected inner gradient."""
    training_examples,outer_examples = tuple(training_examples),tuple(outer_examples)
    if not training_examples or not outer_examples or inner_steps < 0 or inner_learning_rate <= 0:
        raise ValueError("Invalid exact-gradient comparison contract")
    weight,history = float(initial_weight),[]
    for step in range(inner_steps):
        example = training_examples[step % len(training_examples)]
        loss,gradient = _outer_loss(weight,[example],physical_parameters,1)
        new_weight = float(np.clip(weight-inner_learning_rate*gradient,*weight_bounds))
        history.append({"step":step+1,"hard_expected_loss":loss,"true_gradient":gradient,
                        "weight_before":weight,"weight_after":new_weight})
        weight = new_weight
    outer,_ = _outer_loss(weight,outer_examples,physical_parameters,0)
    return {"method":"true_expected_inner_gradient","objective":outer,"final_weight":weight,
            "history":history,"kernel_evaluations":inner_steps+len(outer_examples)}


def fit_meta(training_examples, outer_examples, *, initial=(.4,.9,.45),
             steps=12, learning_rate=.25, **tree_contract):
    """Optimize shape with the full finite-tree hypergradient and retain updates."""
    if steps < 0 or learning_rate <= 0:
        raise ValueError("Expected nonnegative steps and positive learning rate")
    lower,upper = PARAMETER_BOUNDS.T
    shape = np.asarray(initial,dtype=float).copy()
    if shape.shape != (3,) or not np.isfinite(shape).all() or np.any(shape < lower) or np.any(shape > upper):
        raise ValueError("Initial SG shape is outside the registered domain")
    started = time.perf_counter()
    original = shape.copy()
    first = meta_objective(shape,training_examples,outer_examples,**tree_contract)
    evaluations,kernel_evaluations = 1,first.kernel_evaluations
    history = []
    for step in range(steps):
        current = meta_objective(shape,training_examples,outer_examples,**tree_contract)
        evaluations += 1
        kernel_evaluations += current.kernel_evaluations
        rate,accepted = learning_rate,False
        for _ in range(16):
            candidate = np.clip(shape-rate*current.hypergradient,lower,upper)
            checked = meta_objective(candidate,training_examples,outer_examples,derivatives=False,**tree_contract)
            evaluations += 1
            kernel_evaluations += checked.kernel_evaluations
            delta = candidate-shape
            if checked.objective <= current.objective+1e-4*float(current.hypergradient@delta)+1e-14:
                accepted = True
                break
            rate *= .5
        if not accepted:
            raise ArithmeticError("Full-expectation meta line search failed")
        history.append({"step":step+1,"shape_before":shape.tolist(),"shape_after":candidate.tolist(),
                        "shape_delta":delta.tolist(),"hypergradient":current.hypergradient.tolist(),
                        "pathwise_component":current.pathwise_component.tolist(),
                        "score_component":current.score_component.tolist(),
                        "loss_before":current.objective,"loss_after":checked.objective,
                        "accepted_learning_rate":rate})
        shape = candidate
    final = meta_objective(shape,training_examples,outer_examples,**tree_contract)
    evaluations += 1
    kernel_evaluations += final.kernel_evaluations
    return {"method":"exact_expected_outer_gradient_of_hard_event_SG_updates",
            "initial":original.tolist(),"final":shape.tolist(),"shape_delta":(shape-original).tolist(),
            "outer_train_initial":first.objective,"outer_train_final":final.objective,
            "history":history,"final_tree":final.receipt(),"objective_evaluations":evaluations,
            "kernel_evaluations":kernel_evaluations,"elapsed_seconds":time.perf_counter()-started,
            "scope":"bounded finite-tree one-cell meta-learning diagnostic"}
