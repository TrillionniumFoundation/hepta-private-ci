"""Executable BatchedFlow state plus frozen-encoder ridge sufficient statistics.

This schema supports CPU FP64, deterministic execution and closed-form readout
proposals. It has no optimizer, stochastic transition or queued point events:
the bounded Erlang phase populations ARE its renewal state. It saves no AD tape.
The active readout is never replaced by a proposal. Numerical execution remains
the existing PyTorch BatchedFlow kernel, not a new native Rust numerical kernel.
"""

from dataclasses import asdict
import copy
import hashlib
import json
import math

import numpy as np
import torch

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig, FlowState
from qualification.hcsn_adaptive.budget import CostLedger


SCHEMA = b"hepta.hcsn.streaming-ridge-state.v1.cpu-f64.erlang.population"
RULE = b"hepta.hcsn.learning-rule.closed-form-readout.v1"
MASK = b"hepta.hcsn.parameter-mask.v2\0" + b"".join(
    len(name).to_bytes(8, "big") + name for name in (b"readout.bias", b"readout.weight"))
MAGIC = b"hepta.hcsn.complete-research-state.v2\0"
BINDINGS = ("request_digest", "base_checkpoint_digest", "code_digest", "dataset_digest",
            "runtime_digest", "backend_state_schema_digest", "parameter_mask_digest",
            "learning_rule_digest")
MAX_BYTES = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def parse_json(data):
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=nonfinite)


def tensor_record(tensor):
    tensor = tensor.detach().cpu().contiguous()
    if tensor.dtype != torch.float64 or not torch.isfinite(tensor).all():
        raise ValueError("finite FP64 tensor required")
    return {"shape": list(tensor.shape), "bits": tensor.numpy().view(np.uint64).ravel().tolist()}


def tensor_restore(record, shape):
    if (set(record) != {"shape", "bits"} or type(record["shape"]) is not list
            or any(type(x) is not int or x < 0 for x in record["shape"])
            or record["shape"] != list(shape)
            or len(record["bits"]) != math.prod(shape)
            or any(type(x) is not int or not 0 <= x < 2**64 for x in record["bits"])):
        raise ValueError("invalid tensor dimensions or IEEE bits")
    result = torch.from_numpy(np.asarray(record["bits"], dtype=np.uint64).view(np.float64).copy()).reshape(shape)
    if not torch.isfinite(result).all():
        raise ValueError("nonfinite tensor")
    return result


def validate_geometry(flow):
    """Unsaved geometry must equal the exact configuration-derived buffers."""
    c = flow.config
    edges = torch.linspace(0.0, c.extent, c.bins + 1, dtype=torch.float64)
    centers = (edges[1:] + edges[:-1]) / 2
    reset = torch.relu(1 - (centers - c.reset_margin).abs() / (c.extent / c.bins))
    expected = {"edges": edges, "centers": centers, "reset": reset / reset.sum()}
    actual = dict(flow.named_buffers())
    if set(actual) != set(expected) or any(
            actual[name].dtype != torch.float64 or actual[name].device.type != "cpu"
            or not torch.equal(actual[name], value) for name, value in expected.items()):
        raise ValueError("noncanonical geometry cannot use the configuration-only state schema")


def encode_state(binding, sections):
    if set(binding) != set(BINDINGS) or set(sections) != {
            "parameters", "backend", "controller", "rng", "cost_ledger", "history"}:
        raise ValueError("complete named state required")
    digests = [bytes.fromhex(binding[key]) for key in BINDINGS]
    if (any(len(x) != 32 or x == bytes(32) for x in digests)
            or binding["backend_state_schema_digest"] != hashlib.sha256(SCHEMA).hexdigest()
            or binding["learning_rule_digest"] != hashlib.sha256(RULE).hexdigest()
            or binding["parameter_mask_digest"] != hashlib.sha256(MASK).hexdigest()):
        raise ValueError("invalid recovery binding")
    values = [sections["parameters"], sections["backend"], b"", sections["controller"],
              sections["rng"], sections["cost_ledger"], sections["history"]]
    data = MAGIC + b"".join(digests) + b"\0"  # Explicit optimizer NotUsed.
    for section in values:
        data += len(section).to_bytes(8, "big") + section
    if len(data) > MAX_BYTES:
        raise ValueError("complete state exceeds 64 MiB")
    return data


