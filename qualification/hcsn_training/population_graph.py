"""Population B cells share a fixed-grid tensor graph and complete renewal state.

The external input is held over each admitted interval. Logical cells advance
simultaneously at every configured grid boundary, using the predecessor's trace
from the previous grid boundary. Integer substep counts never change the fixed
population dt, grid, refractory queue or frozen original population operator.
"""

from dataclasses import dataclass
import math

import torch
from torch import nn
from qualification.hcsn.baselines import PopulationFluxEncoder
from qualification.hcsn.population_torch import TensorPopulationState
from .joint_graph import GraphSpec, integer, sha256, time_profile_digest

MAX_SUBSTEPS = 4096
MAX_REFRACTORY_STEPS = 256


@dataclass(frozen=True)
class PopulationGraphSpec(GraphSpec):
    step_micros: int
    backend: str = "population_grid_v1"

    def __post_init__(self):
        super().__post_init__()
        integer(self.step_micros, maximum=2**53-1)
        if self.backend != "population_grid_v1":
            raise ValueError("unknown population backend")
        # Original B uses 0.24 seconds of refractory residence. Bound allocation
        # before constructing TorchPopulation and its queue.
        if (240_000+self.step_micros-1)//self.step_micros > MAX_REFRACTORY_STEPS:
            raise ValueError("population refractory queue budget exceeded")


def population_intervals(plans, profile, spec):
    """Validate Rust B plans and return exact integer grid-step counts."""
    profile_digest = time_profile_digest(profile)
    integration = profile["integration"]
    if (integration["kind"] != "population_grid" or integration["step_micros"] != spec.step_micros):
        raise ValueError("population graph and time profile grid differ")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 256:
        raise ValueError("bounded nonempty population intervals required")
    fields = {"schema_version", "start_micros", "end_micros", "elapsed_micros",
              "substep_micros", "substeps", "forecast_horizon_micros", "profile_digest", "checkpoint_before"}
    previous, anchor, result = None, None, []
    for plan in plans:
        if set(plan) != fields or type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
            raise ValueError("unknown population time plan schema/fields")
        start, end = integer(plan["start_micros"], 0), integer(plan["end_micros"])
        elapsed = integer(plan["elapsed_micros"], maximum=2**53-1)
        substep = integer(plan["substep_micros"], maximum=2**53-1)
        count = integer(plan["substeps"], maximum=integration["max_substeps"])
        forecast = integer(plan["forecast_horizon_micros"], maximum=2**53-1)
        sha256(plan["checkpoint_before"])
        if (plan["profile_digest"] != profile_digest or end <= start or elapsed != end-start
                or substep != spec.step_micros or elapsed != count*substep
                or elapsed > profile["maximum_gap_micros"] or forecast != profile["forecast_horizon_micros"]
                or (anchor is not None and plan["checkpoint_before"] != anchor)
                or (previous is not None and start != previous) or end+forecast >= 2**64):
            raise ValueError("inconsistent/non-contiguous population grid time plan")
        previous, anchor = end, plan["checkpoint_before"]
        result.append(count)
    if sum(result) > MAX_SUBSTEPS:
        raise ValueError("population total substep budget exceeded")
    return tuple(result)


class PopulationCellGraph(nn.Module):
    """Reuse B's actual flux, renewal, recovery and filtered absorption trace."""

    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.cells = nn.ModuleList(PopulationFluxEncoder(
            spec.input_size if i == 0 else spec.hidden_size, spec.hidden_size,
            dt=spec.step_micros/1_000_000) for i in range(len(spec.cell_ids)))
        self.readout = nn.Linear(spec.hidden_size, spec.output_size)

    def initial_state(self, batch, *, like=None):
        # Accept an input tensor or the explicit (batch, like=inputs) form.
        if like is None:
            like, batch = batch, batch.shape[0]
        result = []
        for cell in self.cells:
            state = cell.population.initial_state((batch, self.spec.hidden_size))
            trace = like.new_zeros(batch, self.spec.hidden_size)
            result.append((trace, state.active, state.refractory, state.recovery, state.escaped))
        return tuple(result)

    def validate_state(self, state, batch, dtype, device):
        if not isinstance(state, (tuple, list)) or len(state) != len(self.cells):
            raise ValueError("population state must cover every logical cell")
        for cell, values in zip(self.cells, state):
            config = cell.population.config
            prefix = (batch, self.spec.hidden_size)
            shapes = (prefix, prefix+(config.bins,), prefix+(config.refractory_steps,), prefix, prefix)
            if (not isinstance(values, (tuple, list)) or len(values) != len(shapes)
                    or any(not isinstance(v, torch.Tensor) or v.shape != shape or v.dtype != dtype
                           or v.device != device or not bool(torch.isfinite(v).all())
                           for v, shape in zip(values, shapes))):
                raise ValueError("invalid complete population cell state")
            if any(bool((v < 0).any()) for v in values):
                raise ValueError("negative population trace, mass or recovery")
            mass = values[1].sum(-1)+values[2].sum(-1)+values[4]
            if not bool(torch.isclose(mass, torch.ones_like(mass), rtol=2e-5, atol=2e-6).all()):
                raise ValueError("population state mass must include active, refractory and escaped")

    def working_elements(self, batch, intervals):
        # Conservative admission units for the B transition matrices and taped
        # Gaussian branches; this is not a process RSS or physical energy claim.
        per_cell = sum(64*c.population.config.bins**2 + 8*c.population.config.bins
                       + c.population.config.refractory_steps + 4 for c in self.cells)
        return batch*(sum(intervals)*self.spec.hidden_size*per_cell
                      + len(intervals)*self.spec.input_size+self.spec.output_size)

    @staticmethod
    def advance(cell, held, state):
        trace, active, refractory, recovery, escaped = state
        drive = 6*torch.sigmoid(cell.input(held)+cell.recurrent(trace))
        step = cell.population(TensorPopulationState(active, refractory, recovery, escaped), drive=drive)
        decay = math.exp(-cell.population.config.dt/.5)
        trace = decay*trace+(1-decay)*step.rate
        state = step.state
        return trace, state.active, state.refractory, state.recovery, state.escaped

    def forward(self, inputs, intervals, state=None):
        if (inputs.ndim != 3 or inputs.shape[1] != len(intervals) or inputs.shape[-1] != self.spec.input_size
                or not 1 <= inputs.shape[0] <= 64 or not 1 <= len(intervals) <= 256
                or any(type(count) is not int or not 1 <= count <= MAX_SUBSTEPS for count in intervals)
                or sum(intervals) > MAX_SUBSTEPS or not bool(torch.isfinite(inputs).all())):
            raise ValueError("invalid population input or integer grid intervals")
        state = self.initial_state(inputs.shape[0], like=inputs) if state is None else state
        self.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)
        outputs = []
        for k, count in enumerate(intervals):
            for _ in range(count):
                held = (inputs[:, k], *(s[0] for s in state[:-1]))
                state = tuple(self.advance(cell, value, prior) for cell, value, prior in zip(self.cells, held, state))
            outputs.append(self.readout(state[-1][0]))
        return torch.stack(outputs, dim=1), state
