"""Tensor-only complete forward-state records; no claim of restoring past AD."""

from fractions import Fraction

import torch

from qualification.hcsn_currentstate.differentiable import Atom, Flux, State
from .network import NetworkState


FIELDS = ("active", "upper", "hits", "discounted_hits", "occupation", "value", "discount_factor")


def _time(t):
    return [t.numerator, t.denominator]


def _tensor(t):
    return t.detach().clone()


def state_to_record(state):
    """Snapshot all current tensors without aliasing; weights_only load compatible."""
    cells = []
    for cell in state.cells:
        saved = {name: _tensor(getattr(cell, name)) for name in FIELDS}
        saved["time"] = _time(cell.time)
        saved["pending"] = []
        for packet in cell.pending:
            if isinstance(packet, Atom):
                saved["pending"].append({"kind": "atom", "time": _time(packet.time),
                                         "mass": _tensor(packet.mass), "reset": _tensor(packet.reset)})
            elif isinstance(packet, Flux):
                saved["pending"].append({"kind": "flux", "start": _time(packet.start), "end": _time(packet.end),
                                         **{name: _tensor(getattr(packet, name)) for name in
                                            ("alpha", "generator", "output", "reset")}})
            else:
                raise ValueError("unknown pending packet type")
        cells.append(saved)
    return {"schema": "hcsn-causal-network-state-v1", "past_autograd_retained": False,
            "batch_size": state.batch_size, "cells": cells,
            **{name: [_tensor(t) for t in getattr(state, name)] for name in
               ("messages", "written", "initial_totals")}}


def state_from_record(record):
    """Restore a trusted saved forward state, including the one-block messages."""
    if record.get("schema") != "hcsn-causal-network-state-v1" or record.get("past_autograd_retained") is not False:
        raise ValueError("unsupported forward-state schema")
    cells = []
    for saved in record["cells"]:
        pending = []
        for packet in saved["pending"]:
            if packet["kind"] == "atom":
                pending.append(Atom(Fraction(*packet["time"]), packet["mass"], packet["reset"]))
            elif packet["kind"] == "flux":
                pending.append(Flux(Fraction(*packet["start"]), Fraction(*packet["end"]),
                                    *[packet[name] for name in ("alpha", "generator", "output", "reset")]))
            else:
                raise ValueError("unknown pending packet kind")
        cells.append(State(Fraction(*saved["time"]), *[saved[name] for name in FIELDS], tuple(pending)))
    batch = record["batch_size"]
    if type(batch) is not int or not 1 <= batch <= 256:
        raise ValueError("invalid saved batch size")
    result = NetworkState(tuple(cells), *[tuple(record[name]) for name in
                                          ("messages", "written", "initial_totals")], batch)
    if not cells or any(len(x) != len(cells) for x in
                        (result.messages, result.written, result.initial_totals)):
        raise ValueError("saved population count mismatch")
    if any(c.time != result.time for c in cells) or any(not isinstance(t, torch.Tensor)
            or not bool(torch.isfinite(t).all()) for t in result.tensors()):
        raise ValueError("invalid saved state")
    return result
