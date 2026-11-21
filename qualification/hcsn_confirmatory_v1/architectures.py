"""Named causal sequence implementations; no stand-ins for missing official CfC."""
import importlib.metadata
import math

import torch
from torch import nn
from torch.nn import functional as F

KINDS = ("hcsn_finite", "gru", "diagonal_linear_ct_ssm", "lif_surrogate",
         "causal_transformer", "official_cfc")
WIDTHS = dict(zip(KINDS, (28, 6, 28, 12, 4, 10)))


class UnavailableBaseline(RuntimeError):
    pass


class LinearCTSSM(nn.Module):
    """Diagonal stable linear ODE with exact zero-order-hold integration."""
    def __init__(self, width):
        super().__init__()
        self.input = nn.Linear(5, width)
        self.raw_decay = nn.Parameter(torch.linspace(-1., 1., width))

    def forward(self, inputs, dt):
        hidden, outputs = inputs.new_zeros(len(inputs), self.raw_decay.numel()), []
        rate = .01 + F.softplus(self.raw_decay)
        for t in range(inputs.shape[1]):
            decay = torch.exp(-dt[:, t, None] * rate)
            hidden = decay * hidden - torch.expm1(-dt[:, t, None] * rate) / rate * self.input(inputs[:, t])
            outputs.append(hidden)
        return torch.stack(outputs, 1)


class LIFSurrogate(nn.Module):
    """Leaky membrane, hard endpoint spikes/reset, logistic surrogate derivative.

    Refractory time is physical seconds. Expiry inside an interval permits only
    the remaining integration time. Threshold detection remains at sample edges,
    so this is not an exact event-time solver or EventProp.
    """
    def __init__(self, width):
        super().__init__()
        self.input = nn.Linear(5, width)
        self.recurrent = nn.Linear(width, width, bias=False)
        self.raw_tau = nn.Parameter(torch.full((width,), math.log(math.expm1(.09))))
        self.raw_threshold = nn.Parameter(torch.zeros(width))
        nn.init.constant_(self.input.bias, .5)

    def forward(self, inputs, dt):
        voltage = inputs.new_zeros(len(inputs), len(self.raw_tau))
        trace, refractory, outputs = torch.zeros_like(voltage), torch.zeros_like(voltage), []
        tau, threshold = .01 + F.softplus(self.raw_tau), .5 + self.raw_threshold.sigmoid()
        for t in range(inputs.shape[1]):
            elapsed = dt[:, t, None]
            active_time = (elapsed - refractory).clamp_min(0)
            drive = .5 + F.softplus(self.input(inputs[:, t]) + self.recurrent(trace))
            decay = torch.exp(-active_time / tau)
            voltage = decay * voltage + (1 - decay) * drive
            soft = torch.sigmoid(10 * (voltage - threshold))
            hard = ((voltage >= threshold) & (active_time > 0)).to(inputs)
            spike = (soft + (hard - soft).detach()) * (active_time > 0).to(inputs)
            voltage = voltage * (1 - spike)
            refractory = torch.where(hard.bool(), torch.full_like(refractory, .02),
                                     (refractory - elapsed).clamp_min(0))
            trace = torch.exp(-elapsed / .2) * trace + spike
            outputs.append(trace)
        return torch.stack(outputs, 1)


class CausalTransformer(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.input = nn.Linear(5, width)
        self.blocks = nn.ModuleList(nn.TransformerEncoderLayer(
            width, 1, dim_feedforward=width, dropout=0., batch_first=True,
            norm_first=True, activation="gelu") for _ in range(2))

    def forward(self, inputs, dt):
        hidden = self.input(inputs)
        times = dt.cumsum(1)
        frequency = hidden.new_tensor([1., .1])
        angles = times[:, :, None] * frequency
        hidden = hidden + torch.stack((angles.sin(), angles.cos()), -1).flatten(-2)
        mask = torch.ones(inputs.shape[1], inputs.shape[1], dtype=torch.bool, device=inputs.device).triu(1)
        for block in self.blocks:
            hidden = block(hidden, src_mask=mask)
        return hidden


class ArchitectureModel(nn.Module):
    def __init__(self, kind):
        super().__init__()
        if kind not in KINDS:
            raise ValueError("unsupported named architecture")
        self.kind, width = kind, WIDTHS[kind]
        if kind == "hcsn_finite":
            from qualification.hcsn_prepared.model import PreparedSequenceModel
            from qualification.hcsn_scale.model import ModelConfig
            self.encoder = PreparedSequenceModel(ModelConfig("hcsn", 5, width, .1))
            self.encoder.predictor = nn.Identity()  # unused next-sensor head is not counted/trained
            channels = self.encoder.feature_width
        elif kind == "gru":
            self.encoder, channels = nn.GRU(5, width, batch_first=True), width
        elif kind == "diagonal_linear_ct_ssm":
            self.encoder, channels = LinearCTSSM(width), width
        elif kind == "lif_surrogate":
            self.encoder, channels = LIFSurrogate(width), width
        elif kind == "causal_transformer":
            self.encoder, channels = CausalTransformer(width), width
        else:
            try:
                importlib.metadata.version("ncps")
                from ncps.torch import CfC
            except (ImportError, importlib.metadata.PackageNotFoundError) as error:
                raise UnavailableBaseline("official ncps.torch.CfC is not installed") from error
            self.encoder = CfC(5, width, batch_first=True, return_sequences=True,
                               backbone_units=4, backbone_layers=1, backbone_dropout=0.)
            channels = width
        self.readout = nn.Linear(3 * channels, 1)
        self.register_buffer("mean", torch.zeros(3 * channels))
        self.register_buffer("scale", torch.ones(3 * channels))
        self.double()
        count = sum(p.numel() for p in self.parameters())
        if not 238 <= count <= 322:
            raise ValueError(f"declared 280±15% parameter band violated: {kind} has {count}")

    def sequence(self, data):
        x, dt = torch.from_numpy(data["x"]), torch.from_numpy(data["dt"])
        inputs = torch.cat((x, torch.log1p(dt[:, :, None] / .1)), -1)
        if self.kind == "hcsn_finite":
            return self.encoder.encode_batch(inputs, dt)
        if self.kind == "gru":
            return self.encoder(inputs)[0]
        if self.kind == "official_cfc":
            spans = dt[:, :, None].expand(-1, -1, self.encoder.state_size)
            return self.encoder(inputs, timespans=spans)[0]
        return self.encoder(inputs, dt)

    def representations(self, data):
        hidden = self.sequence(data)
        query = torch.from_numpy(data["x"][:, -1, 3:4])
        return torch.cat((hidden[:, -1], hidden.mean(1), query * hidden.mean(1)), 1)

    def forward(self, data):
        return self.readout((self.representations(data) - self.mean) / self.scale)

    def identity(self):
        count = sum(p.numel() for p in self.parameters())
        return {"kind": self.kind, "width": WIDTHS[self.kind], "parameters": count,
                "target_parameters": 280, "relative_difference": (count - 280) / 280,
                "trainable_names": [name for name, _ in self.named_parameters()],
                "input": "same four channels plus log1p(actual_dt/0.1)",
                "time": "same individual physical dt; causal derived times permitted",
                "pool": "same last/mean/query-times-mean; no task-specific semantic prior",
                "parameter_matching_only": "state size, operations and memory are not matched"}

