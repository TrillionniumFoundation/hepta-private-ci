"""Persistent content models; HX channels participate in trained content updates.

The explicit source-tick reset/refractory rule is a new neural mapping, not
continuous first-passage sampling or the financial paper's post-default model.
"""

import math
import torch
from torch import nn
from .hx_torch import FinancialMap


ROW, STEPS, HIDDEN, CELLS = 55, 6, 32, 8
FAMILIES = ("hx_full", "hx_margin", "ordinary_gate", "gru", "ssm", "history")


class Model(nn.Module):
    def __init__(self, family, classes):
        super().__init__()
        if family not in FAMILIES:
            raise ValueError("Unknown declared family")
        self.family, self.classes = family, classes
        self.financial = FinancialMap()
        # Frozen absolute asset units. Changing a boundary buffer must not
        # silently rescale the encoded asset and erase boundary sensitivity.
        self.register_buffer("asset_log_anchor", self.financial.boundary.log().detach().clone()+.5)
        if family in FAMILIES[:3]:
            self.asset_drive = nn.Linear(ROW, CELLS)
            self.candidate = nn.Linear(ROW+HIDDEN, HIDDEN)
            self.gate = nn.Linear(ROW+HIDDEN+5*CELLS, HIDDEN)
            self.rate = nn.Parameter(torch.zeros(HIDDEN))
            self.reset_content = nn.Parameter(torch.zeros(HIDDEN))
        elif family == "gru":
            self.update = nn.GRUCell(ROW, HIDDEN)
        elif family == "ssm":
            self.rate_net, self.gain, self.drive = (nn.Linear(ROW, HIDDEN) for _ in range(3))
        width = STEPS*ROW+STEPS+(0 if family == "history" else HIDDEN)
        self.reader = nn.Sequential(nn.Linear(width, 64), nn.Tanh(), nn.Linear(64, classes))
        self.double()

    def step(self, row, state, mode=None):
        h, membrane, cooldown = state
        dt = row[:, 34:35]
        reset, restored = torch.zeros_like(membrane, dtype=torch.bool), cooldown > 0
        if self.family in FAMILIES[:3]:
            mode = self.family if mode is None else mode
            if mode not in FAMILIES[:3]:
                raise ValueError("Invalid execution channel intervention")
            cooldown_before = cooldown
            cooldown = torch.clamp(cooldown-dt, min=0)
            active = cooldown == 0
            active_dt = torch.clamp(dt-cooldown_before, min=0)
            drift = self.financial.p.rate-self.financial.p.payout-.5*self.financial.p.volatility**2
            proposed = membrane + drift*active_dt + .5*torch.tanh(self.asset_drive(row))
            log_asset = self.asset_log_anchor+1.5*torch.tanh(proposed)
            reset = active & (log_asset <= torch.log(self.financial.boundary))
            if mode == "hx_full":
                features = self.financial(log_asset)
            elif mode == "hx_margin":
                z = log_asset-torch.log(self.financial.boundary)
                features = torch.stack((z, torch.zeros_like(z), torch.zeros_like(z),
                                        torch.zeros_like(z), torch.zeros_like(z)), -1)
            else:
                z = log_asset-torch.log(self.financial.boundary)
                features = torch.stack((z, torch.sigmoid(2*z), torch.sigmoid(-2*z),
                                        torch.sigmoid(-z)-1, .5*torch.tanh(z)), -1)
            gate = torch.sigmoid(self.gate(torch.cat((row, h, features.flatten(1)), -1)))
            proposal = torch.tanh(self.candidate(torch.cat((row, h), -1)))
            decay = torch.exp(-nn.functional.softplus(self.rate)*active_dt.repeat_interleave(HIDDEN//CELLS, dim=1))
            candidate = (1-gate)*decay*h+gate*proposal
            reset_cells = reset.repeat_interleave(HIDDEN//CELLS, dim=1)
            active_cells = active.repeat_interleave(HIDDEN//CELLS, dim=1)
            h = torch.where(reset_cells, self.reset_content, torch.where(active_cells, candidate, h))
            membrane = torch.where(reset, torch.full_like(proposed, .5), torch.where(active, proposed, membrane))
            cooldown = torch.where(reset, torch.full_like(cooldown, .5), cooldown)
            restored = (cooldown_before > 0) & active
        elif self.family == "gru":
            h = self.update(row, h)
        elif self.family == "ssm":
            decay = torch.exp(-nn.functional.softplus(self.rate_net(row))*dt)
            gain = torch.sigmoid(self.gain(row))
            h = (1-gain)*decay*h+gain*torch.tanh(self.drive(row))
        return (h, membrane, cooldown), {"reset": reset, "restored": restored}

    def initial(self, row):
        return (row.new_zeros((len(row), HIDDEN)), row.new_full((len(row), CELLS), -.25),
                row.new_zeros((len(row), CELLS)))

    def classify(self, history, state):
        if not 1 <= len(history) <= STEPS:
            raise ValueError("Content readout requires one to six accepted rows")
        x = torch.stack(history, 1)
        padded = torch.cat((x, x.new_zeros((len(x), STEPS-len(history), ROW))), 1)
        mask = (torch.arange(STEPS, device=x.device) < len(history)).to(x.dtype).expand(len(x), -1)
        features = torch.cat((padded.flatten(1), mask), -1)
        if self.family != "history":
            features = torch.cat((features, state[0]), -1)
        return self.reader(features)

    def forward(self, x, mode=None, return_events=False):
        state = self.initial(x[:, 0])
        outputs, events = [], []
        for step in range(STEPS):
            state, event = self.step(x[:, step], state, mode)
            outputs.append(self.classify([x[:, i] for i in range(step+1)], state)); events.append(event)
        logits = torch.stack(outputs, 1)
        return (logits, events) if return_events else logits
