"""Native parity and true-jump recovery for an immutable full-HX Q fixture."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
from scipy.linalg import expm

from adapter import NativeOperator, ROOT


def invoke(command):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    begin = time.perf_counter()
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(command=[str(x) for x in command], exit_code=result.returncode, stdout=result.stdout,
                stderr=result.stderr, wall_seconds=time.perf_counter()-begin,
                child_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)


def run(fixture, output, build):
    output.mkdir(parents=True, exist_ok=False)
    source = fixture.read_bytes()
    (output/"fixture.json").write_bytes(source)
    model = json.loads(source)
    q, p, emission = np.array(model["Q"]), np.array(model["prior"]), np.array(model["emission"])
    op = NativeOperator(build/"libhcsn_native.so")
    checks, rows = [], []
    result = dict(schema="hcsn-r12-real-contract-native-v1", fixture_sha256=hashlib.sha256(source).hexdigest(),
                  build_receipt=json.loads((build/"BUILD_RECEIPT.json").read_text()), checks=checks, rows=rows)

    def check(name, condition, details=None):
        checks.append(dict(name=name, passed=bool(condition), details=details))
        if not condition:
            (output/"FAILED.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
            raise AssertionError(name)

    for dt in [.05, .15, .45, .75, 1.05, 2.1, 128.]:
        actual, reference = op.propagate(q, p, dt), p @ expm(q*dt)
        error, mass_error = float(np.max(np.abs(actual-reference))), float(actual.sum()-p.sum())
        rows.append(dict(kind="propagation", dt=dt, max_error=error, mass_error=mass_error,
                         actual=actual.tolist(), reference=reference.tolist()))
        check(f"fullHX_Q_dt{dt}", error < 3e-11 and abs(mass_error) < 3e-11)
        for symbol in range(emission.shape[1]):
            likelihood = emission[:, symbol]
            normalizer = reference @ likelihood
            code, posterior = op.raw_observe(actual, likelihood)
            if normalizer == 0:
                check(f"impossible_dt{dt}_symbol{symbol}", code == 4)
            else:
                expected = reference*likelihood/normalizer
                posterior_error = float(np.max(np.abs(posterior-expected)))
                rows.append(dict(kind="posterior", dt=dt, symbol=symbol, max_error=posterior_error,
                                 actual=posterior.tolist(), reference=expected.tolist()))
                check(f"fullHX_Bayes_dt{dt}_symbol{symbol}", code == 0 and posterior_error < 3e-11)

    initial = output/"initial.txt"
    initial.write_text(str(len(p))+"\n"+" ".join(format(x, ".17g") for x in np.concatenate([q.ravel(), p]))+"\n")
    scripts = {"whole": "advance 256\n", "prefix": "advance 64\n", "suffix": "advance 192\n"}
    for name, text in scripts.items(): (output/f"{name}.script").write_text(text)
    seed = 20261031
    exe = build/"hcsn-events"
    executions = [invoke([exe, "init", initial, output/"whole.script", output/"whole.events", seed]),
                  invoke([exe, "init", initial, output/"prefix.script", output/"prefix.events", seed]),
                  invoke([exe, "resume", output/"prefix.events", output/"suffix.script", output/"resumed.events"])]
    result["event_executions"] = executions
    check("three_event_processes_complete", all(x["exit_code"] == 0 for x in executions))
    full, prefix, suffix = [json.loads(x["stdout"]) for x in executions]
    check("distinct_event_processes", len({full["pid"], prefix["pid"], suffix["pid"]}) == 3)
    check("pending_event_future_at_restore", prefix["next_time"] > prefix["time"])
    check("exact_event_trace_replay", full["jumps"] == prefix["jumps"]+suffix["jumps"])
    check("exact_event_checkpoint_replay", (output/"whole.events").read_bytes() == (output/"resumed.events").read_bytes())
    check("many_cycles_one_interval", full["counts"][1] > 1 and full["counts"][3] > 1 and full["counts"][4] > 0,
          dict(counts=full["counts"], order=["jumps", "first_hits", "refractory_phases", "resets", "content_switches"]))
    active, width = len(p)//2-2, len(p)//2
    counts, current, previous_time = [0]*5, full["initial_state"], 0.
    kinds = []
    for jump in full["jumps"]:
        a, b = jump["from"] % width, jump["to"] % width
        same = jump["from"]//width == jump["to"]//width
        if a == 0 and b == active and same: kind = "first_hit"
        elif a == active and b == active+1 and same: kind = "refractory_phase"
        elif a == active+1 and b < active: kind = "reset_keep" if same else "reset_switch"
        elif a < active and b < active and abs(a-b) == 1 and same: kind = "active_jump"
        else: raise AssertionError("Invalid physical transition in raw trace")
        if not (jump["from"] == current and q[jump["from"], jump["to"]] > 0 and previous_time < jump["time"] <= 256.):
            raise AssertionError("Noncausal or unreachable raw event")
        if jump["kind"] != kind: raise AssertionError("Mislabeled event")
        counts[0] += 1
        counts[1] += kind == "first_hit"
        counts[2] += kind == "refractory_phase"
        counts[3] += kind.startswith("reset_")
        counts[4] += kind == "reset_switch"
        current, previous_time = jump["to"], jump["time"]
        if kind != "active_jump": kinds.append(kind)
    check("independent_event_semantics_and_counts", counts == full["counts"] and current == full["current"], counts)
    check("ordered_firsthit_phase_reset", all(kinds[i:i+2] == ["first_hit", "refractory_phase"] and kinds[i+2].startswith("reset_")
          for i in range(0, len(kinds)-2, 3)), kinds[:18])
    for name in ["whole", "prefix", "resumed"]:
        body, digest = (output/f"{name}.events").read_text().rsplit("CHECKSUM ", 1)
        check(f"event_checksum_{name}", hashlib.sha256(body.encode()).hexdigest() == digest.strip())
    original = (output/"prefix.events").read_text()
    bad = original.replace("HCSN_NATIVE_EVENTS_V1", "HCSN_NATIVE_EVENTS_V0", 1)
    (output/"corrupt.events").write_text(bad)
    refused = invoke([exe, "resume", output/"corrupt.events", output/"suffix.script", output/"refused.events"])
    executions.append(refused)
    check("event_corruption_refused", refused["exit_code"] != 0 and not (output/"refused.events").exists(), refused)
    result["summary"] = dict(checks=len(checks), passed=sum(x["passed"] for x in checks),
                             max_probability_error=max(x["max_error"] for x in rows),
                             max_mass_error=max(abs(x["mass_error"]) for x in rows if "mass_error" in x),
                             event_counts=counts, same_Q_fixed_for_entire_path=True,
                             event_trace_equals_expected_occupancy=False, production_qualified=False)
    (output/"RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return result["summary"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", type=Path, default=ROOT/"evidence"/"build")
    args = parser.parse_args()
    print(json.dumps(run(args.fixture.resolve(), args.output.resolve(), args.build.resolve()), indent=2))
