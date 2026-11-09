"""Layered continuous-probability HCSN with an explicit vector-content state.

Each layer transports probability and content mass with one common operator
per time step. Observation updates occur at the *end* of that interval. The
reported events are conditional expected counts, never sampled binary spikes.
All parameters are frozen during a retained episode; optimization is between
episodes. A caller must explicitly construct, retain, detach, or reset state.
"""

import copy
from dataclasses import asdict, dataclass
import math

import torch
from torch import Tensor, nn

from .checkpoint import pack_adam_state, restore_adam_state, rollback_on_error, validate_model_state
from .contract import GridSpec, PhysicalParameters
from .encoder import IrregularSensorEncoder
from .operator import DifferentiableDistributionOperator


@dataclass(frozen=True)
class LayerState:
    probability: Tensor  # [batch, all active/tail/refractory coefficients]
    content_mass: Tensor  # [batch, same coefficient basis, content dimension]

    def detached(self):
        return LayerState(self.probability.detach(), self.content_mass.detach())


@dataclass(frozen=True)
class NetworkState:
    layers: tuple[LayerState, ...]
    elapsed: Tensor  # [batch], elapsed duration since explicit initialization
    steps: Tensor  # [batch], counts valid positions, including missing observations
    parameter_snapshot: dict[str, Tensor]
    configuration_snapshot: dict
    sequence_position: int = 0  # shared input-position count, including padding
    truncate_every: int | None = None  # frozen after the first consumed position

    def detached(self):
        """Explicit truncated-BPTT cut; retain every numerical state component."""
        return NetworkState(tuple(layer.detached() for layer in self.layers),
                            self.elapsed.detach(), self.steps.detach(), self.parameter_snapshot,
                            self.configuration_snapshot, self.sequence_position, self.truncate_every)


@dataclass(frozen=True)
class NetworkOutput:
    predictions: Tensor  # [batch,time,output_dim]; padding predictions are zero
    state: NetworkState
    expected_events: Tensor  # [batch,time,layer], interval expectations
    diagnostics: dict
    trace: tuple


@dataclass(frozen=True)
class SensorStreamState:
    network: NetworkState
    last_timestamp: Tensor  # [batch], independent absolute timestamp precision
    encoder_snapshot: dict[str, Tensor]
    encoder_configuration: dict

    def detached(self):
        return SensorStreamState(self.network.detached(), self.last_timestamp.detach(),
                                 self.encoder_snapshot, self.encoder_configuration)


def _snapshot(module):
    # Include buffers such as discount and normalization scales: changing a
    # nontrainable physical constant would also invalidate a retained episode.
    return {name: value.detach().clone() for name, value in module.state_dict().items()}


def _check_snapshot(module, snapshot):
    current = module.state_dict()
    if current.keys() != snapshot.keys() or any(
        value.shape != snapshot[name].shape or value.dtype != snapshot[name].dtype
        or value.device != snapshot[name].device or not torch.equal(value.detach(), snapshot[name])
        for name, value in current.items()
    ):
        raise ValueError("parameters changed within a retained episode; initialize a new state after optimization")


def _logit(value):
    return math.log(value / (1. - value))


