"""Independent scope probe of exact #6151; does not alter its tests or gates.

For T < delay a zero-time phase atom at the exact reset has first-hit
probability exp(T Q)[reset_index, lower].  Dense matrix exponentiation and
its Frechet derivative remove DDE integration as an error explanation.
The half-line drifted Brownian first-hit formula is compared with an
explicit upper-boundary reach probability bound, not assumed exact for
the finite interval.  All new comparisons are exploratory, not gates.
"""

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import scipy
from scipy.linalg import expm, expm_frechet
from scipy.special import log_ndtr


ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-root", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
arguments = parser.parse_args()
SOURCE = arguments.source_root.resolve()
OUTPUT = arguments.output_dir.resolve()
OUTPUT.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(SOURCE))

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.sensitivities import (
    PARAMETERS,
    solve_aligned_partials,
)


def log_hit(distance, drift, sigma, time):
    scale = sigma * math.sqrt(time)
    return float(np.logaddexp(
        log_ndtr((-distance - drift * time) / scale),
        -2 * drift * distance / sigma**2
        + log_ndtr((-distance + drift * time) / scale),
    ))


def continuum(theta, time):
    boundary, drift, sigma, absolute_reset, _ = theta
    return math.exp(log_hit(math.log(absolute_reset) - boundary, drift, sigma, time))


def main():
    manifest = json.loads((ROOT / "SOURCE.json").read_text())
    hashes = {}
    for path, expected in manifest["verified_remote_blobs"].items():
        raw = (SOURCE / path).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != expected:
            raise AssertionError((path, actual, expected))
        hashes[path] = hashlib.sha256(raw).hexdigest()
    theta = np.array([.01, -.12, .5, math.exp(.51), .15])
    geometry = dict(endpoint=2., grading=1., delay=.2)
    domain, hit_records = [], []
    for intervals in (8, 16, 32, 64, 128):
        low = theta.copy()
        low[2] = .08
        try:
            model, _ = aligned_model(low, left_intervals=intervals // 2,
                                     right_intervals=intervals // 2, **geometry)
            domain.append(dict(intervals=intervals, accepted=True,
                               minimum_rate=float(np.min(model.spatial.rates)),
                               torch_law_row_limit=64,
                               inside_torch_row_budget=intervals <= 64))
        except ValueError as error:
            domain.append(dict(intervals=intervals, accepted=False,
                               rejection=str(error), torch_law_row_limit=64,
                               inside_torch_row_budget=intervals <= 64))
    for intervals in (8, 16, 32, 64):
        model, derivatives = aligned_model(theta, left_intervals=intervals // 2,
                                            right_intervals=intervals // 2, **geometry)
        for time in (.001, .01, .1):
            ctmc = float(expm(time * model.spatial.matrix())[intervals // 2, 0])
            log_reference = log_hit(model.reset, model.spatial.mu, model.spatial.sigma, time)
            log_upper = log_hit(model.spatial.endpoint - model.reset,
                                -model.spatial.mu, model.spatial.sigma, time)
            hit_records.append(dict(intervals=intervals, time=time, ctmc=ctmc,
                continuum_halfline=math.exp(log_reference),
                continuum_log10=log_reference / math.log(10),
                upper_reach_probability_bound=math.exp(log_upper),
                upper_reach_log10=log_upper / math.log(10),
                relative_error=math.expm1(math.log(ctmc) - log_reference),
                absolute_error=ctmc - math.exp(log_reference)))
    intervals, time = 8, .1
    model, derivatives = aligned_model(theta, left_intervals=4, right_intervals=4, **geometry)
    phase = (Packet("reset", Fraction(0), Fraction(0), Fraction(1), (Fraction(2),)),)
    row = solve_aligned_partials(model, derivatives, [0., time],
        np.zeros(intervals + 1), np.zeros((intervals + 1, 1)), phase,
        rtol=2e-11, atol=2e-13, max_step=.02)["rows"][-1]
    partials = []
    for j, parameter in enumerate(PARAMETERS):
        exact_ctmc = float(expm_frechet(time * model.spatial.matrix(),
            time * derivatives[j], compute_expm=False)[4, 0])
        finite_differences = []
        for step in (2e-5, 1e-5):
            delta = np.zeros(5)
            delta[j] = step
            finite_differences.append((continuum(theta + delta, time)
                                       - continuum(theta - delta, time)) / (2 * step))
        variational = float(row["partials"][parameter]["events"][0])
        partials.append(dict(parameter=parameter, variational=variational,
                            dense_ctmc_frechet=exact_ctmc,
                            variational_minus_dense=variational - exact_ctmc,
                            continuum_finite_differences=finite_differences))
    shifted = theta.copy()
    shifted[0] += .02
    shifted[3] *= math.exp(.02)
    shifted_model, _ = aligned_model(shifted, left_intervals=4, right_intervals=4, **geometry)
    identifiability = dict(
        parameter_dependence="B and absolute_reset enter only through log(Vr)-B",
        exact_identity="d/dB + Vr * d/dVr = 0 at fixed moving nodal weights",
        generator_identity_max_residual=float(np.max(abs(derivatives[0] + theta[3] * derivatives[3]))),
        first_hit_identity_residual=partials[0]["variational"] + theta[3] * partials[3]["variational"],
        invariant_transform="B <- B + .02, Vr <- Vr * exp(.02)",
        transformed_generator_max_difference=float(np.max(abs(shifted_model.spatial.matrix() - model.spatial.matrix()))),
        fixed_physical_prior_chain_rule_included=False,
    )
    result = dict(schema="hcsn-independent-p1-domain-and-shorttime-review-v1",
        candidate=manifest, source_sha256=hashes,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python=sys.version, numpy=np.__version__, scipy=scipy.__version__,
        torch_available=importlib.util.find_spec("torch") is not None,
        theta=theta.tolist(), geometry=geometry, identifiability=identifiability,
        all_new_comparisons_exploratory=True, original_gates_changed=False,
        low_noise_domain=domain, first_hit=hit_records,
        partials_fixture=dict(intervals=intervals, time=time,
            first_hit_dde=float(row["primal"]["events"][0]), derivatives=partials),
        conclusions=dict(discrete_parameter_jacobian_error_detected_in_this_probe=False,
            low_noise_with_original_drift_covered_by_native_budget=False,
            short_time_continuum_qualified=False,
            same_model_two_scalar_fit_establishes_task_training_sufficiency=False,
            differentiable_checkpoint_exposed_in_6151=False))
    (OUTPUT / "REVIEW.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
