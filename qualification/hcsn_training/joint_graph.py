"""Logical HX cells in one autograd graph, with previous-boundary coupling.

For [start,end), cell zero holds the supplied left-boundary input. Every other
cell holds its predecessor's memory at start. All new states commit together
at end. This explicit frozen-coefficient scheme is not an exact joint ODE.
No tensor is quantized, serialized or detached between logical cells/time steps.
"""

from dataclasses import asdict, dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re

import torch
from torch import nn
from qualification.hcsn.cells import ValueKernelCell


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=finite, parse_float=finite)


def sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0"*64:
        raise ValueError("expected nonzero lowercase SHA256")
    return value


def integer(value, minimum=1, maximum=2**64-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("integer outside admitted bounds")
    return value


def tensor_digest(tensors):
    result = hashlib.sha256(b"hepta.hcsn.named-tensors.v1\0")
    for name, tensor in sorted(tensors.items()):
        value = tensor.detach().cpu().contiguous()
        if value.dtype not in (torch.float32, torch.float64) or not bool(torch.isfinite(value).all()):
            raise ValueError("tensor must be finite FP32/FP64")
        header = json.dumps([name, str(value.dtype), list(value.shape)], separators=(",", ":")).encode()
        result.update(len(header).to_bytes(8, "big") + header + value.numpy().tobytes())
    return result.hexdigest()


def time_profile_digest(profile):
    """Match the Rust V1 canonical identity for the explicit integration profile."""
    if set(profile) != {"maximum_gap_micros", "forecast_horizon_micros", "integration"}:
        raise ValueError("unknown time profile fields")
    gap = integer(profile["maximum_gap_micros"], maximum=2**53-1)
    horizon = integer(profile["forecast_horizon_micros"], maximum=2**53-1)
    integration = profile["integration"]
    if integration == {"kind": "value_kernel"}:
        suffix = b"\0"
    elif (set(integration) == {"kind", "step_micros", "max_substeps"}
          and integration["kind"] == "population_grid"):
        step = integer(integration["step_micros"], maximum=gap)
        maximum = integer(integration["max_substeps"], maximum=4096)
        suffix = b"\1"+step.to_bytes(8, "big")+maximum.to_bytes(4, "big")
    elif (set(integration) == {"kind", "max_step_micros", "max_substeps"}
          and integration["kind"] == "population_age"):
        step = integer(integration["max_step_micros"], maximum=gap)
        maximum = integer(integration["max_substeps"], maximum=4096)
        suffix = b"\2"+step.to_bytes(8, "big")+maximum.to_bytes(4, "big")
    else:
        raise ValueError("unknown integration time profile")
    domain = b"hepta.neuron.hcsn-time-profile.v1.seconds.zoh-left.sample-boundary.right-output"
    return hashlib.sha256(domain+gap.to_bytes(8, "big")+horizon.to_bytes(8, "big")+suffix).hexdigest()


def interval_seconds(plans, profile):
    """Check Rust A plans against the complete profile; owner authenticates scope."""
    profile_digest = time_profile_digest(profile)
    if profile["integration"] != {"kind": "value_kernel"}:
        raise ValueError("this graph requires the ValueKernel time profile")
    fields = {"schema_version", "start_micros", "end_micros", "elapsed_micros",
              "substep_micros", "substeps", "forecast_horizon_micros", "profile_digest",
              "checkpoint_before"}
    if not isinstance(plans, list) or not 1 <= len(plans) <= 256:
        raise ValueError("bounded nonempty interval plans required")
    previous, horizon, anchor, result = None, None, None, []
    for plan in plans:
        if set(plan) != fields or type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
            raise ValueError("unknown time plan schema/fields")
        start, end = integer(plan["start_micros"], 0), integer(plan["end_micros"])
        elapsed = integer(plan["elapsed_micros"], maximum=2**53-1)
        substep = integer(plan["substep_micros"], maximum=2**53-1)
        forecast = integer(plan["forecast_horizon_micros"], maximum=2**53-1)
        sha256(plan["checkpoint_before"])
        if (plan["profile_digest"] != profile_digest or end <= start or elapsed != end-start
                or substep != elapsed or integer(plan["substeps"]) != 1
                or elapsed > profile["maximum_gap_micros"] or forecast != profile["forecast_horizon_micros"]
                or (anchor is not None and plan["checkpoint_before"] != anchor)
                or (previous is not None and start != previous)
                or (horizon is not None and horizon != forecast) or end+forecast >= 2**64):
            raise ValueError("inconsistent/non-contiguous ValueKernel time plan")
        previous, horizon = end, forecast
        anchor = plan["checkpoint_before"]  # One real outer anchor for the entire coarse training block.
        result.append(elapsed/1_000_000)
    return tuple(result)


@dataclass(frozen=True)
class GraphSpec:
    cell_ids: tuple[str, ...]
    input_size: int
    hidden_size: int
    output_size: int

    def __post_init__(self):
        if (not isinstance(self.cell_ids, tuple) or not 2 <= len(self.cell_ids) <= 16
                or len(set(self.cell_ids)) != len(self.cell_ids)
                or any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", v)
                       for v in self.cell_ids)):
            raise ValueError("two to sixteen unique logical cell IDs required")
        for width in (self.input_size, self.hidden_size, self.output_size):
            integer(width, maximum=128)


