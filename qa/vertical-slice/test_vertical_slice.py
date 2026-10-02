from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("vertical_reference", Path(__file__).with_name("reference.py"))
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Phase = MODULE.Phase
RuntimeSlice = MODULE.RuntimeSlice


class VerticalSliceTests(unittest.TestCase):
    def ready(self) -> RuntimeSlice:
        runtime = RuntimeSlice(7)
        runtime.start(7)
        runtime.prove_identity(7, exact_identity=True, fenced=False)
        runtime.mark_app_server_ready(7, home_matches=True)
        return runtime

    def test_success_path_requires_independent_terminal_observation(self) -> None:
        runtime = self.ready()
        runtime.authorize(7, witness_valid=True)
        runtime.dispatch(7)
        self.assertEqual(runtime.phase, Phase.DISPATCHED)
        self.assertIsNone(runtime.outcome)
        runtime.observe(7, "applied")
        runtime.drain(7)
        runtime.stop(7, outstanding_operations=0)
        self.assertEqual(runtime.phase, Phase.STOPPED)

    def test_ack_loss_stays_open_until_reconciliation(self) -> None:
        runtime = self.ready()
        runtime.authorize(7, witness_valid=True)
        runtime.dispatch(7)
        runtime.lose_ack(7)
        self.assertEqual(runtime.phase, Phase.INDETERMINATE)
        runtime.observe(7, "not_applied")
        self.assertEqual(runtime.outcome, "not_applied")

    def test_generation_drift_fails_closed(self) -> None:
        runtime = RuntimeSlice(7)
        runtime.start(7)
        with self.assertRaisesRegex(ValueError, "generation"):
            runtime.prove_identity(8, exact_identity=True, fenced=False)
        self.assertEqual(runtime.phase, Phase.FAILED)

    def test_identity_or_home_mismatch_never_becomes_ready(self) -> None:
        runtime = RuntimeSlice(7)
        runtime.start(7)
        runtime.prove_identity(7, exact_identity=False, fenced=False)
        self.assertEqual(runtime.phase, Phase.FAILED)
        runtime = RuntimeSlice(7)
        runtime.start(7)
        runtime.prove_identity(7, exact_identity=True, fenced=False)
        runtime.mark_app_server_ready(7, home_matches=False)
        self.assertEqual(runtime.phase, Phase.FAILED)

    def test_stop_rejects_unreconciled_operations(self) -> None:
        runtime = self.ready()
        runtime.drain(7)
        with self.assertRaisesRegex(ValueError, "outstanding"):
            runtime.stop(7, outstanding_operations=1)

    def test_product_source_has_exact_readiness_and_task_fail_closed_markers(self) -> None:
        agent_runtime = (ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(encoding="utf-8")
        unix_driver = (ROOT / "codex-rs/hepta-supervisor/src/unix.rs").read_text(encoding="utf-8")
        self.assertIn("probe_app_server", agent_runtime)
        self.assertIn("mark_app_server_ready", agent_runtime)
        # RuntimeTasks owns cleanup now. Check the composition edge and its
        # cancel/abort/join implementation, not the removed helper's spelling.
        # Behavioral coverage lives in runtime_tasks_tests.rs (listener failure,
        # required-task exit, cooperative drain and forced-abort cleanup).
        task_host = (ROOT / "codex-rs/hepta-agentd/src/runtime_tasks.rs").read_text(encoding="utf-8")
        self.assertIn("RuntimeTasks::new(cancellation.clone(), TASK_SHUTDOWN_GRACE)", agent_runtime)
        self.assertRegex(agent_runtime, r"tasks\.shutdown\(\)\.await;")
        self.assertRegex(agent_runtime, r"\.run_until\(async move \{\s*shutdown_signal\(\)\.await\?;")
        self.assertIn("drain_runtime(state).await", agent_runtime)
        run_until = task_host.split("pub async fn run_until", 1)[1].split("pub async fn shutdown", 1)[0]
        self.assertIn("self.observe_next()", run_until)
        self.assertIn("self.shutdown().await", run_until)
        shutdown = task_host.split("pub async fn shutdown", 1)[1].split("fn lifecycle_warning", 1)[0]
        self.assertIn("self.cancellation.cancel()", shutdown)
        self.assertIn("timeout(grace", shutdown)
        self.assertRegex(shutdown, r"self\.tasks\.abort_all\(\);\s*while let Some\(completion\) = self\.tasks\.join_next_with_id\(\)\.await")
        self.assertIn("exact_identity", unix_driver)
        self.assertIn("readiness_matches", unix_driver)
        self.assertIn("fenced", unix_driver)


if __name__ == "__main__":
    unittest.main()
