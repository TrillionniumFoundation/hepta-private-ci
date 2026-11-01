"""Fitted ordinary recurrent propagators for the legacy renewal assay.

The recurrent sequence consists of four public internal forecast-time nodes,
not four newly observed world states. This is a distribution-replacement
diagnostic; it is not the missing persistent AV GRU/SSM comparison.
"""

import copy
import time

import numpy as np
import torch
from torch import nn

from experiments.hcsn_mechanism_content_v2.renewal import propagation_dataset


class RecurrentCountModel(nn.Module):
    def __init__(self, family, mean, scale, width=32, cap=32):
        super().__init__()
        if family not in ("gru", "ssm"):
            raise ValueError("Expected gru or ssm")
        self.family, self.width, self.cap = family, width, cap
        self.register_buffer("mean", torch.as_tensor(mean, dtype=torch.float64))
        self.register_buffer("scale", torch.as_tensor(scale, dtype=torch.float64))
        if family == "gru":
            self.update = nn.GRUCell(7, width)
        else:
            self.rate = nn.Linear(7, width)
            self.drive = nn.Linear(7, width)
        self.readout = nn.Sequential(nn.Linear(width, width), nn.SiLU(), nn.Linear(width, cap))
        self.double()

    def forward(self, packet):
        h = packet.new_zeros((len(packet), self.width))
        for fraction in (0.0, 1 / 3, 2 / 3, 1.0):
            point = torch.cat((packet[:, :1], packet[:, 1:2] * fraction, packet[:, 2:]), dim=1)
            features = (point - self.mean) / self.scale
            if self.family == "gru":
                h = self.update(features, h)
            else:
                delta = packet[:, 1:2] / 4
                retention = torch.exp(-torch.nn.functional.softplus(self.rate(features)) * delta)
                h = retention * h + (1 - retention) * self.drive(features).tanh()
        logits = self.readout(h)
        n = torch.arange(self.cap, device=packet.device)[None]
        possible = (n == 0) | ((n - 1) * packet[:, 5:6] < packet[:, 1:2] - packet[:, 6:7])
        return logits.masked_fill(~possible, -1e30)


class FittedRecurrentCore:
    def __init__(self, model):
        self.model, self.cap = model.eval(), model.cap
        self.name = model.family
        self.calls = self.work = self.cdf_terms = 0

    def counts(self, x, horizon, physics, remaining=0):
        self.calls += 1
        if horizon <= remaining:
            p = np.zeros(self.cap)
            p[0] = 1
            return p
        packet = torch.tensor([[x, horizon, physics.nu, physics.sigma,
                                physics.reset, physics.refractory, remaining]], dtype=torch.float64)
        with torch.no_grad():
            return self.model(packet).softmax(-1)[0].numpy()


def fit_models(seed, train_size=8192, validation_size=1024, epochs=80):
    """Same sampled count labels, minibatch order, width and fit opportunities.

    Neither family receives analytic CDF labels. Selection uses a separate
    sampled-count validation set; all family outcomes and step-zero remain.
    """
    torch.set_num_threads(1)
    began = time.process_time()
    train_x, train_y, truth, _ = propagation_dataset(seed, train_size)
    val_x, val_y, val_truth, _ = propagation_dataset(seed + 89017, validation_size)
    mean = train_x.astype(np.float64).mean(0)
    scale = np.maximum(train_x.astype(np.float64).std(0), 1e-4)
    data = dict(train_x=train_x, train_y=train_y, truth=truth,
                validation_x=val_x, validation_y=val_y, validation_truth=val_truth)
    generation_cpu = time.process_time() - began
    tx, vx = torch.tensor(train_x, dtype=torch.float64), torch.tensor(val_x, dtype=torch.float64)
    ty, vy = torch.tensor(train_y), torch.tensor(val_y)
    orders = [torch.tensor(np.random.default_rng(np.random.SeedSequence([seed, e, 773])).permutation(train_size))
              for e in range(epochs)]
    models, reports = {}, {}
    for family in ("gru", "ssm"):
        torch.manual_seed(seed)
        model = RecurrentCountModel(family, mean, scale)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.003, weight_decay=1e-4)
        start = time.process_time()
        history, best, selected, weights = [], float("inf"), 0, None
        for epoch in range(epochs + 1):
            if epoch:
                model.train()
                for batch in orders[epoch - 1].split(256):
                    optimizer.zero_grad(set_to_none=True)
                    loss = nn.functional.cross_entropy(model(tx[batch]), ty[batch])
                    loss.backward()
                    optimizer.step()
            model.eval()
            with torch.no_grad():
                score = float(nn.functional.cross_entropy(model(vx), vy))
            history.append(score)
            if score < best:
                best, selected, weights = score, epoch, copy.deepcopy(model.state_dict())
        final_weights = copy.deepcopy(model.state_dict())
        model.load_state_dict(weights)
        models[family] = {"selected": weights, "final": final_weights, "mean": mean, "scale": scale}
        reports[family] = {
            "seed": seed, "train_size": train_size, "validation_size": validation_size,
            "epochs": epochs, "selected_epoch": selected, "validation_nll": best,
            "validation_nll_history": history, "fit_cpu_seconds_inclusive": time.process_time() - start,
            "parameter_count": sum(p.numel() for p in model.parameters()),
            "width": 32, "cap": 32, "dtype": "float64", "internal_forecast_nodes": [0, 1/3, 2/3, 1],
            "training_label_source": "independent inverse-Gaussian event samples",
            "persistent_AV_state": False,
        }
    return models, reports, data, generation_cpu


def load_core(checkpoint, family):
    item = checkpoint[family]
    model = RecurrentCountModel(family, item["mean"], item["scale"])
    model.load_state_dict(item["selected"])
    return FittedRecurrentCore(model)
