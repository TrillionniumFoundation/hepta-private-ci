"""Compile a pure Rust task fixture and compare bounded reachable Python states.

No formal world/cohort is generated. This does not replace the full runtime,
content, ACK, recovery or repository test qualification.
"""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from . import joint_task as task
from .joint_task_audit import fixture
from ..digital_read_before_20261031.task import PUBLIC_NAMES

HERE = Path(__file__).resolve().parent


def scenarios(public):
    states, todo = {}, deque([task.initial(public)])
    waiting = task.initial(public)
    for _ in range(6):
        waiting = task.successor(public, waiting, 1)
        todo.append(waiting)
    while todo and len(states) < 128:
        s = todo.popleft(); key = json.dumps(s, sort_keys=True)
        if key in states:
            continue
        states[key] = s
        for action, valid in enumerate(task.legal(public, s)):
            if not valid or action in (0, 4, 5):
                continue
            due = task.due_request(public, s, action)
            outcomes = [None] if due is None else [dict(observation=y, observation_tick=due) for y in (0, 1)]+[dict(failure=True, observation_tick=due)]
            for outcome in outcomes:
                todo.append(task.successor(public, s, action, outcome))
    cases = []
    for s in states.values():
        for action in range(7):
            try: due = task.due_request(public, s, action)
            except ValueError: due = None
            outcomes = [None, dict(observation=0, observation_tick=s["tick"]+1)]
            if due is not None:
                outcomes += [dict(observation=y, observation_tick=due) for y in (0, 1)]
                outcomes += [dict(failure=True, observation_tick=due), dict(observation=1, observation_tick=due+1)]
            for outcome in outcomes:
                cases.append(dict(state=s, action=action, completion=outcome))
    return states, cases


def expected(public, case):
    s, a, done = case["state"], case["action"], case["completion"]
    try: due = task.due_request(public, s, a)
    except ValueError: due = None
    try:
        after = task.successor(public, s, a, done); error = False
    except ValueError:
        after, error = None, True
    mask = task.legal(public, s)
    return dict(error=error, due=None if due is None else due-1, after=after, legal=mask,
                public_features=task.public_features(public, s).tolist(),
                history_features=task.history_features(s).tolist(),
                fixed=[task.fixed_action(s, mask, p) for p in (.2, .5, .8)])


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--toolchain-bin", type=Path, required=True); parser.add_argument("--cargo-home", type=Path, required=True)
    args = parser.parse_args(); stage = args.stage.resolve(); stage.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time(); source = stage/"src"; source.mkdir()
    for name in ("joint_native_task.rs", "joint_native_task_fixture.rs"):
        shutil.copyfile(HERE/name, source/name)
    manifest = '[package]\nname="joint-native-task-fixture"\nversion="0.1.0"\nedition="2021"\npublish=false\n[[bin]]\nname="joint-native-task-fixture"\npath="src/joint_native_task_fixture.rs"\n[dependencies]\nserde={version="=1.0.228",features=["derive"]}\nserde_json={version="=1.0.149",features=["float_roundtrip"]}\n'
    (stage/"Cargo.toml").write_text(manifest)
    env = dict(os.environ); env["PATH"] = str(args.toolchain_bin)+os.pathsep+env["PATH"]
    env["CARGO_HOME"] = str(args.cargo_home)
    command = [str(args.toolchain_bin/"cargo"), "build", "--offline", "--manifest-path", str(stage/"Cargo.toml")]
    built = subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)
    (stage/"build.stdout").write_text(built.stdout); (stage/"build.stderr").write_text(built.stderr)
    if built.returncode:
        raise RuntimeError(f"actual Rust fixture build failed: {built.returncode}; see {stage}")
    binary = stage/"target/debug/joint-native-task-fixture"
    cohorts = []; total = rejected = 0
    for i, distance in enumerate((.125, .375, .75)):
        p = fixture(); p["id"] += str(i); p["prior_distance"] = distance
        p["read_delay"] = ([1]*6, [2]*6, [2, 1, 2, 1, 2, 1])[i]
        states, cases = scenarios(p)
        request = dict(public=p, cases=cases); raw = json.dumps(request, sort_keys=True).encode()
        (stage/f"input_{i}.json").write_bytes(raw)
        actual = subprocess.run([str(binary)], input=raw, capture_output=True, timeout=45)
        (stage/f"output_{i}.json").write_bytes(actual.stdout); (stage/f"stderr_{i}.txt").write_bytes(actual.stderr)
        if actual.returncode:
            raise RuntimeError(f"Rust task execution failed {actual.returncode}: {actual.stderr!r}")
        result = json.loads(actual.stdout)
        assert result["actions"] == list(task.ACTIONS)
        assert result["public_names"] == PUBLIC_NAMES+[f"drive_{j}" for j in range(6)]+["prior_distance"]
        assert len(result["rows"]) == len(cases)
        for number, (case, row) in enumerate(zip(cases, result["rows"])):
            target = expected(p, case)
            if row != target:
                (stage/"MISMATCH.json").write_text(json.dumps(dict(case=case, actual=row, expected=target), indent=2))
                raise AssertionError((i, number, "Rust/Python task row mismatch"))
            rejected += int(row["error"])
        total += len(cases); cohorts.append(dict(prior_distance=distance, states=len(states), paired_rows=len(cases)))
    result = dict(schema="joint-native-task-pairing-v1", passed=True, paired_rows=total,
                  rejected_rows=rejected, fixtures=cohorts, formal_worlds_generated=0,
                  comparison="all serialized fields exactly; no numeric tolerance", build_command=command,
                  scope="pure task fixture; no actual runtime/content/ACK or nextest gate claim",
                  wall_seconds=time.perf_counter()-wall, parent_cpu_seconds=time.process_time()-cpu,
                  source_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                    for name in ("joint_task.py", "joint_native_task.rs", "joint_native_task_fixture.rs", "joint_native_task_check.py")},
                  lock_sha256=hashlib.sha256((stage/"Cargo.lock").read_bytes()).hexdigest())
    (stage/"SUMMARY.json").write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    out = HERE/"evidence/joint_native_task_pairing.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n"); print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
