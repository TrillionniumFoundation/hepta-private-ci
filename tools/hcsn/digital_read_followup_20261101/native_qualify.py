"""Actual Rust/NumPy pairing and acknowledged cold recovery on validation worlds.

This never creates confirmation worlds or estimates task benefit. Existing
validation packets and frozen final model bytes are inputs, not tuning data.
"""
import argparse
import gzip
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

from . import control_campaign as c
from ..digital_read_before_20261031 import task


def same_state(actual, expected):
    a, b = dict(actual), dict(expected)
    for name in ("elapsed", "charges"):
        if abs(a.pop(name)-b.pop(name)) > 2e-12:
            raise AssertionError("task clock or fee mismatch")
    if a != b:
        raise AssertionError("complete task state mismatch")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--train", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--worlds-per-fit", type=int, default=1)
    a = p.parse_args()
    if not 1 <= a.worlds_per_fit <= 16:
        raise ValueError("bounded validation cohort required")
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    protocol = c.read(c.HERE/"control_protocol.json")
    content = c.HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    adapter = task.ContentAdapter()
    invocations, cases, maximum, pending, actual_reads = [], [], 0., 0, 0
    wall, cpu = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)

    def invoke(public, policy, controller, snapshot, seed, steps, ack=None, expect=0):
        command = [str(a.binary.resolve()), "--public", str(public), "--content-model", str(content),
                   "--policy", str(policy), "--controller", controller, "--snapshot", str(snapshot),
                   "--seed", str(seed), "--steps", str(steps)]
        if ack is not None:
            command += ["--ack", ack]
        start = time.perf_counter()
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
        row = dict(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                   wall_seconds=time.perf_counter()-start)
        invocations.append(row)
        if (expect == 0) != (proc.returncode == 0):
            c.write(out/"FAILED.json.gz", dict(invocations=invocations, reason="unexpected native status"))
            raise AssertionError("unexpected native status")
        return json.loads(proc.stdout) if expect == 0 else None

    for fit in protocol["fits"]:
        for family in protocol["families"]:
            oldpath = c.BASE/f"checkpoints/fit_{fit}/{family}.json.gz"
            newpath = a.train/f"fit_{fit}/{family}.json"
            old, new = c.read(oldpath), c.read(newpath)
            cached = out/f"old_{fit}_{family}.json"
            cached.write_bytes(gzip.decompress(oldpath.read_bytes()))
            for wi in range(a.worlds_per_fit):
                folder = (a.train/f"fit_{fit}/validation_fit{fit}_{wi:04d}").resolve()
                public_path = folder/"public.json"; public = c.read(public_path)
                for arm in protocol["arms"]:
                    structured = arm in ("terminal_only", "repaired_value", "repaired_fixed")
                    artifact = new if arm.startswith("repaired") else old
                    model = newpath.resolve() if arm.startswith("repaired") else cached
                    controller = "fixed" if arm.endswith("fixed") else "structured_value" if structured else "value"
                    policy = c.Policy(artifact, structured)
                    seed = 991000+fit*10000+wi
                    name = f"fit{fit}_{family}_{wi}_{arm}"
                    native = invoke(public_path, model, controller, out/(name+"_full.json"), seed, 7)
                    start = invoke(public_path, model, controller, out/(name+"_resume.json"), seed, 1)
                    pending += start["after"]["task"]["pending"] is not None
                    resumed = invoke(public_path, model, controller, out/(name+"_resume.json"), seed, 7, start["acknowledged_sha256"])
                    if native["after"] != resumed["after"] or native["acknowledged_sha256"] != resumed["acknowledged_sha256"]:
                        raise AssertionError("cold process task/cell/RNG/content/ledger recovery differs")
                    expected, _ = c.run(dict(id=public["id"], folder=str(folder)), adapter, policy,
                                        "fixed" if controller == "fixed" else "value", seed)
                    same_state(native["after"]["task"], expected["final_state"])
                    if [r["action"] for r in native["receipts"]] != [r["action"] for r in expected["decisions"]]:
                        raise AssertionError("independent whole-episode route mismatch")
                    error = 0.
                    for receipt in native["receipts"]:
                        before, after = receipt["before"], receipt["after"]
                        scores = policy.predict(public, before, receipt["cell_before"]["index"])
                        error = max(error, float(np.max(np.abs(np.asarray(scores["q"])-receipt["q"]))), abs(scores["belief"]-receipt["belief"]))
                        if error > 5e-12 or receipt["forced_control"] or not native["actual_native"] or native["production_activation"]:
                            raise AssertionError("native score or execution identity mismatch")
                        same_state(after, task.successor(public, before, receipt["action"], receipt["completion"]))
                        index, rng = receipt["cell_before"]["index"], int(receipt["cell_before"]["rng_hex"], 16)
                        if receipt["action"] not in (0, 4, 5):
                            index, rng, _ = policy.advance(public, before, index, rng)
                        if index != receipt["cell_after"]["index"] or rng != int(receipt["cell_after"]["rng_hex"], 16):
                            raise AssertionError("hard cell/RNG mismatch")
                        actual_reads += receipt["actual_content_calls"]
                    maximum = max(maximum, error)
                    if fit == protocol["fits"][0] and family == protocol["families"][0] and wi == 0:
                        snapshot = out/(name+"_resume.json")
                        digest_before = c.digest(snapshot)
                        invoke(public_path, model, controller, snapshot, seed, 0, expect=1)
                        invoke(public_path, model, controller, snapshot, seed, 0, "0"*64, expect=1)
                        other = "value" if controller != "value" else "fixed"
                        invoke(public_path, model, other, snapshot, seed, 0, resumed["acknowledged_sha256"], expect=1)
                        if c.digest(snapshot) != digest_before:
                            raise AssertionError("refused resume changed acknowledged state")
                    cases.append(dict(name=name, maximum_score_error=error, public_sha256=c.digest(public_path),
                                      policy_sha256=c.digest(model), source_digest=native["source_digest"],
                                      actual_reads=sum(r["actual_content_calls"] for r in native["receipts"]),
                                      full=native, prefix=start, resumed=resumed, python=expected))
                    c.write(out/(name+".evidence.json.gz"), cases[-1])
                    cases[-1] = {k:v for k,v in cases[-1].items() if k not in ("full", "prefix", "resumed", "python")}
        print(json.dumps(dict(stage="native_validation", fit=fit, paired_episodes=len(cases))), flush=True)
    if pending == 0 or actual_reads == 0:
        raise AssertionError("pending recovery and real content execution need actual coverage")
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary = dict(schema="digital-structured-native-qualification-v1", cases=cases, paired_episodes=len(cases),
                   invocations=len(invocations), refusal_invocations=15, maximum_score_error=maximum,
                   recovered_pending_cases=pending, full_run_actual_content_calls=actual_reads,
                   binary_sha256=c.digest(a.binary), content_model_sha256=c.digest(content),
                   wall_seconds=time.perf_counter()-wall, child_cpu_seconds=cpu_after.ru_utime+cpu_after.ru_stime-cpu.ru_utime-cpu.ru_stime,
                   backend="real Rust NeuronRuntime owner and independent NumPy actual FullHX owner",
                   scope="validation implementation and cold ACK recovery; no confirmation utility inference", production_activation=False)
    c.write(out/"INVOCATIONS.json.gz", invocations)
    c.write(out/"SUMMARY.json", summary)
    print(json.dumps({k:v for k,v in summary.items() if k != "cases"}), flush=True)


if __name__ == "__main__":
    main()
