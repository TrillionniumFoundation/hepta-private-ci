"""Differentiable distribution cells with three explicitly different event laws.

The first-passage law is exact for the stated finite-state CTMC, not for the
continuous OU diffusion.  See DYNAMICS.md for the discretisation and refractory
contract.  No straight-through estimator or sampled-event gradient is used.
"""

import math
from typing import Literal

import torch
from torch import Tensor, nn


Mode = Literal["continuous", "clocked", "first_passage"]


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


class EventDynamics(nn.Module):
    """A FP64 Markov distribution cell with N voltage and two refractory states.

    State order is ``[voltage_0, ..., voltage_N-1, refractory_plus,
    refractory_minus]``.  ``drive`` is held constant during one call.  An event
    freezes its path for the rest of the tick.  Old refractory paths can be
    released only at the *end* of the following tick, so they cannot fire during
    that tick.  Event order in returned tensors is ``[plus, minus]``.
    """

    MODES = ("continuous", "clocked", "first_passage")

    def __init__(self, mode: Mode, n_grid: int = 15) -> None:
        super().__init__()
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}, got {mode!r}")
        if n_grid < 5 or n_grid % 2 != 1:
            raise ValueError("n_grid must be odd and at least 5")
        self.mode = mode
        self.n_grid = int(n_grid)
        self.n_states = self.n_grid + 2
        self.reset_sd_normalised = 0.08

        # Bounded physical parameters keep the registered numerical regime
        # explicit.  These are genuine smooth reparameterisations, not clamps.
        self.raw_leak = nn.Parameter(torch.tensor(_logit(0.35 / 2.0), dtype=torch.float64))
        self.raw_diffusion = nn.Parameter(
            torch.tensor(_logit((0.45 - 0.05) / 0.75), dtype=torch.float64)
        )
        self.raw_boundary = nn.Parameter(
            torch.tensor(_logit((1.0 - 0.35) / 1.65), dtype=torch.float64)
        )
        self.raw_reset_plus = nn.Parameter(
            torch.tensor(math.atanh(-0.25 / 0.75), dtype=torch.float64)
        )
        self.raw_reset_minus = nn.Parameter(
            torch.tensor(math.atanh(0.25 / 0.75), dtype=torch.float64)
        )
        self.raw_recovery = nn.Parameter(
            torch.tensor(_logit((0.65 - 0.05) / 0.90), dtype=torch.float64)
        )

        nodes = torch.linspace(-1.0, 1.0, n_grid + 2, dtype=torch.float64)[1:-1]
        midpoints = (nodes[:-1] + nodes[1:]) / 2.0
        edges = torch.cat((nodes.new_tensor([-1.0]), midpoints, nodes.new_tensor([1.0])))
        self.register_buffer("normalised_grid", nodes)
        self.register_buffer("normalised_edges", edges)

        plus = torch.zeros(n_grid, n_grid + 2, dtype=torch.float64)
        minus = torch.zeros_like(plus)
        diagonal = torch.zeros_like(plus)
        for i in range(n_grid):
            diagonal[i, i] = 1.0
            plus[i, i + 1 if i + 1 < n_grid else n_grid] = 1.0
            minus[i, i - 1 if i > 0 else n_grid + 1] = 1.0
        self.register_buffer("plus_generator_basis", plus - diagonal)
        self.register_buffer("minus_generator_basis", minus - diagonal)

    def physical_parameters(self) -> dict[str, Tensor]:
        """Return differentiable physical values, suitable also for logging."""
        boundary = 0.35 + 1.65 * torch.sigmoid(self.raw_boundary)
        return {
            "leak": 2.0 * torch.sigmoid(self.raw_leak),
            "diffusion": 0.05 + 0.75 * torch.sigmoid(self.raw_diffusion),
            "boundary": boundary,
            "reset_plus": boundary * 0.75 * torch.tanh(self.raw_reset_plus),
            "reset_minus": boundary * 0.75 * torch.tanh(self.raw_reset_minus),
            "reset_sd": boundary * self.reset_sd_normalised,
            "recovery_probability": 0.05 + 0.90 * torch.sigmoid(self.raw_recovery),
        }

    def parameter_groups(self) -> dict[str, list[nn.Parameter]]:
        return {
            "dynamics": [self.raw_leak, self.raw_diffusion],
            "boundary": [self.raw_boundary],
            "reset": [self.raw_reset_plus, self.raw_reset_minus],
            "recovery": [self.raw_recovery],
        }

    def active_grid(self) -> Tensor:
        return self.physical_parameters()["boundary"] * self.normalised_grid

    def initial(self, batch: int, device: torch.device | str | None = None) -> Tensor:
        """Start at exactly zero voltage, ready, without an initial event."""
        if batch < 1:
            raise ValueError("batch must be positive")
        initial = torch.zeros(
            batch,
            self.n_states,
            dtype=torch.float64,
            device=device if device is not None else self.raw_leak.device,
        )
        initial[:, self.n_grid // 2] = 1.0
        return initial

    def _drive(self, drive: Tensor) -> Tensor:
        drive = torch.as_tensor(drive, dtype=torch.float64, device=self.raw_leak.device)
        if drive.ndim == 0:
            return drive.reshape(1)
        if drive.ndim == 2 and drive.shape[1] == 1:
            return drive[:, 0]
        if drive.ndim != 1:
            raise ValueError("drive must have shape [batch] or [batch, 1]")
        return drive

    @staticmethod
    def _check_dt(dt: float) -> float:
        dt = float(dt)
        if not math.isfinite(dt) or dt <= 0.0:
            raise ValueError("dt must be finite and positive")
        return dt

    def reset_distributions(self) -> tuple[Tensor, Tensor]:
        """Gaussian reset jitter projected to the common voltage grid.

        Jitter SD is a fixed 0.08 in normalised voltage units.  Tails are folded
        into the two extreme cells.  This is a smooth stochastic reset law,
        deliberately not a straight-through approximation to a point reset.
        """
        centers = 0.75 * torch.tanh(torch.stack((self.raw_reset_plus, self.raw_reset_minus)))
        midpoints = self.normalised_edges[1:-1]
        z = (midpoints[None, :] - centers[:, None]) / self.reset_sd_normalised
        cdf = torch.special.ndtr(z)
        probabilities = torch.cat(
            (cdf[:, :1], cdf[:, 1:] - cdf[:, :-1], torch.special.ndtr(-z[:, -1:])),
            dim=-1,
        )
        return probabilities[0], probabilities[1]

    def _ou_moments(self, drive: Tensor, dt: float) -> tuple[Tensor, Tensor]:
        physical = self.physical_parameters()
        leak = physical["leak"]
        decay = torch.exp(-leak * dt)
        integral_decay = -torch.expm1(-leak * dt) / leak
        mean = decay * self.active_grid()[None, :] + integral_decay * drive[:, None]
        variance = physical["diffusion"].square() * (-torch.expm1(-2.0 * leak * dt)) / (2.0 * leak)
        return mean, torch.sqrt(variance)

    def _gaussian_active_transition(self, drive: Tensor, dt: float) -> tuple[Tensor, Tensor, Tensor]:
        mean, sd = self._ou_moments(drive, dt)
        edges = self.physical_parameters()["boundary"] * self.normalised_edges
        z = (edges[None, None, :] - mean[:, :, None]) / sd
        cdf = torch.special.ndtr(z)
        plus = torch.special.ndtr(-z[:, :, -1])
        minus = cdf[:, :, 0]
        if self.mode == "continuous":
            # No boundary events: project the entire Gaussian law to the grid.
            interior_cdf = cdf[:, :, 1:-1]
            transition = torch.cat(
                (
                    interior_cdf[:, :, :1],
                    interior_cdf[:, :, 1:] - interior_cdf[:, :, :-1],
                    torch.special.ndtr(-z[:, :, -2:-1]),
                ),
                dim=-1,
            )
            return transition, torch.zeros_like(plus), torch.zeros_like(minus)
        return cdf[:, :, 1:] - cdf[:, :, :-1], plus, minus

    def absorbing_generator(self, drive: Tensor) -> Tensor:
        """Upwind OU generator with two absorbing boundary states.

        Matrix orientation is row-source, column-destination.  Its exponential
        is a CTMC transition law.  Upwind drift adds spatial numerical diffusion
        and converges only as the voltage mesh is refined.
        """
        drive = self._drive(drive)
        physical = self.physical_parameters()
        spacing = 2.0 * physical["boundary"] / (self.n_grid + 1)
        drift = drive[:, None] - physical["leak"] * self.active_grid()[None, :]
        diffusive_rate = 0.5 * physical["diffusion"].square() / spacing.square()
        plus_rate = diffusive_rate + torch.relu(drift) / spacing
        minus_rate = diffusive_rate + torch.relu(-drift) / spacing
        active_rows = (
            plus_rate[:, :, None] * self.plus_generator_basis[None, :, :]
            + minus_rate[:, :, None] * self.minus_generator_basis[None, :, :]
        )
        absorbing_rows = torch.zeros(
            drive.shape[0], 2, self.n_states, dtype=drive.dtype, device=drive.device
        )
        return torch.cat((active_rows, absorbing_rows), dim=1)

    def transition_matrix(self, drive: Tensor, dt: float = 1.0) -> tuple[Tensor, Tensor]:
        """Return (Markov transition, event reward) for independent DP users.

        Shapes are [B, N+2, N+2] and [B, N+2, 2].  Multiplying a state mass by
        the second tensor gives expected event counts *for this tick*.  Counts
        can exceed one only after summing across ticks, as the contract permits.
        """
        drive = self._drive(drive)
        dt = self._check_dt(dt)
        batch = drive.shape[0]
        if self.mode == "first_passage":
            absorbed = torch.matrix_exp(dt * self.absorbing_generator(drive))
            active = absorbed[:, : self.n_grid, : self.n_grid]
            plus = absorbed[:, : self.n_grid, self.n_grid]
            minus = absorbed[:, : self.n_grid, self.n_grid + 1]
        else:
            active, plus, minus = self._gaussian_active_transition(drive, dt)

        active_rows = torch.cat((active, plus[:, :, None], minus[:, :, None]), dim=-1)
        event_active = torch.stack((plus, minus), dim=-1)
        zeros_events = torch.zeros(batch, 2, 2, dtype=drive.dtype, device=drive.device)
        event_reward = torch.cat((event_active, zeros_events), dim=1)

        if self.mode == "continuous":
            # The last two placeholder states are unreachable from initial().
            ref_rows = torch.zeros(batch, 2, self.n_states, dtype=drive.dtype, device=drive.device)
            ref_rows[:, 0, self.n_grid] = 1.0
            ref_rows[:, 1, self.n_grid + 1] = 1.0
        else:
            q = self.physical_parameters()["recovery_probability"]
            reset_plus, reset_minus = self.reset_distributions()
            release = q * torch.stack((reset_plus, reset_minus), dim=0)
            refractory = (1.0 - q) * torch.eye(2, dtype=drive.dtype, device=drive.device)
            ref_rows = torch.cat((release, refractory), dim=-1)[None, :, :].expand(batch, -1, -1)
        return torch.cat((active_rows, ref_rows), dim=1), event_reward

    def forward(self, mass: Tensor, drive: Tensor, dt: float = 1.0) -> tuple[Tensor, Tensor]:
        mass = torch.as_tensor(mass, dtype=torch.float64, device=self.raw_leak.device)
        if mass.ndim != 2 or mass.shape[1] != self.n_states:
            raise ValueError(f"mass must have shape [batch, {self.n_states}]")
        drive = self._drive(drive)
        if drive.shape[0] == 1 and mass.shape[0] > 1:
            drive = drive.expand(mass.shape[0])
        if drive.shape[0] != mass.shape[0]:
            raise ValueError("mass and drive batch sizes differ")
        transition, event_reward = self.transition_matrix(drive, dt)
        new_mass = torch.bmm(mass[:, None, :], transition).squeeze(1)
        events = torch.bmm(mass[:, None, :], event_reward).squeeze(1)
        return new_mass, events

    def state_features(self, mass: Tensor) -> Tensor:
        """Unconditional voltage mean/variance and both refractory masses.

        A refractory state's voltage moments are those of its eventual reset
        law; no future input is applied until release.  Reset variance is kept,
        so this feature does not replace E[X^2] by E[X]^2.
        """
        mass = torch.as_tensor(mass, dtype=torch.float64, device=self.raw_leak.device)
        if mass.ndim != 2 or mass.shape[1] != self.n_states:
            raise ValueError(f"mass must have shape [batch, {self.n_states}]")
        grid = self.active_grid()
        reset_plus, reset_minus = self.reset_distributions()
        first = torch.cat((grid, (reset_plus @ grid).reshape(1), (reset_minus @ grid).reshape(1)))
        second = torch.cat(
            (grid.square(), (reset_plus @ grid.square()).reshape(1), (reset_minus @ grid.square()).reshape(1))
        )
        mean = mass @ first
        variance = torch.clamp(mass @ second - mean.square(), min=0.0)
        return torch.stack((mean, variance, mass[:, self.n_grid], mass[:, self.n_grid + 1]), dim=-1)

