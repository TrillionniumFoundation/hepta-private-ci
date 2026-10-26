"""Closed local future-output field for the eight empirical V7 panels.

The H8 retained coordinates shrink72->8. The exact finite-window identity is
conditional on the nominal controlled reference; coefficients are constructed
from complete Adam state. Forecast inputs are deviations from nominal actions.
"""

from dataclasses import dataclass
import time

import numpy as np

from cell_field_response_v7 import build_response


@dataclass
class FuturePanelField:
    observations: list
    inputs: list
    cpu_ns: int
    wall_ns: int

    def forecast(self, delta_actions, initial=None):
        actions = np.asarray(delta_actions,dtype=np.float64)
        h,p,q = len(self.inputs),self.inputs[0].shape[1],len(self.observations[-1])
        if actions.shape!=(h,p) or not np.isfinite(actions).all():
            raise ValueError("finite action deviations from the nominal reference required")
        dimension = self.observations[0].shape[1]
        initial = np.zeros(dimension) if initial is None else np.asarray(initial,dtype=np.float64)
        if initial.shape!=(dimension,) or not np.isfinite(initial).all():
            raise ValueError("finite complete-state tangent origin required")
        retained = self.observations[0]@initial
        fields,losses = [retained.copy()],[retained[:q].copy()]
        for k,action in enumerate(actions):
            retained = retained[q:]+self.inputs[k]@action
            fields.append(retained.copy());losses.append(retained[:q].copy())
        return {"losses":np.asarray(losses),"fields":fields}

    def terminal_maps(self):
        q = len(self.observations[-1])
        return np.asarray([row[-q:] for row in self.inputs])

    def arrays(self):
        h,p,q = len(self.inputs),self.inputs[0].shape[1],len(self.observations[-1])
        observation = np.zeros((h+1,q*(h+1),3*p))
        inputs = np.zeros((h,q*h,p))
        for k,row in enumerate(self.observations):
            observation[k,:len(row)] = row
        for k,row in enumerate(self.inputs):
            inputs[k,:len(row)] = row
        return {"field_observations":observation,"field_inputs":inputs,
                "field_dimensions":np.asarray([len(row) for row in self.observations])}


def from_response(response):
    cpu,wall = time.process_time_ns(),time.perf_counter_ns()
    h,q,p = len(response.transitions),*response.gradients.shape[1:]
    if q!=8 or not 1<=h<=8:
        raise ValueError("V7 requires the declared eight-panel finite window")
    observation,inputs = [None]*(h+1),[None]*h
    observation[h] = np.hstack((response.gradients[h],np.zeros((q,2*p))))
    for k in range(h-1,-1,-1):
        inputs[k] = response.dt*observation[k+1][:,:p]
        current = np.hstack((response.gradients[k],np.zeros((q,2*p))))
        transported = response.transitions[k].vjp(observation[k+1].T).T
        observation[k] = np.vstack((current,transported))
    if not all(np.isfinite(row).all() for row in (*observation,*inputs)):
        raise ValueError("nonfinite future-panel field coefficients")
    return FuturePanelField(observation,inputs,time.process_time_ns()-cpu,time.perf_counter_ns()-wall)


def build_field(state, train, panels, *, horizon=8, dt=.02, nominal_actions=None):
    response = build_response(state,train,panels,horizon=horizon,dt=dt,nominal_actions=nominal_actions)
    return response,from_response(response)
