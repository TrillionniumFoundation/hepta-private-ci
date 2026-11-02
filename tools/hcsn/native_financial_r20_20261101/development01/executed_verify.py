"""Actual native parameter-to-model construction against separate references."""
import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import mpmath as mp
import numpy as np

from tools.hcsn.unified_cell_r12_20261031.cell import Cell

HERE = Path(__file__).resolve().parent
RUSTC = "/tmp/hcsn-r15-runtime-tools/rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc"


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def high_precision(theta):
    """80-digit direct divided differences, independently of native quadrature."""
    with mp.workdps(80):
        sigma, liquidity, m = map(lambda x: mp.mpf(float(x)), theta)
        r, delta, alpha, tax, coupon, principal = map(mp.mpf, [".08", ".02", ".6", ".27", "6.39", "61.68"])
        s2, rate = sigma ** 2, r + liquidity
        a = (r - delta - s2 / 2) / s2
        z, zt = mp.sqrt(a*a + 2*r/s2), mp.sqrt(a*a + 2*rate/s2)
        eta, gamma = z - a, z + a
        s, c, p = sigma * mp.sqrt(m), coupon/m, principal/m
        q, discount = p - c/rate, mp.exp(-rate*m)
        cost = (1-tax)*coupon - mp.expm1(-rate*m)*q
        phi = lambda x: mp.erfc(-x/mp.sqrt(2))/2

        def b(y):
            return (phi(y*s) - mp.exp((z*z-y*y)*s*s/2)*phi(-z*s))/(z+y)

        bs = b(-zt) + b(zt)
        value = (cost/eta + q*discount*(b(-a)+b(a)) + c/rate*bs)/(s2*(gamma+1)/2 + alpha/m*bs)
        return float(value)


def reference(theta):
    cell = Cell(theta)
    q = np.kron(cell.Q[::2, ::2], np.eye(4)) + np.kron(cell.Q[::2, 1::2], (np.ones((4, 4))-np.eye(4))/3)
    read = np.zeros((40, 5))
    read[:32, :4] = .1
    read[np.arange(32), np.arange(32) % 4] = .7
    read[32:, 4] = 1.
    refresh = np.full((40, 4), .01)
    refresh[np.arange(40), np.arange(40) % 4] = .97
    prior = np.repeat(np.r_[cell.reset_weights, np.zeros(2)] / 4, 4)
    return np.r_[cell.boundary, q.ravel(), read.ravel(), refresh.ravel(), prior]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", type=int, required=True)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    start_cpu, start_wall = time.process_time(), time.monotonic()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    if args.formal:
        receipt = json.loads((HERE / "PUBLICATION.json").read_text())
        if not receipt["readback_verified"] or args.namespace != protocol["confirmation_namespace"]:
            raise ValueError("Unfrozen confirmation")
    identity = {n: hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in protocol["sources"]}
    if args.formal and identity != receipt["source_sha256"]:
        raise ValueError("Changed frozen financial source")
    binary = args.output / "financial"
    command = [RUSTC, "--edition=2024", "-D", "warnings", "-O", str(HERE / "main.rs"), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True)
    (args.output / "build.stdout").write_bytes(result.stdout)
    (args.output / "build.stderr").write_bytes(result.stderr)
    write(args.output / "BUILD.json", dict(command=command, exit_code=result.returncode, source_sha256=identity))
    result.check_returncode()
    rng = np.random.default_rng(args.namespace)
    cases = list(itertools.product([.15, .4], [.002, .04], [.5, 2.]))
    cases += [tuple(x) for x in rng.uniform([.15, .002, .5], [.4, .04, 2.], size=(64, 3))]
    rows, errors = [], []
    maxima = dict(boundary_vs_mp=0., model_vs_r12=0., row_mass=0., prior_mass=0., cdf_relative=0.)
    for theta in cases:
        call = subprocess.run([str(binary), *map(repr, map(float, theta))], capture_output=True)
        if call.returncode:
            errors.append(dict(theta=theta, returncode=call.returncode, stderr=call.stderr.decode()))
            continue
        value = np.asarray(json.loads(call.stdout))
        ordinary, gold = reference(theta), high_precision(theta)
        q = value[1:1601].reshape(40, 40)
        deltas = dict(boundary_vs_mp=abs(value[0]-gold), model_vs_r12=float(np.max(abs(value-ordinary))),
                      row_mass=float(np.max(abs(q.sum(1)))), prior_mass=abs(float(value[-40:].sum())-1))
        for key, number in deltas.items():
            maxima[key] = max(maxima[key], number)
        rows.append(dict(theta=theta, native=value.tolist(), reference=ordinary.tolist(), mp_boundary=gold, errors=deltas))
    cdf_rows = []
    for x in np.r_[np.linspace(-12., 12., 97), rng.uniform(-12, 12, 32)]:
        call = subprocess.run([str(binary), "cdf", repr(float(x))], capture_output=True, check=True)
        value = float(call.stdout)
        with mp.workdps(80):
            gold = float(mp.erfc(-mp.mpf(float(x))/mp.sqrt(2))/2)
        difference = abs(value-gold)/gold
        maxima["cdf_relative"] = max(maxima["cdf_relative"], difference)
        cdf_rows.append(dict(x=float(x), native=value, reference=gold, relative=difference))
    negatives = []
    for theta in [[.149, .01, 1], [.401, .01, 1], [.3, .001, 1], [.3, .041, 1], [.3, .01, .49], [.3, .01, 2.01], ["nan", .01, 1]]:
        call = subprocess.run([str(binary), *map(str, theta)], capture_output=True)
        negatives.append(dict(arguments=theta, exit_code=call.returncode, stderr=call.stderr.decode(), passed=call.returncode==2 and not call.stdout))
    gates = dict(no_valid_failure=not errors, model=maxima["model_vs_r12"]<=protocol["model_tolerance"],
                 high_precision_boundary=maxima["boundary_vs_mp"]<=protocol["boundary_tolerance"],
                 row_mass=maxima["row_mass"]<=protocol["mass_tolerance"],
                 prior_mass=maxima["prior_mass"]<=protocol["mass_tolerance"],
                 normal_tail=maxima["cdf_relative"]<=protocol["cdf_relative_tolerance"], rejections=all(x["passed"]for x in negatives))
    payload = dict(models=rows, cdf=cdf_rows, rejections=negatives, failures=errors)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with (args.output / "RAW.json.gz").open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    write(args.output / "SUMMARY.json", dict(gates=gates, passed=all(gates.values()), maxima=maxima, cases=len(cases),
        cdf_cases=len(cdf_rows), namespace=args.namespace, source_sha256=identity,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), raw_sha256=hashlib.sha256(raw).hexdigest(),
        parent_cpu_seconds=time.process_time()-start_cpu, child_cpu_seconds=child.ru_utime+child.ru_stime-child_before.ru_utime-child_before.ru_stime,
        wall_seconds=time.monotonic()-start_wall, cost_scope="recorded verifier/build/child interval; excludes final summary serialization and unmetered first smoke compile; lower bound",
        production_activation=False, all_blockers_closed=False))
    print(json.dumps(dict(gates=gates, maxima=maxima), sort_keys=True))
    raise SystemExit(not all(gates.values()))


if __name__ == "__main__":
    main()
