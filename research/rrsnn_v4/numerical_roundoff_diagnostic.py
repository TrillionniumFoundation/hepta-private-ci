"""Post-result operator precision diagnosis; never replaces frozen evaluations.

Run only after all 60 original Lambert-versus-Brent controls are complete.
The grid is an independent conservative control envelope, not a task dataset.
No model weights, task scenarios, thresholds, or frozen sources are changed.
"""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prerequisites():
    path = ROOT / "results/numerical_matrix_status.json"
    status = json.loads(path.read_text())
    if status.get("all_completed") is not True:
        raise ValueError("All 60 original numerical controls must finish first")
    outputs = [item for run in status["completed"] for item in run["outputs"]]
    if len(outputs) != 60 or len({item["path"] for item in outputs}) != 60:
        raise ValueError("Original matrix is incomplete or duplicated")
    for item in outputs:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Original numerical result changed")
    freeze = json.loads((ROOT / "pre_data_freeze.json").read_text())
    for name, expected in freeze["source_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Frozen source changed: " + name)
    return {"matrix_status_sha256": sha(path),
            "selection_sha256": sha(ROOT / "selection.json"),
            "pre_data_protocol_sha256": sha(ROOT / "pre_data_freeze.json"),
            "original_comparison_files_verified": len(outputs),
            "original_matrix_identity": status["identity"],
            "frozen_source_sha256": freeze["source_sha256"]}


