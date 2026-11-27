"""Read-only continuum diagnostic of the exact warm-1 nodal initial law.

No CTMC generator is advanced. The authentic FP64 arrays remain nodal point
masses, including signed content; no density reconstruction or normalization
is introduced. The primary reference also retains the actual two-node reset
law. Its half-line/finite-upper difference has an explicit strong-Markov bound.
"""

import argparse
import hashlib
import json
import math
import struct
import time
import zipfile
from fractions import Fraction
from pathlib import Path

import mpmath as mp

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import adapter


ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
DENSE = ROOT / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/N256_WARM1.bin"
SPARSE = HERE / "evidence/attempt001-20261119/artifact-14501927547.zip"
EXPECTED_DENSE = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"
EXPECTED_ZIP = "8f6a75afafeedaa5cfe6ad2b8b80af6b7d2b54f102f75d406ac1d92eb4b36629"


def unpack(payload):
    return [item[0] for item in struct.iter_unpack("<d", payload)]


def first_hit_parts(distance, horizon, drift, sigma, discount):
    """G_rho=A+B; F=G_0 for dX=mu dt+sigma dW, killed at zero."""
    if horizon == 0:
        return mp.mpf(0), mp.mpf(0)
    chi = mp.sqrt(drift*drift + 2*discount*sigma*sigma)
    scale = sigma*mp.sqrt(horizon)
    cdf = lambda z: mp.erfc(-z/mp.sqrt(2))/2
    first = mp.exp((-drift+chi)*distance/(sigma*sigma))*cdf((-distance-chi*horizon)/scale)
    second = mp.exp((-drift-chi)*distance/(sigma*sigma))*cdf((-distance+chi*horizon)/scale)
    return first, second


def source_convolutions(distance, horizon, drift, sigma, discount):
    """Exact constant-release convolutions; global discount starts at time zero.

    J_F = integral_0^T F(s) ds = T*F(T)-E[tau; tau<=T].
    J_G = integral_0^T exp(-rho*u)G(T-u)du
        = (G(T)-exp(-rho*T)*F(T))/rho.
    The actual drift and discount are nonzero; no zero-parameter limit is used.
    """
    if drift == 0 or discount <= 0:
        raise ValueError("this frozen diagnostic requires nonzero drift and positive discount")
    a, b = first_hit_parts(distance, horizon, drift, sigma, mp.mpf(0))
    probability = a + b
    discounted = mp.fsum(first_hit_parts(distance, horizon, drift, sigma, discount))
    truncated_first_moment = distance/abs(drift)*(b-a)
    return horizon*probability-truncated_first_moment, (discounted-mp.exp(-discount*horizon)*probability)/discount


def calculate(nodes, channels, rates, reset_nodes, reset_weights, physics, dps):
    with mp.workdps(dps):
        horizon = mp.mpf(float(Fraction(1, 1000)))
        drift, sigma, discount = (mp.mpf(physics[name]) for name in ("mu", "sigma", "discount"))
        kernels = [[mp.fsum(first_hit_parts(mp.mpf(x), horizon, drift, sigma, rho))
                    for x in nodes[1:-1]] for rho in (mp.mpf(0), discount)]
        initial = [[mp.fsum(mp.mpf(weight)*kernel for weight, kernel in zip(channel[1:-1], values))
                    for values in kernels] for channel in channels]
        reset_integrals = [source_convolutions(mp.mpf(x), horizon, drift, sigma, discount) for x in reset_nodes]
        reset_pair = [mp.fsum(mp.mpf(weight)*pair[k] for weight, pair in zip(reset_weights, reset_integrals))
                      for k in range(2)]
        exact_reset = source_convolutions(mp.mpf(physics["reset_distance"]), horizon, drift, sigma, discount)
        source = [[mp.mpf(rate)*value for value in reset_pair] for rate in rates]
        source_exact_reset = [[mp.mpf(rate)*value for value in exact_reset] for rate in rates]
        total = [[initial[c][k]+source[c][k] for k in range(2)] for c in range(5)]
        upper_hit = mp.fsum(first_hit_parts(mp.mpf(nodes[-1]), horizon, drift, sigma, mp.mpf(0)))
        upper_bounds = [(mp.fsum(abs(mp.mpf(w)) for w in channel[1:-1])+abs(mp.mpf(rate))*horizon)*upper_hit
                        for channel, rate in zip(channels, rates)]
        return {"initial": initial, "source": source, "total": total,
                "source_exact_reset": source_exact_reset, "upper_bounds": upper_bounds,
                "upper_hitting_probability": upper_hit, "reset_integrals": reset_integrals}


