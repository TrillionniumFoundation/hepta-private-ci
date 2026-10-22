"""Actual spawned NPZ inference, controller counts and fail-closed IPC boundaries."""

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time
import unittest
from unittest.mock import patch

import torch

from cell_evolution_snapshot import (EvolutionBudgetV1, EvolutionError, WithdrawalViewV1,
    bootstrap_snapshot, load_snapshot, retire_snapshot)
from cell_process_owner import SnapshotProcessOwnerV1, SnapshotWorkerPoolV1
from cell_process_protocol import (MAX_WIRE_BYTES, ProcessInferenceError, ProcessMessageV1,
    feature_payload, match_response, read_features, snapshot_pins)
from cell_router_training import RouterTrainingError
from feature_bundle import FeatureBundleV1, FeatureBundleError
import test_cell_router_training as router_fixture
from test_cell_router_training import IDENTITY, cohort


class Withdrawals:
    def __init__(self):
        self.view = WithdrawalViewV1(IDENTITY.scope_id)

    def __call__(self):
        return self.view

    def revoke(self, source):
        self.view = replace(self.view, epoch=self.view.epoch + 1,
                            revoked_source_digests=tuple(sorted(set(self.view.revoked_source_digests) | {source})))


class WireMutation:
    """Test peer that modifies actual bytes crossing a real local pipe."""
    def __init__(self, connection, *, send=None, receive=None):
        self.connection, self.send, self.receive = connection, send, receive

    def send_bytes(self, data):
        message = ProcessMessageV1.decode(data)
        self.connection.send_bytes(self.send(message).encode() if self.send else data)

    def recv_bytes(self, limit):
        data = self.connection.recv_bytes(limit)
        message = ProcessMessageV1.decode(data)
        return self.receive(message).encode() if self.receive else data

    def close(self):
        self.connection.close()


class CellProcessInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the real trained two-specialist fixture; no fake inference path.
        router_fixture.CellRouterTrainingTests.setUpClass()
        cls.storage = tempfile.TemporaryDirectory()
        cls.root = Path(cls.storage.name)
        fixture = router_fixture.CellRouterTrainingTests
        cls.budget = EvolutionBudgetV1()
        cls.parent = bootstrap_snapshot(fixture.cells, fixture.router,
            {"train": fixture.train.source_group_ids, "calibration": fixture.cal.source_group_ids,
             "future": fixture.holdouts["future"].source_group_ids}, cls.root / "parent", cls.budget, Withdrawals())
        cls.retired = retire_snapshot(cls.parent, "b", cls.root / "retired", cls.budget, Withdrawals())
        cls.bundle = cohort("process-evaluation").bundle

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()
        router_fixture.CellRouterTrainingTests.tearDownClass()

    def setUp(self):
        self.withdrawals = Withdrawals()
        self.owner = SnapshotProcessOwnerV1(self.parent, self.withdrawals)

    def pool(self, workers=1):
        pool = SnapshotWorkerPoolV1(self.owner, worker_count=workers)
        self.addCleanup(pool.close)
        return pool

    def mutate(self, pool, **kwargs):
        process, connection, counters = pool._workers[0]
        pool._workers[0] = (process, WireMutation(connection, **kwargs), counters)

    def head_calls(self, pool):
        return sum(h["example_calls"] for worker in pool.counts() for h in worker["heads"].values())

    def test_one_two_workers_reload_real_npz_and_match_reference_exactly(self):
        reference = self.parent.predict_task(self.bundle, self.withdrawals)
        for workers in (1, 2):
            with self.subTest(workers=workers), self.pool(workers) as pool:
                with patch.object(self.parent.cells[0].head, "predict_task", side_effect=AssertionError("owner Head ran")):
                    output = pool.predict_task(self.bundle)
                    second = pool.predict_task(self.bundle)
                self.assertTrue(torch.equal(output["task_probabilities"], reference["task_probabilities"]))
                self.assertTrue(torch.equal(second["task_probabilities"], output["task_probabilities"]))
                self.assertEqual(output["routes"], reference["routes"])
                self.assertEqual(output["head_example_calls"], 32)
                self.assertEqual(output["router_forward_calls"], 1)
                self.assertEqual(self.head_calls(pool), 64)
                self.assertEqual(sum(c["module_forwards"] for c in output["controller_head_counts"]), 2)
                self.assertTrue(all(w["pid"] != os.getpid() for w in pool.counts()))
                self.assertEqual(len({w["pid"] for w in pool.counts()}), workers)
                self.assertTrue(all(w["router_forwards"] == 0 for w in pool.counts()))
                receipt = pool.transport_receipt()
                self.assertEqual(receipt["sent_payload_bytes"], sum(e["sent_bytes"] for e in receipt["events"]))
                self.assertEqual(receipt["received_payload_bytes"], sum(e["received_bytes"] for e in receipt["events"]))
                self.assertEqual(receipt["sent_frames"], workers + 4)

    def test_withdrawn_ancestor_and_query_are_rejected_without_head_execution(self):
        for source in (self.parent.report["source_closure"][0], self.bundle.source_record_digests[0]):
            with self.subTest(source=source):
                self.withdrawals = Withdrawals()
                self.owner = SnapshotProcessOwnerV1(self.parent, self.withdrawals)
                pool = self.pool()
                self.withdrawals.revoke(source)
                with self.assertRaises((EvolutionError, ProcessInferenceError)):
                    pool.predict_task(self.bundle)
                self.assertEqual(self.head_calls(pool), 0)
                with self.assertRaises(ProcessInferenceError):
                    pool.predict_task(self.bundle)

    def test_lifetime_limit_closes_pool_before_router_or_head_execution(self):
        for workers in (1, 2):
            limit = 1 + (2 // workers)  # Load plus one complete two-Cell dispatch.
            with self.subTest(workers=workers), SnapshotWorkerPoolV1(
                    self.owner, worker_count=workers, max_requests_per_worker=limit) as pool:
                output = pool.predict_task(self.bundle)
                self.assertEqual(output["head_example_calls"], 32)
                before, receipt = pool.counts(), pool.transport_receipt()
                self.assertEqual(receipt["requests_issued_per_worker"], [limit] * workers)
                with patch.object(self.parent.router._net, "forward",
                                  side_effect=AssertionError("exhausted pool ran Router")):
                    with self.assertRaisesRegex(ProcessInferenceError, "limit.*before routing"):
                        pool.predict_task(self.bundle)
                self.assertEqual(pool.counts(), before)
                self.assertEqual(pool.transport_receipt(), receipt)
                self.assertTrue(pool._closed)
                self.assertTrue(all(not worker[0].is_alive() for worker in pool._workers))
                self.assertLessEqual(len(receipt["events"]), workers * limit)
                with self.assertRaises(ProcessInferenceError):
                    pool.predict_task(self.bundle)
        with SnapshotWorkerPoolV1(self.owner, max_requests_per_worker=1) as pool:
            with self.assertRaisesRegex(ProcessInferenceError, "before routing"):
                pool.predict_task(self.bundle)
            self.assertEqual(self.head_calls(pool), 0)
        for value in (0, 1025, True, 2.0):
            with self.subTest(invalid_limit=value), self.assertRaises(ProcessInferenceError):
                SnapshotWorkerPoolV1(self.owner, max_requests_per_worker=value)

    def test_revoke_after_worker_execution_discards_result_and_latches_frontier(self):
        pool = self.pool()
        original = pool._exchange
        def exchange(requests):
            result = original(requests)
            self.withdrawals.revoke(self.parent.report["source_closure"][0])
            return result
        with patch.object(pool, "_exchange", side_effect=exchange), self.assertRaises(EvolutionError):
            pool.predict_task(self.bundle)
        self.assertEqual(self.head_calls(pool), 32)
        self.withdrawals.view = WithdrawalViewV1(IDENTITY.scope_id)
        with self.assertRaisesRegex(EvolutionError, "frontier"):
            SnapshotWorkerPoolV1(self.owner)

    def test_generation_change_after_execution_discards_old_result_no_fallback(self):
        pool = self.pool()
        original = pool._exchange
        def exchange(requests):
            result = original(requests)
            self.owner.commit(self.retired, expected_parent_manifest_sha256=self.parent.manifest_sha256)
            return result
        with patch.object(pool, "_exchange", side_effect=exchange), self.assertRaisesRegex(ProcessInferenceError, "generation"):
            pool.predict_task(self.bundle)
        self.assertEqual(self.owner.current.generation, 2)
        self.assertEqual(self.head_calls(pool), 32)
        with self.assertRaisesRegex(ProcessInferenceError, "closed"):
            pool.predict_task(self.bundle)
        with self.pool(2) as replacement:
            result = replacement.predict_task(self.bundle)
        expected = self.retired.predict_task(self.bundle, self.withdrawals)
        self.assertTrue(torch.equal(result["task_probabilities"], expected["task_probabilities"]))
        self.assertEqual(result["router_forward_calls"], 0)
        self.assertTrue(all(r["actual_calls"] == ["a"] for r in result["routes"]))

    def test_late_withdrawal_rejects_snapshot_commit_without_adopting_successor(self):
        predecessor = self.owner.current
        original_commit = self.owner._owner.commit

        def withdraw_after_cas(candidate, *, expected_parent_manifest_sha256):
            original_commit(candidate, expected_parent_manifest_sha256=expected_parent_manifest_sha256)
            self.withdrawals.revoke(predecessor.report["source_closure"][0])

        # The first checks and the internal CAS succeed; the independent
        # withdrawal view advances before post-admission verification.
        with patch.object(self.owner._owner, "commit", side_effect=withdraw_after_cas):
            with self.assertRaisesRegex(EvolutionError, "withdrawn"):
                self.owner.commit(self.retired,
                    expected_parent_manifest_sha256=predecessor.manifest_sha256)
        self.assertIs(self.owner.current, predecessor)
        self.assertEqual(self.owner.current.generation, 1)

        # Neither predecessor nor successor becomes usable on a revoked
        # source; the observed frontier is not rolled back with the pointer.
        with self.assertRaises(EvolutionError):
            self.owner.capture()
        self.withdrawals.view = WithdrawalViewV1(IDENTITY.scope_id)
        with self.assertRaisesRegex(EvolutionError, "frontier"):
            self.owner.capture()
        self.assertIs(self.owner.current, predecessor)

    def test_wrong_feature_scope_is_rejected_before_any_worker_forward(self):
        pool = self.pool()
        bad = cohort("different-scope", identity=replace(IDENTITY, scope_id="another-owner")).bundle
        with self.assertRaises(FeatureBundleError):
            pool.predict_task(bad)
        self.assertEqual(self.head_calls(pool), 0)

    def test_mutated_feature_storage_after_dispatch_is_not_published(self):
        bundle = cohort("mutated-during-dispatch").bundle
        pool = self.pool()
        original = pool._exchange
        def exchange(requests):
            result = original(requests)
            bundle._tensors["global_features"][0, 0] += 1
            return result
        with patch.object(pool, "_exchange", side_effect=exchange), self.assertRaises(FeatureBundleError):
            pool.predict_task(bundle)
        self.assertEqual(self.head_calls(pool), 32)

    def test_lowered_budget_with_no_candidate_executes_no_head(self):
        pool = self.pool()
        with self.assertRaisesRegex(RouterTrainingError, "no legal"):
            pool.predict_task(self.bundle, budget_units=0.5)
        self.assertEqual(self.head_calls(pool), 0)

    def test_corrupted_features_and_reordered_request_fail_before_execution(self):
        def corrupt(message):
            payload = json.loads(json.dumps(message.payload))
            payload["features"]["bundle_sha256"] = "f" * 64
            return replace(message, payload=payload)
        def reorder(message):
            sequence = message.sequence + 1
            return replace(message, sequence=sequence, request_id=message.request_id.rsplit(":", 1)[0] + f":{sequence}")
        for mutation in (corrupt, reorder):
            with self.subTest(mutation=mutation.__name__):
                pool = self.pool()
                self.mutate(pool, send=mutation)
                with self.assertRaises(ProcessInferenceError):
                    pool.predict_task(self.bundle)
                self.assertEqual(self.head_calls(pool), 0)

    def test_replayed_response_and_worker_supplied_digest_cannot_replace_owner_pin(self):
        def replay(message):
            return replace(message, request_id=message.request_id.rsplit(":", 1)[0] + ":0", sequence=0)
        def foreign_pin(message):
            return replace(message, pins=replace(message.pins, snapshot_sha256="f" * 64))
        def feature_pin(message):
            return replace(message, payload={**message.payload, "request_payload_sha256": "e" * 64})
        for mutation in (replay, foreign_pin, feature_pin):
            with self.subTest(mutation=mutation.__name__):
                pool = self.pool()
                self.mutate(pool, receive=mutation)
                with self.assertRaises(ProcessInferenceError):
                    pool.predict_task(self.bundle)
                self.assertGreater(self.head_calls(pool), 0)
                with self.assertRaises(ProcessInferenceError):
                    pool.predict_task(self.bundle)

    def test_real_worker_crash_is_rejected(self):
        pool = self.pool(2)
        pool._workers[0][0].terminate()
        pool._workers[0][0].join(2)
        with self.assertRaises(ProcessInferenceError):
            pool.predict_task(self.bundle)
        self.assertTrue(pool._closed)

    @unittest.skipUnless(hasattr(signal, "SIGSTOP"), "real process pause requires POSIX signals")
    def test_real_worker_timeout_is_bounded_and_pool_is_not_reused(self):
        pool = self.pool()
        pool._timeout = 0.1
        os.kill(pool._workers[0][0].pid, signal.SIGSTOP)
        started = time.monotonic()
        with self.assertRaises(ProcessInferenceError):
            pool.predict_task(self.bundle)
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(pool._workers[0][0].is_alive())
        with self.assertRaises(ProcessInferenceError):
            pool.predict_task(self.bundle)

    def test_worker_reloads_exact_bytes_instead_of_inheriting_owner_parameters(self):
        directory = self.root / "corrupt-copy"
        shutil.copytree(self.parent.directory, directory)
        loaded = load_snapshot(directory, expected_manifest_sha256=self.parent.manifest_sha256,
                               budget=self.budget, withdrawal_provider=self.withdrawals)
        owner = SnapshotProcessOwnerV1(loaded, self.withdrawals)
        path = directory / "head-0" / "weights.npz"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaises(ProcessInferenceError):
            SnapshotWorkerPoolV1(owner)

    def test_bounded_codec_and_all_identity_fields_are_enforced(self):
        pins = snapshot_pins(self.parent, self.withdrawals.view)
        request = ProcessMessageV1("infer", "a" * 32 + ":0:1", 1, 0, 1, pins, {})
        response = replace(request, kind="result")
        for identity_field, value in (("scope_id", "different"), ("purpose", "different"),
                                      ("generation", 2), ("encoder_sha256", "b" * 64)):
            changed = replace(pins, feature_identity={**pins.feature_identity, identity_field: value})
            with self.subTest(field=identity_field), self.assertRaises(ProcessInferenceError):
                match_response(replace(response, pins=changed), request, "result")
        for changed in (replace(response, pins=replace(pins, frontier_epoch=1)),
                        replace(response, worker_index=1), replace(response, generation=2)):
            with self.assertRaises(ProcessInferenceError):
                match_response(changed, request, "result")
        with self.assertRaises(ProcessInferenceError):
            replace(request, payload={"excess": "x" * MAX_WIRE_BYTES}).encode()
        for malformed in (b"{\"schema\":1,\"schema\":2}", b"[1]", b"x" * (MAX_WIRE_BYTES + 1)):
            with self.assertRaises(ProcessInferenceError):
                ProcessMessageV1.decode(malformed)
        wire = feature_payload(self.bundle)
        restored = read_features(wire, IDENTITY)
        self.assertEqual(restored.manifest(), self.bundle.manifest())


if __name__ == "__main__":
    unittest.main()
