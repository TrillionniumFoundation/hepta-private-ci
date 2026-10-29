"""New shared-boundary v/q/z flow with explicit, differentiable ETD2.

v=log(V), q=log(K), beta=kappa/(1+kappa), x=v-q-log(beta).
The actual boundary is log(B)=q+log(beta). A step freezes the external
drive throughout its internal substeps. It never updates content memory.
"""

import math

import torch
from torch import nn

from .numerics import OPERATOR_MODES, call_put, phi1, phi2


FLOW_VERSION = "hepta-stable-flow-20261029-v1"
State = tuple[torch.Tensor, torch.Tensor, torch.Tensor]


def _raw_bounded(value: float, low: float, high: float) -> float:
    fraction = (value - low) / (high - low)
    return math.log(fraction / (1.0 - fraction))


class BoundaryFlow(nn.Module):
    """Same parameter layout across analytic, matched_c1 and sigmoid modes.

    tau_v v' = -v + Iv
    tau_q q' = -q + q* + gC(a-a*) + gP(p-p*) - (z-z*) + Ib
    tau_z z' = -z + gz p

    q*=-x*-log(beta); z*=gz p(x*). Initial state is (0,q*,z*).
    This is parameter-dependent initialization, with all dependencies kept
    in the autograd graph. It is an equilibrium for zero projected drive.
    Finite raw parameters guarantee tau_z > tau_q + .25 mathematically;
    floating sigmoid saturation may attain the closed interval endpoints.
    """

    def __init__(
        self, mode: str, input_dim: int, heads: int, *, max_step: float
    ) -> None:
        super().__init__()
        if mode not in OPERATOR_MODES:
            raise ValueError(f"Unknown operator mode: {mode}")
        if input_dim <= 0 or heads <= 0 or not math.isfinite(max_step) or max_step <= 0:
            raise ValueError("input_dim, heads and max_step must be positive")
        self.mode = mode
        self.input_dim = input_dim
        self.heads = heads
        self.max_step = float(max_step)
        self.drive_v = nn.Linear(input_dim, heads)
        self.drive_q = nn.Linear(input_dim, heads)
        nn.init.zeros_(self.drive_v.bias)
        nn.init.zeros_(self.drive_q.bias)
        initial = {
            "kappa": _raw_bounded(1.0, 0.25, 4.0),
            "x_star": _raw_bounded(0.5, -0.5, 1.5),
            "tau_v": _raw_bounded(1.0, 0.25, 8.0),
            "tau_q": _raw_bounded(1.5, 0.25, 8.0),
            "tau_z_fraction": _raw_bounded(6.0, 1.75, 32.0),
            "g_call": _raw_bounded(1.0, 0.0, 4.0),
            "g_put": _raw_bounded(2.0, 0.0, 4.0),
            "g_recovery": _raw_bounded(2.0, 0.0, 4.0),
        }
        self.raw = nn.ParameterDict(
            {name: nn.Parameter(torch.full((heads,), value)) for name, value in initial.items()}
        )

    def effective_parameters(self) -> dict[str, torch.Tensor]:
        """Physical parameters and operator-derived reference equilibrium."""
        p = {
            "kappa": 0.25 + 3.75 * self.raw["kappa"].sigmoid(),
            "x_star": -0.5 + 2.0 * self.raw["x_star"].sigmoid(),
            "tau_v": 0.25 + 7.75 * self.raw["tau_v"].sigmoid(),
            "tau_q": 0.25 + 7.75 * self.raw["tau_q"].sigmoid(),
            "g_call": 4.0 * self.raw["g_call"].sigmoid(),
            "g_put": 4.0 * self.raw["g_put"].sigmoid(),
            "g_recovery": 4.0 * self.raw["g_recovery"].sigmoid(),
        }
        lower = p["tau_q"] + 0.25
        p["tau_z"] = lower + (32.0 - lower) * self.raw["tau_z_fraction"].sigmoid()
        p["beta"] = p["kappa"] / (1.0 + p["kappa"])
        p["log_beta"] = p["beta"].log()
        p["call_star"], p["put_star"] = call_put(p["x_star"], p["kappa"], self.mode)
        p["q_star"] = -p["x_star"] - p["log_beta"]
        p["z_star"] = p["g_recovery"] * p["put_star"]
        return p

    def initial_state(self, batch: int, device=None, dtype=None) -> State:
        """Broadcast the learned reference point without detaching it."""
        p = self.effective_parameters()
        q = p["q_star"].to(device=device, dtype=dtype).expand(batch, -1)
        z = p["z_star"].to(device=device, dtype=dtype).expand(batch, -1)
        return torch.zeros_like(q), q, z

    def currents(self, drive: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Bounded, trainable projections of the raw external input."""
        return 3.0 * self.drive_v(drive).tanh(), 3.0 * self.drive_q(drive).tanh()

    def margin(self, state: State) -> torch.Tensor:
        p = self.effective_parameters()
        return state[0] - state[1] - p["log_beta"]

    def _targets(self, state: State, currents, p) -> State:
        v, q, z = state
        a, put = call_put(v - q - p["log_beta"], p["kappa"], self.mode)
        target_q = (
            p["q_star"]
            + p["g_call"] * (a - p["call_star"])
            + p["g_put"] * (put - p["put_star"])
            - (z - p["z_star"])
            + currents[1]
        )
        return currents[0], target_q, p["g_recovery"] * put

    def rhs(self, drive: torch.Tensor, state: State) -> State:
        """Continuous RHS for diagnostics; an independent oracle must rederive it."""
        p = self.effective_parameters()
        targets = self._targets(state, self.currents(drive), p)
        return tuple(
            (target - value) / p[name]
            for target, value, name in zip(targets, state, ("tau_v", "tau_q", "tau_z"))
        )

    def step(self, drive: torch.Tensor, dt, state: State) -> tuple[State, torch.Tensor, torch.Tensor]:
        """ETD2 with equal substeps and a protocol-explicit maximum step.

        dt is a scalar, [batch] or [batch,1], finite and nonnegative. Per-example
        counts ceil(dt/max_step) are detached scheduling metadata; independent
        meshes make the map invariant to the other examples in a batch.
        dt still differentiates through each chosen discrete integration map.
        Parameter values and projected currents are reused across substeps.
        """
        batch = drive.shape[0]
        times = torch.as_tensor(dt, dtype=drive.dtype, device=drive.device)
        if times.ndim == 0:
            times = times.expand(batch).unsqueeze(-1)
        elif times.ndim == 1 and times.shape[0] == batch:
            times = times.unsqueeze(-1)
        elif times.shape != (batch, 1):
            raise ValueError("dt must be scalar, [batch], or [batch,1]")
        if not bool(torch.isfinite(times).all()) or bool((times < 0).any()):
            raise ValueError("dt must be finite and nonnegative")
        counts = torch.ceil(times.detach() / self.max_step).clamp_min(1)
        count = int(counts.max().cpu())
        h = times / counts
        p = self.effective_parameters()
        projected = self.currents(drive)
        rates = torch.stack([p["tau_v"], p["tau_q"], p["tau_z"]])
        s = -h.unsqueeze(0) / rates.unsqueeze(1)
        decay = s.exp()
        weight_one = -s * phi1(s)
        weight_two = -s * phi2(s)
        values = torch.stack(state)
        for index in range(count):
            targets = torch.stack(self._targets(tuple(values.unbind(0)), projected, p))
            predictor = decay * values + weight_one * targets
            next_targets = torch.stack(self._targets(tuple(predictor.unbind(0)), projected, p))
            # Algebraically ETD2. For s<=0 the three scalar coefficients are
            # nonnegative in exact arithmetic; no clamp changes the dynamics.
            updated = decay * values + (weight_one - weight_two) * targets + weight_two * next_targets
            values = torch.where((index < counts).unsqueeze(0), updated, values)
        result = tuple(values.unbind(0))
        a, put = call_put(result[0] - result[1] - p["log_beta"], p["kappa"], self.mode)
        return result, a, put
