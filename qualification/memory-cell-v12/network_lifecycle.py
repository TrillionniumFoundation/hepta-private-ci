"""Portable research checkpoints and explicit per-cell maintenance transitions."""

import copy
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from network import Cell, Network, digest, fit_cell


def _payload(cell):
    if cell.model is not None:
        return cell.model.export(include_optimizer=True)
    value = json.loads(Path(cell.sleeping["path"]).read_text())
    if digest(value) != cell.sleeping["digest"]:
        raise ValueError("sleep dependency identity changed")
    return value


def save_network(path, network):
    path = Path(path)
    state = copy.deepcopy(network.export())
    dependencies = {}
    for cell in state["cells"]:
        pin = cell.get("sleeping")
        if pin is None:
            continue
        raw = Path(pin["path"]).read_bytes()
        if digest(json.loads(raw)) != pin["digest"]:
            raise ValueError("sleep dependency differs before copy")
        name = "sleep-" + pin["digest"] + ".json"
        destination = path.parent / name
        if destination.exists():
            if destination.read_bytes() != raw:
                raise ValueError("portable dependency name collision")
        else:
            with destination.open("xb") as stream:
                stream.write(raw)
        pin.update(path=name, bytes=len(raw), portable=True)
        dependencies[name] = len(raw)
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    with gzip.open(path, "wb") as stream:
        stream.write(raw)
    return dict(path=path.name, bytes=path.stat().st_size, dependency_bytes=sum(dependencies.values()),
                dependencies=dependencies, raw_serialized_bytes=len(raw),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def load_network(path):
    path = Path(path)
    with gzip.open(path, "rb") as stream:
        state = json.load(stream)
    for cell in state["cells"]:
        pin = cell.get("sleeping")
        if pin is None:
            continue
        if pin.get("portable") and Path(pin["path"]).name != pin["path"]:
            raise ValueError("portable dependency must be a local basename")
        local = path.parent / Path(pin["path"]).name
        value = json.loads(local.read_text())
        if digest(value) != pin["digest"]:
            raise ValueError("portable sleep dependency identity changed")
        pin["path"] = str(local.resolve())
    return Network.restore(state)


def refresh(previous, x, y, mask, dependencies, seed, protocol):
    hidden, steps = protocol["hidden"], protocol["steps"]
    objective = protocol.get("objective", "binary")
    if previous is None:
        cell = fit_cell("parent", "universal", x, y, np.arange(len(mask)), dependencies,
                        hidden=hidden, steps=steps, seed=seed, objective=objective)
        return Network([cell], len(mask))
    refreshed, audit = [], []
    _, routes = previous.scores(x, mask)
    for i, old in enumerate(previous.cells):
        before = _payload(old)
        assigned = np.array([old.name in route for route in routes])
        action = "sleeping" if old.model is None else "unassigned" if not assigned.any() else "continued"
        if action != "continued":
            cell = Cell.restore(old.export())
        else:
            cell = fit_cell(old.name, old.kind, x[assigned], y[assigned], old.allowed,
                            old.dependencies + dependencies, hidden=hidden, steps=steps,
                            seed=seed + i, initial=old.model, objective=objective)
            cell.receipts = old.receipts + cell.receipts
        after = _payload(cell)
        audit.append(dict(name=old.name, action=action,
                          before_parameter_sha256=before["parameter_sha256"],
                          after_parameter_sha256=after["parameter_sha256"],
                          before_optimizer_step=before.get("optimizer", {}).get("step", 0),
                          after_optimizer_step=after.get("optimizer", {}).get("step", 0)))
        refreshed.append(cell)
    result = Network(refreshed, len(mask), previous.top_k)
    result.refresh_receipt = audit
    if len(refreshed) > 1:
        result.fit_router(x, y)
    verify_refresh(previous, result)
    return result


def verify_refresh(previous, result):
    if [cell.name for cell in previous.cells] != [cell.name for cell in result.cells]:
        raise AssertionError("refresh changed the cell identity set")
    if len(result.refresh_receipt) != len(previous.cells):
        raise AssertionError("incomplete refresh provenance")
    for old, new, item in zip(previous.cells, result.cells, result.refresh_receipt, strict=True):
        before, after = _payload(old), _payload(new)
        if item["name"] != old.name or item["before_parameter_sha256"] != before["parameter_sha256"] or item["after_parameter_sha256"] != after["parameter_sha256"]:
            raise AssertionError("refresh parameter provenance mismatch")
        if item["action"] == "continued":
            if len(new.receipts) != len(old.receipts) + 1 or new.receipts[-1]["initial_parameter_sha256"] != before["parameter_sha256"]:
                raise AssertionError("continuation used a different parent")
            if item["after_optimizer_step"] <= item["before_optimizer_step"]:
                raise AssertionError("continuation did not advance the optimizer")
        elif item["action"] in ("sleeping", "unassigned"):
            if before != after or old.receipts != new.receipts:
                raise AssertionError("untrained cell parameters or optimizer changed")
        else:
            raise AssertionError("unknown refresh transition")
    return True
