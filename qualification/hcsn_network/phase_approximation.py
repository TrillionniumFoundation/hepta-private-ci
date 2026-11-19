"""Explicit Erlang-delay alternative to the deterministic-delay population.

This changes the waiting-time law (variance d**2/stages). It is not lossless
compression of the exact pending packets and does not inherit their value or
optimal-boundary claims. Same content writes and one-block message convention.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib

import torch


@dataclass(frozen=True)
class PhaseState:
    density: tuple
    hits: tuple
    discounted_hits: tuple
    occupation: tuple
    value: tuple
    discount_factor: tuple
    messages: tuple
    written: tuple
    initial_totals: tuple
    active_nodes: int
    stages: int
    time: Fraction
    sample_interval: Fraction
    batch_size: int
    content_size: int
    message_mode: str
    law_digests: tuple
    physics_tensor_bytes: int
    operator_tensor_bytes: int

    def tensors(self):
        for name in TENSOR_FIELDS:
            yield from getattr(self, name)

    def tensor_bytes(self):
        """Dynamic tensor payload; excludes hash/clock metadata and the AD tape.

Physics and returned transition/integral tensors are reported separately as
logical view sizes. Their temporary matrix-exponential/AD storage is not
represented by these counters; process/allocator measurements remain separate.
        """
        return sum(t.numel()*t.element_size() for t in self.tensors())

    def balances(self):
        return tuple(x.sum(1)-start-torch.cat((w.new_zeros(1), w.flatten()))
                     for x, start, w in zip(self.density, self.initial_totals, self.written))


TENSOR_FIELDS = ("density", "hits", "discounted_hits", "occupation", "value", "discount_factor",
                 "messages", "written", "initial_totals")
PHYSICS_FIELDS = ("generator", "lower", "upper", "reset", "reward", "escape_reward",
                  "spike_reward", "discount")


def _law_digest(physics):
    """Bind exact frozen values, dtype/device, shapes and logical delay."""
    digest = hashlib.sha256(str(physics.delay).encode())
    for name in PHYSICS_FIELDS:
        tensor = getattr(physics, name)
        digest.update(f"{name}:{tensor.dtype}:{tensor.device}:{tuple(tensor.shape)}".encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _generator(physics, stages):
    if type(stages) is not int or not 1 <= stages <= 128:
        raise ValueError("Erlang stage count must lie in 1..128")
    q, n = physics.generator, physics.lower.numel()
    rate = q.new_tensor(stages/float(physics.delay))
    eye = torch.eye(stages, dtype=q.dtype, device=q.device)
    phase = -rate*eye
    if stages > 1:
        phase = phase + torch.diag(rate.expand(stages-1), diagonal=1)
    upper_row = torch.cat((q, physics.lower[:, None]*eye[:1], physics.upper[:, None]), 1)
    phase_rows = torch.cat((rate*eye[:, -1:]*physics.reset[None], phase, q.new_zeros(stages, 1)), 1)
    generator = torch.cat((upper_row, phase_rows, q.new_zeros(1, n+stages+1)), 0)
    event = torch.cat((physics.lower, q.new_zeros(stages+1)))
    return generator, event


def _integrals(generator, weights, duration):
    if duration < 0:
        raise ValueError("nonnegative duration required")
    n, k = weights.shape
    augmented = torch.cat((torch.cat((generator, weights), 1), generator.new_zeros(k, n+k)), 0)
    action = torch.matrix_exp(augmented*duration)
    if not bool(torch.isfinite(action).all()):
        raise FloatingPointError("nonfinite phase action")
    return action[:n, :n], action[:n, n:]


def phase_transition(physics, duration, stages):
    """One exact finite Markov transition and event-count integral."""
    generator, event = _generator(physics, stages)
    transition, integral = _integrals(generator, event[:, None], duration)
    return transition, integral[:, 0], generator


def _operators(physics, duration, stages):
    generator, event = _generator(physics, stages)
    occupation = torch.cat((physics.lower.new_ones(physics.lower.numel()),
                            physics.lower.new_zeros(stages), physics.lower.new_ones(1)))
    reward = torch.cat((physics.reward, physics.reward.new_zeros(stages), physics.escape_reward[None]))
    transition, ordinary = _integrals(generator, torch.stack((event, occupation), 1), duration)
    shifted = generator-physics.discount*torch.eye(generator.shape[0], dtype=generator.dtype, device=generator.device)
    _, discounted = _integrals(shifted, torch.stack((event, reward), 1), duration)
    return transition, ordinary, discounted, generator


def phase_forward(flow, sequence, physics, stages, state=None):
    """Batch-shared fixed law with full forward state and optional continuation.

