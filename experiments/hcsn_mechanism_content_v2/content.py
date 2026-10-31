"""Shared causal content addressing with optional ordinary or finite-flow adapters.

The attention and content capacity are shared across adapter families. The
analytic adapter is the published finite-grid regenerative model, not a global
continuous He--Xiong solution. A shared-only arm isolates the common SDPA gain.
"""

import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_task_value_v1.model import RewardFlowCell


GROUPS = ("content", "dynamics", "boundary", "reset", "refractory")


def parameter_hash(module):
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str((str(value.dtype), tuple(value.shape))).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def positional(times, width):
    frequencies = torch.exp(torch.arange(0, width, 2, device=times.device,
                                        dtype=times.dtype) * (-math.log(10000) / width))
    phase = times[..., None] * frequencies
    return torch.stack((phase.sin(), phase.cos()), -1).flatten(-2)[..., :width]


class CausalAddressBlock(nn.Module):
    """Residual content-based retrieval, available identically to both families."""

    def __init__(self, width):
        super().__init__()
        self.heads = max(h for h in (1, 2, 4) if width % h == 0)
        self.norm1, self.norm2 = nn.LayerNorm(width), nn.LayerNorm(width)
        self.qkv, self.output = nn.Linear(width, 3 * width), nn.Linear(width, width)
        self.ffn = nn.Sequential(nn.Linear(width, 2 * width), nn.GELU(),
                                 nn.Linear(2 * width, width))

    def forward(self, sequence, valid):
        batch, length, width = sequence.shape
        qkv = self.qkv(self.norm1(sequence)).reshape(batch, length, 3,
                                                  self.heads, width // self.heads)
        query, key, value = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        causal = torch.ones(length, length, dtype=torch.bool, device=sequence.device).tril()
        mask = causal[None, None] & valid[:, None, None, :]
        retrieved = F.scaled_dot_product_attention(query, key, value, attn_mask=mask,
                                                   dropout_p=0.0)
        retrieved = retrieved.transpose(1, 2).reshape(batch, length, width)
        result = sequence + self.output(retrieved)
        return result + self.ffn(self.norm2(result))


class SharedContent(nn.Module):
    """Trainable feature encoder and causal residual SDPA; no pretrained claims."""

    def __init__(self, input_dim, output_dim, width, depth, audiovisual):
        super().__init__()
        self.audiovisual = audiovisual
        self.width = width
        if audiovisual:
            self.audio = nn.Sequential(nn.Linear(32, width), nn.GELU(), nn.Linear(width, width))
            self.video = nn.Sequential(nn.Linear(32, width), nn.GELU(), nn.Linear(width, width))
            self.metadata = nn.Linear(11, width)
        else:
            self.encoder = nn.Sequential(nn.Linear(input_dim + 3, width), nn.GELU(),
                                         nn.Linear(width, width))
        self.norm = nn.LayerNorm(width)
        self.blocks = nn.ModuleList(CausalAddressBlock(width) for _ in range(depth))
        self.readout = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, output_dim))

    def encode(self, x, dt, observed):
        clock = torch.stack((dt, dt.cumsum(1), observed.to(x.dtype)), -1)
        if self.audiovisual:
            encoded = (self.audio(x[..., :32]) * x[..., 34:35]
                       + self.video(x[..., :32]) * x[..., 35:36]
                       + self.metadata(torch.cat((x[..., 32:], clock), -1)))
        else:
            encoded = self.encoder(torch.cat((x, clock), -1))
        # Ordinal position is a causal count, not a full-sequence normalized time.
        index = torch.arange(x.shape[1], dtype=x.dtype, device=x.device)[None]
        return self.norm(encoded) + .2 * positional(index, self.width) + .1 * positional(dt.cumsum(1), self.width)

    def decode(self, sequence, valid):
        for block in self.blocks:
            sequence = block(sequence, valid)
        return self.readout(sequence)


