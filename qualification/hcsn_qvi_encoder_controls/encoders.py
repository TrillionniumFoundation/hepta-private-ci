"""Fixed causal feature maps with at most two editable scalar coordinates."""
import math

import torch


class EconomyEncoder:
    def __init__(self, mode, width, seed):
        if mode not in {"audio", "lif", "attention"}:
            raise ValueError("unknown encoder mode")
        self.mode = mode
        self.width = width
        self.channels = 0 if mode == "audio" else 9
        generator = torch.Generator(device="cpu").manual_seed(seed)

        def random_projection(n, out):
            return torch.randn((n, out), generator=generator, dtype=torch.float64) / math.sqrt(n)

        self.matrices = []
        if mode == "lif":
            self.matrices = [random_projection(width, 9)]
        if mode == "attention":
            self.matrices = [random_projection(width, 9) for _ in range(3)]
            self.matrices.append(random_projection(9, 9))

    def origin(self):
        return torch.zeros(0 if self.mode == "audio" else 2, dtype=torch.float64)

    def counts(self, method):
        frozen = sum(matrix.numel() for matrix in self.matrices)
        nonlinear = self.origin().numel()
        head = (self.width + self.channels + 1) * 3
        return {"frozen_projections":frozen, "nonlinear_coordinates":nonlinear,
                "outer_trainable":nonlinear if method == "bp" else 0,
                "svd_trainable":head, "total_model":frozen+nonlinear+head,
                "total_fitted_or_BP_eligible":head+(nonlinear if method=="bp" else 0)}

    def features(self, theta, x, dt):
        if x.ndim != 3 or dt.shape != x.shape[:2] or x.shape[-1] != self.width:
            raise ValueError("unaligned observations/clock")
        if self.mode == "audio":
            return x
        if self.mode == "lif":
            current = x @ self.matrices[0] + theta[0]
            threshold = 0.5 * torch.exp(theta[1])
            voltage = torch.zeros_like(current[:, 0])
            history = []
            for t in range(x.shape[1]):
                voltage = torch.exp(-dt[:,t,None]) * voltage + current[:,t]
                margin = voltage - threshold
                hard = (margin >= 0).to(x.dtype)
                surrogate = torch.sigmoid(4.0 * margin)
                event = hard + (surrogate - surrogate.detach())
                voltage = voltage - threshold * event
                history.append(event)
            transformed = torch.stack(history, dim=1)
        else:
            wq, wk, wv, wo = self.matrices
            timeline = torch.cumsum(dt, dim=1)
            elapsed = timeline[:, :, None] - timeline[:, None, :]
            projections = (x @ wq) @ (x @ wk).transpose(-1,-2) / 3 + theta[0] * elapsed
            future = torch.ones_like(projections, dtype=torch.bool).triu(diagonal=1)
            weights = torch.softmax(projections.masked_fill(future, -torch.inf), dim=-1)
            transformed = torch.tanh((weights @ (x @ wv)) @ wo + theta[1])
        return torch.cat((x, transformed), dim=-1)
