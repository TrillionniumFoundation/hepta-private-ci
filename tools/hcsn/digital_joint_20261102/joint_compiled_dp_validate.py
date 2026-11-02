"""Full-table/actual-read fixture qualification, never efficacy confirmation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import numpy as np

from . import joint_compiled_dp as compiled
from . import joint_task as task
from .joint_law import IndependentLaw


def fixture(out):
    folder = out/"world"; folder.mkdir()
    public = dict(schema=task.SCHEMA, id="compiled-dp-fixture", deadline=6, initial_budget=3, target_tick=6,
                  duration=[.25]*6, drive=[1, -1, 1, 1, -1, 1], reliability=[.85]*6,
                  read_price=[.01]*6, read_delay=[2, 1, 2, 1, 1, 1], prior_distance=.375,
                  latency_price=.005, repair_price=.01, failure_probability=.15, packets=[], packet_sha256=[])
    for i, symbol in enumerate([0, 1, 1, 0, 1, 1]):
        raw = compiled.json_bytes(task.packet(symbol, 7300+i, 8)); name = f"boundary_{i+1}.json"
        public["packets"].append(name); public["packet_sha256"].append(hashlib.sha256(raw).hexdigest())
        if i != 1:
            (folder/name).write_bytes(raw)
    task.save(folder/"public.json", public); task.save(folder/"evaluator.json", dict(label=1))
    law = IndependentLaw([.2, -.1, .5, .1, .2, -.2, .1, 0.])
    confusion = [[.97, .03], [.04, .96]]
    allowed = {Path(compiled.__file__).resolve(), Path(task.__file__).resolve(), Path(sys.modules[IndependentLaw.__module__].__file__).resolve()}
    old_bytes, old_text = Path.read_bytes, Path.read_text
    def guarded_bytes(path):
        if path.resolve() not in allowed:
            raise AssertionError("compilation attempted private or unrelated file access")
        return old_bytes(path)
    def guarded_text(path, *a, **k):
        raise AssertionError("compilation attempted private or unrelated text read")
    records, comparisons, max_error, attempts, success = [], 0, 0., 0, 0
    for failure in (0., .15, 1.):
        world = dict(public, failure_probability=failure)
        with patch.object(Path, "read_bytes", guarded_bytes), patch.object(Path, "read_text", guarded_text):
            artifact = compiled.compile_policy(world, law, confusion, "fixture_declared_law_declared_decoder")
            warm = compiled.compile_policy(world, law, confusion, "fixture_declared_law_declared_decoder", cold_law=False)
        assert warm["states"] == artifact["states"]
        policy, payload, load = compiled.serialize_load(artifact)
        (out/f"compiled_{failure}.json").write_bytes(payload)
        oracle = task.Oracle(world, IndependentLaw(law.raw, law.n_grid), confusion)
        for key, row in artifact["states"].items():
            state = oracle._state(json.loads(key)); prediction = policy.predict(world, state)
            mask = np.asarray(task.legal(world, state)); q = oracle.q(state)
            error = max(float(np.max(np.abs(np.asarray(prediction["q"])[mask]-q[mask]))), abs(prediction["belief"]-oracle.posterior(state)))
            max_error = max(max_error, error); comparisons += 1
            assert int(np.argmax(np.where(mask, prediction["q"], -np.inf))) == int(np.argmax(q))
            state["charges"] = 123.45; assert policy.predict(world, state) == prediction
        adapter = task.ContentAdapter(); episodes = []
        for controller in ("fixed", "value"):
            result = compiled.run_episode(world, folder, adapter, policy, controller)
            for row in result["decisions"]:
                before = row["receipt"]["before"]; mask = task.legal(world, before)
                expected = task.fixed_action(before, mask, oracle.posterior(before)) if controller == "fixed" else int(np.argmax(oracle.q(before)))
                assert row["receipt"]["action"] == expected
                assert row["receipt"]["after"] == task.successor(world, before, expected, row["receipt"]["completion"])
                attempts += row["receipt"]["source_opened"] is not None
                success += "observation" in (row["receipt"]["content"] or {})
            episodes.append(result)
        try:
            policy.predict(dict(world, id="wrong-world"), task.initial(world))
            raise AssertionError("wrong world accepted")
        except ValueError:
            pass
        records.append(dict(public=world, compile=artifact["compile_measurement"], load=load, states=len(artifact["states"]), episodes=episodes))
    assert max_error < 2e-12
    report = dict(schema="joint-compiled-dp-fixture-v1", passed=True, compared_states=comparisons,
                  maximum_q_or_belief_error=max_error, compilation_private_reads=0, read_attempts=attempts,
                  successful_decodes=success, records=records, scope="fixture correctness/cost only; no fit or task-benefit claim",
                  sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(compiled.__file__)]})
    task.save(out/"SUMMARY.json", report)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--out", type=Path, required=True); p.add_argument("--worker", action="store_true"); a = p.parse_args()
    if a.worker:
        fixture(a.out); return
    a.out.mkdir(parents=True, exist_ok=False); wall = time.perf_counter()
    command = [sys.executable, "-m", __spec__.name, "--out", str(a.out), "--worker"]
    with (a.out/"stdout.log").open("x") as stdout, (a.out/"stderr.log").open("x") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(child.pid, 0); child.returncode = os.waitstatus_to_exitcode(status)
    task.save(a.out/"PROCESS.json", dict(returncode=child.returncode, wall_seconds=time.perf_counter()-wall,
              user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime, maximum_resident_kib=usage.ru_maxrss,
              scope="complete fixture worker process including imports, all compiles, independent verification, actual reads, serialization and exit"))
    if child.returncode:
        raise RuntimeError("compiled DP fixture failed; retain complete output")


if __name__ == "__main__":
    main()