class TrainablePhysics(nn.Module):
    """Four independent scalar parameters with an explicit admissible domain.

    b is represented by log_boundary in (-.12,.12); the *absolute* reset's
    logarithm is independently in (.22,.65). Their disjoint intervals preserve
    a=log(absolute_reset)-log_boundary>0 without coupling their gradients.
    Refractory duration and discount are fixed for this first candidate.
    """

    def __init__(self, *, mu=-.12, sigma=.35, log_boundary=0., log_absolute_reset=.32,
                 discount=.15):
        super().__init__()
        if not (-.8 < mu < .8 and .1 < sigma < .8 and -.12 < log_boundary < .12
                and .22 < log_absolute_reset < .65 and .001 <= discount <= 4):
            raise ValueError("initial physical parameters are outside the declared open domain")
        self.raw_mu = nn.Parameter(torch.tensor(math.atanh(mu / .8), dtype=torch.float64))
        self.raw_sigma = nn.Parameter(torch.tensor(_logit((sigma - .1) / .7), dtype=torch.float64))
        self.raw_log_boundary = nn.Parameter(torch.tensor(math.atanh(log_boundary / .12), dtype=torch.float64))
        self.raw_absolute_reset = nn.Parameter(torch.tensor(_logit((log_absolute_reset - .22) / .43), dtype=torch.float64))
        self.register_buffer("discount", torch.tensor(float(discount), dtype=torch.float64))

    def forward(self):
        return PhysicalParameters(
            log_boundary=.12 * torch.tanh(self.raw_log_boundary),
            mu=.8 * torch.tanh(self.raw_mu),
            sigma=.1 + .7 * torch.sigmoid(self.raw_sigma),
            absolute_reset=torch.exp(.22 + .43 * torch.sigmoid(self.raw_absolute_reset)),
            discount=self.discount,
        )


class ContentLayer(nn.Module):
    def __init__(self, input_dim, content_dim, grid, operator=None):
        super().__init__()
        if operator is not None and operator.grid != grid:
            raise ValueError("operator.grid must equal the layer grid, including active/phase ownership")
        self.grid = grid
        self.state_count = grid.active_cells + 1 + grid.phase_cells
        self.active_count = grid.active_cells + 1
        self.physics = TrainablePhysics()
        self.operator = operator if operator is not None else DifferentiableDistributionOperator(grid)
        # Five channels: call, first-hit risk, successor-margin proxy, expected
        # interval event count, and current active occupancy. They are readouts
        # of one propagated law, not two independently evolving physical states.
        self.likelihood = nn.Linear(input_dim + 5, self.state_count)
        self.write_gate = nn.Linear(input_dim + 5, self.state_count)
        self.content_proposal = nn.Linear(input_dim + 5, content_dim)
        self.state_embedding = nn.Parameter(torch.empty(self.state_count, content_dim))
        nn.init.normal_(self.state_embedding, std=.15)
        nn.init.constant_(self.write_gate.bias, -1.5)

    def condition(self, probability, content_mass, observation, channels, observed):
        joined = torch.cat((observation, channels), dim=-1)
        likelihood = torch.exp(.5 * torch.tanh(self.likelihood(joined)))
        likelihood = torch.where(observed[:, None], likelihood, torch.ones_like(likelihood))
        weighted = probability * likelihood
        evidence = weighted.sum(-1, keepdim=True)
        if not bool(torch.isfinite(evidence).all()) or bool((evidence <= 0).any()):
            raise FloatingPointError("nonpositive or nonfinite observation evidence")
        posterior = weighted / evidence
        transported_content = content_mass * likelihood.unsqueeze(-1) / evidence.unsqueeze(-1)
        gate = torch.sigmoid(self.write_gate(joined)).unsqueeze(-1)
        gate = torch.where(observed[:, None, None], gate, torch.zeros_like(gate))
        proposal = torch.tanh(self.content_proposal(joined)[:, None, :] + self.state_embedding[None, :, :])
        posterior_content = ((1. - gate) * transported_content
                             + gate * posterior.unsqueeze(-1) * proposal)
        # Even normalization by an almost-unit sum would be a hidden change on
        # a missing/padded sample. Select the unconditioned transport verbatim.
        posterior = torch.where(observed[:, None], posterior, probability)
        posterior_content = torch.where(observed[:, None, None], posterior_content, content_mass)
        return LayerState(posterior, posterior_content), evidence.squeeze(-1)


