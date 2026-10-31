"""Unbounded Gaussian/probit endpoint policy using the common learned readout."""

import hashlib
import json
import math
import struct
import time

import numpy as np
import torch

from ..round7.policy import keyed_uniform
from ..round7.task import ACTIONS, features, legal_actions
from .kernels import gaussian_events, gaussian_propagate, probit_events


class UnboundedGaussianPolicy:
    """Exact latent propagation; quadrature only evaluates the nonlinear readout.

    No event is emitted and no voltage is clipped or reset. With hard
    deployment, the actual continuous sample is propagated at the next tick.
    With mean deployment, the entire Gaussian law is propagated and readout
    expectations use a declared Gauss-Hermite order.
    """

    def __init__(self, model, *, seed=0, deployment="hard", order=48, operator="gaussian"):
        if deployment not in ("hard", "mean") or operator not in ("gaussian", "probit"):
            raise ValueError("invalid unbounded endpoint policy")
        self.model, self.seed, self.deployment = model, int(seed), deployment
        self.operator, self.order, self.calls = operator, order, 0
        self.mean = torch.tensor(0.0, dtype=torch.float64)
        self.variance = torch.tensor(0.0, dtype=torch.float64)
        nodes, weights = np.polynomial.hermite.hermgauss(order)
        self.nodes = torch.from_numpy(nodes)
        self.weights = torch.from_numpy(weights / math.sqrt(math.pi))

    def snapshot(self):
        return {"schema": "unbounded-gaussian-policy-v1", "seed": self.seed, "calls": self.calls,
                "mean": float(self.mean), "variance": float(self.variance),
                "deployment": self.deployment, "quadrature_order": self.order,
                "operator": self.operator, "leak": 0.0}

    @torch.no_grad()
    def act(self, state):
        started = time.perf_counter_ns()
        x = torch.from_numpy(features(state)[None])
        content, drive = self.model.encode(x)
        p = self.model.core.physical_parameters()
        kernel_start = time.perf_counter_ns()
        mean, variance = gaussian_propagate(self.mean, self.variance, drive[0], p["diffusion"], 1.0)
        event_function = gaussian_events if self.operator == "gaussian" else probit_events
        endpoint_partition = event_function(mean, variance, -p["boundary"], p["boundary"])
        kernel_ns = time.perf_counter_ns() - kernel_start
        if self.deployment == "hard":
            uniform = torch.tensor(keyed_uniform(self.seed, self.calls, "latent"), dtype=torch.float64)
            # SHA draws are in [0,1); a zero draw has a defined finite inverse
            # on this floating implementation's representable probability set.
            uniform = uniform.clamp(torch.finfo(torch.float64).tiny, 1 - torch.finfo(torch.float64).eps)
            self.mean = mean + torch.sqrt(variance) * torch.special.ndtri(uniform)
            self.variance = variance.new_zeros(())
            values, weights = self.mean.reshape(1), self.mean.new_ones(1)
        else:
            self.mean, self.variance = mean, variance
            values = mean + torch.sqrt(2 * variance) * self.nodes
            weights = self.weights
        latent = torch.stack((values, values.square(), torch.zeros_like(values), torch.zeros_like(values)), -1)
        public = torch.cat((x, content), -1).expand(len(values), -1)
        per_point = self.model.readout(torch.cat((public, latent), -1)).reshape(len(values), 2, len(ACTIONS))
        q = (weights[:, None] * per_point[:, 1, :]).sum(0)
        allowed = legal_actions(state)
        legal = torch.tensor([a in allowed for a in ACTIONS])
        action = ACTIONS[int(q.masked_fill(~legal, -torch.inf).argmax())]
        self.calls += 1
        encoded = json.dumps(self.snapshot(), sort_keys=True, allow_nan=False).encode()
        moments = [float(self.mean), float(self.variance), 0.0, 0.0]
        packet = struct.pack("<I5d", self.calls, *moments, 0.0) + action.encode()
        return action, {"q": q.tolist(), "event_count": 0.0, "expected_event_count": 0.0,
                        "kernel_ns": kernel_ns, "prediction_ns": time.perf_counter_ns() - started,
                        "moments": moments,
                        "endpoint_partition_put_idle_call": endpoint_partition.tolist(),
                        "state_bytes": len(encoded), "wire_bytes": len(packet), "wire_hex": packet.hex(),
                        "wire_semantics": "same concrete serialized packet as finite policies; not yet transported",
                        "state_sha256": hashlib.sha256(encoded).hexdigest(),
                        "event_semantics": "endpoint channel probabilities are diagnostics, not emitted spikes",
                        "propagation": "exact unbounded Brownian Gaussian; no tail folding",
                        "readout_quadrature_order": self.order if self.deployment == "mean" else 0}
