"""Small causal content models; dense CTMC exponentials are reference kernels.

Each interval precedes its observation. Read before write. A missing observation
does not change the controlled generator or memory. The controlled threshold is
task-trained, not a He-Xiong optimal stopping boundary.
"""

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_distributional_v2.distribution_kernel import (
    Grid, initial_probability, make_flow, remap_operator)
from .marked_flow import assemble, values


ARMS = ("flow", "diagonal", "gru", "snn", "transformer")
WIDTH = 24
STATES = 5


class SurrogateSpike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, voltage):
        ctx.save_for_backward(voltage)
        return (voltage >= 0).to(voltage.dtype)

    @staticmethod
    def backward(ctx, gradient):
        voltage, = ctx.saved_tensors
        return gradient / (1 + 5 * voltage.abs()).square()


class ContentModel(nn.Module):
    def __init__(self, arm, input_dim, classes=8):
        super().__init__()
        if arm not in ARMS:
            raise ValueError(arm)
        self.arm, self.classes = arm, classes
        self.encode = nn.Sequential(nn.Linear(input_dim, WIDTH), nn.Tanh(),
                                    nn.Linear(WIDTH, WIDTH), nn.Tanh())
        self.intervention = None  # Evaluation-only; original checkpoint unchanged.
        if arm in ("flow", "diagonal"):
            self.write = nn.Linear(WIDTH, 1)
            nn.init.constant_(self.write.bias, -1.5)
            self.control = nn.Linear(WIDTH, 2 if arm == "flow" else STATES)
            self.physical = nn.Parameter(torch.tensor([-1., -1., 0., 1., -3.]))
            self.read = nn.Sequential(nn.Linear(STATES * WIDTH + STATES + 3 + WIDTH, 64),
                                      nn.Tanh(), nn.Linear(64, classes))
        elif arm == "gru":
            self.cell = nn.GRUCell(WIDTH, 64)
            self.decay = nn.Parameter(torch.full((64,), -3.))
            self.read = nn.Sequential(nn.Linear(64 + WIDTH, 64), nn.Tanh(),
                                      nn.Linear(64, classes))
        elif arm == "snn":
            self.incoming = nn.Linear(WIDTH, 64)
            self.recurrent = nn.Linear(64, 64, bias=False)
            self.decay = nn.Parameter(torch.full((64,), -1.))
            self.read = nn.Sequential(nn.Linear(128 + WIDTH, 64), nn.Tanh(),
                                      nn.Linear(64, classes))
        else:
            self.time = nn.Linear(4, WIDTH)
            self.qkv = nn.Linear(WIDTH, 3 * WIDTH)
            self.project = nn.Linear(WIDTH, WIDTH)
            self.norm1, self.norm2 = nn.LayerNorm(WIDTH), nn.LayerNorm(WIDTH)
            self.ff = nn.Sequential(nn.Linear(WIDTH, 4 * WIDTH), nn.GELU(),
                                    nn.Linear(4 * WIDTH, WIDTH))
            self.read = nn.Linear(WIDTH, classes)

    def _flow_matrices(self, encoded, dt, observed):
        batch, steps = dt.shape
        # Index zero is the initial policy; observation t creates policy t+1.
        control = self.control(encoded).double()
        control = torch.cat((torch.zeros(batch, 1, 2, dtype=torch.float64,
                                         device=dt.device), control), 1)
        old, new, previous = [], [], torch.zeros(batch, dtype=torch.long, device=dt.device)
        for t in range(steps):
            old.append(previous)
            previous = torch.where(observed[:, t], t + 1, previous)
            new.append(previous)
        old, new = torch.stack(old, 1), torch.stack(new, 1)
        rows = torch.arange(batch, device=dt.device)[:, None]
        before, after = control[rows, old], control[rows, new]
        physical = self.physical.double()
        sigma = .15 + .4 * torch.sigmoid(physical[0])
        tau = .15 + .7 * torch.sigmoid(physical[1])
        eta = torch.sigmoid(physical[3])
        decay = .05 * torch.sigmoid(physical[4])
        if self.intervention == "no_marks":
            eta = eta * 0 + 1
        boundary = .6 + .8 * torch.sigmoid(before[..., 0])
        mu = .05 + .9 * torch.sigmoid(before[..., 1] + physical[2])
        grid = Grid(cells=4, lower=-1.5, refractory_stages=1)
        flow = make_flow(mu, sigma, boundary, -.5, tau, grid)
        matrices = assemble(flow)
        q, r = matrices["Q"], matrices["R"]
        eye = torch.eye(STATES, dtype=q.dtype, device=q.device)
        p_transition = torch.matrix_exp(q * dt.double()[..., None, None])
        content_q = q - (1 - eta) * r - decay * eye
        content_transition = torch.matrix_exp(content_q * dt.double()[..., None, None])
        new_flow = make_flow(mu, sigma, .6 + .8 * torch.sigmoid(after[..., 0]), -.5, tau, grid)
        remap = remap_operator(boundary, new_flow)
        destination = F.one_hot(torch.tensor(4, device=q.device), STATES).double()
        event_map = remap["event_vector"][..., :, None] * destination
        content_remap = remap["transition"] - (1 - eta) * event_map
        value = values(flow, rho=.5, cost=.2)
        initial_flow = make_flow(mu[:, 0], sigma, boundary[:, 0], -.5, tau, grid)
        return dict(P=p_transition.float(), T=content_transition.float(),
                    R=remap["transition"].float(), MR=content_remap.float(),
                    initial=initial_probability(initial_flow, -.5).float(),
                    J=value["value_vector"].float(), G=value["next_event_discount_vector"].float(),
                    b=boundary.float())

    def forward(self, x, dt, observed):
        if x.ndim != 3 or dt.shape != x.shape[:2] or observed.shape != dt.shape:
            raise ValueError("Expected x[B,T,D], dt[B,T], observed[B,T]")
        if (bool((dt < 0).any()) or not bool(torch.isfinite(dt).all())
                or not bool(torch.isfinite(x).all())):
            raise ValueError("Finite inputs and nonnegative time required")
        encoded = self.encode(x)
        if self.arm == "transformer":
            elapsed = dt.cumsum(1)
            position = observed.cumsum(1).to(dt.dtype)
            times = torch.stack((torch.log1p(elapsed), torch.sin(elapsed),
                                 torch.cos(elapsed), position / 16), -1)
            h = encoded + self.time(times)
            b, t, _ = h.shape
            q, k, v = self.qkv(h).reshape(b, t, 3, 4, WIDTH // 4).permute(2, 0, 3, 1, 4)
            causal = torch.ones(t, t, dtype=torch.bool, device=x.device).tril()
            allowed = causal[None] & observed[:, None, :]
            # All-masked propagation placeholders are never scored or retained.
            allowed = allowed | ((~allowed.any(-1))[..., None] & torch.eye(t, dtype=torch.bool, device=x.device))
            attended = F.scaled_dot_product_attention(q, k, v, attn_mask=allowed[:, None])
            h = self.norm1(h + self.project(attended.transpose(1, 2).reshape(b, t, WIDTH)))
            h = self.norm2(h + self.ff(h))
            return self.read(h)
        batch, steps = dt.shape
        outputs = []
        if self.arm in ("flow", "diagonal"):
            memory = x.new_zeros(batch, STATES, WIDTH)
            if self.arm == "flow":
                matrices = self._flow_matrices(encoded, dt, observed)
                probability = matrices["initial"]
            else:
                probability = x.new_full((batch, STATES), 1 / STATES)
            for t in range(steps):
                if self.arm == "flow":
                    probability = (probability[:, None] @ matrices["P"][:, t]).squeeze(1)
                    memory = matrices["T"][:, t].transpose(-1, -2) @ memory
                    extra = torch.stack(((probability * matrices["J"][:, t]).sum(-1),
                                         (probability * matrices["G"][:, t]).sum(-1),
                                         matrices["b"][:, t]), -1)
                    if self.intervention == "factorized_content":
                        factorized = probability[..., None] * memory.sum(1, keepdim=True)
                        memory = torch.where(observed[:, t, None, None], factorized, memory)
                else:
                    memory = memory * torch.exp(-F.softplus(self.physical)[None, :, None]
                                                  * dt[:, t, None, None])
                    extra = x.new_zeros(batch, 3)
                outputs.append(self.read(torch.cat((memory.flatten(1), probability, extra,
                                                    encoded[:, t]), -1)))
                if self.arm == "flow":
                    probability = (probability[:, None] @ matrices["R"][:, t]).squeeze(1)
                    memory = matrices["MR"][:, t].transpose(-1, -2) @ memory
                    write_distribution = probability
                else:
                    write_distribution = self.control(encoded[:, t]).softmax(-1)
                gate = self.write(encoded[:, t]).sigmoid() * observed[:, t, None]
                memory = (1 - gate[..., None]) * memory + gate[..., None] * (
                    write_distribution[..., None] * encoded[:, t, None, :])
            return torch.stack(outputs, 1)
        hidden = x.new_zeros(batch, 64)
        spikes = torch.zeros_like(hidden)
        for t in range(steps):
            hidden = hidden * torch.exp(-F.softplus(self.decay) * dt[:, t, None])
            features = (hidden, encoded[:, t]) if self.arm == "gru" else (hidden, spikes, encoded[:, t])
            outputs.append(self.read(torch.cat(features, -1)))
            if self.arm == "gru":
                updated = self.cell(encoded[:, t], hidden)
            else:
                voltage = hidden + self.incoming(encoded[:, t]) + self.recurrent(spikes)
                new_spikes = SurrogateSpike.apply(voltage - 1)
                updated = voltage - new_spikes
                spikes = torch.where(observed[:, t, None], new_spikes, spikes)
            hidden = torch.where(observed[:, t, None], updated, hidden)
        return torch.stack(outputs, 1)

    def resource_shape(self, sequence_length):
        parameters = sum(p.numel() for p in self.parameters())
        state = {"flow": STATES * (WIDTH + 1) + 2, "diagonal": STATES * WIDTH,
                 "gru": 64, "snn": 128, "transformer": 2 * WIDTH * sequence_length}[self.arm]
        return dict(parameters=parameters, persistent_state_scalars=state,
                    matrix_precision="float64" if self.arm == "flow" else None,
                    content_precision="float32", compiled=False,
                    state_note="Transformer value is conceptual K/V; this reference recomputes prefixes")