class JointCellGraph(nn.Module):
    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.cells = nn.ModuleList(ValueKernelCell(spec.input_size if i == 0 else spec.hidden_size,
                                                   spec.hidden_size) for i in range(len(spec.cell_ids)))
        self.readout = nn.Linear(spec.hidden_size, spec.output_size)

    def initial_state(self, batch, *, like=None):
        # Accept an input tensor or the explicit (batch, like=inputs) form.
        if like is None:
            like, batch = batch, batch.shape[0]
        return tuple(cell.initial_state(batch, like=like) for cell in self.cells)

    def validate_state(self, state, batch, dtype, device):
        if (not isinstance(state, (list, tuple)) or len(state) != len(self.cells)
                or any(not isinstance(s, (list, tuple)) or len(s) != 2 for s in state)
                or any(not isinstance(v, torch.Tensor) or v.shape != (batch, self.spec.hidden_size)
                       or v.dtype != dtype or v.device != device or not bool(torch.isfinite(v).all())
                       for s in state for v in s)):
            raise ValueError("state does not cover the logical cells")

    def forward(self, inputs, intervals, state=None):
        if (inputs.ndim != 3 or inputs.shape[1] != len(intervals)
                or inputs.shape[-1] != self.spec.input_size or not 1 <= inputs.shape[0] <= 64
                or not 1 <= len(intervals) <= 256 or not bool(torch.isfinite(inputs).all())
                or any(type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0 for dt in intervals)):
            raise ValueError("invalid graph input or time intervals")
        state = self.initial_state(inputs.shape[0], like=inputs) if state is None else state
        self.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)
        params = [c.financial_parameters() for c in self.cells]
        boundaries = [c._base_boundary(p) for c, p in zip(self.cells, params)]
        outputs = []
        for k, dt in enumerate(intervals):
            held = (inputs[:, k], *(s[0] for s in state[:-1]))
            state = tuple(c.step(x, s, dt, params=p, base_boundary=b)
                          for c, x, s, p, b in zip(self.cells, held, state, params, boundaries))
            outputs.append(self.readout(state[-1][0]))
        return torch.stack(outputs, dim=1), state


def model_bytes(model, **extra):
    buffer = io.BytesIO()
    from .population_graph import PopulationCellGraph
    from .population_age_graph import PopulationAgeCellGraph
    version = 3 if isinstance(model, PopulationAgeCellGraph) else 2 if isinstance(model, PopulationCellGraph) else 1
    torch.save(dict(schema_version=version, spec=asdict(model.spec),
                    dtype=str(next(model.parameters()).dtype),
                    model_state={n: p.detach().cpu().clone() for n, p in model.state_dict().items()},
                    **extra), buffer)
    return buffer.getvalue()