def decode_state(data, expected_binding):
    if len(data) > MAX_BYTES or not data.startswith(MAGIC):
        raise ValueError("invalid complete-state envelope")
    offset = len(MAGIC)
    binding = {}
    for key in BINDINGS:
        binding[key] = data[offset:offset + 32].hex()
        offset += 32
    if binding != expected_binding or data[offset:offset + 1] != b"\0":
        raise ValueError("recovery identity or optimizer mismatch")
    offset += 1
    sections = {}
    for key in ("parameters", "backend", "optimizer", "controller", "rng", "cost_ledger", "history"):
        if offset + 8 > len(data):
            raise ValueError("truncated section")
        size = int.from_bytes(data[offset:offset + 8], "big")
        offset += 8
        if size > len(data) - offset:
            raise ValueError("truncated section body")
        sections[key] = data[offset:offset + size]
        offset += size
    if offset != len(data) or sections.pop("optimizer") != b"" or encode_state(binding, sections) != data:
        raise ValueError("noncanonical state envelope")
    return {name: parse_json(value) for name, value in sections.items()}


def check_cost(records, identity, controller, batch):
    """Verify the exported journal, including failed work, without a live learner."""
    tail, pending, observations, examples, solves, budget, wall = "0" * 64, None, 0, 0, 0, None, 0.0
    for index, item in enumerate(records):
        if (set(item) != {"canonical", "hash"}
                or hashlib.sha256(item["canonical"].encode()).hexdigest() != item["hash"]):
            raise ValueError("invalid cost journal hash")
        record = parse_json(item["canonical"])
        budget = record["budget"] if budget is None else budget
        if record["previous"] != tail or record["identity"] != identity or record["budget"] != budget:
            raise ValueError("cost chain, request or budget mismatch")
        if record["kind"] == "reserve":
            if pending is not None or record["operation"] != index:
                raise ValueError("overlapping or unbound cost operation")
            if (record["name"] not in ("stream_observation", "closed_form_readout", "checkpoint")
                    or any(type(x) is not int or x < 0 for x in record["charge"].values())):
                raise ValueError("unsupported work in streaming journal")
            pending = record
        elif record["kind"] == "settle":
            if (pending is None or pending["operation"] != record["operation"]
                    or pending["name"] != record["name"] or record["status"] not in ("completed", "failed")
                    or not math.isfinite(record["cumulative_wall_seconds"])
                    or record["cumulative_wall_seconds"] < wall):
                raise ValueError("invalid cost settlement")
            if record["status"] == "completed":
                if record["name"] == "stream_observation":
                    observations += 1
                    examples += pending["charge"]["training_examples"]
                    if pending["charge"]["training_examples"] not in (0, batch):
                        raise ValueError("wrong supervised batch charge")
                solves += int(record["name"] == "closed_form_readout")
            wall, pending = record["cumulative_wall_seconds"], None
        else:
            raise ValueError("unknown cost event")
        tail = item["hash"]
    if pending is not None or (observations, examples, solves) != tuple(
            controller[name] + controller["discarded_" + name] for name in ("observations", "examples", "solves")):
        raise ValueError("controller is not backed by settled physical work")


def validate_statistics(gram, cross, examples, ridge):
    if (gram.ndim != 2 or gram.shape[0] != gram.shape[1] or cross.ndim != 2
            or cross.shape[0] != len(gram) or not torch.isfinite(gram).all()
            or not torch.isfinite(cross).all() or not torch.equal(gram, gram.T)
            or bool((gram.diag() < 0).any()) or gram[-1, -1] != examples):
        raise ValueError("invalid ridge sufficient-statistic matrix")
    if examples == 0:
        if bool((gram != 0).any()) or bool((cross != 0).any()):
            raise ValueError("unobserved statistics must be zero")
    else:
        penalty = torch.eye(len(gram), dtype=torch.float64) * ridge
        penalty[-1, -1] = 0
        # A positive ridge with observations requires a positive-definite normal
        # matrix. No task tolerance or previous qualification threshold is changed.
        normal = gram + penalty
        if not torch.isfinite(normal).all() or bool(torch.linalg.cholesky_ex(normal).info != 0):
            raise ValueError("ridge normal matrix is not positive definite")


