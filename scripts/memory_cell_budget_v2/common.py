"""Reuse frozen accounting primitives without importing a model runtime."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
_ledger = importlib.import_module("scripts.memory_cell_budget.budget_ledger")
BudgetExceeded, BudgetLedger, METERS = (
    _ledger.BudgetExceeded,
    _ledger.BudgetLedger,
    _ledger.METERS,
)
canonical, digest, quantities = _ledger.canonical, _ledger.digest, _ledger.quantities
file_record = importlib.import_module(
    "scripts.memory_cell_cost_v2.storage_ledger"
).file_record

__all__ = [
    "BudgetExceeded",
    "BudgetLedger",
    "METERS",
    "canonical",
    "digest",
    "quantities",
    "file_identity",
    "read_json",
    "save",
    "observations",
]


def file_identity(path):
    record, _ = file_record(path)
    return {key: record[key] for key in ("bytes", "sha256")}


def read_json(path, expected, maximum=16 * 1024**2):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("pinned regular file required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if (
        len(raw) > maximum
        or {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} != expected
    ):
        raise ValueError("pinned bytes changed")
    return json.loads(raw)


def save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def observations(value):
    if type(value) is not dict or set(value) != set(METERS):
        raise ValueError("every observed meter must be explicit, including null")
    for number in value.values():
        if number is not None and (type(number) is not int or not 0 <= number < 2**127):
            raise ValueError("nonnegative observation or null required")
    return dict(value)
