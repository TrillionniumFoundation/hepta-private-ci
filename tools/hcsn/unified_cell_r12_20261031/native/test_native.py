"""Independent expm/Frechet, Bayes, refusal, process recovery and cost audit.

This tests the finite generator contract, not continuum or production admission.
Every output directory is create-only so failed audit records can be retained.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
from scipy.linalg import expm, expm_frechet

from adapter import NativeOperator, ROOT


def generator(rng, n):
    q = rng.uniform(.01, 1., (n, n)) / max(1, n)
    np.fill_diagonal(q, 0.)
    np.fill_diagonal(q, -q.sum(axis=1))
    return q


def regenerative_fixture(active=8):
    """Synthetic two-content first-hit/recovery chain, independent of HX code."""
    width = active + 2
    q = np.zeros((2 * width, 2 * width))
    h, sigma, drift = .8 / active, .25, .08 - .02 - .25**2 / 2
    down, up = .5 * sigma**2 / h**2 + max(-drift, 0) / h, .5 * sigma**2 / h**2 + max(drift, 0) / h
    for content in range(2):
        offset = content * width
        for i in range(active):
            q[offset + i, offset + i - 1 if i else offset + active] = down
            if i + 1 < active:
                q[offset + i, offset + i + 1] = up
        q[offset + active, offset + active + 1] = 2 / .35
        for target in range(2):
            q[offset + active + 1, target * width + active // 2] = 2 / .35 * (.75 if target == content else .25)
    np.fill_diagonal(q, -q.sum(axis=1))
    p = np.zeros(2 * width)
    p[active // 2], p[width + active // 2] = .6, .4
    return q, p


def launch(binary, mode, original, script, destination):
    command = [str(binary), mode, str(original), str(script), str(destination)]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                wall_seconds=time.perf_counter() - start,
                child_cpu_seconds=(after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime))


def run(output, build):
    output.mkdir(parents=True, exist_ok=False)
    op = NativeOperator(build / "libhcsn_native.so")
    binary = build / "hcsn-native"
    rows, checks = [], []
    report = dict(schema="hcsn-r12-native-audit-v1", source_identity=json.loads((build / "BUILD_RECEIPT.json").read_text())["source_identity"],
                  build_receipt=json.loads((build / "BUILD_RECEIPT.json").read_text()), rows=rows, checks=checks,
                  scope="Finite Q, f64 arithmetic, Linux process checkpoints; no continuum/GPU/energy/production qualification")

    def check(name, condition, details=None):
        checks.append(dict(name=name, passed=bool(condition), details=details))
        if not condition:
            (output / "FAILED.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
            raise AssertionError(name)

    rng = np.random.default_rng(607113)
    for n in [1, 2, 5, 20, 24, 64]:
        q = generator(rng, n)
        p = rng.dirichlet(np.ones(n))
        for dt in [0., .05, .75, 2.1, 128.]:
            actual = op.propagate(q, p, dt)
            reference = p @ expm(q * dt)
            row = dict(kind="expm", n=n, dt=dt, q=q.tolist(), prior=p.tolist(), actual=actual.tolist(),
                       reference=reference.tolist(), max_absolute_error=float(np.max(np.abs(actual - reference))),
                       mass_error=float(actual.sum() - p.sum()), minimum_probability=float(actual.min()))
            rows.append(row)
            check(f"expm_n{n}_dt{dt}", row["max_absolute_error"] < 3e-11 and abs(row["mass_error"]) < 3e-11 and row["minimum_probability"] >= 0)

    q, p = regenerative_fixture()
    for dt in [.05, .15, .45, .75, 1.05, 2.1, 128.]:
        actual, reference = op.propagate(q, p, dt), p @ expm(q * dt)
        rows.append(dict(kind="regenerative", n=len(p), dt=dt, q=q.tolist(), prior=p.tolist(), actual=actual.tolist(),
                         reference=reference.tolist(), max_absolute_error=float(np.max(np.abs(actual-reference))),
                         mass_error=float(actual.sum()-p.sum())))
        check(f"regenerative_dt{dt}", np.max(np.abs(actual-reference)) < 3e-11)
    full = op.propagate(q, p, 1.2)
    split = op.propagate(q, op.propagate(q, p, .3), .9)
    check("semigroup_split", np.max(np.abs(full-split)) < 3e-11, float(np.max(np.abs(full-split))))
    huge = op.propagate(np.array([[-2., 2.], [1., -1.]]), np.array([1., 0.]), 1000.)
    check("long_horizon_analytic_stationary", np.max(np.abs(huge - [1/3, 2/3])) < 3e-11,
          dict(probability=huge.tolist(), mass_error=float(huge.sum()-1)))

    qd = generator(rng, 20)
    q0 = generator(rng, 20)
    pd = rng.dirichlet(np.ones(20))
    for dt in [.15, .75, 2.1]:
        epsilon = 1e-5
        numeric = (op.propagate(q0+epsilon*qd, pd, dt)-op.propagate(q0-epsilon*qd, pd, dt))/(2*epsilon)
        reference = pd @ expm_frechet(q0*dt, qd*dt, compute_expm=False)
        error = float(np.max(np.abs(numeric-reference)))
        rows.append(dict(kind="frechet", dt=dt, step=epsilon, max_absolute_error=error,
                         native_secant=numeric.tolist(), independent_frechet=reference.tolist()))
        check(f"frechet_dt{dt}", error < 2e-8)

    prior = np.array([.2, .3, .5])
    for scale in [1e-300, 1., 1e300]:
        likelihood = scale*np.array([4., 2., 1.])
        posterior = op.observe(prior, likelihood)
        check(f"bayes_scale_{scale}", np.max(np.abs(posterior - np.array([8., 6., 5.])/19)) < 2e-15,
              posterior.tolist())

    invalid = [
        ("negative_time", q, p, -1., 2),
        ("nan_time", q, p, float("nan"), 2),
        ("work_bound", q, p, 1e100, 5),
        ("nonconserving_q", q+np.eye(len(p))*.1, p, .1, 3),
        ("negative_offdiagonal", np.array([[-1., 1.], [-.1, .1]]), np.array([1., 0.]), .1, 3),
        ("invalid_prior_mass", q, p*.5, .1, 4),
        ("empty_dimension", np.zeros((0, 0)), np.zeros(0), .1, 1),
    ]
    for name, qq, pp, dt, expected in invalid:
        code, result = op.raw_propagate(qq, pp, dt)
        check(name, code == expected and np.all(result == -12345.), dict(code=code, expected=expected))
    for name, pp, ll, expected in [
        ("zero_likelihood", [.2, .8], [0., 0.], 4),
        ("impossible_observation", [1., 0.], [0., 1.], 4),
        ("negative_likelihood", [.2, .8], [1., -1.], 2),
        ("nan_likelihood", [.2, .8], [1., float("nan")], 2),
    ]:
        code, result = op.raw_observe(pp, ll)
        check(name, code == expected and np.all(result == -12345.), dict(code=code, expected=expected))
    check("null_pointer_rejected", op.library.propagate(2, None, .1, None, None) == 7)

    initial = output / "initial.txt"
    initial.write_text(str(len(p))+"\n"+" ".join(format(x, ".17g") for x in np.concatenate([q.ravel(), p]))+"\n")
    likelihood = np.linspace(.1, .9, len(p))
    commands = ["advance 0.15", "observe "+" ".join(format(x, ".17g") for x in likelihood),
                "advance 0.45", "observe "+" ".join(format(x, ".17g") for x in likelihood[::-1]), "advance 2.1"]
    for name, lines in [("whole", commands), ("prefix", commands[:3]), ("suffix", commands[3:])]:
        (output / f"{name}.script").write_text("\n".join(lines)+"\n")
    executions = [launch(binary, "init", initial, output/"whole.script", output/"whole.checkpoint"),
                  launch(binary, "init", initial, output/"prefix.script", output/"prefix.checkpoint"),
                  launch(binary, "resume", output/"prefix.checkpoint", output/"suffix.script", output/"resumed.checkpoint")]
    report["process_executions"] = executions
    check("three_processes_complete", all(x["exit_code"] == 0 for x in executions), executions)
    states = [json.loads(x["stdout"]) for x in executions]
    check("different_real_processes", len({s["pid"] for s in states}) == 3, [s["pid"] for s in states])
    check("restore_checkpoint_bytes_equal", (output/"whole.checkpoint").read_bytes() == (output/"resumed.checkpoint").read_bytes())
    expected = p.copy()
    for line in commands:
        words = line.split()
        values = np.array([float(x) for x in words[1:]])
        if words[0] == "advance":
            expected = expected @ expm(q*values[0])
        else:
            expected = expected*values
            expected /= expected.sum()
    restore_error = float(np.max(np.abs(np.array(states[2]["probability"])-expected)))
    check("restore_independent_expm", restore_error < 3e-11, restore_error)
    report["recovery_reference"] = expected.tolist()
    for name in ["whole", "prefix", "resumed"]:
        body, digest = (output/f"{name}.checkpoint").read_text().rsplit("CHECKSUM ", 1)
        check(f"independent_sha256_{name}", hashlib.sha256(body.encode()).hexdigest() == digest.strip())
    text = (output/"prefix.checkpoint").read_text()
    altered = text.replace("HCSN_NATIVE_CHECKPOINT_V1", "HCSN_NATIVE_CHECKPOINT_V0", 1)
    for name, content in [("corrupt", altered), ("rehash_wrong_version", altered.rsplit("CHECKSUM ", 1)[0])]:
        if name == "rehash_wrong_version":
            content += "CHECKSUM "+hashlib.sha256(content.encode()).hexdigest()+"\n"
        path = output/f"{name}.checkpoint"
        path.write_text(content)
        record = launch(binary, "resume", path, output/"suffix.script", output/f"refused_{name}.checkpoint")
        executions.append(record)
        check(name, record["exit_code"] != 0 and not (output/f"refused_{name}.checkpoint").exists(), record)
    before = (output/"resumed.checkpoint").read_bytes()
    record = launch(binary, "resume", output/"prefix.checkpoint", output/"suffix.script", output/"resumed.checkpoint")
    executions.append(record)
    check("checkpoint_create_only", record["exit_code"] != 0 and (output/"resumed.checkpoint").read_bytes() == before, record)

    timing = []
    for dt in [.15, .45, 2.1]:
        begin = time.process_time_ns()
        cached = expm(q*dt)
        setup = (time.process_time_ns()-begin)*1e-9
        for count in [24, 64, 256]:
            for implementation in ["native_full_validation", "scipy_cached_matrix_multiply"]:
                samples = []
                for _ in range(5):
                    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                    for _ in range(count):
                        if implementation == "native_full_validation":
                            last = op.propagate(q, p, dt)
                        else:
                            last = p @ cached
                    samples.append(dict(cpu_seconds=(time.process_time_ns()-cpu)*1e-9,
                                        wall_seconds=(time.perf_counter_ns()-wall)*1e-9))
                timing.append(dict(n_states=len(p), cells=count, dt=dt, implementation=implementation,
                                   cache_setup_cpu_seconds=setup, samples=samples, last=last.tolist()))
    report["batch_timings"] = timing
    report["cost_scope"] = "Shared-host CPU; native includes ctypes conversion/allocation and full generator validation. Cached matrix baseline excludes its separately recorded expm setup. No GPU/Joules or financial-kernel cost."
    report["summary"] = dict(checks=len(checks), passed=sum(x["passed"] for x in checks),
                             max_propagation_error=max(r["max_absolute_error"] for r in rows if r["kind"] in ["expm", "regenerative"]),
                             max_mass_error=max(abs(r["mass_error"]) for r in rows if "mass_error" in r),
                             max_frechet_error=max(r["max_absolute_error"] for r in rows if r["kind"] == "frechet"),
                             recovery_max_error=restore_error, production_qualified=False, native_fp32_qualified=False)
    (output/"RESULTS.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    return report["summary"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", type=Path, default=ROOT/"evidence"/"build")
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve(), args.build.resolve()), indent=2))