class StreamingRidge:
    """A concrete bounded inference/training state; all future work is deterministic."""

    def __init__(self, flow, readout, *, batch, ridge, binding, ledger):
        if (type(flow) is not BatchedFlow or type(batch) is not int
                or type(ridge) is not float or not math.isfinite(ridge) or ridge <= 0
                or type(readout) is not torch.nn.Linear or readout.bias is None
                or readout.in_features != len(flow.feature_names)
                or not 1 <= readout.out_features <= 64
                or any(p.dtype != torch.float64 or p.device.type != "cpu"
                       for p in (*flow.parameters(), *readout.parameters()))):
            raise ValueError("CPU FP64 BatchedFlow and matching readout required")
        if not isinstance(ledger, CostLedger) or ledger.identity != binding["request_digest"] or ledger.pending is not None:
            raise ValueError("settled admitted cost journal required")
        validate_geometry(flow)
        # Reconstruct the admitted modules so hooks or incidental Python object
        # attributes cannot become unsaved future-relevant behavior.
        with torch.random.fork_rng(devices=[]):
            self.flow = BatchedFlow(flow.config)
            self.readout = torch.nn.Linear(readout.in_features, readout.out_features, dtype=torch.float64)
        self.flow.load_state_dict(flow.state_dict())
        self.readout.load_state_dict(readout.state_dict())
        self.flow.requires_grad_(False)
        self.readout.requires_grad_(False)
        self.state = self.flow.initial_state(batch)
        self.ridge, self.binding, self.ledger = ridge, dict(binding), ledger
        width = readout.in_features + 1
        self.gram = torch.zeros(width, width, dtype=torch.float64)
        self.cross = torch.zeros(width, readout.out_features, dtype=torch.float64)
        self.observations = self.examples = self.solves = 0
        self.discarded_observations = self.discarded_examples = self.discarded_solves = 0

    @torch.no_grad()
    def observe(self, inputs, *, dt, targets=None, boundary=None):
        batch = self.state.density.shape[0]
        if (inputs.shape != (batch, self.flow.config.input_size)
                or (targets is not None and (targets.shape != (batch, self.readout.out_features)
                    or targets.dtype != torch.float64 or targets.device.type != "cpu"
                    or not torch.isfinite(targets).all()))):
            raise ValueError("matching input batch and finite FP64 targets required")
        with self.ledger.operation("stream_observation", encoder_events=batch,
                                   forward_examples=batch, training_examples=0 if targets is None else batch):
            features, state, _ = self.flow.step(inputs, self.state, dt=dt, boundary_override=boundary)
            prediction = self.readout(features)
            gram, cross = self.gram, self.cross
            if targets is not None:
                design = torch.cat((features, torch.ones(batch, 1, dtype=torch.float64)), 1)
                gram, cross = gram + design.T @ design, cross + design.T @ targets
                if not torch.isfinite(gram).all() or not torch.isfinite(cross).all():
                    raise FloatingPointError("nonfinite ridge statistics")
            if not torch.isfinite(prediction).all():
                raise FloatingPointError("nonfinite prediction")
            self.state, self.gram, self.cross = state.detach(), gram, cross
            self.observations += 1
            self.examples += 0 if targets is None else batch
        return prediction, features

    @torch.no_grad()
    def propose(self):
        if self.examples == 0:
            raise ValueError("no supervised observations")
        with self.ledger.operation("closed_form_readout", proposals=1):
            penalty = torch.eye(len(self.gram), dtype=torch.float64) * self.ridge
            penalty[-1, -1] = 0
            weight = torch.linalg.solve(self.gram + penalty, self.cross)
            if not torch.isfinite(weight).all():
                raise FloatingPointError("nonfinite ridge proposal")
            candidate = copy.deepcopy(self.readout)
            candidate.weight.copy_(weight[:-1].T)
            candidate.bias.copy_(weight[-1])
            self.solves += 1
        return candidate

    def snapshot(self):
        if self.ledger.pending is not None:
            raise ValueError("cannot snapshot an unsettled operation")
        validate_geometry(self.flow)
        self.flow.validate_state(self.state, len(self.state.boundary), torch.float64, torch.device("cpu"))
        validate_statistics(self.gram, self.cross, self.examples, self.ridge)
        parameters = {"flow": {key: tensor_record(value) for key, value in self.flow.named_parameters()},
                      "readout": {key: tensor_record(value) for key, value in self.readout.named_parameters()}}
        cost = []
        for item in self.ledger.records:
            record = {key: value for key, value in item.items() if key != "hash"}
            cost.append({"canonical": canonical(record).decode(), "hash": item["hash"]})
        sections = {
            "parameters": parameters,
            "backend": {"schema": SCHEMA.decode(), "config": asdict(self.flow.config),
                        "batch": len(self.state.boundary), "output_size": self.readout.out_features,
                        "density": tensor_record(self.state.density), "boundary": tensor_record(self.state.boundary),
                        "time_micros": self.state.time_micros},
            "controller": {"rule": "closed_form_readout", "ridge": self.ridge,
                           **{key: getattr(self, key) for key in ("observations", "examples", "solves",
                             "discarded_observations", "discarded_examples", "discarded_solves")}},
            "rng": {"kind": "not_used", "reason": "deterministic_frozen_encoder_and_ridge"},
            "cost_ledger": {"identity": self.ledger.identity, "records": cost},
            "history": {"kind": "ridge_sufficient_statistics", "gram": tensor_record(self.gram),
                        "cross": tensor_record(self.cross), "past_autograd_retained": False},
        }
        check_cost(cost, self.ledger.identity, sections["controller"], len(self.state.boundary))
        return encode_state(self.binding, {name: canonical(value) for name, value in sections.items()})

    @classmethod
    def restore(cls, data, *, expected_binding, expected_digest, ledger):
        """The expected digest/bindings must be retained independently of the file."""
        if hashlib.sha256(data).hexdigest() != expected_digest:
            raise ValueError("unacknowledged checkpoint bytes")
        sections = decode_state(data, expected_binding)
        backend, controller, history = (sections[key] for key in ("backend", "controller", "history"))
        if (set(backend) != {"schema", "config", "batch", "output_size", "density", "boundary", "time_micros"}
                or backend["schema"] != SCHEMA.decode()
                or sections["rng"] != {"kind": "not_used", "reason": "deterministic_frozen_encoder_and_ridge"}
                or set(controller) != {"rule", "ridge", "observations", "examples", "solves",
                                      "discarded_observations", "discarded_examples", "discarded_solves"}
                or controller["rule"] != "closed_form_readout"
                or set(history) != {"kind", "gram", "cross", "past_autograd_retained"}
                or history["kind"] != "ridge_sufficient_statistics" or history["past_autograd_retained"] is not False):
            raise ValueError("unsupported backend, learning rule or history")
        # Constructor initialization cannot alter the caller's unrelated RNG stream.
        with torch.random.fork_rng(devices=[]):
            flow = BatchedFlow(FlowConfig(**backend["config"]))
            readout = torch.nn.Linear(len(flow.feature_names), backend["output_size"], dtype=torch.float64)
        if set(sections["parameters"]) != {"flow", "readout"}:
            raise ValueError("invalid parameter sections")
        for group, model in (("flow", flow), ("readout", readout)):
            saved, expected = sections["parameters"][group], dict(model.named_parameters())
            if set(saved) != set(expected):
                raise ValueError("parameter names mismatch")
            with torch.no_grad():
                for name, parameter in expected.items():
                    parameter.copy_(tensor_restore(saved[name], parameter.shape))
        result = cls(flow, readout, batch=backend["batch"], ridge=controller["ridge"],
                     binding=expected_binding, ledger=ledger)
        batch, width = backend["batch"], readout.in_features + 1
        result.state = FlowState(tensor_restore(backend["density"], result.state.density.shape),
                                 tensor_restore(backend["boundary"], (batch,)),
                                 backend["time_micros"], flow.config)
        flow.validate_state(result.state, batch, torch.float64, torch.device("cpu"))
        result.gram = tensor_restore(history["gram"], (width, width))
        result.cross = tensor_restore(history["cross"], (width, readout.out_features))
        for key in ("observations", "examples", "solves", "discarded_observations", "discarded_examples", "discarded_solves"):
            if type(controller[key]) is not int or not 0 <= controller[key] < 2**53:
                raise ValueError("invalid controller count")
            setattr(result, key, controller[key])
        if (result.examples > result.observations * batch or result.examples % batch
                or result.gram[-1, -1] != result.examples
                or not torch.equal(result.gram, result.gram.T)
                or bool((result.gram.diag() < 0).any())):
            raise ValueError("ridge statistics and controller disagree")
        validate_statistics(result.gram, result.cross, result.examples, result.ridge)
        saved_cost = sections["cost_ledger"]
        if set(saved_cost) != {"identity", "records"} or saved_cost["identity"] != ledger.identity:
            raise ValueError("cost identity mismatch")
        expected_cost = []
        for item in ledger.records[:len(saved_cost["records"])]:
            raw = {key: value for key, value in item.items() if key != "hash"}
            expected_cost.append({"canonical": canonical(raw).decode(), "hash": item["hash"]})
        if saved_cost["records"] != expected_cost:
            raise ValueError("checkpoint cost is not an authenticated journal prefix")
        check_cost(saved_cost["records"], ledger.identity, controller, batch)
        # Physical work after this checkpoint stays charged in the same ledger.
        reservations = {item["operation"]: item for item in ledger.records if item["kind"] == "reserve"}
        for item in ledger.records[len(expected_cost):]:
            if item["kind"] == "settle" and item["status"] == "completed":
                reservation = reservations[item["operation"]]
                if item["name"] == "stream_observation":
                    result.discarded_observations += 1
                    result.discarded_examples += reservation["charge"]["training_examples"]
                result.discarded_solves += int(item["name"] == "closed_form_readout")
        return result