def load_training_checkpoint(path, expected_sha256):
    """Recover exact tensors; the owner must check saved binding/time against its context."""
    if Path(path).stat().st_size > 32*1024*1024:
        raise ValueError("checkpoint byte budget exceeded")
    with Path(path).open("rb") as stream:
        payload = stream.read(32*1024*1024+1)
    if len(payload) > 32*1024*1024 or hashlib.sha256(payload).hexdigest() != sha256(expected_sha256):
        raise ValueError("checkpoint byte identity/size mismatch")
    saved = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
    fields = {"schema_version", "spec", "dtype", "model_state"}
    candidate_fields = {"optimizer", "binding", "final_state", "last_end_micros"}
    if (set(saved) not in (fields, fields | candidate_fields) or type(saved["schema_version"]) is not int
            or saved["schema_version"] not in (1, 2, 3) or saved["dtype"] not in ("torch.float32", "torch.float64")):
        raise ValueError("unsupported checkpoint schema/precision")
    spec = dict(saved["spec"], cell_ids=tuple(saved["spec"]["cell_ids"]))
    if saved["schema_version"] == 1:
        model = JointCellGraph(GraphSpec(**spec))
    elif saved["schema_version"] == 2:
        from .population_graph import PopulationCellGraph, PopulationGraphSpec
        model = PopulationCellGraph(PopulationGraphSpec(**spec))
    else:
        from .population_age_graph import PopulationAgeCellGraph, PopulationAgeGraphSpec
        if set(spec) != set(PopulationAgeGraphSpec.__dataclass_fields__):
            raise ValueError("population age checkpoint requires explicit kernel and migration fields")
        model = PopulationAgeCellGraph(PopulationAgeGraphSpec(**spec))
    model = model.to(dtype=getattr(torch, saved["dtype"].split(".")[1]))
    tensor_digest(saved["model_state"])
    if any(t.dtype != next(model.parameters()).dtype for t in saved["model_state"].values()):
        raise ValueError("checkpoint tensor precision mismatch")
    for name, buffer in model.named_buffers():
        if name not in saved["model_state"] or not torch.equal(buffer, saved["model_state"][name]):
            raise ValueError("checkpoint changed fixed population grid/reset buffers")
    model.load_state_dict(saved["model_state"], strict=True)
    state = saved.get("final_state")
    if set(saved) == fields | candidate_fields and state is None:
        raise ValueError("candidate checkpoint lacks complete final state")
    if state is not None:
        integer(saved["last_end_micros"])
        if saved["schema_version"] in (2, 3):
            if (not isinstance(state, (list, tuple)) or not state or not isinstance(state[0], (list, tuple))
                    or not state[0] or not isinstance(state[0][0], torch.Tensor) or state[0][0].ndim != 2):
                raise ValueError("invalid checkpoint population state")
            integer(state[0][0].shape[0], maximum=64)
            model.validate_state(state, state[0][0].shape[0], next(model.parameters()).dtype, torch.device("cpu"))
        elif (not isinstance(state, (list, tuple)) or len(state) != len(model.cells)
                or any(not isinstance(s, (list, tuple)) or len(s) != 2 for s in state)
                or any(not isinstance(v, torch.Tensor) or v.ndim != 2 or not 1 <= v.shape[0] <= 64
                       or v.shape != state[0][0].shape or v.shape[1] != model.spec.hidden_size
                       or v.dtype != next(model.parameters()).dtype for s in state for v in s)):
            raise ValueError("invalid checkpoint logical cell state")
        tensor_digest({str(i): v for i, v in enumerate(v for s in state for v in s)})
    return model, state, {k: v for k, v in saved.items() if k not in {"model_state", "final_state"}}


def load_model(path, expected_sha256):
    return load_training_checkpoint(path, expected_sha256)[0]
