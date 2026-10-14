"""Strict local journal durability/CAS/rollback tests; no product authority."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import multiprocessing as mp
from threading import Event
import json
from pathlib import Path
import tempfile
import unittest

from amcn_core import Refused, digest
from amcn_quarantine_ledger import ShadowQuarantineLedger, ZERO_SHA
import test_amcn_revocation as fixture


def _process_stale_cas(directory, artifacts, sources, head, start, result):
    from amcn_core import Refused
    from amcn_quarantine_ledger import ShadowQuarantineLedger
    import test_amcn_revocation as f
    start.wait(2)
    try:
        receipt = ShadowQuarantineLedger(directory).apply(
            artifacts, sources, scope="tenant:lab", generation="g1",
            externally_pinned_frontier_sha256=f.pinned(sources),
            expected_previous_sha256=head,
        )
        result.put(bool(receipt["metrics"]["recorded"]))
    except Refused:
        result.put(False)


class DurableShadowLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger"
        self.owner = ShadowQuarantineLedger(self.path)
        self.artifacts, self.sources = fixture.ParameterLineageTests().network()
        self.args = dict(scope="tenant:lab", generation="g1")

    def first(self):
        return self.owner.apply(
            self.artifacts, self.sources,
            externally_pinned_frontier_sha256=fixture.pinned(self.sources),
            expected_previous_sha256=ZERO_SHA, initialize=True, **self.args,
        )["metrics"]["journal_head_sha256"]

    def preflight(self, selected, head, sources=None):
        current = sources if sources is not None else self.sources
        return self.owner.preflight(
            selected, self.artifacts, current,
            externally_pinned_frontier_sha256=fixture.pinned(current),
            expected_journal_head_sha256=head, **self.args,
        )

    def test_creation_reopen_and_shadow_only(self):
        head = self.first()
        reopened = ShadowQuarantineLedger(self.path)
        packet = reopened.preflight(
            self.artifacts[0].artifact_id, self.artifacts, self.sources,
            expected_journal_head_sha256=head,
            externally_pinned_frontier_sha256=fixture.pinned(self.sources), **self.args,
        )
        self.assertTrue(packet["metrics"]["eligible_for_local_shadow_replay"])
        self.assertFalse(packet["metrics"]["granted_runtime_ability"])
        self.assertFalse(packet["production_accepted"])
        with self.assertRaises(Refused):
            self.preflight(digest("unknown"), head)

    def test_revocation_propagates_and_never_revives(self):
        head = self.first()
        revoked = [replace(self.sources[0], revoked=True), self.sources[1]]
        next_head = self.owner.apply(
            self.artifacts, revoked, externally_pinned_frontier_sha256=fixture.pinned(revoked),
            expected_previous_sha256=head, **self.args,
        )["metrics"]["journal_head_sha256"]
        for index in (0, 1, 3):
            with self.assertRaises(Refused):
                self.preflight(self.artifacts[index].artifact_id, next_head, revoked)
        self.assertFalse(self.preflight(self.artifacts[2].artifact_id,
                                       next_head, revoked)["production_accepted"])
        restored_head = self.owner.apply(
            self.artifacts, self.sources,
            externally_pinned_frontier_sha256=fixture.pinned(self.sources),
            expected_previous_sha256=next_head, **self.args,
        )["metrics"]["journal_head_sha256"]
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[0].artifact_id, restored_head)
        self.assertTrue(self.preflight(self.artifacts[2].artifact_id,
                                       restored_head)["metrics"]["eligible_for_local_shadow_replay"])

    def test_change_without_commit_refuses_and_stale_head_fails(self):
        first = self.first()
        changes = [replace(self.sources[0], content_sha256=digest("rewritten")), self.sources[1]]
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[0].artifact_id, first, changes)
        second = self.owner.apply(self.artifacts, changes,
                                  externally_pinned_frontier_sha256=fixture.pinned(changes),
                                  expected_previous_sha256=first, **self.args)["metrics"]["journal_head_sha256"]
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, first)
        with self.assertRaises(Refused):
            self.owner.apply(self.artifacts, self.sources,
                             externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                             expected_previous_sha256=first, **self.args)
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[0].artifact_id, second, changes)

    def test_crash_before_link_requires_explicit_latest_source_recovery(self):
        first = self.first()
        attempted = self.owner.apply(self.artifacts, self.sources,
                                     externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                     expected_previous_sha256=first,
                                     crash_at="prepared", **self.args)
        self.assertFalse(attempted["metrics"]["recorded"])
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, first)
        revised = [replace(self.sources[0], revoked=True), self.sources[1]]
        recovery = self.owner.recover(self.artifacts, revised,
                                      externally_pinned_frontier_sha256=fixture.pinned(revised),
                                      expected_previous_sha256=first, **self.args)
        self.assertTrue(recovery["metrics"]["recovery_committed"])
        self.assertEqual(recovery["metrics"]["discarded_orphan_count"], 1)
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[0].artifact_id,
                           recovery["metrics"]["journal_head_sha256"], revised)
        self.preflight(self.artifacts[2].artifact_id,
                       recovery["metrics"]["journal_head_sha256"], revised)

    def test_crash_after_link_requires_new_chain_event(self):
        first = self.first()
        result = self.owner.apply(self.artifacts, self.sources,
                                  externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                  expected_previous_sha256=first,
                                  crash_at="linked", **self.args)
        self.assertIsNone(result["metrics"]["journal_head_sha256"])
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, first)
        events = sorted(self.owner.events.glob("*.json"))
        self.assertEqual(len(events), 2)
        published = events[-1].stem.split("-", 1)[1]
        recovery = self.owner.recover(self.artifacts, self.sources,
                                      externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                      expected_previous_sha256=published, **self.args)
        self.assertNotEqual(recovery["metrics"]["journal_head_sha256"], published)
        self.preflight(self.artifacts[2].artifact_id,
                       recovery["metrics"]["journal_head_sha256"])

    def test_corruption_or_rollback_of_event_bytes_cannot_be_ignored(self):
        first = self.first()
        event = next(self.owner.events.glob("*.json"))
        event.write_bytes(event.read_bytes().replace(b'"production_accepted":false',
                                                     b'"production_accepted":true'))
        with self.assertRaises((Refused, ValueError)):
            self.preflight(self.artifacts[2].artifact_id, first)

    def test_delete_last_event_denied_by_external_head_pin(self):
        first = self.first()
        second = self.owner.apply(self.artifacts, self.sources,
                                  externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                  expected_previous_sha256=first, **self.args)["metrics"]["journal_head_sha256"]
        sorted(self.owner.events.glob("*.json"))[-1].unlink()
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, second)

    def test_missing_middle_event_gap_is_not_recoverable_by_relabeling(self):
        first = self.first()
        second = self.owner.apply(self.artifacts, self.sources,
                                  externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                  expected_previous_sha256=first, **self.args)["metrics"]["journal_head_sha256"]
        third = self.owner.apply(self.artifacts, self.sources,
                                 externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                 expected_previous_sha256=second, **self.args)["metrics"]["journal_head_sha256"]
        sorted(self.owner.events.glob("*.json"))[1].unlink()
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, third)

    def test_parallel_cas_allows_exactly_one_writer(self):
        head = self.first()
        def issue(i):
            try:
                result = self.owner.apply(self.artifacts, self.sources,
                                          externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                          expected_previous_sha256=head, **self.args)
                return bool(result["metrics"]["recorded"])
            except Refused:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(issue, (1, 2))), [False, True])

    def test_independent_processes_observe_same_host_cas(self):
        head = self.first()
        ctx = mp.get_context("spawn")
        start, results = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_process_stale_cas,
                                 args=(self.path, self.artifacts, self.sources,
                                       head, start, results)) for _ in range(2)]
        for p in processes:
            p.start()
        try:
            start.set()
            decisions = [results.get(timeout=5) for _ in processes]
            for p in processes:
                p.join(timeout=5)
            self.assertEqual(sorted(decisions), [False, True])
            self.assertTrue(all(p.exitcode == 0 for p in processes))
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()
                    p.join()
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, head)

    def test_symlinked_journal_event_or_pending_file_never_replayed(self):
        head = self.first()
        first_event = next(self.owner.events.glob("*.json"))
        external = Path(self.temp.name) / "untrusted.json"
        external.write_bytes(first_event.read_bytes())
        first_event.unlink()
        first_event.symlink_to(external)
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, head)

    def test_owner_lock_remains_held_around_local_shadow_consumer(self):
        first = self.first()
        started, committed = Event(), Event()
        def mutation():
            started.set()
            record = self.owner.apply(
                self.artifacts, self.sources,
                externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                expected_previous_sha256=first, **self.args,
            )
            committed.set()
            return record["metrics"]["journal_head_sha256"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.owner.hold_shadow_candidate(
                self.artifacts[2].artifact_id, self.artifacts, self.sources,
                expected_journal_head_sha256=first,
                externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                **self.args,
            ) as receipt:
                future = pool.submit(mutation)
                self.assertTrue(started.wait(1.0))
                self.assertFalse(committed.wait(0.05))
                self.assertFalse(receipt["metrics"]["independent_source_owner_fenced"])
            newhead = future.result(timeout=2.0)
        with self.assertRaises(Refused):
            self.preflight(self.artifacts[2].artifact_id, first)
        self.preflight(self.artifacts[2].artifact_id, newhead)

    def test_cross_scope_manifest_substitution_fails_before_commit(self):
        first = self.first()
        with self.assertRaises(Refused):
            # Manifest constructor itself detects the tamper before any append.
            replace(self.artifacts[0], manifest_sha256=digest("tampered"))
        with self.assertRaises(Refused):
            self.owner.preflight(self.artifacts[0].artifact_id, self.artifacts,
                                 self.sources, expected_journal_head_sha256=first,
                                 externally_pinned_frontier_sha256=fixture.pinned(self.sources),
                                 scope="another", generation="g1")

    def test_fake_source_pin_and_missing_owner_do_not_fail_open(self):
        with self.assertRaises(Refused):
            self.owner.preflight(self.artifacts[0].artifact_id, self.artifacts,
                                 self.sources, expected_journal_head_sha256=ZERO_SHA,
                                 externally_pinned_frontier_sha256=fixture.pinned(self.sources), **self.args)
        first = self.first()
        with self.assertRaises(Refused):
            self.owner.apply(self.artifacts, self.sources,
                             externally_pinned_frontier_sha256=digest("forged"),
                             expected_previous_sha256=first, **self.args)
        with self.assertRaises(Refused):
            self.owner.preflight(self.artifacts[0].artifact_id, self.artifacts,
                                 self.sources, expected_journal_head_sha256=first,
                                 externally_pinned_frontier_sha256=None, **self.args)


if __name__ == "__main__":
    unittest.main()
