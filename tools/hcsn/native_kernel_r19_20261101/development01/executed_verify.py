"""Execute the standalone Rust kernel against independent SciPy matrix algebra."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np
from scipy.linalg import expm

from tools.hcsn.addressed_decision_r15_20261101.law import Law, default_free_raw

HERE = Path(__file__).resolve().parent
RUSTC = "/tmp/hcsn-r15-runtime-tools/rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frame(model, prior, commands):
    values = ["HCSN_FINITE_40_V1"]
    for array in [model.Q, model.E_read, model.E_refresh, prior]:
        values.extend(format(float(x), ".17e") for x in array.ravel())
    return (" ".join(values) + "\n" + "\n".join(commands) + "\n").encode()


def reference(model, prior, commands):
    q = model.Q
    killed = q.copy()
    rate = np.zeros(40)
    for content in range(4):
        rate[content] = q[content, 32 + content]
        killed[content, 32 + content] = 0
    p = prior.copy()
    records = []
    for command in commands:
        fields = command.split()
        op = fields[0]
        if op == "PROP":
            p = p @ expm(float(fields[1]) * q)
        elif op in ("READ", "REFRESH"):
            weighted = p * (model.E_read if op == "READ" else model.E_refresh)[:, int(fields[1])]
            p = weighted / weighted.sum()
        elif op == "RESET":
            p = np.r_[np.zeros(32), p.reshape(10, 4).sum(0), np.zeros(4)]
        elif op == "DIAG":
            dt = float(fields[1])
            augmented = np.zeros((41, 41))
            augmented[:40, 40] = rate
            augmented[:40, :40] = q
            events = float(p @ expm(dt * augmented)[:40, 40])
            augmented[:40, :40] = killed
            records.append(dict(op=op, state=p.tolist(), future=(p @ expm(dt * q)).tolist(),
                                survivor=(p @ expm(dt * killed)).tolist(),
                                first=float(p @ expm(dt * augmented)[:40, 40]), events=events))
            continue
        elif op != "MISSING":
            raise ValueError(op)
        records.append(dict(op=op, state=p.tolist()))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--namespace", type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    start_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    binary = args.output / "kernel"
    build = subprocess.run([RUSTC, "--edition=2024", "-O", str(HERE / "main.rs"), "-o", str(binary)], capture_output=True)
    (args.output / "build.stdout").write_bytes(build.stdout)
    (args.output / "build.stderr").write_bytes(build.stderr)
    if build.returncode:
        raise RuntimeError("native build failed")
    binary_hash = digest(binary.read_bytes())
    model_data = []
    for theta in [(.3, .018), (.15, .002), (.4, .04), (.22, .01)]:
        model_data.append(Law(theta))
    for adjustment in [(-1., .2, -.4, -.5), (.7, -.3, .2, .8), (0., 0., 0., 0.), (-.5, -.5, -.5, 1.2)]:
        model_data.append(Law(mode="free", free_raw=default_free_raw() + adjustment))
    raw = []
    maximum = dict(state=0., future=0., survivor=0., first=0., events=0., mass=0., tiny_first_relative=0.)
    failures = []
    cold_equal = semigroup_checks = repeated_over_one = tiny_positive = 0
    rng = np.random.default_rng(args.namespace)

    def execute(model, prior, commands):
        request = frame(model, prior, commands)
        run = subprocess.run([str(binary)], input=request, capture_output=True)
        if run.returncode:
            failures.append(dict(input_sha256=digest(request), returncode=run.returncode, stderr=run.stderr.decode()))
            raise RuntimeError("native valid case rejected")
        return json.loads("[" + ",".join(run.stdout.decode().splitlines()) + "]"), request, run.stdout

    for model_index, model in enumerate(model_data):
        for case in range(8):
            prior = model.initial_prior(case % 4) if case < 4 else rng.dirichlet(np.ones(40) * .3)
            commands = ["DIAG 0", "DIAG 1e-200", "PROP .031", f"READ {case % 4}", "MISSING", "PROP .79",
                        f"REFRESH {(case + 1) % 4}", "DIAG .75", "RESET", "READ 4", "PROP 1.2", "DIAG 20"]
            actual, request, stdout = execute(model, prior, commands)
            expected = reference(model, prior, commands)
            for got, want in zip(actual, expected, strict=True):
                for name in ("state", "future", "survivor", "first", "events"):
                    if name in want:
                        maximum[name] = max(maximum[name], float(np.max(np.abs(np.asarray(got[name]) - want[name]))))
                for name in ("state", "future", "survivor"):
                    if name in got and min(got[name]) < 0:
                        failures.append(dict(kind="negative_state", model=model_index, case=case, name=name))
                maximum["mass"] = max(maximum["mass"], abs(sum(got["state"]) - 1))
                if got["op"] == "DIAG":
                    maximum["mass"] = max(maximum["mass"], abs(sum(got["survivor"]) + got["first"] - 1))
                    repeated_over_one += int(got["events"] > 1)
                    if 0 < want["first"] < 1e-190:
                        tiny_positive += int(got["first"] > 0)
                        maximum["tiny_first_relative"] = max(maximum["tiny_first_relative"], abs(got["first"] / want["first"] - 1))
            resumed, _, _ = execute(model, np.array(actual[6]["state"]), commands[7:])
            cold_equal += int(resumed == actual[7:])
            once, _, _ = execute(model, prior, ["PROP .8"])
            split, _, _ = execute(model, prior, ["PROP .3", "PROP .5"])
            semigroup_error = float(np.max(np.abs(np.array(once[-1]["state"]) - split[-1]["state"])))
            semigroup_checks += int(semigroup_error <= 2e-11)
            raw.append(dict(model=model_index, case=case, input=request.decode(), output=stdout.decode(),
                            expected=expected, cold_equal=resumed == actual[7:], semigroup_error=semigroup_error))

    model = model_data[0]
    valid = frame(model, model.prior, ["PROP .1"])
    negatives = []
    alterations = {}
    q = model.Q.copy(); q[0, 4] = -.2
    alterations["negative_edge"] = (q, model.prior, ["PROP .1"])
    q = model.Q.copy(); q[0, 0] += .01
    alterations["nonconservative"] = (q, model.prior, ["PROP .1"])
    alterations["negative_time"] = (model.Q, model.prior, ["PROP -1"])
    alterations["excessive_time"] = (model.Q, model.prior, ["PROP 21"])
    alterations["nonfinite"] = (model.Q, model.prior, ["PROP NaN"])
    alterations["invalid_token"] = (model.Q, model.prior, ["READ 5"])
    alterations["zero_likelihood"] = (model.Q, model.initial_prior(0), ["READ 4"])
    alterations["unknown_operation"] = (model.Q, model.prior, ["UNDECLARED"])
    q = np.eye(40) * -1e-300; q[np.arange(40), (np.arange(40) + 1) % 40] = 1e-300
    alterations["clock_underflow"] = (q, model.prior, ["PROP 1e-300"])
    for name, (q, prior, commands) in alterations.items():
        fields = valid.decode().split()
        fields[1:1601] = [format(float(x), ".17e") for x in q.ravel()]
        altered = (" ".join(fields[:2001]) + "\n" + "\n".join(commands) + "\n").encode()
        run = subprocess.run([str(binary)], input=altered, capture_output=True)
        negatives.append(dict(name=name, returncode=run.returncode, stderr=run.stderr.decode(), input=altered.decode()))
    for name, request in [("truncated", valid[:100]), ("unknown_schema", valid.replace(b"HCSN_FINITE_40_V1", b"UNSUPPORTED"))]:
        run = subprocess.run([str(binary)], input=request, capture_output=True)
        negatives.append(dict(name=name, returncode=run.returncode, stderr=run.stderr.decode(), input=request.decode()))
    (args.output / "RAW.json").write_text(json.dumps(dict(models=[x.export() for x in model_data], cases=raw, negatives=negatives), separators=(",", ":")))
    gates = dict(no_valid_failure=not failures, numerical=max(maximum[k] for k in ("state", "future", "survivor", "first", "events")) <= 2e-11,
                 mass=maximum["mass"] <= 4e-11, tiny_first=maximum["tiny_first_relative"] <= 1e-9 and tiny_positive > 0,
                 repeated_events= repeated_over_one > 0, cold_restart=cold_equal == 64,
                 semigroup=semigroup_checks == 64, rejection=all(x["returncode"] != 0 for x in negatives))
    end_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary = dict(schema="hcsn-native-kernel-r19-v1", namespace=args.namespace, gates=gates, maximum=maximum,
                   cases=64, cold_equal=cold_equal, semigroup_checks=semigroup_checks, repeated_over_one=repeated_over_one,
                   tiny_positive=tiny_positive, negatives=len(negatives), failures=failures,
                   source_sha256={name:digest((HERE/name).read_bytes()) for name in ("main.rs", "verify.py", "PROTOCOL.json")},
                   binary_sha256=binary_hash, rustc_version=subprocess.check_output([RUSTC,"--version"]).decode().strip(),
                   cpu_scope="whole verify process plus waited compiler/native children, including build and failed negative cases; not development or project cost",
                   parent_cpu_seconds=time.process_time()-start_cpu,
                   child_cpu_seconds=(end_child.ru_utime+end_child.ru_stime)-(start_child.ru_utime+start_child.ru_stime),
                   wall_seconds=time.perf_counter()-start_wall, production_activation=False)
    (args.output / "SUMMARY.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))
    binary.unlink()
    if not all(gates.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
