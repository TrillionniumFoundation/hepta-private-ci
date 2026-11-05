"""Explicit TSV export and numerical comparison; no pickle or whole-model claim."""
import hashlib
import math
import subprocess

ACTIONS = ("refine_semantic", "refine_image", "refine_text", "couple")
SCHEMA = "hepta.ndu-v6.continuation-linear.v1"
OUTPUT = "hepta.ndu-v6.continuation-linear-output.v1"


def _vector(value, n):
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise ValueError("Invalid numerical dimension")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError("Numbers must be explicit JSON numbers")
    row = [float(x) for x in value]
    if not all(math.isfinite(x) for x in row):
        raise ValueError("Nonfinite numerical value")
    return row


def export_request(record, features):
    """Export already identity-validated bundle arrays; this is not admission."""
    if record.get("schema") != "hepta.ndu-v6.continuation-head.v1":
        raise ValueError("Unknown continuation checkpoint schema")
    if record.get("actions") != list(ACTIONS):
        raise ValueError("Unknown continuation action order")
    f = len(record["mean"])
    b = len(features)
    if not 1 <= f <= 8192 or not 1 <= b <= 4096:
        raise ValueError("Dimension outside bounds")
    mean, scale = _vector(record["mean"], f), _vector(record["scale"], f)
    if any(s <= 0 for s in scale) or len(record["weight"]) != f + 1:
        raise ValueError("Invalid scale or weight dimension")
    weights = [_vector(row, 4) for row in record["weight"]]
    inputs = [_vector(row, f) for row in features]
    lines = [f"{SCHEMA}\t{f}\t{b}", "actions\t" + "\t".join(ACTIONS)]
    for name, rows in (("mean", [mean]), ("scale", [scale]),
                       ("weight", weights), ("features", inputs)):
        lines.extend(name + "\t" + "\t".join(format(v, ".17g") for v in row) for row in rows)
    raw = ("\n".join(lines) + "\n").encode("ascii")
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Numerical export exceeds byte limit")
    return raw


def compare_native(binary, record, features, torch_expected, *, atol=1e-10, rtol=1e-10):
    """Compare to caller-supplied actual Torch forward values from these weights."""
    if any(not math.isfinite(v) or v < 0 for v in (atol, rtol)):
        raise ValueError("Invalid comparison tolerance")
    request = export_request(record, features)
    expected = [_vector(row, 4) for row in torch_expected]
    if len(expected) != len(features):
        raise ValueError("Torch reference batch differs")
    process = subprocess.run([str(binary)], input=request, capture_output=True, timeout=30, check=True)
    lines = process.stdout.decode("ascii").splitlines()
    if (len(lines) != len(expected) + 2 or lines[0] != f"{OUTPUT}\t{len(expected)}"
            or lines[1] != "STOP\t" + "\t".join(ACTIONS)):
        raise ValueError("Unknown native output schema or dimensions")
    actual = [_vector([float(v) for v in line.split("\t")], 5) for line in lines[2:]]
    if any(row[0] != 0 for row in actual):
        raise ValueError("STOP must be exactly zero")
    errors = [abs(a - e) for row, ref in zip(actual, expected) for a, e in zip(row[1:], ref)]
    if any(abs(a - e) > atol + rtol * abs(e)
           for row, ref in zip(actual, expected) for a, e in zip(row[1:], ref)):
        raise ValueError(f"Torch/native numerical mismatch; max_abs_error={max(errors)}")
    return {"scope": "standardized_linear_continuation_head_only", "rows": len(actual),
            "features": len(record["mean"]), "max_abs_error": max(errors), "stop_value": 0,
            "atol": atol, "rtol": rtol, "request_sha256": hashlib.sha256(request).hexdigest()}
