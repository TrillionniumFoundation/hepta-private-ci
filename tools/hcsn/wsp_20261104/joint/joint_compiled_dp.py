"""Public-world DP compilation; execution never recomputes a teacher posterior.

Supplied-law optimality is not unknown-true-law optimality. Each world pays its
own cold compile, serialization, load, lookup and actual Owner execution costs.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from . import joint_task as task
from .joint_law import IndependentLaw

SCHEMA = "joint-compiled-dp-v1"


def state_key(s):
    p = s["pending"]
    key = (s["tick"], s["budget"], s["broken"], None if p is None else (p["source_tick"], p["due_tick"]),
           tuple((r["source_tick"], r["observation_tick"], r["observation"]) for r in s["history"]))
    return json.dumps(key, separators=(",", ":"))


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()


def object_bytes(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value)); total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(object_bytes(k, seen)+object_bytes(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        total += sum(object_bytes(v, seen) for v in value)
    return total


def compile_policy(public, law, confusion, reference_scope="supplied_law_and_decoder_reference", max_states=20000, cold_law=True):
    """Compile every structurally lawful history, using public/model only.

    Oracle history/DP caches are always new. A cold law also discards physics
    caches; explicit warm reuse is public dt/drive/law math only and must have
    its preparation charged. No folder, evaluator or packet path is accepted.
    """
    wall, cpu = time.perf_counter(), time.process_time()
    task.validate_public(public)
    if not isinstance(reference_scope, str) or not reference_scope or len(reference_scope) > 200:
        raise ValueError("explicit bounded reference-scope label required")
    if not isinstance(max_states, int) or not 1 <= max_states <= 20000:
        raise ValueError("bounded positive state cap required")
    fresh = IndependentLaw(law.raw, law.n_grid) if cold_law else law
    oracle = task.Oracle(public, fresh, confusion)
    rows, pending = {}, [task.initial(public)]
    while pending:
        state = pending.pop(); key = state_key(state)
        if key in rows:
            continue
        if len(rows) >= max_states:
            raise OverflowError("compiled DP state cap exceeded; compilation rejected")
        mask = np.asarray(task.legal(public, state)); q = oracle.q(state)
        rows[key] = dict(q=np.where(mask, q, 0.).tolist(), legal=mask.tolist(),
                         belief=oracle.posterior(state), action=int(np.argmax(q)))
        for action in np.flatnonzero(mask):
            if action in (0, 4, 5):
                continue
            due = task.due_request(public, state, int(action))
            completions = [None]
            if due is not None:
                completions = [dict(failure=True, observation_tick=due)]
                completions += [dict(observation=y, observation_tick=due) for y in (0, 1)]
            pending += [task.successor(public, state, int(action), outcome) for outcome in completions]
    sources = [Path(__file__), Path(task.__file__), Path(sys.modules[IndependentLaw.__module__].__file__)]
    artifact = dict(schema=SCHEMA, public=copy.deepcopy(public), law=fresh.export(),
                    decoder_confusion=np.asarray(confusion).tolist(), reference_scope=reference_scope,
                    states=rows, state_count=len(rows),
                    scope="exact DP of supplied finite CTMC/decoder model; no unknown-true-law or production claim",
                    key_contract="observed history/tick/budget/pending/broken; additive sunk fees omitted",
                    sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    artifact["compile_measurement"] = dict(cpu_seconds=time.process_time()-cpu,
                                          wall_seconds=time.perf_counter()-wall,
                                          cold_law=bool(cold_law), fresh_oracle=True,
                                          serialization_and_load_excluded=True)
    return artifact


class CompiledPolicy:
    def __init__(self, artifact):
        if artifact.get("schema") != SCHEMA or not 0 < artifact["state_count"] <= 20000:
            raise ValueError("incompatible compiled policy")
        self.public, self.reference_scope = copy.deepcopy(artifact["public"]), artifact["reference_scope"]
        self.rows = copy.deepcopy(artifact["states"])
        if len(self.rows) != artifact["state_count"]:
            raise ValueError("compiled state count mismatch")
        for row in self.rows.values():
            if len(row["q"]) != 6 or len(row["legal"]) != 6 or not np.isfinite(row["q"]).all() or not 0 <= row["belief"] <= 1:
                raise ValueError("invalid compiled scores")

    def predict(self, public, state):
        if public != self.public or state["terminal"]:
            raise ValueError("wrong bound public world or terminal state")
        row = self.rows[state_key(state)]  # No teacher fallback on an unknown history.
        if task.legal(public, state) != row["legal"]:
            raise ValueError("compiled legal mask mismatch")
        return dict(q=list(row["q"]), belief=row["belief"])


def serialize_load(artifact):
    wall, cpu = time.perf_counter(), time.process_time()
    payload = json_bytes(artifact)
    serialization = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    wall, cpu = time.perf_counter(), time.process_time()
    policy = CompiledPolicy(json.loads(payload))
    load = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    return policy, payload, dict(serialization=serialization, load=load, serialized_bytes=len(payload),
                                loaded_python_reachable_bytes=object_bytes(policy.__dict__),
                                memory_scope="reachable Python object sizes; not allocator/RSS peak")


def run_episode(public, folder, adapter, policy, controller="value"):
    if controller not in ("fixed", "value"):
        raise ValueError("fixed/value controller required")
    wall, cpu = time.perf_counter(), time.process_time()
    owner, decisions = task.Owner(public, folder, adapter), []
    while not owner.state["terminal"]:
        before = copy.deepcopy(owner.state); mask = task.legal(public, before)
        tick_wall, tick_cpu = time.perf_counter(), time.process_time()
        scores = policy.predict(public, before)
        action = task.fixed_action(before, mask, scores["belief"]) if controller == "fixed" else int(np.argmax(np.where(mask, scores["q"], -np.inf)))
        lookup = dict(cpu_seconds=time.process_time()-tick_cpu, wall_seconds=time.perf_counter()-tick_wall)
        decisions.append(dict(receipt=owner.step(action), **scores, lookup_measurement=lookup))
    label = json.loads((Path(folder)/"evaluator.json").read_text())["label"]
    return dict(decisions=decisions, final_state=owner.state, outcome=task.evaluate_terminal(owner.state, label),
                cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                reference_scope=policy.reference_scope, evaluator_read_only_after_termination=True)
