"""A finite-horizon loss-observability quotient of the full Adam tangent system.

O_k stacks C_k, C_(k+1) A_k, ..., C_H A_(H-1)...A_k. Consequently
O_(k+1) A_k = drop_first_two_rows(O_k). The retained state z_k=O_k delta_x_k
has 2(H-k+1) coordinates and evolves by a shift plus O_(k+1) E_k u_k.
Every loss output is preserved for arbitrary tangent origins and action sequences.

This is an exact finite-window LTV identity, not a globally closed nonlinear
observer. Complete state and known training context supply all charged coefficients.
"""

from dataclasses import dataclass
import time

import numpy as np

from cell_field_response_v5 import build_response


@dataclass
class FutureLossField:
    observations: list
    inputs: list
    cpu_ns: int
    wall_ns: int

    def forecast(self, actions, initial=None):
        actions = np.asarray(actions,dtype=np.float64)
        h,p = len(self.inputs),self.inputs[0].shape[1]
        if actions.shape != (h,p) or not np.isfinite(actions).all():
            raise ValueError("finite frozen action sequence required")
        full_dim = self.observations[0].shape[1]
        initial = np.zeros(full_dim) if initial is None else np.asarray(initial,dtype=np.float64)
        if initial.shape != (full_dim,) or not np.isfinite(initial).all():
            raise ValueError("finite complete tangent origin required")
        field = self.observations[0] @ initial
        rows,retained = [field[:2].copy()],[field.copy()]
        for k,action in enumerate(actions):
            field = field[2:] + self.inputs[k] @ action
            rows.append(field[:2].copy())
            retained.append(field.copy())
        return {"losses":np.asarray(rows),"fields":retained}

    def terminal_maps(self):
        return np.asarray([matrix[-2:] for matrix in self.inputs])

    def arrays(self):
        h,p = len(self.inputs),self.inputs[0].shape[1]
        observation = np.zeros((h+1,2*(h+1),3*p))
        inputs = np.zeros((h,2*h,p))
        for k,row in enumerate(self.observations):
            observation[k,:len(row)] = row
        for k,row in enumerate(self.inputs):
            inputs[k,:len(row)] = row
        return {"field_observations":observation,"field_inputs":inputs,
                "field_dimensions":np.asarray([len(row) for row in self.observations])}


def from_response(response):
    cpu,wall = time.process_time_ns(),time.perf_counter_ns()
    h,p = len(response.transitions),response.gradients.shape[-1]
    observation = [None]*(h+1)
    inputs = [None]*h
    observation[h] = np.hstack((response.gradients[h],np.zeros((2,2*p))))
    for k in range(h-1,-1,-1):
        inputs[k] = response.dt*observation[k+1][:,:p]
        current = np.hstack((response.gradients[k],np.zeros((2,2*p))))
        transported = response.transitions[k].vjp(observation[k+1].T).T
        observation[k] = np.vstack((current,transported))
    if not all(np.isfinite(row).all() for row in (*observation,*inputs)):
        raise ValueError("nonfinite finite-window field coefficients")
    return FutureLossField(observation,inputs,time.process_time_ns()-cpu,time.perf_counter_ns()-wall)


def build_field(state,split,*,horizon=8,dt=.02):
    response = build_response(state,split["current_train"],
        (split["current_probe"],split["old_probe"]),horizon=horizon,dt=dt)
    field = from_response(response)
    return response,field
