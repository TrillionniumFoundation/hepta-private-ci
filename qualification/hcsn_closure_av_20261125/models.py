"""Matched width-8 offline AV encoders; capacity is measured, not assumed equal."""

import math
import torch
from torch import nn
from torch.nn import functional as F

from qualification.hcsn_closure_20261124.fast_kernel import FastSignedHCSN
from qualification.hcsn_smallnet_20261124.model import ModelConfig


class BinarySpike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, voltage):
        ctx.save_for_backward(voltage)
        return (voltage >= 0).to(voltage)

    @staticmethod
    def backward(ctx, upstream):
        voltage, = ctx.saved_tensors
        return upstream/(1+voltage.abs()).square()


class LIF(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(8, 8)
        self.recurrent = nn.Linear(8, 8, bias=False)

    def forward(self, inputs):
        voltage = inputs.new_zeros(len(inputs), 8)
        spike = torch.zeros_like(voltage)
        outputs = []
        for value in inputs.unbind(1):
            voltage = .9*voltage+self.input(value)+self.recurrent(spike)
            spike = BinarySpike.apply(voltage-1)
            voltage = voltage-spike.detach()
            outputs.append(spike)
        result = torch.stack(outputs, 1)
        self.diagnostics = {"logical_state_bytes": 2*voltage.numel()*voltage.element_size(),
                            "physical_population_state_bytes": 0, "spike_fraction": float(result.detach().mean())}
        return result


class Encoder(nn.Module):
    def __init__(self, arm, seed):
        super().__init__()
        self.arm = arm
        with torch.random.fork_rng():
            torch.manual_seed(seed+101)
            self.frontend = nn.Linear(130, 8)
            torch.manual_seed(seed+202)
            if arm == "hcsn":
                self.core = FastSignedHCSN(ModelConfig(input_size=8, neurons=8, message_mode="flow",
                    boundary_mode="qvi", feature_bank="value_risk", precision="mixed", backend="uniformized"), scripted=True)
                self.core.readout = nn.Identity()
                dimension = self.core.feature_dim
            elif arm == "transformer":
                layer = nn.TransformerEncoderLayer(8, 2, dim_feedforward=16, dropout=0., batch_first=True, norm_first=True)
                self.core = nn.TransformerEncoder(layer, 1, enable_nested_tensor=False)
                dimension = 8
            elif arm == "lif":
                self.core, dimension = LIF(), 8
            else:
                raise ValueError("unknown AV arm")
            torch.manual_seed(seed+303)
            self.projection = nn.Linear(dimension, 32)
        self.diagnostics = {}

    def forward(self, inputs):
        if inputs.ndim != 3 or inputs.shape[1:] != (32, 130) or not bool(torch.isfinite(inputs).all()):
            raise ValueError("finite [batch,32,130] offline inputs required")
        values = torch.tanh(self.frontend(inputs))
        if self.arm == "hcsn":
            _, sequence, state = self.core(values.transpose(0, 1), return_features=True)
            sequence = sequence.transpose(0, 1)
            state_bytes = sum(t.numel()*t.element_size() for t in (state.density, state.boundary, state.drift, state.cost, state.message))
            self.diagnostics = {**self.core.last_diagnostics, "physical_population_state_bytes": state_bytes,
                                "logical_state_bytes": state_bytes}
        elif self.arm == "transformer":
            mask = torch.ones(32, 32, dtype=torch.bool, device=values.device).triu(1)
            sequence = self.core(values, mask=mask)
            self.diagnostics = {"physical_population_state_bytes": 0,
                "logical_state_bytes": sequence.numel()*sequence.element_size(),
                "state_scope": "32x8 token representation only; attention temporaries/autograd not counted; process peak RSS separately"}
        else:
            sequence = self.core(values)
            self.diagnostics = dict(self.core.diagnostics)
        return self.projection(sequence.mean(1))


class PairedEncoder(nn.Module):
    def __init__(self, arm, seed):
        super().__init__()
        self.arm, self.seed = arm, seed
        self.audio, self.video = Encoder(arm, seed+1000), Encoder(arm, seed+2000)
        with torch.random.fork_rng():
            torch.manual_seed(seed+3000)
            self.head = nn.Linear(32, 6)

    def forward(self, audio, video):
        if audio.shape != video.shape:
            raise ValueError("aligned paired modalities required")
        a, v = self.audio(audio), self.video(video)
        al, vl = self.head(a), self.head(v)
        return {"audio_embedding": a, "video_embedding": v, "audio_logits": al,
                "video_logits": vl, "fused_logits": .5*(al+vl)}

    def counts(self):
        total = sum(p.numel() for p in self.parameters())
        trainable = sum(p.numel() for p in self.parameters() if p.requires_grad)
        masked = 0
        if self.arm == "hcsn":
            for encoder in (self.audio, self.video):
                m = encoder.core.synaptic_mask.clone()
                m[:, :16] = 0
                masked += m.numel()-int(torch.count_nonzero(m))
        return {"total": total, "requires_grad": trainable, "structurally_active": trainable-masked,
                "masked_recurrent": masked, "scope": "exact declared masks, not effective functional rank; equal width is not equal capacity"}


def objective(output, labels):
    a = F.normalize(output["audio_embedding"], dim=-1, eps=1e-12)
    v = F.normalize(output["video_embedding"], dim=-1, eps=1e-12)
    scores = a@v.T/.1
    index = torch.arange(len(labels), device=labels.device)
    contrastive = .5*(F.cross_entropy(scores, index)+F.cross_entropy(scores.T, index))
    return (F.cross_entropy(output["fused_logits"], labels)
        +.25*(F.cross_entropy(output["audio_logits"], labels)+F.cross_entropy(output["video_logits"], labels))+.5*contrastive)