def main():
    if sorted(os.sched_getaffinity(0)) != [2]:
        raise ValueError("This diagnostic is allocated CPU2 only")
    identity = prerequisites()
    destination = ROOT / "results/numerical_roundoff_operator_diagnostic.json"
    fixture = destination.with_suffix(".npz")
    if destination.exists() or fixture.exists():
        raise FileExistsError("Precision diagnosis is write-once")

    import numpy as np
    import torch
    from scipy.special import lambertw
    from .operators import (_LambertW0, frozen_control_boundary,
                            numerical_control_boundary)
    from .train import check_disk

    available_before = check_disk()
    torch.set_num_threads(1)
    sigma, discount, refractory = .4, .4, .1
    drift_bound = 1.5 * math.tanh(1.)
    # RRPolicy: context=tanh(...), drift=1.5*tanh(context), resource in [0,1],
    # pressure=alive/(remaining+.25) in [0,4], and cost in [.20,.98].
    # The rectangle is conservative: its points need not all be jointly reachable.
    drift_values = np.linspace(-drift_bound, drift_bound, 65)
    cost_values = np.linspace(.20, .98, 65)
    aa, cc = np.meshgrid(drift_values, cost_values, indexing="ij")
    a32 = torch.tensor(aa, dtype=torch.float32)
    c32 = torch.tensor(cc, dtype=torch.float32)
    a64, c64 = a32.double(), c32.double()
    with torch.no_grad():
        shipped = frozen_control_boundary(a32, c32)
        root32 = numerical_control_boundary(a32, c32)
        root64 = numerical_control_boundary(a64, c64)
        analytic64 = frozen_control_boundary(a64, c64)
        promoted = analytic64.to(a32.dtype)
        g32 = (torch.sqrt(a32.square()+2*discount*sigma*sigma)-a32)/(sigma*sigma)
        g64 = (torch.sqrt(a64.square()+2*discount*sigma*sigma)-a64)/(sigma*sigma)
        z32 = -torch.exp(-discount*refractory-1-g32*c32)
        z64 = -torch.exp(-discount*refractory-1-g64*c64)
        rounded_gamma = c64 + (1+_LambertW0.apply(
            -torch.exp(-discount*refractory-1-g32.double()*c64)))/g32.double()
        rounded_gamma_and_z = c64 + (1+_LambertW0.apply(z32.double()))/g32.double()
        w32 = _LambertW0.apply(z32)
        rounded_gamma_z_w = c64 + (1+w32.double())/g32.double()
        reconstructed = c32+(1+w32)/g32
        if not torch.equal(reconstructed, shipped):
            raise AssertionError("Staged implementation does not reproduce the frozen path")
        scipy64 = c64.numpy() + (1+lambertw(z64.numpy(), k=0).real)/g64.numpy()

    def array(value):
        return value.detach().cpu().numpy() if torch.is_tensor(value) else np.asarray(value)

    def differences(left, right):
        x, y = array(left), array(right)
        delta = np.abs(x.astype(np.float64)-y.astype(np.float64))
        index = np.unravel_index(int(delta.argmax()), delta.shape)
        return {"max_abs": float(delta[index]),
                "rms_abs": float(np.sqrt(np.mean(delta*delta))),
                "unequal_values": int(np.count_nonzero(x != y)),
                "number_of_values": int(delta.size),
                "argmax": {"index": list(map(int, index)),
                    "drift_float32_input": float(a32[index]),
                    "cost_float32_input": float(c32[index]),
                    "left": float(x[index]), "right": float(y[index])}}

    stages = {"all_double_analytic": analytic64,
              "only_gamma_rounded_float32": rounded_gamma,
              "gamma_and_lambert_input_z_rounded_float32": rounded_gamma_and_z,
              "gamma_lambert_input_z_and_w_output_rounded_float32": rounded_gamma_z_w,
              "shipped_all_outer_arithmetic_float32": shipped,
              "proposed_all_double_then_final_float32": promoted}
    staged = {name: {"against_double_root": differences(value, root64),
                    "after_final_float32_against_root_float32":
                        differences(value.float(), root32)}
              for name, value in stages.items()}

    # Separate, fixed derivative fixtures: root implicit differentiation is an
    # independent formula. It does not use the Lambert autograd implementation.
    da, dc = np.meshgrid(np.array([-drift_bound, -.8, -.2, 0., .2, .8, drift_bound]),
                        np.array([.20, .5, .98]), indexing="ij")
    derivatives = {}
    for label, function, promote in (
            ("shipped", frozen_control_boundary, False),
            ("double_then_final_cast_proposal", frozen_control_boundary, True),
            ("implicit_root", numerical_control_boundary, False)):
        a = torch.tensor(da, dtype=torch.float32, requires_grad=True)
        c = torch.tensor(dc, dtype=torch.float32, requires_grad=True)
        h = function(a.double(), c.double()).to(a.dtype) if promote else function(a, c)
        grad_a, grad_c = torch.autograd.grad(h.sum(), (a, c))
        derivatives[label] = {"drift": array(grad_a), "cost": array(grad_c)}
    gradient_summary = {}
    for label in ("shipped", "double_then_final_cast_proposal"):
        gradient_summary[label] = {}
        for field in ("drift", "cost"):
            difference = np.abs(derivatives[label][field].astype(np.float64)
                                - derivatives["implicit_root"][field].astype(np.float64))
            gradient_summary[label][field] = {"maximum_absolute_error": float(difference.max()),
                "number_unequal": int(np.count_nonzero(difference)),
                "fixture_count": int(difference.size)}

    np.savez_compressed(fixture, drift=a32.numpy(), cost=c32.numpy(),
        root_float32=root32.numpy(), root_float64=root64.numpy(),
        gamma_float32=g32.numpy(), gamma_float64=g64.numpy(),
        z_float32=z32.numpy(), z_float64=z64.numpy(), scipy_lambert_float64=scipy64,
        **{name: array(value) for name, value in stages.items()},
        derivative_drift_inputs_float32=da.astype(np.float32),
        derivative_cost_inputs_float32=dc.astype(np.float32),
        derivative_nominal_drift_inputs_float64=da,
        derivative_nominal_cost_inputs_float64=dc,
        **{f"gradient_{name}_{field}": values[field]
           for name, values in derivatives.items() for field in ("drift", "cost")})
    report = {"schema": "rrsnn-v4-post-result-operator-roundoff-diagnosis-1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity, "diagnostic_source_sha256": sha(__file__),
        "fixture_file": str(fixture.relative_to(ROOT)), "fixture_sha256": sha(fixture),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "free_disk_bytes_before": available_before,
        "scope": "Post-result diagnostic; independent conservative operator grid. This is not task evidence, a new heldout result, or a replacement for the original 60 comparisons.",
        "fixture": {"drift_count": 65, "cost_count": 65, "points": int(a32.numel()),
            "drift_interval": [-drift_bound, drift_bound], "cost_interval": [.20, .98],
            "input_rounding": "Both methods receive exactly identical float32 inputs.",
            "envelope_source": "Frozen RRPolicy.controls in models.py; independent rectangular envelope, not all points are jointly reachable.",
            "sigma": sigma, "discount": discount, "refractory": refractory},
        "shipped_against_root_float32": differences(shipped, root32),
        "proposed_against_root_float32": differences(promoted, root32),
        "clamped_shipped_against_clamped_root": differences(shipped.clamp(.55,2.25), root32.clamp(.55,2.25)),
        "clamped_proposal_against_clamped_root": differences(promoted.clamp(.55,2.25), root32.clamp(.55,2.25)),
        "double_analytic_against_double_root": differences(analytic64, root64),
        "double_analytic_against_scipy_lambert": differences(analytic64, scipy64),
        "gamma_float32_against_float64": differences(g32, g64),
        "staged_roundoff": staged,
        "staging_caution": "Stages replace operations cumulatively; errors are not additive, monotone, or a statistical causal decomposition. Gamma cancellation is only one candidate contribution.",
        "gradient_fixtures": gradient_summary,
        "minimal_precision_proposal": "In a separate experimental wrapper only, call the unchanged frozen_control_boundary with drift.double() and cost.double(), then cast the final threshold to torch.result_type(drift,cost), preserving the original expression output dtype for mixed and zero-dimensional inputs. Preserve all formula constants, branches, clamps, weights, actor seeds, task scheduling, and the original 1e-7 event-time criterion.",
        "formal_sources_modified": False, "formal_outputs_modified": False,
        "training_performed": False, "heldout_scenarios_loaded": False,
        "event_time_tolerance_changed": False,
        "attribution_boundary": "Forward operator agreement can establish a roundoff mechanism on this envelope; attributing every original closed-loop event-time difference requires a separately labeled same-weight replay. Original failures remain failures."}
    # Re-check the original evidence and frozen source after the diagnostic.
    if prerequisites() != identity:
        raise AssertionError("Original matrix identity changed during diagnosis")
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    temporary.replace(destination)
    check_disk()
    print(json.dumps({"report": str(destination), "sha256": sha(destination),
        "shipped_vs_root": report["shipped_against_root_float32"],
        "proposal_vs_root": report["proposed_against_root_float32"],
        "gradient_fixtures": gradient_summary}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
