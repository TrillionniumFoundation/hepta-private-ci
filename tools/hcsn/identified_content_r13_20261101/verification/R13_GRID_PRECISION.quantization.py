"""Post-observation diagnosis of eight original-input sensitivity deviations.

Preserves the frozen DS algorithm and the complete original 448-point result.
"""

import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "precision"))
from fresh import reference_tools
from development import error


def main():
    source = ROOT / "R13_GRID_PRECISION.json.gz"
    original = json.loads(gzip.decompress(source.read_bytes()))
    rows = []
    for row in original["rows"]:
        if row["original_input_comparison_pass"]:
            continue
        theta, x = row["theta_original"], row["state_original"]
        qt, qx = row["theta_quantized"], row["state_quantized"]
        ref = np.array(row["reference_original_jacobian"])
        quantized = np.array(row["reference_quantized_jacobian"])
        half = reference_tools.jac(theta, x, "log_distance", "5e-19")
        theta_only = reference_tools.jac(qt, x, "log_distance", "5e-19")
        state_only = reference_tools.jac(theta, qx, "log_distance", "5e-19")
        actual = np.array(row["jacobian"])
        normalized = np.abs(actual - ref) / np.maximum(1.0, np.abs(ref))
        f, p = np.unravel_index(np.argmax(normalized), normalized.shape)
        rows.append(dict(
            seed=row["seed"], center_index=row["index"], state=x,
            field_index=int(f), derivative_index=int(p),
            original_reference_halving_error=error(half, ref),
            original_half_step_jacobian=half.tolist(),
            theta_only_quantized_jacobian=theta_only.tolist(),
            state_only_quantized_jacobian=state_only.tolist(),
            theta_only_error=error(theta_only, ref),
            state_only_error=error(state_only, ref),
            all_inputs_quantization_error=error(quantized, ref),
            focus=dict(original=float(ref[f, p]),
                       theta_only=float(theta_only[f, p]),
                       state_only=float(state_only[f, p]),
                       both_quantized=float(quantized[f, p]),
                       actual=float(actual[f, p])),
        ))
    output = ROOT / "R13_GRID_PRECISION.quantization.json"
    assert not output.exists()
    payload = dict(
        status="Post-observation diagnostic of all eight original-input failures; no source, threshold, or primary result changed",
        original_results_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        interpretation="Quantization changes the evaluation point of the continuous Jacobian; these are not derivatives through the quantizer",
        rows=rows,
        max_original_reference_halving_error=max(r["original_reference_halving_error"] for r in rows),
    )
    output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps([{k: v for k, v in r.items() if not k.endswith("jacobian")} for r in rows], indent=2))


if __name__ == "__main__":
    main()
