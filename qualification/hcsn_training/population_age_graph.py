"""Opt-in B integration with physical-time refractory cohorts.

Absorption is deposited at each numerical right boundary. Its exact integer
microsecond expiry is retained, and future intervals split at that expiry before
reinjection. A conservative finite-volume generator replaces the old repeated
spatial projection. Frozen nonlinear drift and right-endpoint absorption deposit
remain numerical approximations to the continuous first-passage/reset PDE.
The original fixed-grid research operator and checkpoint schema remain unchanged.
"""

from dataclasses import dataclass
import math

import torch
from .joint_graph import GraphSpec, integer, sha256, time_profile_digest
from .population_graph import PopulationCellGraph, MAX_SUBSTEPS
from .population_generator import finite_volume_transition

REFRACTORY_MICROS = 240_000


@dataclass(frozen=True)
class PopulationAgeGraphSpec(GraphSpec):
    max_step_micros: int
    max_substeps: int
    backend: str = "population_age_v1"
    kernel: str = "upwind_ctmc_v1"
    legacy_step_micros: int = 0
    spatial_bins: int = 32

    def __post_init__(self):
        super().__post_init__()
        integer(self.max_step_micros, maximum=2**53-1)
        integer(self.max_substeps, maximum=MAX_SUBSTEPS)
        integer(self.legacy_step_micros, 0, maximum=2**53-1)
        integer(self.spatial_bins, minimum=8, maximum=128)
        if self.backend != "population_age_v1" or self.kernel != "upwind_ctmc_v1":
            raise ValueError("unknown population age backend/kernel")
        if self.maximum_remaining_micros > 2**24:
            raise ValueError("legacy refractory times exceed exact FP32 integer budget")

    @property
    def maximum_remaining_micros(self):
        step = self.legacy_step_micros
        return REFRACTORY_MICROS if not step else max(
            REFRACTORY_MICROS, ((REFRACTORY_MICROS+step-1)//step)*step)


def population_age_intervals(plans, profile, spec):
    """Validate Rust event budgets and return coarse elapsed microseconds.

    Unlike fixed-grid plans, substeps is an allowed event-step budget. The actual
    schedule also depends on authenticated initial cohort expiries and is planned
    before allocating the numerical tensor graph.
    """
    identity = time_profile_digest(profile)
    if profile["integration"] != dict(kind="population_age", max_step_micros=spec.max_step_micros,
                                      max_substeps=spec.max_substeps):
        raise ValueError("population age graph and time profile differ")
    fields = {"schema_version", "start_micros", "end_micros", "elapsed_micros", "substep_micros",
              "substeps", "forecast_horizon_micros", "profile_digest", "checkpoint_before"}
    if not isinstance(plans, list) or not 1 <= len(plans) <= 256:
        raise ValueError("bounded nonempty population age intervals required")
    previous, anchor, result = None, None, []
    for plan in plans:
        if set(plan) != fields or type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
            raise ValueError("unknown population age plan schema/fields")
        start, end = integer(plan["start_micros"], 0), integer(plan["end_micros"])
        elapsed = integer(plan["elapsed_micros"], maximum=2**53-1)
        sha256(plan["checkpoint_before"])
        if (plan["profile_digest"] != identity or end <= start or elapsed != end-start
                or integer(plan["substep_micros"]) != spec.max_step_micros
                or integer(plan["substeps"]) != spec.max_substeps
                or (elapsed+spec.max_step_micros-1)//spec.max_step_micros > spec.max_substeps
                or elapsed > profile["maximum_gap_micros"]
                or integer(plan["forecast_horizon_micros"]) != profile["forecast_horizon_micros"]
                or end+profile["forecast_horizon_micros"] >= 2**64
                or (previous is not None and start != previous)
                or (anchor is not None and plan["checkpoint_before"] != anchor)):
            raise ValueError("inconsistent/non-contiguous population age plan")
        previous, anchor = end, plan["checkpoint_before"]
        result.append(elapsed)
    return tuple(result)


class PopulationAgeCellGraph(PopulationCellGraph):
    """Joint BP through mass transport with independently bounded event times."""

    def __init__(self, spec):
        # Reuse the original encoder's parameter shapes and immutable spatial
        # buffers. Its fixed-grid forward and refractory queue are never called.
        from .population_graph import PopulationGraphSpec
        bootstrap = PopulationGraphSpec(spec.cell_ids, spec.input_size, spec.hidden_size,
                                        spec.output_size, REFRACTORY_MICROS, spatial_bins=spec.spatial_bins)
        super().__init__(bootstrap)
        self.spec = spec

    def initial_state(self, batch, *, like=None):
        if like is None:
            like, batch = batch, batch.shape[0]
        return tuple((values[0], values[1], like.new_zeros(batch, self.spec.hidden_size, 0),
                      values[3], values[4], like.new_zeros(0))
                     for values in super().initial_state(batch, like=like))

    def validate_state(self, state, batch, dtype, device):
        if not isinstance(state, (list, tuple)) or len(state) != len(self.cells):
            raise ValueError("population age state must cover every logical cell")
        previous_ages = None
        for cell, values in zip(self.cells, state):
            if (not isinstance(values, (list, tuple)) or len(values) != 6
                    or any(not isinstance(v, torch.Tensor) or v.dtype != dtype or v.device != device
                           or not bool(torch.isfinite(v).all()) for v in values)):
                raise ValueError("invalid complete population age state")
            trace, active, queue, recovery, escaped, ages = values
            prefix = (batch, self.spec.hidden_size)
            if (ages.ndim != 1 or len(ages) > MAX_SUBSTEPS or ages.requires_grad
                    or trace.shape != prefix or recovery.shape != prefix or escaped.shape != prefix
                    or active.shape != prefix+(cell.population.config.bins,)
                    or queue.shape != prefix+(len(ages),)
                    or any(bool((v < 0).any()) for v in values)
                    or bool(((ages <= 0) | (ages > self.spec.maximum_remaining_micros) | (ages != ages.round())).any())
                    or bool((ages[1:] < ages[:-1]).any())
                    or (previous_ages is not None and not torch.equal(ages, previous_ages))):
                raise ValueError("invalid population age shapes or integer cohort expiries")
            mass = active.sum(-1)+queue.sum(-1)+escaped
            if not bool(torch.isclose(mass, torch.ones_like(mass), rtol=2e-5, atol=2e-6).all()):
                raise ValueError("population age total mass must remain one")
            previous_ages = ages

    def event_schedule(self, intervals, state=None):
        if (not isinstance(intervals, (tuple, list)) or not 1 <= len(intervals) <= 256
                or any(type(dt) is not int or not 1 <= dt <= 2**53-1 for dt in intervals)):
            raise ValueError("bounded integer elapsed microseconds required")
        ages = () if state is None else tuple(int(a) for a in state[0][5].tolist())
        result, total = [], 0
        for elapsed in intervals:
            steps = []
            while elapsed:
                dt = min(elapsed, self.spec.max_step_micros, ages[0] if ages else elapsed)
                if len(steps) >= self.spec.max_substeps or total >= MAX_SUBSTEPS:
                    raise ValueError("population age event-step budget exceeded")
                expired = sum(a == dt for a in ages)
                ages = tuple(sorted(tuple(a-dt for a in ages if a > dt)+(REFRACTORY_MICROS,)))
                if len(ages) > MAX_SUBSTEPS:
                    raise ValueError("population age cohort budget exceeded")
                steps.append((dt, expired))
                elapsed -= dt
                total += 1
            result.append(tuple(steps))
        return tuple(result)

    def working_elements(self, batch, intervals, state=None):
        count = sum(map(len, self.event_schedule(intervals, state)))
        cohorts = count+(0 if state is None else len(state[0][5]))
        per_cell = sum(64*(c.population.config.bins+2)**2+8*c.population.config.bins+2*cohorts+4
                       for c in self.cells)
        return batch*(count*self.spec.hidden_size*per_cell
                      + len(intervals)*self.spec.input_size+self.spec.output_size)

    @staticmethod
    def advance_age(cell, held, state, micros, expired):
        trace, active, queue, recovery, escaped, ages = state
        cfg, dt = cell.population.config, micros/1_000_000
        drive = 6*torch.sigmoid(cell.input(held)+cell.recurrent(trace))
        edges = cell.population.edges
        drift = cfg.base_drift+cfg.leak*(cfg.rest_margin-edges)-drive[..., None]+recovery[..., None]
        matrix, hit, escape = finite_volume_transition(edges, drift, cfg.sigma, dt)
        absorbed = (active*hit).sum(-1)
        lost = (active*escape).sum(-1)
        active = torch.einsum("...i,...ij->...j", active, matrix)
        active = active+queue[..., :expired].sum(-1)[..., None]*cell.population.reset_weights
        queue = torch.cat((queue[..., expired:], absorbed[..., None]), -1)
        ages = torch.cat((ages[expired:]-micros, ages.new_tensor([REFRACTORY_MICROS])))
        # Migrated legacy cohorts may expire later than a newly deposited cohort.
        order = torch.argsort(ages, stable=True)
        ages, queue = ages[order], queue[..., order]
        recovery = recovery*math.exp(-dt/cfg.recovery_tau)+cfg.recovery_strength*absorbed
        decay = math.exp(-dt/.5)
        trace = decay*trace+(1-decay)*absorbed/dt
        return trace, active, queue, recovery, escaped+lost, ages

    def forward(self, inputs, intervals, state=None):
        if (inputs.ndim != 3 or inputs.shape[1] != len(intervals)
                or inputs.shape[-1] != self.spec.input_size or not 1 <= inputs.shape[0] <= 64
                or not bool(torch.isfinite(inputs).all())):
            raise ValueError("invalid population age inputs")
        state = self.initial_state(inputs) if state is None else state
        self.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)
        schedule = self.event_schedule(intervals, state)
        outputs = []
        for k, steps in enumerate(schedule):
            for dt, expired in steps:
                held = (inputs[:, k], *(values[0] for values in state[:-1]))
                state = tuple(self.advance_age(cell, value, prior, dt, expired)
                              for cell, value, prior in zip(self.cells, held, state))
            outputs.append(self.readout(state[-1][0]))
        return torch.stack(outputs, 1), state


def migrate_fixed_grid(source, state, *, max_step_micros, max_substeps):
    """Explicitly transition a validated legacy state to the new numerical profile.

    Old slot j still releases after (j+1)*old_step microseconds, even when its
    effective refractory duration exceeded 240ms. All saved numerical values are
    copied and detached. The source step is part of the new graph identity; an
    owner must admit this model/profile change as a new training lineage.
    """
    if type(source) is not PopulationCellGraph:
        raise ValueError("migration requires the fixed-grid population backend")
    if (not isinstance(state, (list, tuple)) or not state or not state[0]
            or not isinstance(state[0][0], torch.Tensor) or state[0][0].ndim != 2):
        raise ValueError("complete fixed-grid state required for migration")
    parameter = next(source.parameters())
    source.validate_state(state, state[0][0].shape[0], parameter.dtype, parameter.device)
    old = source.spec
    spec = PopulationAgeGraphSpec(old.cell_ids, old.input_size, old.hidden_size, old.output_size,
                                  max_step_micros, max_substeps, legacy_step_micros=old.step_micros,
                                  spatial_bins=old.spatial_bins)
    model = PopulationAgeCellGraph(spec).to(dtype=parameter.dtype, device=parameter.device)
    model.load_state_dict({name: value.detach().clone() for name, value in source.state_dict().items()})
    migrated = tuple(tuple(value.detach().clone() for value in values)+(
        values[0].new_tensor([(i+1)*old.step_micros for i in range(values[2].shape[-1])]),)
        for values in state)
    model.validate_state(migrated, state[0][0].shape[0], parameter.dtype, parameter.device)
    return model, migrated
