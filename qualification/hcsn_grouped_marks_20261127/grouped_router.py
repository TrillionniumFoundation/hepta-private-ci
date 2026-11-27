"""Extend the pinned caption model by keeping four independent release measures."""
import math
import torch

from model import Captioner

ARMS = ('grouped_hcsn', 'hcsn', 'grouped_smooth', 'lif', 'mean', 'dense')


def grouped_mark(content, releases):
    """Aggregate four sequential content patches using three observed release tensors."""
    batch_rows, timesteps, width = content.shape
    groups = releases[0].shape[-1]
    if width % groups or len(releases) != timesteps - 1:
        raise ValueError('Incompatible content and release dimensions')
    coordinates = content.reshape(batch_rows, timesteps, groups, width // groups)
    remaining = torch.ones_like(releases[0])
    output = torch.zeros_like(coordinates[:, 0])
    for index, release in enumerate(releases):
        mass = remaining * release
        output = output + mass.unsqueeze(-1) * coordinates[:, index]
        remaining = remaining - mass
    output = output + remaining.unsqueeze(-1) * coordinates[:, -1]
    return output.flatten(1)


class GroupedRouter(torch.nn.Module):
    def __init__(self, original):
        super().__init__()
        self.arm = original.arm
        self.drive = original.drive
        self.rec = original.rec
        self.law = original.law

    def forward(self, patches):
        count, _, width = patches.shape
        rows = patches.reshape(count * 4, 4, width)
        drives = self.drive(rows)
        previous_boundary = drives.new_zeros((count * 4, 4))
        margin = previous_boundary + 0.18
        equity = previous_boundary + self.law.a0
        risk = previous_boundary + self.law.f0
        releases = []
        for index in range(3):
            feedback = 0.4 * torch.tanh((equity - self.law.a0) / 20)
            feedback = feedback + 0.4 * torch.tanh(risk - self.law.f0)
            drive = torch.tanh(drives[:, index] + self.rec(previous_boundary) + feedback)
            boundary = torch.log1p(self.law.kappa * drive)
            distance = margin + previous_boundary - boundary
            base, principal_slope, annual, quarter, margin = self.law.lookup(distance).unbind(-1)
            if self.arm == 'hcsn':
                equity = torch.where(distance > 0, base + principal_slope * (0.28 * self.law.principal * drive), 0.)
                risk = annual
                releases.append(quarter)
            else:
                equity = self.law.a0 + 20 * torch.tanh((distance - 0.18) * self.law.da / 20)
                risk = self.law.f0 + torch.tanh((distance - 0.18) * self.law.df)
                base_logit = math.log(self.law.h0 / (1 - self.law.h0))
                logit = base_logit + (distance - 0.18) * self.law.dh / (self.law.h0 * (1 - self.law.h0))
                releases.append(torch.sigmoid(logit))
            previous_boundary = boundary
        return grouped_mark(rows, releases).reshape(count, 4, width)


def build_model(arm, vocabulary_size):
    if arm not in ARMS:
        raise ValueError(arm)
    base_arm = {'grouped_hcsn': 'hcsn', 'grouped_smooth': 'smooth'}.get(arm, arm)
    model = Captioner(base_arm, vocabulary_size)
    if arm.startswith('grouped_'):
        # A pure change of aggregation preserves every initialized tensor and optimizer parameter.
        model.router = GroupedRouter(model.router)
    return model