class TwoGateAdapter(nn.Module):
    """Strong ordinary retention/write recurrence, including zero-dt arrivals."""

    def __init__(self, width):
        super().__init__()
        self.candidate = nn.Linear(2 * width, width)
        self.retention = nn.Linear(2 * width, width)
        self.write = nn.Linear(2 * width, width)
        self.raw_decay = nn.Parameter(torch.full((width,), -3.0))
        self.output = nn.Linear(width, width, bias=False)

    def forward(self, sequence, dt, observed):
        state = torch.zeros_like(sequence[:, 0])
        result = []
        for index in range(sequence.shape[1]):
            state = state * torch.exp(-F.softplus(self.raw_decay) * dt[:, index, None])
            joined = torch.cat((sequence[:, index], state), -1)
            keep = self.retention(joined).sigmoid()
            write = self.write(joined).sigmoid()
            proposed = keep * state + (1 - keep) * write * self.candidate(joined).tanh()
            state = torch.where(observed[:, index, None], proposed, state)
            result.append(sequence[:, index] + self.output(state))
        return torch.stack(result, 1), {"state": state}


class ContentModel(nn.Module):
    """Matched content stack, with explicitly scoped adapter and freeze groups."""

    def __init__(self, task, family="analytic", width=32, depth=2, seed=0, physical=1):
        super().__init__()
        if task not in ("selective_copy", "mqar", "async_av", "av_binding"):
            raise ValueError("Unknown content task")
        if family not in ("shared", "encoder_only", "two_gate", "analytic"):
            raise ValueError("Unknown content family")
        if width < 4 or depth < 1 or physical < 1:
            raise ValueError("Positive content dimensions required")
        self.config = dict(task=task, family=family, width=width, depth=depth,
                           seed=seed, physical=physical)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            audiovisual = task in ("async_av", "av_binding")
            self.common = SharedContent(40 if audiovisual else 64,
                2 if task == "av_binding" else 6 if audiovisual else 8, width,
                0 if family == "encoder_only" else depth, audiovisual)
            if family == "analytic":
                self.adapter = RewardFlowCell(width, physical=physical)
            elif family == "two_gate":
                self.adapter = TwoGateAdapter(width)
            else:
                self.adapter = None

    def forward(self, x, dt, observed=None, valid=None, return_aux=False, disable_adapter=False):
        if x.ndim != 3 or dt.shape != x.shape[:2] or not x.shape[1]:
            raise ValueError("Expected nonempty x[B,T,D] and dt[B,T]")
        if not bool(torch.isfinite(x).all() and torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("Nonfinite inputs or negative times")
        valid = torch.ones_like(dt, dtype=torch.bool) if valid is None else valid.bool()
        observed = valid if observed is None else observed.bool() & valid
        sequence = self.common.encode(x, dt, observed)
        auxiliary = {}
        if self.adapter is not None and not disable_adapter:
            if self.config["family"] == "analytic":
                adapted, state, auxiliary = self.adapter(sequence, dt, observed)
                auxiliary["state"] = state
            else:
                adapted, auxiliary = self.adapter(sequence, dt, observed)
            # Shared residual preserves a trained content path in every family.
            sequence = sequence + .2 * (adapted - sequence)
        if self.config["family"] == "encoder_only":
            count = valid.cumsum(1).clamp_min(1)[..., None]
            sequence = (sequence * valid[..., None]).cumsum(1) / count
        logits = self.common.decode(sequence, valid)
        return (logits, auxiliary) if return_aux else logits

    def parameter_groups(self):
        groups = {key: [] for key in GROUPS}
        for name, parameter in self.named_parameters():
            if any(part in name for part in ("raw_K", "raw_threshold", "reward_input", "raw_reward")):
                key = "boundary"
            elif "raw_reset" in name:
                key = "reset"
            elif "raw_refractory" in name:
                key = "refractory"
            elif any(part in name for part in ("drift_input", "mu_bias", "raw_sigma", "raw_rho", "raw_decay")):
                key = "dynamics"
            else:
                key = "content"
            groups[key].append((name, parameter))
        return groups

    def freeze(self, *, shared=False, groups=()):
        if shared:
            for parameter in self.common.parameters():
                parameter.requires_grad_(False)
        for key in groups:
            if key not in GROUPS:
                raise ValueError("Unknown freeze group")
            for _, parameter in self.parameter_groups()[key]:
                parameter.requires_grad_(False)

    def load_shared(self, checkpoint):
        if self.config["family"] == "encoder_only":
            raise ValueError("Encoder-only has a different declared temporal head")
        donor = checkpoint["config"]
        if any(donor[key] != self.config[key] for key in ("task", "width", "depth")):
            raise ValueError("Shared checkpoint architecture mismatch")
        self.common.load_state_dict(checkpoint["common_state"], strict=True)
        if parameter_hash(self.common) != checkpoint["common_sha256"]:
            raise ValueError("Shared checkpoint state identity mismatch")

