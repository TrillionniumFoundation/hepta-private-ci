"""E1–E6 mathematical prerequisites: fresh synthetic arrays, zero model calls."""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

import numpy as np

from . import pft_linear as pft


RESULTS = {"lq_cases": [], "normal_cases": [], "negative_controls": {}}


def fingerprint(arrays):
    digest = hashlib.sha256()
    for value in arrays:
        value = np.asarray(value, dtype="<f8")
        digest.update(json.dumps(value.shape).encode() + value.tobytes())
    return digest.hexdigest()


def example(dim, horizon, deficient):
    seed = 1729 + dim * 100 + horizon * 10 + int(deficient)
    rng = np.random.default_rng(seed)
    A = [.7 * np.eye(dim) + rng.normal(0, .03 / np.sqrt(dim), (dim, dim)) for _ in range(horizon)]
    E = [rng.normal(0, .5 / np.sqrt(dim), (dim, dim)) for _ in range(horizon)]
    if deficient:
        for e in E:
            e[:, dim // 2:] = e[:, :dim // 2]
    L = [rng.normal(0, 1 / np.sqrt(dim), (2, dim)) for _ in range(horizon + 1)]
    targets = [rng.normal(0, .2, 2) for _ in L]
    L, targets = pft.augment_terminal(L, targets, [
        (rng.normal(0, 1 / np.sqrt(dim), (2, dim)), np.array([.7, -.4]), 1.3),
        (rng.normal(0, 1 / np.sqrt(dim), (1, dim)), np.zeros(1), 2.)])
    costs = []
    for _ in range(horizon):
        square = rng.normal(0, 1 / np.sqrt(dim), (dim, dim))
        costs.append(square @ square.T + .3 * np.eye(dim))
    return (A, E, L, targets, costs), rng, seed


class QualificationTests(unittest.TestCase):
    def test_full_compressed_and_independent_condensed(self):
        for dim in (8, 32, 64):
            for horizon in (1, 3, 6):
                for deficient in (False, True):
                    system, rng, seed = example(dim, horizon, deficient)
                    A, E, L, targets, costs = system
                    started = time.perf_counter_ns()
                    full = pft.solve_lq(*system)
                    full_ns = time.perf_counter_ns() - started
                    started = time.perf_counter_ns()
                    bases, ranks = pft.effective_action_bases(A, E, L, costs)
                    basis_ns = time.perf_counter_ns() - started
                    started = time.perf_counter_ns()
                    small, _ = pft.reduce_actions(*system, bases=bases)
                    compressed_ns = time.perf_counter_ns() - started
                    for origin in range(3):
                        with self.subTest(dim=dim, horizon=horizon, deficient=deficient, origin=origin):
                            initial = rng.normal(0, .3, dim)
                            innovations = rng.normal(0, .02, (horizon, dim))
                            observed = pft.rollout(full, initial)
                            reduced = pft.rollout(small, initial)
                            expanded = [b @ u for b, u in zip(bases, reduced["actions"], strict=True)]
                            started = time.perf_counter_ns()
                            condensed = pft.condensed_kkt(*system, initial)
                            condensed_ns = time.perf_counter_ns() - started
                            noisy_full = pft.rollout(full, initial, innovations)
                            noisy_small = pft.rollout(small, initial, innovations)
                            actions = np.asarray(observed["actions"])
                            errors = dict(condensed_action=float(np.max(np.abs(actions - condensed["actions"]))),
                                          compressed_action=float(np.max(np.abs(actions - expanded))),
                                          compressed_cost=abs(observed["objective"] - reduced["objective"]),
                                          condensed_cost=abs(observed["objective"] - condensed["objective"]),
                                          noisy_cost=abs(noisy_full["objective"] - noisy_small["objective"]),
                                          noisy_state=float(np.max(np.abs(noisy_full["states"] - noisy_small["states"]))),
                                          kkt_stationarity=condensed["stationarity"])
                            record = dict(dim=dim, horizon=horizon, deficient=deficient, origin=origin,
                                          seed=seed, shared_policy_group=seed,
                                          policy_timing_scope="one shared construction per group; repeated per-origin metadata",
                                          array_sha256=fingerprint(sum((list(g) for g in system), [])),
                                          initial=initial.tolist(), innovations=innovations.tolist(), ranks=ranks,
                                          full_actions=actions.tolist(), compressed_actions=[u.tolist() for u in expanded],
                                          condensed_actions=[u.tolist() for u in condensed["actions"]],
                                          full_endpoint=observed["states"][-1].tolist(), errors=errors,
                                          objectives={"full": observed["objective"], "compressed": reduced["objective"],
                                                      "condensed": condensed["objective"], "noisy_full": noisy_full["objective"],
                                                      "noisy_compressed": noisy_small["objective"]},
                                          timing_ns=dict(full_policy=full_ns, basis=basis_ns,
                                                         compressed_policy=compressed_ns, condensed=condensed_ns))
                            RESULTS["lq_cases"].append(record)
                            self.assertLess(max(errors.values()), 1e-9)
                            self.assertLess(max(r["metric_error"] for r in ranks), 1e-10)
                            self.assertLess(max(r["dropped_norm"] for r in ranks), 1e-10)

    def test_pooled_shards_recursive_and_average(self):
        for dim in (8, 32, 64):
            rng = np.random.default_rng(431 + dim)
            batches = []
            for slot, count in enumerate((7, 19, 41)):
                x = rng.normal(size=(count, dim)) * (1 + slot)
                x[:, 0] += 2 * slot
                x[-2:] = x[:2]
                y = rng.normal(size=(count, 2)) + slot
                batches.append((x, y))
            x, y = (np.concatenate([b[j] for b in batches]) for j in (0, 1))
            gram, rhs = sum(a.T @ a for a, _ in batches), sum(a.T @ b for a, b in batches)
            started = time.perf_counter_ns()
            pooled = pft.solve_normal(x.T @ x, x.T @ y)
            pooled_ns = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            sharded = pft.solve_normal(gram, rhs)
            sharded_ns = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            recursive = pft.recursive_ridge(batches)
            rls_ns = time.perf_counter_ns() - started
            local = [pft.solve_normal(a.T @ a, a.T @ b) for a, b in batches]
            average = np.mean(local, axis=0)
            weighted = np.average(local, axis=0, weights=[len(a) for a, _ in batches])
            def loss(weight):
                return float(.5 * (np.square(x @ weight - y).sum() + .2 * np.square(weight).sum()))
            errors = dict(shard=float(np.max(np.abs(pooled - sharded))),
                          rls=float(np.max(np.abs(pooled - recursive))),
                          kkt=float(np.max(np.abs(x.T @ (x @ pooled - y) + .2 * pooled))))
            RESULTS["normal_cases"].append(dict(dim=dim, rows=[7, 19, 41], seed=431 + dim,
                data_sha256=fingerprint([x, y]), regularizer=.2, errors=errors,
                pooled=pooled.tolist(), sharded=sharded.tolist(), rls=recursive.tolist(),
                local_average=average.tolist(), weighted_average=weighted.tolist(),
                objective={"pooled": loss(pooled), "average": loss(average), "weighted": loss(weighted)},
                timing_ns=dict(pooled=pooled_ns, sharded=sharded_ns, rls=rls_ns)))
            self.assertLess(max(errors.values()), 2e-8)
            self.assertGreater(loss(average) - loss(pooled), 1e-3)
            self.assertGreater(loss(weighted) - loss(pooled), 1e-3)

    def test_new_terminal_direction_and_zero_rank(self):
        A, E, costs = [np.eye(2)], [np.eye(2)], [np.eye(2)]
        old_L, old_r = [np.zeros((0, 2)), np.array([[1., 0.]])], [np.zeros(0), np.zeros(1)]
        old_basis, _ = pft.effective_action_bases(A, E, old_L, costs)
        L, targets = pft.augment_terminal(old_L, old_r, [(np.array([[0., 1.]]), np.ones(1), 1.)])
        full = pft.rollout(pft.solve_lq(A, E, L, targets, costs), np.zeros(2))
        correct, bases = pft.reduce_actions(A, E, L, targets, costs)
        stale, _ = pft.reduce_actions(A, E, L, targets, costs, bases=old_basis)
        correct, stale = pft.rollout(correct, np.zeros(2)), pft.rollout(stale, np.zeros(2))
        RESULTS["negative_controls"]["stale_terminal_basis"] = dict(
            old_rank=old_basis[0].shape[1], augmented_rank=bases[0].shape[1],
            full_cost=full["objective"], augmented_cost=correct["objective"], stale_cost=stale["objective"])
        self.assertAlmostEqual(full["objective"], correct["objective"], places=14)
        self.assertGreater(stale["objective"] - full["objective"], .1)
        L = [np.zeros((1, 2)) for _ in range(2)]
        zero, basis = pft.reduce_actions(A, E, L, [np.zeros(1)] * 2, costs)
        self.assertEqual(basis[0].shape, (2, 0))
        self.assertEqual(pft.rollout(zero, np.ones(2))["objective"], 0.)

    def test_invalid_statistics_and_costs_reject(self):
        for gram, rhs in ((np.eye(2), np.ones(3)), (-np.eye(2), np.ones(2)),
                          (np.full((2, 2), np.nan), np.ones(2)), (np.array([[1., 1.], [0., 1.]]), np.ones(2))):
            with self.assertRaises(ValueError):
                pft.solve_normal(gram, rhs)
        with self.assertRaises(ValueError):
            pft.solve_lq([np.eye(2)], [np.eye(2)], [np.eye(2)] * 2, [np.zeros(2)] * 2, [-np.eye(2)])
        RESULTS["negative_controls"]["malformed_statistics_and_indefinite_cost"] = {"rejections": 5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(QualificationTests))
    payload = dict(schema="hepta.e1e6.pft-linear-qualification.v1", passed=result.wasSuccessful(),
        scope="synthetic mathematical prerequisites; no independent task, learning, or adoption acceptance",
        model_calls=0, test_cases=result.testsRun, test_log=stream.getvalue(), results=RESULTS,
        runtime=dict(python=sys.version, numpy=np.__version__, platform=platform.platform(),
                     ended_at=datetime.now(timezone.utc).isoformat()),
        source_references={"riccati": "32b8a11ae5d55a2e7324a8b31c5057f7b911a139",
                           "resident_ridge": "2395cf55831d480d4ca7cce2886e39ba9b04d063"},
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (Path(__file__), Path(pft.__file__))},
        timing_ns=dict(wall=time.perf_counter_ns() - start, cpu=time.process_time_ns() - cpu))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        output.write("\n")
    print(stream.getvalue(), end="")
    print(json.dumps({"passed": payload["passed"], "lq_cases": len(RESULTS["lq_cases"]),
                      "normal_cases": len(RESULTS["normal_cases"]), "output": str(args.output)}))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