def run():
    started, cpu = time.perf_counter(), time.process_time()
    authentic = adapter.load_authentic_input(ROOT)
    metadata = json.loads((ROOT / adapter.RELATIVE["metadata"]).read_text())
    migration = ROOT / "qualification/hcsn_initial_law/migration.py"
    if hashlib.sha256(migration.read_bytes()).hexdigest() != metadata["source_input_sha256"]["migration"]:
        raise ValueError("nodal migration source identity")
    nodes, probability, content = map(unpack, (authentic.nodes_payload, authentic.active_payload, authentic.signed_content_payload))
    channels = [probability] + [[content[4*i+j] for i in range(257)] for j in range(4)]
    if len(nodes) != 257 or any(channel[0] != 0 for channel in channels):
        raise ValueError("exact exported nodal layout and zero initial lower atom")
    if metadata["upper_semantics"] != "permanently active nonreturning escape coordinate":
        raise ValueError("upper coordinate interpretation")
    active_sources = [item for item in authentic.phase_packets if item[1] < Fraction(1, 1000)]
    if len(active_sources) != 1 or active_sources[0][1] != 0 or active_sources[0][2] < Fraction(1, 1000):
        raise ValueError("one original constant release source on the entire interval")
    rates = [float(x) for x in active_sources[0][3]]
    reset = metadata["reset_distance"]
    right = next(j for j, x in enumerate(nodes) if x > reset)
    theta = (reset-nodes[right-1])/(nodes[right]-nodes[right-1])
    reset_nodes, reset_weights = nodes[right-1:right+1], [1.0-theta, theta]
    dense_raw = DENSE.read_bytes()
    if hashlib.sha256(dense_raw).hexdigest() != EXPECTED_DENSE or hashlib.sha256(SPARSE.read_bytes()).hexdigest() != EXPECTED_ZIP:
        raise ValueError("executed finite-state reference identity")
    with zipfile.ZipFile(SPARSE) as archive:
        sparse_raw = archive.read("N256_WARM1_SPARSE.bin")
    capsules = {name: wire.decode(raw, 8*1024**2) for name, raw in (("dense", dense_raw), ("sparse", sparse_raw))}
    emitted = next(packet for packet in capsules["dense"].packets if packet.generation == 2)
    injection = unpack(emitted.generator.payload)[:256]
    expected = [0.0]*256
    expected[right-1], expected[right] = reset_weights
    if struct.pack("<256d", *expected) != emitted.generator.payload[:256*8]:
        raise ValueError("reset mixture is not byte-identical to the actual oracle injection")
    if [unpack(emitted.alpha.payload)[c*256] for c in range(5)] != rates:
        raise ValueError("original source amplitudes differ")
    physics = {**metadata["physics"], "reset_distance": reset}
    values45, values80 = (calculate(nodes, channels, rates, reset_nodes, reset_weights, physics, dps)
                          for dps in (45, 80))
    with mp.workdps(80):
        horizon = mp.mpf(float(Fraction(1, 1000)))
        drift, sigma, discount = (mp.mpf(physics[k]) for k in ("mu", "sigma", "discount"))
        quadrature = []
        for position, (x, closed) in enumerate(zip(reset_nodes, values80["reset_integrals"])):
            x = mp.mpf(x)
            f_end = mp.fsum(first_hit_parts(x, horizon, drift, sigma, mp.mpf(0)))
            g_end = mp.fsum(first_hit_parts(x, horizon, drift, sigma, discount))
            f_scaled = lambda v: mp.fsum(first_hit_parts(x, horizon*v, drift, sigma, mp.mpf(0)))/f_end
            g_scaled = lambda v: mp.exp(-discount*horizon*(1-v))*mp.fsum(first_hit_parts(x, horizon*v, drift, sigma, discount))/g_end
            limits = [0, mp.mpf(".5"), mp.mpf(".9"), mp.mpf(".99"), 1]
            integrated = [horizon*f_end*mp.quad(f_scaled, limits), horizon*g_end*mp.quad(g_scaled, limits)]
            quadrature.append({"reset_index": position, "closed": list(map(str, closed)),
                               "independent_scaled_quadrature": list(map(str, integrated)),
                               "relative_disagreements": [str(abs(a-b)/abs(a)) for a, b in zip(closed, integrated)]})
        rows = []
        for channel in range(5):
            row = {"channel": channel, "initial_total_signed_mass": math.fsum(channels[channel]),
                   "permanently_active_upper_mass": channels[channel][-1],
                   "absolute_finite_upper_correction_bound": str(values80["upper_bounds"][channel])}
            for index, quantity in enumerate(("hit", "discounted_hit")):
                exact = values80["total"][channel][index]
                details = {"continuous_reference_80_digits": str(exact),
                           "initial_nodal_mixture": str(values80["initial"][channel][index]),
                           "original_release_source_convolution": str(values80["source"][channel][index]),
                           "exact_resetpoint_source_sensitivity": str(values80["source_exact_reset"][channel][index]-values80["source"][channel][index]),
                           "precision_45_vs_80_absolute_difference": str(abs(values45["total"][channel][index]-exact))}
                for name, capsule in capsules.items():
                    field = "mass" if quantity == "hit" else "discounted_hit"
                    actual = unpack(next(b.tensor.payload for b in capsule.blocks if b.name == field))[channel*2]
                    error = mp.mpf(actual)-exact
                    details[name] = {"actual": actual, "signed_error": float(error),
                                     "absolute_error": float(abs(error)), "relative_error": float(abs(error)/abs(exact))}
                row[quantity] = details
            rows.append(row)
        return {"schema": "hcsn-n256-warm1-continuum-nodal-diagnostic-v1", "rows": rows,
                "input_bundle_sha256": adapter.INPUT_BUNDLE_SHA256,
                "reference_initial_law": "Exact binary FP64 exported masses at their exact binary FP64 node locations; no renormalization or original-cell reconstruction.",
                "reference_reset_law": "Same two-node FP64 reset mixture as the actual finite generator; exact resetpoint is separately labeled sensitivity only.",
                "physics_fp64": physics, "horizon_fraction": "1/1000", "horizon_fp64_hex": float(horizon).hex(),
                "reset_nodes": reset_nodes, "reset_weights": reset_weights, "original_source_rates": rates,
                "source_packet_end": str(active_sources[0][2]), "refractory": "1/5 > 1/1000, so no newly emitted mass returns",
                "upper_boundary": nodes[-1], "upper_hitting_probability_bound": str(values80["upper_hitting_probability"]),
                "upper_bound_argument": "After reaching upper L, the probability of subsequently hitting zero by T is <=F(T;L) by strong Markov; multiply by initial interior total variation plus released total variation.",
                "source_convolution_checks": quadrature, "precision_digits": [45, 80], "mpmath_version": mp.__version__,
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (Path(__file__), migration, ROOT/adapter.RELATIVE["metadata"], DENSE, SPARSE)},
                "new_finite_generator_advances": 0, "new_matrix_exponential_actions": 0,
                "old_bitwise_gate": "RED unchanged", "original_gate_tolerances_changed": False,
                "full_continuum_or_training_domain_qualified": False,
                "wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        result = run()
        json.dump(result, stream, allow_nan=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "channel0": result["rows"][0],
                      "wall_seconds": result["wall_seconds"]}, allow_nan=False))