class ContinuousSpikingNetwork(nn.Module):
    """A stack of genuine recurrent probability/content layers.

    This candidate uses deterministic remaining-time refractory QPR operators.
    One observed gap must be <= each layer's fixed refractory duration; larger
    gaps are rejected rather than silently introducing extra advance calls.
    Finite-grid QPR does not assert an exact physical semigroup.
    """

    def __init__(self, input_dim, content_dim=6, output_dim=1, *, layer_count=2,
                 grid=None, operators=None, mass_tolerance=2e-6):
        super().__init__()
        if min(input_dim, content_dim, output_dim, layer_count) < 1:
            raise ValueError("network dimensions and layer_count must be positive")
        if not math.isfinite(mass_tolerance) or mass_tolerance <= 0:
            raise ValueError("mass_tolerance must be finite and positive")
        grid = GridSpec() if grid is None else grid
        if operators is not None and len(operators) != layer_count:
            raise ValueError("provide exactly one operator per recurrent layer")
        self.input_dim, self.content_dim, self.output_dim = input_dim, content_dim, output_dim
        self.mass_tolerance = mass_tolerance
        self.layers = nn.ModuleList([
            ContentLayer(input_dim if index == 0 else content_dim + 5, content_dim, grid,
                         None if operators is None else operators[index])
            for index in range(layer_count)
        ])
        self.readout = nn.Linear(content_dim + 5, output_dim)
        self.double()  # The current differentiable physical contract is FP64.

    def configuration(self):
        return dict(schema="hcsn-probability-content-network-v1", input_dim=self.input_dim,
                    content_dim=self.content_dim, output_dim=self.output_dim,
                    layer_count=len(self.layers), grids=[asdict(layer.grid) for layer in self.layers],
                    operators=[layer.operator.configuration() for layer in self.layers],
                    mass_tolerance=self.mass_tolerance,
                    physics_profile="independent-bounded-mu-sigma-logb-absolute-reset-v1")

    def initial_state(self, batch_size, *, absolute_initial=None):
        """Start/reset an episode explicitly; this is never called by forward."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        reference = next(self.parameters())
        initial = (reference.new_full((batch_size,), math.exp(.55)) if absolute_initial is None
                   else torch.as_tensor(absolute_initial, dtype=reference.dtype, device=reference.device))
        if initial.ndim == 0:
            initial = initial.expand(batch_size)
        if initial.shape != (batch_size,):
            raise ValueError("absolute_initial must be scalar or have shape [batch]")
        layers = []
        for layer in self.layers:
            probability = layer.operator.initial_probability(initial, layer.physics().log_boundary)
            layers.append(LayerState(probability, probability.new_zeros(batch_size, layer.state_count, self.content_dim)))
        state = NetworkState(tuple(layers), reference.new_zeros(batch_size),
                             torch.zeros(batch_size, device=reference.device, dtype=torch.int64),
                             _snapshot(self), copy.deepcopy(self.configuration()))
        self._validate_state(state, batch_size)
        return state

    def _validate_state(self, state, batch_size):
        if not isinstance(state, NetworkState) or len(state.layers) != len(self.layers):
            raise ValueError("a complete compatible NetworkState is required")
        if state.configuration_snapshot != self.configuration():
            raise ValueError("configuration changed within a retained episode")
        if (isinstance(state.sequence_position, bool) or not isinstance(state.sequence_position, int) or state.sequence_position < 0
                or (state.truncate_every is not None
                    and (not isinstance(state.truncate_every, int) or state.truncate_every < 1))):
            raise ValueError("invalid retained BPTT position or policy")
        if state.elapsed.shape != (batch_size,) or state.steps.shape != (batch_size,):
            raise ValueError("state clocks do not match the batch")
        reference = next(self.parameters())
        if (state.elapsed.dtype != reference.dtype or state.elapsed.device != reference.device
                or state.steps.dtype != torch.int64 or state.steps.device != reference.device
                or not bool(torch.isfinite(state.elapsed).all()) or bool((state.elapsed < 0).any())
                or bool((state.steps < 0).any())):
            raise ValueError("invalid state clock dtype, device or value")
        if bool((state.steps > state.sequence_position).any()):
            raise ValueError("valid-step count exceeds the global sequence position")
        if state.sequence_position == 0 and (bool((state.steps != 0).any()) or bool((state.elapsed != 0).any())):
            raise ValueError("position-zero state requires zero valid steps and elapsed time")
        if bool(((state.steps == 0) & (state.elapsed != 0)).any()):
            raise ValueError("zero valid steps cannot advance physical time")
        _check_snapshot(self, state.parameter_snapshot)
        for layer, current in zip(self.layers, state.layers):
            if (current.probability.shape != (batch_size, layer.state_count)
                    or current.content_mass.shape != (batch_size, layer.state_count, self.content_dim)):
                raise ValueError("incomplete probability/content state")
            if any(t.dtype != reference.dtype or t.device != reference.device
                   for t in (current.probability, current.content_mass)):
                raise ValueError("state dtype/device must match the network")
            self._state_invariants(current)

    def _state_invariants(self, current):
        p, m = current.probability, current.content_mass
        if not bool(torch.isfinite(p).all()) or not bool(torch.isfinite(m).all()):
            raise FloatingPointError("nonfinite probability or content mass")
        mass_error = (p.sum(-1) - 1.).abs().max()
        negative = (-p).clamp_min(0.).max()
        if float(mass_error.detach()) > self.mass_tolerance or float(negative.detach()) > self.mass_tolerance:
            raise FloatingPointError("unconditioned probability invariant failed; no clipping/repair is applied")
        return mass_error, negative

    def forward(self, features, dt, *, state, observed=None, valid_mask=None,
                truncate_every=None, return_trace=False):
        if features.ndim != 3 or features.shape[-1] != self.input_dim:
            raise ValueError("features must have shape [batch,time,input_dim]")
        batch, steps, _ = features.shape
        reference = next(self.parameters())
        if batch < 1 or steps < 1 or features.dtype != reference.dtype or features.device != reference.device:
            raise ValueError("nonempty features must match model dtype/device")
        if not bool(torch.isfinite(features).all()):
            raise ValueError("features must be finite; use the sensor adapter for raw missing values")
        if dt.shape != (batch, steps) or dt.dtype != features.dtype or dt.device != features.device:
            raise ValueError("dt must have shape [batch,time] and feature dtype/device")
        if not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("dt must be finite and nonnegative")
        if bool((dt > min(layer.grid.refractory for layer in self.layers)).any()):
            raise ValueError("this candidate requires dt <= the fixed refractory duration")
        if observed is None:
            observed = torch.ones((batch, steps), device=features.device, dtype=torch.bool)
        if valid_mask is None:
            valid_mask = torch.ones_like(observed)
        for mask in (observed, valid_mask):
            if mask.shape != (batch, steps) or mask.dtype != torch.bool or mask.device != features.device:
                raise ValueError("observed/valid masks must be bool [batch,time] on the model device")
        if bool((dt[~valid_mask] != 0).any()) or bool((observed & ~valid_mask).any()):
            raise ValueError("padding requires dt=0 and observed=False")
        if truncate_every is not None and (not isinstance(truncate_every, int) or truncate_every < 1):
            raise ValueError("truncate_every must be a positive number of sequence positions")
        self._validate_state(state, batch)
        # None inherits the bound policy on continuation. A policy can first be
        # chosen at position zero; switching it mid-episode requires an explicit
        # new episode. Counts are shared sequence positions, not per-row events.
        if state.sequence_position:
            if truncate_every is not None and truncate_every != state.truncate_every:
                raise ValueError("BPTT policy changed within a retained episode")
            truncate_every = state.truncate_every

        current = list(state.layers)
        outputs, event_rows, defects, negatives, evidence_rows, traces = [], [], [], [], [], []
        elapsed, step_count = state.elapsed, state.steps
        position = state.sequence_position
        # Cache physical tensors only for this call, preserving their graph.
        # Operator table caching must never survive a parameter update.
        physical = [layer.physics() for layer in self.layers]
        for index in range(steps):
            if truncate_every is not None and position > 0 and position % truncate_every == 0:
                current = [layer.detached() for layer in current]
            message = features[:, index]
            events, step_trace = [], []
            for depth, layer in enumerate(self.layers):
                flow = layer.operator.advance(current[depth].probability, current[depth].content_mass,
                                              dt[:, index], physical[depth])
                predicted = LayerState(flow.probability, flow.content_mass)
                defect, negative = self._state_invariants(predicted)
                defects.append(defect)
                negatives.append(negative)
                active = predicted.probability[:, :layer.active_count].sum(-1)
                channels = torch.tanh(torch.stack((flow.call, flow.risk, flow.margin,
                                                  flow.expected_events, active), dim=-1))
                successor, evidence = layer.condition(predicted.probability, predicted.content_mass,
                                                      message, channels, observed[:, index])
                defect, negative = self._state_invariants(successor)
                defects.append(defect)
                negatives.append(negative)
                evidence_rows.append(evidence)
                current[depth] = successor
                message = torch.cat((successor.content_mass.sum(1), channels), dim=-1)
                events.append(flow.expected_events)
                if return_trace:
                    step_trace.append(dict(probability=successor.probability, content_mass=successor.content_mass,
                                           expected_events=flow.expected_events, channels=channels))
            value = self.readout(message)
            outputs.append(torch.where(valid_mask[:, index, None], value, torch.zeros_like(value)))
            event_rows.append(torch.stack(events, dim=-1))
            elapsed = elapsed + dt[:, index]
            step_count = step_count + valid_mask[:, index].to(torch.int64)
            position += 1
            if return_trace:
                traces.append(tuple(step_trace))
        next_state = NetworkState(tuple(current), elapsed, step_count, state.parameter_snapshot,
                                  state.configuration_snapshot, position, truncate_every)
        diagnostics = dict(maximum_mass_residual=float(torch.stack(defects).max().detach()),
                           maximum_negative_probability=float(torch.stack(negatives).max().detach()),
                           minimum_observation_evidence=float(torch.stack(evidence_rows).min().detach()),
                           advance_calls=steps * len(self.layers), layer_count=len(self.layers),
                           event_semantics="conditional expected interval counts, not sampled spikes",
                           bptt="full" if truncate_every is None else "explicit_truncated",
                           truncate_every=truncate_every, sequence_position=position,
                           truncation_unit="global shared input positions, including padding")
        return NetworkOutput(torch.stack(outputs, dim=1), next_state, torch.stack(event_rows, dim=1),
                             diagnostics, tuple(traces))

    def checkpoint(self, state, optimizer=None):
        self._validate_state(state, state.elapsed.shape[0])
        return dict(schema="hcsn-network-checkpoint-v2", configuration=self.configuration(),
                    model={name: tensor.detach().cpu().clone() for name, tensor in self.state_dict().items()},
                    layers=[dict(probability=layer.probability.detach().cpu().clone(),
                                 content_mass=layer.content_mass.detach().cpu().clone()) for layer in state.layers],
                    elapsed=state.elapsed.detach().cpu().clone(), steps=state.steps.detach().cpu().clone(),
                    sequence_position=state.sequence_position, truncate_every=state.truncate_every,
                    optimizer=pack_adam_state(self, optimizer),
                    torch_rng=torch.random.get_rng_state().clone())

    def restore_checkpoint(self, payload, optimizer=None):
        if payload.get("schema") != "hcsn-network-checkpoint-v2" or payload.get("configuration") != self.configuration():
            raise ValueError("checkpoint schema/configuration mismatch")
        model_state = payload["model"]
        validate_model_state(self, model_state)
        reference = next(self.parameters())
        converted = tuple(LayerState(item["probability"].to(reference.device).clone(),
                                     item["content_mass"].to(reference.device).clone()) for item in payload["layers"])
        # Validate numerical state before committing any model bytes. Shape and
        # snapshot checks follow strict model restoration below.
        for layer in converted:
            self._state_invariants(layer)
        with rollback_on_error(self, optimizer):
            self.load_state_dict(model_state, strict=True)
            restored = NetworkState(converted, payload["elapsed"].to(reference.device).clone(),
                                    payload["steps"].to(reference.device).clone(), _snapshot(self),
                                    copy.deepcopy(self.configuration()), payload["sequence_position"],
                                    payload["truncate_every"])
            self._validate_state(restored, restored.elapsed.shape[0])
            restore_adam_state(self, optimizer, payload.get("optimizer"))
            torch.random.set_rng_state(payload["torch_rng"].cpu())
        return restored


class IrregularHCSNEncoder(nn.Module):
    """Compose the sensor adapter and layered HCSN with retained stream state."""

    def __init__(self, sensor_dim, embedding_dim=6, content_dim=6, output_dim=1, *, grid=None,
                 layer_count=2, time_scale=1.):
        super().__init__()
        self.encoder = IrregularSensorEncoder(sensor_dim, embedding_dim, time_scale=time_scale)
        self.network = ContinuousSpikingNetwork(embedding_dim, content_dim, output_dim,
                                               layer_count=layer_count, grid=grid)
        self.double()

    def initial_state(self, batch_size, *, start_time=0., absolute_initial=None):
        reference = next(self.parameters())
        clock = torch.as_tensor(start_time, dtype=torch.float64, device=reference.device)
        if clock.ndim == 0:
            clock = clock.expand(batch_size).clone()
        if clock.shape != (batch_size,) or not bool(torch.isfinite(clock).all()):
            raise ValueError("start_time must be finite scalar or [batch]")
        return SensorStreamState(self.network.initial_state(batch_size, absolute_initial=absolute_initial),
                                 clock, _snapshot(self.encoder), self._encoder_profile())

    def _encoder_profile(self):
        return dict(input_dim=self.encoder.input_dim, embedding_dim=self.encoder.embedding_dim,
                    time_scale=self.encoder.time_scale)

    def forward(self, values, timestamps, observation_mask=None, valid_mask=None, *, state,
                truncate_every=None, return_trace=False):
        if not isinstance(state, SensorStreamState):
            raise ValueError("provide explicit retained SensorStreamState")
        if state.encoder_configuration != self._encoder_profile():
            raise ValueError("encoder configuration changed within a retained episode")
        _check_snapshot(self.encoder, state.encoder_snapshot)
        encoded = self.encoder(values, timestamps, observation_mask, valid_mask,
                               start_time=state.last_timestamp)
        result = self.network(encoded.features, encoded.dt, state=state.network,
                              observed=encoded.observed, valid_mask=encoded.valid,
                              truncate_every=truncate_every, return_trace=return_trace)
        stream_state = SensorStreamState(result.state, encoded.last_timestamp, state.encoder_snapshot,
                                         state.encoder_configuration)
        return result, stream_state

    def checkpoint(self, state, optimizer=None):
        _check_snapshot(self.encoder, state.encoder_snapshot)
        if state.encoder_configuration != self._encoder_profile():
            raise ValueError("encoder configuration changed within a retained episode")
        return dict(schema="hcsn-irregular-sensor-checkpoint-v2",
                    encoder={name: value.detach().cpu().clone() for name, value in self.encoder.state_dict().items()},
                    encoder_profile=self._encoder_profile(),
                    network=self.network.checkpoint(state.network),
                    last_timestamp=state.last_timestamp.detach().cpu().clone(),
                    optimizer=pack_adam_state(self, optimizer))

    def restore_checkpoint(self, payload, optimizer=None):
        profile = self._encoder_profile()
        if payload.get("schema") != "hcsn-irregular-sensor-checkpoint-v2" or payload.get("encoder_profile") != profile:
            raise ValueError("sensor checkpoint profile mismatch")
        validate_model_state(self.encoder, payload["encoder"])
        with rollback_on_error(self, optimizer):
            self.encoder.load_state_dict(payload["encoder"], strict=True)
            network_state = self.network.restore_checkpoint(payload["network"])
            clock = payload["last_timestamp"].to(next(self.parameters()).device).clone()
            if clock.shape != network_state.elapsed.shape or not bool(torch.isfinite(clock).all()):
                raise ValueError("sensor checkpoint timestamp shape or value mismatch")
            restore_adam_state(self, optimizer, payload.get("optimizer"))
        return SensorStreamState(network_state, clock, _snapshot(self.encoder), profile)
