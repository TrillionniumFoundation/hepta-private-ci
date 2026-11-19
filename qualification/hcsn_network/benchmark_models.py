"""Small comparable encoders for a predeclared PenDigits CPU study."""

from dataclasses import replace
from fractions import Fraction
import torch
from ncps.torch import CfC
from qualification.hcsn_currentstate.differentiable import Work

from .network import FlowNetwork
from .phase_approximation import phase_forward
from .task_physics import task_physics


ARMS = ("flow", "flow_fixed", "flow_mass", "flow_no_return", "flow_erlang4",
        "gate", "gru", "cfc", "snn", "transformer")


class FlowClassifier(torch.nn.Module):
    def __init__(self, arm):
        super().__init__()
        self.arm = arm
        self.flow = FlowNetwork(2, 8, layers=2, dt=Fraction(1, 20),
                                message_mode="mass" if arm == "flow_mass" else "full")
        self.readout = torch.nn.Linear(16, 10)
        if arm == "flow_fixed":
            self.register_buffer("raw_cost", torch.zeros(()))
        else:
            self.raw_cost = torch.nn.Parameter(torch.zeros(()))
        self.last_state_bytes = self.last_physics_bytes = 0
        self.last_balance_error = None
        self.capture_state = False

    def episode(self):
        cost = .15+.02*self.raw_cost.tanh()
        theta = torch.cat((cost.new_tensor([-.2, .55, .3, 1.2, .8, .25]), cost[None]))
        return task_physics(theta)

    def forward(self, x):
        episode = self.episode()
        p = episode.physics
        if self.arm == "flow_no_return":
            # Counterfactual no return within this T=.5 episode: all emitted
            # mass waits beyond observation. The original boundary is retained
            # for a one-factor reset ablation; optimality is not transferred.
            p = replace(p, delay=Fraction(1))
        physics = (p, p)
        if self.arm == "flow_erlang4":
            _, state, generators = phase_forward(self.flow, x.transpose(0, 1), physics, 4)
            active = state.density[-1][1:, :state.active_nodes].sum(1).reshape(len(x), 8)
            cumulative = state.hits[-1][1:].reshape(len(x), 8)
            self.last_physics_bytes = state.physics_tensor_bytes
            self.last_operator_bytes = state.operator_tensor_bytes
        else:
            work = Work()
            _, state = self.flow(x.transpose(0, 1), physics, work=work)
            self.last_forward_exponentials = work.exponentials
            self.last_largest_dimension = work.largest_dimension
            active = state.cells[-1].active[1:].sum(1).reshape(len(x), 8)
            cumulative = state.cells[-1].hits[1:].reshape(len(x), 8)
            self.last_physics_bytes = 2*sum(t.numel()*t.element_size() for t in
                (p.generator, p.lower, p.upper, p.reset, p.reward,
                 p.escape_reward, p.spike_reward, p.discount))
            self.last_operator_bytes = None
        self.last_state_bytes = state.tensor_bytes()
        # Reads are part of measured model work. No cached trajectory/graph
        # is retained between optimizer steps.
        self.last_state = state if self.capture_state else None
        self.last_balance_error = (max(float(t.detach().abs().max()) for t in state.balances())
                                   if self.capture_state else None)
        features = torch.cat((cumulative, active), 1)
        return self.readout(features)


class GateClassifier(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.gate = torch.nn.Linear(10, 16)
        self.readout = torch.nn.Linear(8, 10)

    def forward(self, x):
        h = x.new_zeros(len(x), 8)
        for step in x.unbind(1):
            candidate, gate = self.gate(torch.cat((step, h), 1)).chunk(2, 1)
            h = gate.sigmoid()*h + (1-gate.sigmoid())*candidate.tanh()
        self.last_state_bytes = h.numel()*h.element_size()
        return self.readout(h)


class RecurrentClassifier(torch.nn.Module):
    def __init__(self, arm):
        super().__init__()
        self.arm = arm
        self.rnn = (torch.nn.GRU(2, 6, batch_first=True) if arm == "gru"
                    else CfC(2, 6, backbone_units=0, backbone_layers=0, batch_first=True))
        self.readout = torch.nn.Linear(6, 10)

    def forward(self, x):
        if self.arm == "cfc":
            # Installed ncps CfC.forward squeezes a [batch,1] interval into
            # [batch], which does not broadcast over hidden units. Every
            # sample here has the same fixed interval; call its actual cell
            # with that scalar, retaining the original CfC equations.
            hidden = x.new_zeros(len(x), 6)
            for step in x.unbind(1):
                _, hidden = self.rnn.rnn_cell(step, hidden, .05)
            final = hidden
        else:
            y, hidden = self.rnn(x)
            final = y[:, -1]
        self.last_state_bytes = hidden.numel()*hidden.element_size()
        return self.readout(final)


class _SurrogateSpike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, voltage):
        ctx.save_for_backward(voltage)
        return (voltage >= 0).to(voltage.dtype)

    @staticmethod
    def backward(ctx, gradient):
        (voltage,) = ctx.saved_tensors
        return gradient/(1+5*voltage.abs()).square()


class SNNClassifier(torch.nn.Module):
    """Recurrent LIF, discrete spikes, surrogate BP and subtractive reset."""
    def __init__(self):
        super().__init__()
        self.input = torch.nn.Linear(2, 10)
        self.recurrent = torch.nn.Linear(10, 10, bias=False)
        self.readout = torch.nn.Linear(10, 10)

    def forward(self, x):
        voltage = x.new_zeros(len(x), 10)
        spike, count = torch.zeros_like(voltage), torch.zeros_like(voltage)
        for step in x.unbind(1):
            voltage = .8*voltage + self.input(step) + self.recurrent(spike)
            spike = _SurrogateSpike.apply(voltage-1.)
            voltage = voltage-spike.detach()
            count = count+spike
        self.last_state_bytes = sum(t.numel()*t.element_size() for t in (voltage, spike, count))
        return self.readout(count/x.shape[1])


class TransformerClassifier(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.input = torch.nn.Linear(2, 4)
        self.position = torch.nn.Parameter(torch.randn(10, 4)*.02)
        self.layer = torch.nn.TransformerEncoderLayer(4, 1, dim_feedforward=8,
                        dropout=0., batch_first=True, activation="gelu")
        self.readout = torch.nn.Linear(4, 10)

    def forward(self, x):
        y = self.input(x)+self.position[:x.shape[1]]
        mask = torch.ones(x.shape[1], x.shape[1], dtype=torch.bool, device=x.device).triu(1)
        return self.readout(self.layer(y, src_mask=mask)[:, -1])


def make_model(arm):
    if arm not in ARMS:
        raise ValueError("unknown frozen arm")
    if arm.startswith("flow"):
        model = FlowClassifier(arm)
    elif arm == "gate":
        model = GateClassifier()
    elif arm in ("gru", "cfc"):
        model = RecurrentClassifier(arm)
    elif arm == "snn":
        model = SNNClassifier()
    else:
        model = TransformerClassifier()
    return model.double()
