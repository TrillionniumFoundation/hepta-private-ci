"""Executable R16 compression invariants and real R15 owner histories.

Run from the repository root with ``python -m tools.hcsn.
reachable_state_r16_20261101.compression_checks``.  This is a correctness study,
not a task-utility confirmation or a speed benchmark.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..addressed_decision_r15_20261101.world import Episode
from .compression import (
    GROUPS, ProjectionLaw, ProjectionPrecisionError, decode, encode, metadata,
    project,
)


def invariants(p, law, mode):
    """Check retained marginals, support, likelihood, and projection idempotence."""
    q = project(p, mode)
    original = np.asarray(p).reshape(-1, 10, 4)
    projected = q.reshape(-1, 10, 4)
    assert np.isfinite(q).all() and np.all(q >= 0)
    assert not np.any((original > 0) & (projected == 0))
    error = dict(
        mass=float(np.max(np.abs(q.sum(-1) - 1))),
        phase=float(np.max(np.abs(original.sum(-1) - projected.sum(-1)))),
        content=float(np.max(np.abs(original.sum(-2) - projected.sum(-2)))),
        group_content=0.,
        read_likelihood=float(np.max(np.abs(np.asarray(p) @ law.E_read - q @ law.E_read))),
        refresh_likelihood=float(np.max(np.abs(
            np.asarray(p) @ law.E_refresh - q @ law.E_refresh))),
        idempotence=float(np.max(np.abs(project(q, mode) - q))),
    )
    for indices in GROUPS[mode]:
        residual = original[:, indices, :].sum(1) - projected[:, indices, :].sum(1)
        error["group_content"] = max(error["group_content"], float(np.max(abs(residual))))
    assert max(error.values()) < 2e-14, error
    assert np.array_equal(decode(encode(p, mode)), q)
    return error


def check_histories(law):
    """Run causal fixed READ histories and restore a live checkpoint each query."""
    trace = []
    observed = erased = checkpoints = support_checks = 0
    minimum_likelihood = {mode: 1. for mode in GROUPS}
    for domain in ("iid", "ood"):
        for seed in range(161901, 161917):
            owner = Episode(law, seed, domain)
            exact = BeliefMemory(law, owner.initial_values)
            memories = {mode: BeliefMemory(law, owner.initial_values, projection=mode)
                        for mode in GROUPS}
            for query, key in enumerate(owner.query_keys):
                key, dt = int(key), float(owner.dts[query])
                for event in owner.events_at(query):
                    if event["kind"] == "WRITE":
                        exact.write(event["key"], event["value"])
                        for memory in memories.values():
                            memory.write(event["key"], event["value"])
                for step in range(1, 4):
                    exact.advance(dt)
                    for memory in memories.values():
                        memory.advance(dt)
                    token = owner.observe(key, float(owner.starts[query] + step * dt),
                                          "read", query, step)
                    observed += 1
                    erased += int(token == 4)
                    row = dict(domain=domain, seed=seed, world=owner.fingerprint,
                               query=query, key=key, step=step, token=token, modes={})
                    for mode, memory in memories.items():
                        assert not np.any((exact.beliefs > 0) & (memory.beliefs == 0))
                        likelihood = float(memory.beliefs[key] @ law.E_read[:, token])
                        assert likelihood > 0
                        minimum_likelihood[mode] = min(minimum_likelihood[mode], likelihood)
                        support_checks += 1
                        before = memory.checkpoint()
                        restored = BeliefMemory.restore(law, before)
                        assert restored.checkpoint() == before
                        memory.observe(key, token, "read")
                        restored.observe(key, token, "read")
                        assert restored.checkpoint() == memory.checkpoint()
                        checkpoints += 1
                        row["modes"][mode] = dict(likelihood=likelihood,
                                                   checkpoint=memory.checkpoint()["sha256"])
                    exact.observe(key, token, "read")
                    for memory in memories.values():
                        assert not np.any((exact.beliefs > 0) & (memory.beliefs == 0))
                    trace.append(row)
    return dict(worlds=32, legal_observations=observed, recovery_erasure_observations=erased,
                paired_checkpoint_continuations=checkpoints, support_checks=support_checks,
                minimum_likelihood=minimum_likelihood, impossible_observations=0), trace


def run():
    start = time.process_time()
    base = Law()
    law = ProjectionLaw(base)
    assert law.identity == base.identity and law.operator_identity == base.operator_identity
    assert law.export() == base.export()
    rng = np.random.default_rng(161815)
    rows = [row for row in np.eye(40)]
    for index in range(512):
        row = np.exp(-rng.uniform(0, 250, size=40))
        if index % 2 == 0:
            row[rng.random(40) < .5] = 0
        row /= row.sum()
        rows.append(row)
    # Safe float64 rare-coordinate tests and structural zeros are explicit.
    for exponent in (20, 80, 120, 150):
        row = np.zeros(40)
        row[0], row[5] = 10. ** -exponent, 1.
        row /= row.sum()
        rows.append(row)
    batch = np.asarray(rows)
    maxima = {mode: invariants(batch, law, mode) for mode in GROUPS}
    # Also exercise arbitrary batch dimensions, not just vectors/matrices.
    for mode in GROUPS:
        invariants(batch[:48].reshape(2, 3, 8, 40), law, mode)
    underflow = np.zeros(40)
    underflow[0], underflow[5] = 1e-200, 1.
    rejected = []
    for mode in GROUPS:
        try:
            project(underflow, mode)
        except ProjectionPrecisionError:
            rejected.append(mode)
        else:
            raise AssertionError("Positive-coordinate underflow was silently accepted")
    # Historical failure: an index mean can eliminate recovery despite a
    # positive chance of receiving the erasure token. New projections cannot.
    witness = np.zeros(40)
    witness[0], witness[36] = .9, .1
    old = base.project(witness, "mean")
    original_erasure = float(witness @ base.E_read[:, 4])
    old_erasure = float(old @ base.E_read[:, 4])
    assert original_erasure > 0 and old_erasure == 0
    recovery = {mode: float(project(witness, mode) @ base.E_read[:, 4]) for mode in GROUPS}
    assert all(value == original_erasure for value in recovery.values())
    histories, trace = check_histories(law)
    result = dict(
        schema="hcsn-r16-compression-validation-v1", passed=True,
        law_identity=law.identity, operator_identity=law.operator_identity,
        invariant_beliefs_per_mode=len(batch), maximum_absolute_errors=maxima,
        float64_underflow_fail_closed_modes=rejected,
        old_mean_regression=dict(original_erasure=original_erasure,
                                 old_mean_erasure=old_erasure, new_erasure=recovery),
        real_owner_histories=histories,
        formats={mode: metadata(mode) for mode in GROUPS},
        current_owner_state_bytes_per_address=40 * 8,
        compressed_encoding_bytes_per_address={mode: encode(base.prior, mode).nbytes
                                               for mode in GROUPS},
        no_task_utility_or_speed_claim=True,
        finite_precision_scope="Positive float64 support is checked; unrepresentable lifts are rejected without smoothing. Exact-arithmetic support proof does not certify all float64 propagation operations.",
        process_cpu_seconds=time.process_time() - start,
    )
    return result, trace


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent / "results" / "COMPRESSION_VALIDATION.json")
    args = parser.parse_args()
    result, trace = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    trace_path = args.output.with_name("COMPRESSION_TRACES.jsonl")
    trace_bytes = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                   allow_nan=False) + "\n" for row in trace).encode()
    trace_path.write_bytes(trace_bytes)
    result["trace"] = dict(path=trace_path.name, bytes=len(trace_bytes),
                           sha256=hashlib.sha256(trace_bytes).hexdigest())
    result["source_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ("compression.py", "compression_checks.py")}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))
