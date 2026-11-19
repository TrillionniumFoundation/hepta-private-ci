import json
import multiprocessing
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import durability_lab as lab


def _hold_contender_at_initial_commit(root, barrier, results):
    """Pause two real processes after intent COMMIT, before either can claim.

    This exposes a stale ready-state read rather than testing an already-held
    claim. The wrapper changes scheduling only, not the production SQL.
    """
    original_connect = lab.connect

    class CommitBarrierConnection:
        def __init__(self, connection, is_workflow):
            self.connection = connection
            self.is_workflow = is_workflow
            self.first_commit = True

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, statement, *args):
            result = self.connection.execute(statement, *args)
            if self.is_workflow and statement == "COMMIT" and self.first_commit:
                self.first_commit = False
                barrier.wait(timeout=10)
            return result

    def connect(path):
        return CommitBarrierConnection(original_connect(path), path.name == "workflow.sqlite")

    lab.connect = connect
    try:
        results.put(lab.worker(root, "checkpoint_hold"))
    except Exception as error:
        results.put({"error": repr(error)})
        raise


class DurabilityMechanismTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, name):
        root = self.root / name
        lab.initialize(root)
        return root

    def test_every_crash_point_uses_actual_sigkill_and_resumes(self):
        for route in lab.ROUTES:
            for point in lab.CRASH_POINTS:
                with self.subTest(route=route, point=point):
                    root = self.case(route + point)
                    killed = lab.run_worker(root, route, point)
                    self.assertEqual(killed["exit_code"], -signal.SIGKILL)
                    before = lab.observe(root)
                    recovered = lab.run_worker(root, route)["events"][-1]
                    after = lab.observe(root)
                    if point == "intent_before_commit":
                        self.assertEqual(before["states"], [])
                        self.assertEqual(before["outbox_count"], 0)
                    if point == "effect_before_commit":
                        self.assertEqual(before["effect_count"], 0)
                        self.assertEqual(before["ledger_count"], 0)
                    if route == "checkpoint_hold" and point in (
                            "before_effect", "effect_before_commit", "after_effect"):
                        self.assertEqual(recovered["state"], "HOLD_UNKNOWN")
                        self.assertEqual(after["effect_count"], int(point == "after_effect"))
                    else:
                        expected = 2 if route == "checkpoint_retry" and point == "after_effect" else 1
                        self.assertEqual(after["effect_count"], expected)
                        self.assertEqual(recovered["state"], "done")
                    if route.startswith("outbox_"):
                        self.assertEqual(after["ledger_count"], 1)

    def test_revocation_between_preflight_and_effect_is_not_closed_by_preflight(self):
        for route in lab.ROUTES:
            with self.subTest(route=route):
                root = self.case(route)
                result = lab.rendezvous(root, [route], revoke_before_resume=True)[0]
                expected = 0 if route == "outbox_final_use" else 1
                self.assertEqual(lab.observe(root)["effect_count"], expected)
                self.assertEqual(result["state"], "denied" if not expected else "done")

    def test_concurrent_replay_is_deduped_by_sink_not_checkpoint(self):
        for route in ("checkpoint_retry", "outbox_dedupe", "outbox_preflight", "outbox_final_use"):
            with self.subTest(route=route):
                root = self.case(route)
                results = lab.rendezvous(root, [route, route])
                state = lab.observe(root)
                self.assertEqual(state["effect_attempts"], 2)
                self.assertEqual(state["effect_count"], 2 if route == "checkpoint_retry" else 1)
                self.assertTrue(all(result["state"] == "done" for result in results))

    def test_hold_claim_serializes_competing_dispatcher(self):
        root = self.case("hold-claim")
        # This lab targets Linux. Fork preserves the isolated scheduling wrapper
        # without adding a test-only protocol to the worker implementation.
        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [context.Process(target=_hold_contender_at_initial_commit,
                                     args=(root, barrier, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=15)
                self.assertFalse(process.is_alive(), "claim contender did not finish")
                self.assertEqual(process.exitcode, 0)
            observed_results = [results.get(timeout=1) for _ in processes]
            self.assertTrue(all(row.get("state") in ("done", "HOLD_UNKNOWN")
                                for row in observed_results), observed_results)
            self.assertTrue(any(row.get("state") == "done" for row in observed_results))
            observed = lab.observe(root)
            self.assertEqual(observed["effect_count"], 1)
            self.assertEqual(observed["effect_attempts"], 1)
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                if process.pid is not None:
                    process.join(timeout=5)
            results.close()
            results.join_thread()

    def test_same_id_changed_payload_rejected_at_sink(self):
        for route in ("outbox_dedupe", "outbox_preflight", "outbox_final_use"):
            with self.subTest(route=route):
                root = self.case(route)
                plan = json.loads((root / "plan.json").read_text())
                lab.effect(root, plan, route, None)
                plan["payload"] = "different effect"
                plan["digest"] = lab.digest(plan["payload"])
                with self.assertRaisesRegex(lab.Rejected, "idempotency key reused"):
                    lab.effect(root, plan, route, None)
                self.assertEqual(lab.observe(root)["effect_count"], 1)

    def test_false_payload_digest_rejected_even_on_cached_replay(self):
        root = self.case("tamper")
        plan = json.loads((root / "plan.json").read_text())
        lab.effect(root, plan, "outbox_final_use", None)
        plan["payload"] = "tampered bytes with old digest"
        with self.assertRaisesRegex(lab.Rejected, "payload digest mismatch"):
            lab.effect(root, plan, "outbox_final_use", None)
        self.assertEqual(lab.observe(root)["effect_count"], 1)

    def test_completed_effect_replay_after_revoke_creates_no_new_effect(self):
        root = self.case("replay")
        lab.run_worker(root, "outbox_final_use", "after_effect")
        lab.revoke(root)
        result = lab.run_worker(root, "outbox_final_use")["events"][-1]
        self.assertTrue(result["deduplicated"])
        self.assertEqual(result["state"], "done")
        self.assertEqual(lab.observe(root)["effect_count"], 1)

    def test_expired_proof_cannot_create_new_effect(self):
        root = self.case("expired")
        plan = json.loads((root / "plan.json").read_text())
        plan["deadline_ns"] = 0
        (root / "plan.json").write_text(json.dumps(plan))
        result = lab.run_worker(root, "outbox_final_use")["events"][-1]
        self.assertEqual(result["state"], "denied")
        self.assertEqual(lab.observe(root)["effect_count"], 0)

    def test_preflight_rejects_old_permission_but_cannot_retrieve_completed_receipt(self):
        root = self.case("preflight-replay")
        lab.run_worker(root, "outbox_preflight", "after_effect")
        lab.revoke(root)
        result = lab.run_worker(root, "outbox_preflight")["events"][-1]
        self.assertEqual(result["state"], "denied")
        self.assertEqual(lab.observe(root)["effect_count"], 1)

    def test_changed_epoch_denies_even_when_authority_still_enabled(self):
        root = self.case("epoch")
        with lab.connect(root / "effect.sqlite") as db:
            db.execute("UPDATE authority SET epoch=2")
        result = lab.run_worker(root, "outbox_final_use")["events"][-1]
        self.assertEqual(result["state"], "denied")
        self.assertEqual(lab.observe(root)["effect_count"], 0)

    def test_late_retry_after_dedupe_retention_loss_exposes_duplicate(self):
        root = self.case("retention")
        lab.run_worker(root, "outbox_final_use", "after_effect")
        with lab.connect(root / "effect.sqlite") as db:
            db.execute("DELETE FROM dedupe")
        lab.run_worker(root, "outbox_final_use")
        self.assertEqual(lab.observe(root)["effect_count"], 2)

    def test_local_plan_identity_change_cannot_silently_resume(self):
        root = self.case("plan")
        lab.run_worker(root, "outbox_final_use", "after_intent")
        plan = json.loads((root / "plan.json").read_text())
        plan["payload"] = "mutated plan"
        plan["digest"] = lab.digest(plan["payload"])
        (root / "plan.json").write_text(json.dumps(plan))
        with self.assertRaisesRegex(lab.Rejected, "local operation payload changed"):
            lab.worker(root, "outbox_final_use")
        self.assertEqual(lab.observe(root)["effect_count"], 0)

    def test_run_harness_rejects_missed_fault_and_unexpected_crash(self):
        for requested, status, event in (
                ("after_effect", 0, {"state": "done"}),
                (None, -signal.SIGKILL, {"fault": "after_effect", "signal": "SIGKILL"}),
                ("after_effect", -signal.SIGKILL, {"fault": "before_effect", "signal": "SIGKILL"})):
            with self.subTest(requested=requested, status=status):
                result = subprocess.CompletedProcess([], status, json.dumps(event), "")
                with patch.object(lab.subprocess, "run", return_value=result):
                    with self.assertRaises(RuntimeError):
                        lab.run_worker(self.root, "checkpoint_retry", requested)


if __name__ == "__main__":
    unittest.main()
