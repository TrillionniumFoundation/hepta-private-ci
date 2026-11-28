"""Explicit graph intervention; original physical forward copied with three declared changes.

Origin: frozen_readout_diagnostic.py SHA256
509ca451c61285927ae0e813870143a21503b9dc4808129744c56bdb34828b72.
Changes: optional bridge argument; final-step coefficient capture/tied signed mark;
return coefficients. No probability, QVI, reset, timing or existing head changes.
"""
import time
import numpy as np
from temporal_probe import previous
_old = previous()

class BridgeReplay(_old.Replay):
    def forward(self, x, baseline, bridge=False):
        started = time.perf_counter()
        b, steps, choices, width = x.shape
        seq = x.transpose(1, 0, 2, 3).reshape(steps, b*choices, width)
        batch = b*choices
        assert 1 <= batch <= 256 and steps == 6 and choices == 2
        boundary = np.broadcast_to(self.fixed, (batch, 8))
        density = np.zeros((batch, 8, 2, 10))
        density[..., 0, :6] = self.deposit(self.absolute-boundary)
        message = np.zeros((batch, 3, 8))
        worst = {"mass_error": 0., "mark_excess": 0., "negative_probability": 0., "risk_count_excess": 0.}
        recurrent = self.w["recurrent.weight"]*self.w["synaptic_mask"]
        for tick, inputs in enumerate(seq):
            if tick:
                message = message.copy()
                message[:, 0] -= self.fixed
            learned_message = message.astype(np.float32)
            learned_message[:, 1:] = 0.
            rec = learned_message.reshape(batch, 24) @ recurrent.T
            drive = np.pad(inputs @ self.w["input_drive.weight"].T+self.w["input_drive.bias"], ((0, 0), (0, 4)))+rec
            raw_mark = np.pad(inputs @ self.w["input_mark.weight"].T+self.w["input_mark.bias"], ((0, 0), (0, 4)))+rec
            old_boundary = boundary
            if tick % 2 == 0:
                drift = (-.2+.15*np.tanh(drive)).astype(np.float64)
                cost = (.15+.02*np.tanh(self.w["raw_cost"]+.15*drive)).astype(np.float64)
                boundary = self.qvi(drift, cost)
                propagate, first_prob, value_vector = self.operators(drift, boundary, cost)
            index = np.arange(7, dtype=np.float64)
            cdf = np.clip((boundary-old_boundary)[..., None, None]/self.h+index[None, :]-index[:-1, None], 0., 1.)
            overlap = cdf[..., 1:]-cdf[..., :-1]
            lower, upper = cdf[..., 0], 1-cdf[..., -1]
            old = density[..., :6]
            jump = (old*lower[..., None, :]).sum(-1)
            projected = (old*upper[..., None, :]).sum(-1)
            active = old @ overlap
            active[..., -1] += projected
            remapped = np.concatenate((active, density[..., 6:]), -1)
            remapped[..., 6] += jump
            if tick == 5:
                weighted_history = remapped[..., 1, :].copy()
                weighted_history[..., :6] *= .5
                offset = (jump[..., 1] + (weighted_history*propagate[..., :10, 10]).sum(-1))/self.dt
                alpha = .5*(remapped[..., 0, :6]*propagate[..., :6, 10]).sum(-1)/self.dt
                basis = {"offset": offset[:, 4:].copy(), "alpha": alpha[:, 4:].copy(),
                         "rec": rec[:, 4:].copy(), "xlast": inputs.copy()}
                if bridge:
                    raw_mark[:, 4:] += inputs @ self.w["input_mark.weight"].T+self.w["input_mark.bias"]
            mark = np.tanh(raw_mark).astype(np.float64)
            written = remapped.copy()
            written[..., 1, :6] = .5*remapped[..., 1, :6]+.5*mark[..., None]*remapped[..., 0, :6]
            result = np.pad(written, ((0, 0), (0, 0), (0, 0), (0, 2))) @ propagate
            density, increments = result[..., :10], result[..., 10:]
            never_hit = written[..., 0, :].copy()
            never_hit[..., 6] -= jump[..., 0]
            risk = jump[..., 0]+(never_hit*first_prob).sum(-1)
            continuation = (density[..., 0, :]*value_vector).sum(-1)
            margin = (density[..., 0, :6]*self.centers).sum(-1)/self.extent
            hits = jump+increments[..., 0]
            assert np.min(risk) >= -2e-9 and np.max(risk) <= 1+2e-9 and np.max(risk-hits[..., 0]) <= 2e-9
            features = np.stack((continuation, risk, hits[..., 1]/self.dt, hits[..., 0]/self.dt, margin), -1)[:, 4:].reshape(batch, 20).astype(np.float32)
            message = np.stack((boundary, hits[..., 0]/self.dt, hits[..., 1]/self.dt), 1)
            worst["mass_error"] = max(worst["mass_error"], float(np.max(np.abs(density[..., 0, :].sum(-1)-1))))
            worst["mark_excess"] = max(worst["mark_excess"], float(np.max(np.abs(density[..., 1, :])-density[..., 0, :])))
            worst["negative_probability"] = max(worst["negative_probability"], float(-np.min(density[..., 0, :])))
            worst["risk_count_excess"] = max(worst["risk_count_excess"], float(np.max(risk-hits[..., 0])))
            assert np.isfinite(density).all() and max(worst.values()) <= 2e-9
        f = features.reshape(b, 2, 20)
        logits = f @ self.w["readout.weight"].T+self.w["readout.bias"]
        scores = baseline+(logits[..., 1]-logits[..., 0])
        basis["features"] = f.copy()
        basis["baseline"] = baseline.copy()
        return f, scores, {**worst, "wall_seconds": time.perf_counter()-started, "operator_builds": 3, "ticks": 6}, basis
