"""Capacity-matched event-temperature control, explicitly not an FPT semigroup."""

import math

import torch
from torch import nn

from .dynamics import EventDynamics


class EventTemperature(EventDynamics):
    """Freeze diffusion; learn one event/non-event logit temperature instead.

    Conditional active-state and event-direction distributions are retained.
    Recovery rows are unchanged. Reweighting the endpoint of a CTMC destroys
    its semigroup interpretation, which is why this is a mechanism control.
    """

    def __init__(self, n_grid=15):
        super().__init__("first_passage", n_grid)
        self.raw_diffusion.requires_grad_(False)
        self.raw_temperature = nn.Parameter(torch.tensor(math.log(3 / 4), dtype=torch.float64))

    def physical_parameters(self):
        parameters = super().physical_parameters()
        if hasattr(self, "raw_temperature"):
            parameters["event_temperature"] = 0.25 + 1.75 * torch.sigmoid(self.raw_temperature)
        return parameters

    def parameter_groups(self):
        groups = super().parameter_groups()
        groups["temperature"] = [self.raw_temperature]
        return groups

    def transition_matrix(self, drive, dt=1.0):
        transition, events = super().transition_matrix(drive, dt)
        active_rows = transition[:, :self.n_grid, :]
        active = active_rows[:, :, :self.n_grid]
        event = active_rows[:, :, self.n_grid:]
        survival_mass = active.sum(dim=-1)
        event_mass = event.sum(dim=-1)
        has_survival = survival_mass > 0
        has_event = event_mass > 0
        if bool((~has_survival & ~has_event).any()):
            raise ValueError("the underlying transition has an empty active row")

        # Use the actual conditional masses, not a clamped probability or
        # 1-p: either replacement changes the distribution in extreme tails.
        # Ones are used only on an exactly absent support to avoid log(0) and
        # 0/0. Mask after scaling so an infinite masked logit cannot inject an
        # infinite derivative with respect to temperature.
        survival_denominator = torch.where(has_survival, survival_mass, torch.ones_like(survival_mass))
        event_denominator = torch.where(has_event, event_mass, torch.ones_like(event_mass))
        temperature = self.physical_parameters()["event_temperature"]
        logits = torch.stack((survival_denominator.log(), event_denominator.log()), dim=-1) / temperature
        support = torch.stack((has_survival, has_event), dim=-1)
        weights = torch.softmax(logits.masked_fill(~support, -torch.inf), dim=-1)
        active = (active / survival_denominator[:, :, None]) * weights[:, :, :1]
        event = (event / event_denominator[:, :, None]) * weights[:, :, 1:]
        active_rows = torch.cat((active, event), dim=-1)
        return torch.cat((active_rows, transition[:, self.n_grid:, :]), dim=1), torch.cat(
            (event, events[:, self.n_grid:, :]), dim=1)
