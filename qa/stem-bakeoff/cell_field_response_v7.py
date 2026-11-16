"""Eight-panel derivatives along an actual, nominally controlled Adam rollout.

Panel order is four current then four old. All response maps act on deviations
from nominal_actions, not on absolute replacement actions. Full optimizer state
and known training/panel inputs supply the coefficients; no independent-probe
or nonlinear sufficiency guarantee is asserted by these local maps.
"""

from dataclasses import dataclass
import time

import numpy as np

from cell_field_response_v5 import AdamDerivative, HeadDerivative
from cell_field_state import dataset_digest


@dataclass
class PanelResponse:
    states: np.ndarray
    observations: np.ndarray
    gradients: np.ndarray
    transitions: list
    nominal_actions: np.ndarray
    panel_digests: tuple
    dt: float
    cpu_ns: int
    wall_ns: int

    def terminal_sequence_maps(self):
        """Terminal eight-panel loss Jacobian with respect to every action."""
        h, q, p = len(self.transitions), *self.gradients.shape[1:]
        backward = np.vstack((self.gradients[-1].T, np.zeros((2*p,q))))
        maps = np.zeros((h,q,p))
        for k in range(h-1,-1,-1):
            maps[k] = self.dt*backward[:p].T
            backward = self.transitions[k].vjp(backward)
        return maps

    def impulse_maps(self):
        """All local outputs from a first-step action deviation only."""
        h, q, p = len(self.transitions), *self.gradients.shape[1:]
        sensitivity = np.vstack((self.dt*np.eye(p), np.zeros((2*p,p))))
        maps = np.zeros((h+1,q,p))
        for k in range(1,h+1):
            maps[k] = self.gradients[k]@sensitivity[:p]
            if k<h:
                sensitivity = self.transitions[k].jvp(sensitivity)
        return maps


def build_response(state, train, panels, *, horizon=8, dt=.02, nominal_actions=None):
    """Replay a warmed deterministic reference with a declared H-by-p control."""
    if (state.protocol["sampler"]!="full_batch" or state.step_count<1
            or type(horizon) is not int or not 1<=horizon<=8 or not 0<dt<=1
            or len(panels)!=8 or not 1<=state.parameter_count<=4096):
        raise ValueError("warmed full-batch state, H1..H8 and eight ordered panels required")
    cpu,wall = time.process_time_ns(),time.perf_counter_ns()
    if state.contexts.get(state.active_context)!=dataset_digest(*train):
        raise ValueError("response training bytes differ from selected complete-state context")
    identities = tuple(dataset_digest(*panel) for panel in panels)
    p = state.parameter_count
    actions = (np.zeros((horizon,p)) if nominal_actions is None
               else np.asarray(nominal_actions,dtype=np.float64).copy())
    if actions.shape!=(horizon,p) or not np.isfinite(actions).all() or np.any(np.abs(actions)>1e6):
        raise ValueError("finite bounded nominal action matrix required")
    initial = state.digest()
    vectors,observations,gradients,transitions = [state.vector()],[],[],[]
    for k in range(horizon+1):
        head = state.head_from_vector(vectors[-1])
        rows = [HeadDerivative(head,*panel) for panel in panels]
        observations.append([row.loss for row in rows])
        gradients.append(np.vstack([row.gradient for row in rows]))
        if k<horizon:
            derivative = AdamDerivative(state,vectors[-1],state.step_count+k,train)
            transitions.append(derivative)
            following = derivative.next.copy()
            following[:p] += dt*actions[k]
            vectors.append(following)
    if state.digest()!=initial:
        raise RuntimeError("controlled response construction mutated its origin")
    result = PanelResponse(np.asarray(vectors),np.asarray(observations),np.asarray(gradients),
        transitions,actions,identities,dt,time.process_time_ns()-cpu,time.perf_counter_ns()-wall)
    if not all(np.isfinite(a).all() for a in (result.states,result.observations,result.gradients)):
        raise ValueError("nonfinite controlled reference")
    return result


def loss2_coefficients(response):
    """Two aggregate loss states with all eight immediate Mealy output rows.

    z_next=T*z+B*du; y_next=D*z+F*du. The direct F term is never projected.
    Earlier perturbations use the inherited physical-coordinate pseudoinverse.
    """
    h,p = len(response.transitions),response.gradients.shape[-1]
    means = response.gradients.reshape(h+1,2,4,p).mean(axis=2)
    direct = response.dt*response.gradients[1:]
    inputs = response.dt*means[1:]
    transition,outputs = [],[]
    for k in range(h):
        aggregate = np.hstack((means[k],np.zeros((2,2*p))))
        reconstructed = np.linalg.pinv(aggregate,rcond=1e-10)
        transported = response.transitions[k].jvp(reconstructed)
        observed = response.gradients[k+1]@transported[:p]
        outputs.append(observed)
        transition.append(observed.reshape(2,4,2).mean(axis=1))
    return {"transition":np.asarray(transition),"outputs":np.asarray(outputs),
            "inputs":inputs,"direct":direct}


def loss2_terminal_maps(response):
    """Terminal q8 maps; final-step input is exact even when retained state is2D."""
    h,p = len(response.transitions),response.gradients.shape[-1]
    if h==1:
        return (response.dt*response.gradients[-1])[None]
    system = loss2_coefficients(response)
    maps = np.zeros((h,8,p))
    maps[-1] = system["direct"][-1]
    backward = system["outputs"][-1]
    for k in range(h-2,-1,-1):
        maps[k] = backward@system["inputs"][k]
        backward = backward@system["transition"][k]
    return maps


def loss2_impulse_maps(response):
    """All q8 outputs with exact first-step input/output feedthrough."""
    h,p = len(response.transitions),response.gradients.shape[-1]
    system = loss2_coefficients(response)
    maps = np.zeros((h+1,8,p))
    maps[1] = system["direct"][0]
    retained = system["inputs"][0]
    for k in range(1,h):
        maps[k+1] = system["outputs"][k]@retained
        retained = system["transition"][k]@retained
    return maps
