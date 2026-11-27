"""Parameter-matched matrix-memory arms with causal, value-blind addressing.

The shared parser is an explicit task prior, not learned KV discovery.
Every answer must pass through the current associative matrix. The ordinary
arm changes the controller feature map as well as its operator interpretation;
only analytic versus matched_c1 isolates the analytic boundary shape.
"""

from dataclasses import asdict, dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F

from .data import (
    COPY_QUERY,
    COPY_VALUE,
    CUE,
    KEY_QUERY,
    WRITE_KEY,
    WRITE_VALUE,
    TaskConfig,
)
from .flow import BoundaryFlow
from .memory import exact_delta_step, memory_read


ARMS = ("analytic", "matched_c1", "sigmoid", "ordinary", "frozen_flow")


@dataclass(frozen=True)
class ModelConfig:
    heads: int = 1
    key_dim: int = 16
    value_dim: int = 8
    max_step: float = 0.0625
    initial_leak: float = 1 / 512
    initial_write: float = 1.0


def _inverse_softplus(value):
    return math.log(math.expm1(value))


class AssociativeModel(nn.Module):
    """Shared Q/K/V/readout and exact leaky delta memory across five arms."""

    def __init__(self, arm, config=ModelConfig(), task_config=TaskConfig()):
        super().__init__()
        if arm not in ARMS:
            raise ValueError(f"Unknown arm {arm}")
        self.arm, self.config, self.task_config = arm, config, task_config
        h, k, v = config.heads, config.key_dim, config.value_dim
        self.key_projection = nn.Linear(task_config.key_vocab, h * k, bias=False)
        self.query_projection = nn.Linear(task_config.key_vocab, h * k, bias=False)
        self.value_projection = nn.Linear(task_config.value_vocab, h * v, bias=False)
        self.readout = nn.Linear(h * v, task_config.value_vocab)
        mode = (
            "analytic"
            if arm == "frozen_flow"
            else "sigmoid"
            if arm == "ordinary"
            else arm
        )
        self.flow = BoundaryFlow(
            mode, task_config.input_dim, h, max_step=config.max_step
        )
        self.rate_raw = nn.ParameterDict(
            {
                "leak_bias": nn.Parameter(
                    torch.full((h,), _inverse_softplus(config.initial_leak))
                ),
                "write_bias": nn.Parameter(
                    torch.full((h,), _inverse_softplus(config.initial_write))
                ),
                "call_gain": nn.Parameter(torch.full((h,), _inverse_softplus(1.0))),
                "put_gain": nn.Parameter(torch.full((h,), _inverse_softplus(1.0))),
            }
        )
        if arm == "frozen_flow":
            self.flow.requires_grad_(False)

    def parameter_groups(self):
        groups = {
            name: []
            for name in ("content", "boundary_input", "boundary_dynamics", "rate_head")
        }
        for name, parameter in self.named_parameters():
            group = (
                "boundary_dynamics"
                if name.startswith("flow.raw.")
                else "boundary_input"
                if name.startswith("flow.")
                else "rate_head"
                if name.startswith("rate_raw.")
                else "content"
            )
            groups[group].append((name, parameter))
        return groups

    def accounting(self):
        c, t = self.config, self.task_config
        return {
            "arm": self.arm,
            "model_config": asdict(c),
            "parameters_total": sum(p.numel() for p in self.parameters()),
            "parameters_trainable": sum(
                p.numel() for p in self.parameters() if p.requires_grad
            ),
            "group_trainable": {
                g: sum(p.numel() for _, p in values if p.requires_grad)
                for g, values in self.parameter_groups().items()
            },
            "persistent_float_state_per_episode": c.heads
            * (c.key_dim * c.value_dim + 3)
            + t.key_vocab,
            "persistent_integer_state_per_episode": 3,
            "discrete_state_dtypes": [
                "write_count:int64",
                "read_count:int64",
                "cued:bool",
            ],
            "state_components": {
                "matrix": c.heads * c.key_dim * c.value_dim,
                "flow": 3 * c.heads,
                "pending_key": t.key_vocab,
                "write_counter_read_counter_cue_flag": 3,
            },
            "interpretation": (
                "frozen controller parameters; evolving states; fewer trainable parameters"
                if self.arm == "frozen_flow"
                else "ordinary changes controller features"
                if self.arm == "ordinary"
                else "shared scalar margin drives both operator channels"
            ),
        }

    def _rates(self, state, call, put, reference):
        if self.arm == "ordinary":
            v, q, z = state
            first = torch.tanh(v - q) - torch.tanh(-reference["q_star"])
            second = torch.tanh(v + z) - torch.tanh(reference["z_star"])
        else:
            first, second = call - reference["call_star"], put - reference["put_star"]
        leak = F.softplus(
            self.rate_raw["leak_bias"] - F.softplus(self.rate_raw["call_gain"]) * first
        )
        write = F.softplus(
            self.rate_raw["write_bias"] + F.softplus(self.rate_raw["put_gain"]) * second
        )
        return leak, write

    def forward(self, inputs, dt=None, *, return_diagnostics=False):
        """Consume a prefix strictly in order; no targets enter this method.

        The two integer counters and the pending key see only current role,
        selection and key fields. In particular they cannot inspect values,
        future inputs, or labels when constructing read/write addresses.
        """
        batch, length, _ = inputs.shape
        c, t = self.config, self.task_config
        if dt is None:
            dt = inputs.new_ones((batch, length))
        prepared = self.flow.prepare_sequence(dt)
        state = self.flow.initial_state(
            batch, device=inputs.device, dtype=inputs.dtype, prepared=prepared
        )
        reference = prepared.parameters
        memory = inputs.new_zeros((batch, c.heads, c.value_dim, c.key_dim))
        pending = inputs.new_zeros((batch, t.key_vocab))
        write_count = torch.zeros(batch, dtype=torch.long, device=inputs.device)
        read_count = torch.zeros_like(write_count)
        cued = torch.zeros(batch, dtype=torch.bool, device=inputs.device)
        outputs, traces = [], []
        for index in range(length):
            token = inputs[:, index]
            key_field = token[:, t.key_start : t.value_start]
            value_field = token[:, t.value_start : t.select_index]
            key_event = token[:, WRITE_KEY] > 0.5
            pending = torch.where(key_event[:, None], key_field, pending)
            copy_write = (token[:, COPY_VALUE] > 0.5) & (token[:, t.select_index] > 0.5)
            mqar_write = token[:, WRITE_VALUE] > 0.5
            copy_slot = F.one_hot(
                write_count.clamp_max(t.key_vocab - 1), t.key_vocab
            ).to(inputs.dtype)
            write_key = torch.where(copy_write[:, None], copy_slot, pending)
            writing = copy_write | mqar_write
            write_key = write_key * writing[:, None]
            write_count = write_count + copy_write.long()
            pending = torch.where(
                mqar_write[:, None], torch.zeros_like(pending), pending
            )
            cue = token[:, CUE] > 0.5
            cued = cued | cue
            read_count = torch.where(cue, torch.zeros_like(read_count), read_count)
            copy_query = (token[:, COPY_QUERY] > 0.5) & cued
            read_slot = F.one_hot(
                read_count.clamp_max(t.key_vocab - 1), t.key_vocab
            ).to(inputs.dtype)
            query_key = torch.where(copy_query[:, None], read_slot, key_field)
            querying = copy_query | (token[:, KEY_QUERY] > 0.5)
            query_key = query_key * querying[:, None]
            read_count = read_count + copy_query.long()
            key = F.normalize(
                self.key_projection(write_key).view(batch, c.heads, c.key_dim),
                dim=-1,
                eps=1e-8,
            )
            query = F.normalize(
                self.query_projection(query_key).view(batch, c.heads, c.key_dim),
                dim=-1,
                eps=1e-8,
            )
            value = self.value_projection(value_field).view(batch, c.heads, c.value_dim)
            state, call, put = self.flow.step_prepared(token, state, prepared, index)
            leak, write = self._rates(state, call, put, reference)
            memory = exact_delta_step(
                memory, key, value, leak, write * writing[:, None], dt[:, index, None]
            )
            read = memory_read(memory, query).flatten(1)
            outputs.append(self.readout(read))
            if return_diagnostics:
                traces.append(
                    torch.stack(
                        (
                            self.flow.margin(state, prepared=prepared),
                            call,
                            put,
                            leak,
                            write,
                        ),
                        dim=-1,
                    )
                )
        logits = torch.stack(outputs, dim=1)
        if return_diagnostics:
            return logits, {
                "flow_rate_trace": torch.stack(traces, dim=1),
                "final_memory": memory,
                "final_state": state,
            }
        return logits


def build_model(arm, seed, config=ModelConfig(), task_config=TaskConfig()):
    """Identical learned initial tensors for all arms under a shared seed."""
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        return AssociativeModel(arm, config, task_config)
