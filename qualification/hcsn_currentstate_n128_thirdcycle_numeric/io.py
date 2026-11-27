"""Binary output helpers for the third-cycle numerical stage."""

import hashlib
import json
from pathlib import Path

import numpy as np


def write_f64le(path, values):
    array = np.fromiter(values, dtype="<f8")
    target = Path(path)
    target.write_bytes(array.tobytes(order="C"))
    return len(array), hashlib.sha256(target.read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
