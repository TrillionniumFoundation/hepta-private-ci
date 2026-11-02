"""Shared finite-study IO and seven predeclared policy arms."""

import gzip
import hashlib
import json
import fcntl
from pathlib import Path

from experiments.hcsn_unknown_generator_r18_20261101.posterior import query_key
from experiments.hcsn_unknown_generator_r20_20261101.model import infer
from .controller import ReceiptFailure, execute

ROOT = Path(__file__).parent
ARM_MODELS = {
    "context_robust": ("context_mixture", "context_orbit"),
    "context_mixture": ("context_mixture",), "context_orbit": ("context_orbit",),
    "first_robust": ("first_mixture", "first_orbit"),
    "first_mixture": ("first_mixture",), "first_orbit": ("first_orbit",),
    "r20_context_common": ("r20_context_common",),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _new_bytes(path, data):
    # Linux research profile: serialize concurrent output-budget reservations.
    limit = json.loads((ROOT / "protocol.json").read_text())["total_output_budget_bytes"]
    with (ROOT / "output_budget.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        if size + len(data) > limit:
            raise OSError("Predeclared total component output budget exhausted")
        with Path(path).open("xb") as stream:
            stream.write(data)


def write(path, value):
    _new_bytes(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def archive(output, name, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path = output / (name + ".json.gz")
    _new_bytes(path, gzip.compress(raw, mtime=0))
    return dict(path=str(path.relative_to(ROOT)), sha256=digest(path), raw_sha256=hashlib.sha256(raw).hexdigest())


def frozen(name, publication):
    source = json.loads((ROOT / name).read_text())
    receipt = json.loads((ROOT / publication).read_text())
    if receipt.get("readback_verified") is not True or receipt.get("freeze_sha256") != digest(ROOT / name):
        raise ValueError("Missing verified remote freeze publication")
    for path, expected in source["files"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("Frozen scientific object changed: " + path)
    print(json.dumps(dict(verified_freeze=name, freeze_sha256=digest(ROOT / name),
        publication_sha256=digest(ROOT / publication), bound_files=len(source["files"])), sort_keys=True), flush=True)
    return source


def load_models():
    identity = json.loads((ROOT / "development_fit_final/FIT_IDENTITY.json").read_text())
    path = ROOT / "development_fit_final/MODELS.json.gz"
    if digest(path) != identity["files"]["MODELS.json.gz"]["sha256"]:
        raise ValueError("Corrected fitted model changed")
    models = json.loads(gzip.decompress(path.read_bytes()))
    legacy = ROOT / "inputs/r20_models.json.gz"
    if digest(legacy) != "c6f68af4cf9027464d7560c5d5c23ebc96a3892c0e410453cee23329bc007a86":
        raise ValueError("Legacy diagnostic model changed")
    models["r20_context_common"] = json.loads(gzip.decompress(legacy.read_bytes()))["context_orbit"]
    return models


def public(world):
    return {name:world[name].tolist() for name in ("prefix", "observed", "bridges", "query", "dt", "owner_events")}


def predictions(world, models, policies):
    # Policy names map to (science arm, threshold). Every policy independently
    # acquires its own token; only the common public-prefix computation is shared.
    try:
        key = query_key(world["bridges"], world["query"])
    except ValueError as error:
        return {name:dict(invalid=True, reason=str(error), fee=0., read_index=None) for name in policies}
    states, failures = {}, {}
    for name, model in models.items():
        try:
            states[name] = infer(world["prefix"], world["observed"], model)
        except ValueError as error:
            failures[name] = str(error)
    result = {}
    for policy, (arm, threshold) in policies.items():
        members = ARM_MODELS[arm]
        if any(name in failures for name in members):
            result[policy] = dict(invalid=True, reason="Declared model inference failed", fee=0., read_index=None)
            continue
        try:
            result[policy] = execute(world, [states[name] for name in members], key, threshold)
        except ReceiptFailure as error:
            result[policy] = dict(invalid=True, reason=str(error), read_index=error.read_index,
                                  fee=error.fee, issued_read=True, payoff=None)
        except ValueError as error:
            result[policy] = dict(invalid=True, reason=str(error), read_index=None, fee=0., payoff=None)
    return result


def counter():
    return dict(worlds=0, invalid=0, accepted=0, errors=0, fractional=0, fractional_errors=0,
                reads=0, fees=0., utility=0., before_brier=0., support_losses=0)


def accumulate(count, value):
    count["worlds"] += 1
    count["invalid"] += value["invalid"]
    count["fees"] += value["fee"]
    count["reads"] += value["read_index"] is not None
    if value["invalid"]:
        return
    a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
    for name, amount in zip(("accepted", "errors", "fractional", "fractional_errors"), (a, a and e, f, f and e), strict=True):
        count[name] += amount
    count["utility"] += value["payoff"]
    count["before_brier"] += value["before_brier"]
    count["support_losses"] += value["true_probability"] <= 0