Fixed physics, delay, sample interval and message mode are checked before
continuing a saved state. Tensor-only cold records retain future state, not the
past autograd graph. The Erlang law remains an explicit model approximation.
    """
    if sequence.ndim != 3 or flow.rate_drive or flow.activation != "tanh":
        raise ValueError("batched fixed-physics tanh flow required")
    steps, batch, size = sequence.shape
    if not steps or not 1 <= batch <= 256 or size != flow.input_size or not bool(torch.isfinite(sequence).all()):
        raise ValueError("finite nonempty sequence with matching input and batch 1..256 required")
    if len(physics) != flow.layers or any(p.lower.numel() != physics[0].lower.numel() for p in physics):
        raise ValueError("one equal-size finite spatial law per layer required")
    k = flow.content_size
    digests = tuple(_law_digest(p) for p in physics)
    if state is not None and (state.law_digests != digests or state.stages != stages
            or state.sample_interval != flow.dt or state.batch_size != batch
            or state.content_size != k or state.message_mode != flow.message_mode):
        raise ValueError("phase continuation requires the identical frozen law and coupling contract")
    operators = tuple(_operators(p, float(flow.dt), stages) for p in physics)
    physics_bytes = sum(getattr(p, name).numel()*getattr(p, name).element_size()
                        for p in physics for name in PHYSICS_FIELDS)
    operator_bytes = sum(t.numel()*t.element_size() for operator in operators for t in operator)
    if state is None:
        density, hits, messages, written, starts = [], [], [], [], []
        for p in physics:
            probability = torch.cat((p.reset, p.reset.new_zeros(stages+1)))
            x = torch.cat((probability[None], probability.new_zeros(batch*k, len(probability))), 0)
            density.append(x)
            hits.append(x.new_zeros(1+batch*k))
            messages.append(x.new_zeros(batch, 1+k))
            written.append(x.new_zeros(batch, k))
            starts.append(x.sum(1))
        discounted_hits, occupation, value = [list(hits) for _ in range(3)]
        factors, current_time = [p.discount.new_ones(()) for p in physics], Fraction(0)
    else:
        density, hits, discounted_hits, occupation, value, factors, messages, written, starts = \
            [list(getattr(state, name)) for name in TENSOR_FIELDS]
        current_time = state.time
    emissions = []
    for vector in sequence:
        old_messages = messages
        messages = []
        for i, p in enumerate(physics):
            source = vector if i == 0 else old_messages[i-1]
            if i and flow.message_mode == "mass":
                source = torch.cat((source[:, :1], torch.zeros_like(source[:, 1:])), 1)
            mark = flow.writers[i](source).tanh()
            x, n = density[i], p.lower.numel()
            active_mark = torch.cat((mark.flatten()[:, None]*x[:1, :n],
                                     x.new_zeros(batch*k, stages+1)), 1)
            written[i] = written[i] + mark*x[0, :n].sum()
            x = torch.cat((x[:1], x[1:]+active_mark), 0)
            transition, ordinary, discounted, _ = operators[i]
            increments, credits = x @ ordinary, factors[i]*(x @ discounted)
            density[i], hits[i] = x @ transition, hits[i]+increments[:, 0]
            discounted_hits[i] = discounted_hits[i]+credits[:, 0]
            occupation[i] = occupation[i]+increments[:, 1]
            value[i] = value[i]+credits[:, 1]+p.spike_reward*credits[:, 0]
            factors[i] = factors[i]*torch.exp(-p.discount*float(flow.dt))
            messages.append(torch.cat((increments[:1, 0].expand(batch, 1), increments[1:, 0].reshape(batch, k)), 1))
        emissions.append(messages[-1])
        current_time += flow.dt
    state = PhaseState(*[tuple(x) for x in (density, hits, discounted_hits, occupation, value, factors,
                                           messages, written, starts)], physics[0].lower.numel(), stages,
                       current_time, flow.dt, batch, k, flow.message_mode, digests, physics_bytes, operator_bytes)
    if any(not bool(torch.isfinite(t).all()) for t in state.tensors()):
        raise FloatingPointError("nonfinite phase state")
    return torch.stack(emissions), state, tuple(o[3] for o in operators)


def phase_state_to_record(state):
    """Complete alias-free tensor snapshot, compatible with weights_only loading."""
    return {"schema": "hcsn-erlang-forward-state-v1", "past_autograd_retained": False,
            **{name: [t.detach().clone() for t in getattr(state, name)] for name in TENSOR_FIELDS},
            **{name: getattr(state, name) for name in ("active_nodes", "stages", "batch_size", "content_size",
                "message_mode", "physics_tensor_bytes", "operator_tensor_bytes")},
            "law_digests": list(state.law_digests), "time": [state.time.numerator, state.time.denominator],
            "sample_interval": [state.sample_interval.numerator, state.sample_interval.denominator]}


def phase_state_from_record(record):
    """Restore trusted forward records; the next call checks the frozen law."""
    if record.get("schema") != "hcsn-erlang-forward-state-v1" or record.get("past_autograd_retained") is not False:
        raise ValueError("unsupported phase state schema")
    state = PhaseState(*[tuple(record[name]) for name in TENSOR_FIELDS], record["active_nodes"], record["stages"],
                       Fraction(*record["time"]), Fraction(*record["sample_interval"]), record["batch_size"],
                       record["content_size"], record["message_mode"], tuple(record["law_digests"]),
                       record["physics_tensor_bytes"], record["operator_tensor_bytes"])
    if not 1 <= len(state.density) <= 8 or any(type(v) is not int or not low <= v <= high for v, low, high in
            ((state.batch_size, 1, 256), (state.content_size, 1, 64), (state.active_nodes, 1, 64), (state.stages, 1, 128))):
        raise ValueError("invalid phase state dimensions")
    if (state.time < 0 or state.sample_interval <= 0 or state.message_mode not in ("full", "mass")
            or len(state.law_digests) != len(state.density)):
        raise ValueError("invalid phase state metadata")
    if any(len(getattr(state, name)) != len(state.density) for name in TENSOR_FIELDS) or any(
            not isinstance(t, torch.Tensor) or not bool(torch.isfinite(t).all()) for t in state.tensors()):
        raise ValueError("invalid phase forward state")
    channels = 1+state.batch_size*state.content_size
    shapes = {"density": (channels, state.active_nodes+state.stages+1), "messages": (state.batch_size, 1+state.content_size),
              "written": (state.batch_size, state.content_size), "discount_factor": ()}
    for name in TENSOR_FIELDS:
        if any(t.shape != shapes.get(name, (channels,)) for t in getattr(state, name)):
            raise ValueError("invalid phase state tensor shape")
    return state
