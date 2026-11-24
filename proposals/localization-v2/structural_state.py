"""Development-only CPU AdamW checkpoint repartitioning, never native adoption.

Split/merge move whole named tensor records through the existing ORG-1 reference.
They do not change neuron count or distribute execution. Materialization uses a
fresh-episode template; RNG, schedulers and live hidden states are outside scope.
Measured serialization is to memory, not physical/network migration traffic.
The post-encoding 64 MiB object limit is not an aggregate memory bound; the
retained checkpoint trace grows with the number of records transferred.
"""

import base64
import copy
from functools import wraps
import hashlib
import io
import time

import torch

from scripts.ndu_real_runtime.causal_protocol import digest
from scripts.ndu_real_runtime.causal_topology import _graph as validate_graph
from scripts.ndu_real_runtime.organization_reference import _index, _transition, _values
from scripts.ndu_real_runtime.organization_reference_artifacts import encoded, graph


class StateTransferError(ValueError):
    """A rejected attempt retains observations, including partial serializations."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


def _measured(function):
    @wraps(function)
    def run(*args, **kwargs):
        wall, cpu = time.perf_counter(), time.process_time()
        receipt = {
            "stage": function.__name__,
            "status": "failed",
            "json_bytes_serialized": 0,
            "torch_archive_bytes_serialized": 0,
            "torch_archive_bytes_loaded": 0,
            "checkpoints": [],
            "lineage": [],
            "tensor_payload_bytes_moved": 0,
            "archive_payload_bytes_moved": 0,
            "physical_transferred_bytes": None,
            "energy_joules": None,
            "full_physical_cost_known": False,
            "scientific_acceptance": "HOLD",
            "adoption_authorized": False,
            "failure_disposition": "discard_uninstalled_copy",
            "scope": "CPU fresh-episode development checkpoint; in-memory serialization",
        }
        try:
            result = function(receipt, *args, **kwargs)
            receipt["status"] = "completed"
            return result | {"receipt": receipt}
        except Exception as error:
            receipt["error"] = str(error)
            raise StateTransferError(str(error), receipt) from error
        finally:
            receipt["cpu_seconds"] = time.process_time() - cpu
            receipt["wall_seconds"] = time.perf_counter() - wall

    return run


def _json(value, receipt):
    raw = encoded(value)
    receipt["json_bytes_serialized"] += len(raw)
    if len(raw) > 64 * 1024**2:
        raise ValueError("development checkpoint exceeds 64 MiB")
    return raw


def _tensor_bytes(value):
    if isinstance(value, torch.Tensor):
        if (
            value.device.type != "cpu"
            or value.layout != torch.strided
            or not bool(torch.isfinite(value).all())
        ):
            raise ValueError("finite dense CPU tensors required")
        return value.numel() * value.element_size()
    if isinstance(value, dict):
        return sum(_tensor_bytes(v) for v in value.values())
    return 0


def _layout(model, optimizer):
    if type(optimizer) is not torch.optim.AdamW:
        raise ValueError("only the declared AdamW checkpoint schema is supported")
    pairs = list(model.named_parameters(remove_duplicate=False))
    tensors = model.state_dict()
    _tensor_bytes(tensors)
    pointers = [p.untyped_storage().data_ptr() for p in tensors.values()]
    if len(pointers) != len(set(pointers)) or any(p.grad is not None for _, p in pairs):
        raise ValueError(
            "untied parameters and a cleared-gradient step boundary required"
        )
    names = {id(p): name for name, p in pairs}
    groups, covered = [], []
    for group in optimizer.param_groups:
        roster = [names[id(p)] for p in group["params"]]
        if not roster or group.get("capturable") or group.get("differentiable"):
            raise ValueError("nonempty ordinary CPU AdamW groups required")
        options = copy.deepcopy({k: v for k, v in group.items() if k != "params"})
        options["betas"] = list(options["betas"])
        groups.append({"names": roster, "options": options})
        covered.extend(roster)
    if len(covered) != len(set(covered)) or set(covered) != {
        n for n, p in pairs if p.requires_grad
    }:
        raise ValueError("optimizer must cover each trainable named parameter once")
    if any(names.get(id(p)) not in covered for p in optimizer.state):
        raise ValueError("optimizer contains an unowned state")
    return dict(pairs), groups


def _identity(contract, kind, name):
    return hashlib.sha256((contract + ":" + kind + ":" + name).encode()).hexdigest()


def _validate(snapshot, expected_sha256, receipt):
    raw = _json(snapshot, receipt)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("checkpoint identity differs from caller's starting point")
    if snapshot["schema"] != "hepta.org1.trained-state-development.v1" or not digest(
        snapshot["contract"]
    ):
        raise ValueError("unsupported checkpoint or model contract")
    nodes, _ = validate_graph(snapshot["graph"], 4)
    state = snapshot["state"]
    if state["generation"] != snapshot["graph"]["generation"] or set(
        state["states"]
    ) != set(nodes):
        raise ValueError("graph and installed state membership differ")
    if any(
        n["state_owner"] != "python-reference:" + name
        or n["bundle_sha256"] != snapshot["contract"]
        for name, n in nodes.items()
    ):
        raise ValueError("owner or bundle identity drift")
    records = _values(state)
    if set(records) != set(snapshot["manifest"]):
        raise ValueError("missing or duplicate state record")
    for key, record in records.items():
        identity = {k: record[k] for k in ("name", "kind", "identity", "origin_owner")}
        if identity != snapshot["manifest"][key] or record["identity"] != _identity(
            snapshot["contract"], record["kind"], record["name"]
        ):
            raise ValueError("record lineage differs from the source manifest")
        raw = base64.b64decode(record["archive"], validate=True)
        if hashlib.sha256(raw).hexdigest() != record["archive_sha256"]:
            raise ValueError("training-state archive changed")
    return records


@_measured
def capture(receipt, model, optimizer, *, model_contract_sha256):
    """Detach named parameters, buffers, AdamW moments/steps and group settings."""
    if not digest(model_contract_sha256):
        raise ValueError("explicit source/configuration contract digest required")
    parameters, groups = _layout(model, optimizer)
    records, manifest = {}, {}
    payload_bytes = {"parameter": 0, "buffer": 0, "optimizer": 0}
    for index, (name, tensor) in enumerate(sorted(model.state_dict().items())):
        kind = "parameter" if name in parameters else "buffer"
        state = (
            copy.deepcopy(optimizer.state.get(parameters[name], {}))
            if kind == "parameter"
            else {}
        )
        value = {"tensor": tensor.detach().clone(), "optimizer": state}
        sizes = {
            kind: _tensor_bytes(value["tensor"]),
            "optimizer": _tensor_bytes(state),
        }
        for category, size in sizes.items():
            payload_bytes[category] += size
        stream = io.BytesIO()
        torch.save(value, stream)
        raw = stream.getvalue()
        receipt["torch_archive_bytes_serialized"] += len(raw)
        key = f"k{index:04}"
        manifest[key] = {
            "name": name,
            "kind": kind,
            "origin_owner": "python-reference:general",
            "identity": _identity(model_contract_sha256, kind, name),
        }
        records[key] = manifest[key] | {
            "archive": base64.b64encode(raw).decode(),
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "tensor_bytes": sizes,
        }
    snapshot = {
        "schema": "hepta.org1.trained-state-development.v1",
        "contract": model_contract_sha256,
        "manifest": manifest,
        "optimizer_groups": groups,
        "graph": graph(("general", "recovery"), 1, model_contract_sha256),
        "state": {
            "generation": 1,
            "states": {"general": {"records": records}, "recovery": {"completed": {}}},
        },
    }
    pin = hashlib.sha256(_json(snapshot, receipt)).hexdigest()
    receipt["tensor_payload_bytes"] = payload_bytes
    return {"snapshot": snapshot, "sha256": pin}


@_measured
def migrate(
    receipt, snapshot, operation, *, expected_sha256, interrupt_after_persist=False
):
    """Stage one existing reference transition; failed copies are never installed."""
    receipt.update(operation=operation, before_sha256=expected_sha256)
    records = _validate(snapshot, expected_sha256, receipt)
    if (
        type(interrupt_after_persist) is not bool
        or operation not in {"no_change", "split", "merge", "rewire"}
        or (operation == "no_change" and interrupt_after_persist)
    ):
        raise ValueError("unsupported operation or nonexistent no-change failure point")
    names = {n["id"] for n in snapshot["graph"]["nodes"]}
    expected = (
        {"left", "right", "recovery"}
        if operation == "merge"
        else {"general", "recovery"}
    )
    if operation != "no_change" and (
        names != expected
        or snapshot["graph"]
        != graph(names, snapshot["graph"]["generation"], snapshot["contract"])
    ):
        raise ValueError("operation requires its exact unrevised source layout")
    candidate, previous = copy.deepcopy(snapshot), _index(snapshot["state"])

    def persist(current_graph, state):
        nonlocal previous
        graph_raw, state_raw = _json(current_graph, receipt), _json(state, receipt)
        receipt["checkpoints"].append(
            {"graph_json": graph_raw.decode(), "state_json": state_raw.decode()}
        )
        current = _index(state)
        for key in sorted(current):
            if previous[key] != current[key]:
                record = records[key]
                receipt["lineage"].append(
                    {
                        "identity": record["identity"],
                        "from_owner": "python-reference:" + previous[key],
                        "to_owner": "python-reference:" + current[key],
                    }
                )
                receipt["tensor_payload_bytes_moved"] += sum(
                    record["tensor_bytes"].values()
                )
                receipt["archive_payload_bytes_moved"] += len(
                    base64.b64decode(record["archive"])
                )
        previous = current

    candidate["graph"], candidate["state"] = _transition(
        candidate["graph"],
        candidate["state"],
        operation,
        persist,
        inject=interrupt_after_persist,
    )
    pin = hashlib.sha256(_json(candidate, receipt)).hexdigest()
    installed = _validate(candidate, pin, receipt)
    if installed != records or (
        operation in {"no_change", "rewire"}
        and candidate["state"]["states"] != snapshot["state"]["states"]
    ):
        raise ValueError("transition changed trained values or no-move ownership")
    receipt.update(operation=operation, before_sha256=expected_sha256, after_sha256=pin)
    return {"snapshot": candidate, "sha256": pin}


@_measured
def materialize(
    receipt,
    snapshot,
    template_model,
    template_optimizer,
    *,
    expected_sha256,
    model_contract_sha256,
):
    """Return private model/optimizer copies, mapping saved states by stable name."""
    records = _validate(snapshot, expected_sha256, receipt)
    if snapshot["contract"] != model_contract_sha256:
        raise ValueError("model source/configuration contract mismatch")
    parameters, live_groups = _layout(template_model, template_optimizer)
    templates = template_model.state_dict()
    if {r["name"] for r in records.values()} != set(templates):
        raise ValueError("template tensor roster differs from checkpoint")
    weights, states = {}, {}
    for record in records.values():
        raw = base64.b64decode(record["archive"])
        receipt["torch_archive_bytes_loaded"] += len(raw)
        value = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
        name, tensor = record["name"], value["tensor"]
        if (
            tensor.shape != templates[name].shape
            or tensor.dtype != templates[name].dtype
            or record["kind"] != ("parameter" if name in parameters else "buffer")
        ):
            raise ValueError("template tensor shape, dtype or role differs")
        if {
            record["kind"]: _tensor_bytes(tensor),
            "optimizer": _tensor_bytes(value["optimizer"]),
        } != record["tensor_bytes"]:
            raise ValueError("tensor payload count differs from loaded bytes")
        weights[name], states[name] = tensor, value["optimizer"]
    saved_groups = {
        frozenset(g["names"]): g["options"] for g in snapshot["optimizer_groups"]
    }
    if len(saved_groups) != len(live_groups) or set(saved_groups) != {
        frozenset(g["names"]) for g in live_groups
    }:
        raise ValueError("optimizer group membership differs")
    model, optimizer = copy.deepcopy((template_model, template_optimizer))
    target = optimizer.state_dict()
    target["state"] = {}
    for group, live in zip(target["param_groups"], live_groups):
        ids = group["params"]
        options = copy.deepcopy(saved_groups[frozenset(live["names"])])
        options["betas"] = tuple(options["betas"])
        group.clear()
        group.update(options, params=ids)
        for identity, name in zip(ids, live["names"]):
            if states[name]:
                target["state"][identity] = states[name]
    model.load_state_dict(weights, strict=True)
    optimizer.load_state_dict(target)
    return {"model": model, "optimizer": optimizer}
