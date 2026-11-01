"""Fixed research fixtures from the R13 propagation contract, with provenance."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
R13 = ROOT.parent
sys.path.insert(0, str(R13))
from propagation.api import generator_numpy
from propagation.api import make_grid


def fvm_fixture(inner_step=0.025, sigma=0.3, reset_x=0.325):
    edges = make_grid(inner_step=inner_step, horizon=29.4)
    result = generator_numpy(sigma, 0.06-sigma**2/2, reset_x, edges)
    return {key: np.asarray(value) for key, value in result.items()}


def save_fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    models = {"coarse": fvm_fixture(0.05), "default": fvm_fixture(),
              "fine": fvm_fixture(0.0125, 0.4), "updated": fvm_fixture(0.025, 0.36, 0.28)}
    receipts = []
    for name, model in models.items():
        path = destination / f"{name}.npz"
        np.savez_compressed(path, **model)
        receipts.append({"name": name, "path": str(path), "n": len(model["prior"]),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    source = {str(p.relative_to(R13)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((R13/"propagation").glob("*.py"))}
    (destination/"FIXTURES.json").write_text(json.dumps({"models": receipts,
        "propagation_source_sha256": source, "parameters": {"horizon": 29.4,
        "default_sigma": 0.3, "default_reset_x": 0.325, "drift": "0.06-sigma^2/2"}}, indent=2)+"\n")
    return models
