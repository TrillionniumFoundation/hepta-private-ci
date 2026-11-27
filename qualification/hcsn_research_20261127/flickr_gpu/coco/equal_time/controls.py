import torch
from torch import nn
from torch.nn import functional as F


class CausalAttention(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.width = width
        self.embedding = nn.Linear(32, width)
        self.position = nn.Parameter(torch.zeros(6, 1, width))
        self.norm = nn.LayerNorm(width)
        self.qkv = nn.Linear(width, 3 * width)
        self.output = nn.Linear(width, width)
        self.feedforward = nn.Sequential(
            nn.LayerNorm(width), nn.Linear(width, 2 * width), nn.GELU(),
            nn.Linear(2 * width, width),
        )

    def forward(self, sequence):
        hidden = (self.embedding(sequence) + self.position).transpose(0, 1)
        batch, time, width = hidden.shape
        q, k, v = self.qkv(self.norm(hidden)).view(batch, time, 3, 4, width // 4).permute(2, 0, 3, 1, 4).unbind(0)
        attended = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        hidden = hidden + self.output(attended.transpose(1, 2).reshape(batch, time, width))
        return (hidden + self.feedforward(hidden)).transpose(0, 1)


class DiagonalSelectiveSSM(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.input = nn.Linear(32, width)
        self.step = nn.Linear(32, width)
        self.gate = nn.Linear(32, width)
        self.log_rate = nn.Parameter(torch.zeros(width))
        self.output = nn.Linear(width, width)

    def forward(self, sequence):
        keep = (-F.softplus(self.log_rate) * F.softplus(self.step(sequence))).exp()
        drive = self.input(sequence).tanh()
        gate = self.gate(sequence).sigmoid()
        state = torch.zeros_like(drive[0])
        out = []
        for k, u, g in zip(keep.unbind(), drive.unbind(), gate.unbind()):
            state = k * state + (1 - k) * u
            out.append(self.output(state) * g)
        return torch.stack(out)
