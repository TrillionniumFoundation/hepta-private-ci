from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DAEMON = ROOT / "codex-rs" / "hepta-supervisor" / "src" / "daemon.rs"


def section(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


class SupervisorLockBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DAEMON.read_text(encoding="utf-8")

    def test_roster_registry_io_precedes_owner_lock(self) -> None:
        body = section(
            self.source,
            "SupervisordMethod::Roster { limit } => {",
            "SupervisordMethod::Snapshot { agent_id }",
        )
        registry = body.index("registry.load()")
        owner_lock = body.index("state.supervisor.lock().await")
        self.assertLess(registry, owner_lock)
        self.assertIn("spawn_blocking", body)
        self.assertNotIn("status_from(\n                        &state.supervisor_epoch,\n                        &record,\n                        supervisor.snapshot", body)

    def test_snapshot_registry_io_is_outside_owner_lock(self) -> None:
        body = section(
            self.source,
            "async fn agent_status<D: ProcessDriver>",
            "fn agent_status_locked<D: ProcessDriver>",
        )
        registry = body.index("registry.load_agent")
        owner_lock = body.index("state.supervisor.lock().await")
        self.assertLess(registry, owner_lock)
        self.assertIn("spawn_blocking", body)
        self.assertNotIn("agent_status_locked(state", body)

    def test_mutation_path_keeps_exact_locked_revalidation(self) -> None:
        body = section(
            self.source,
            "async fn handle_mutation<D: ProcessDriver>",
            "enum PreparedMutation",
        )
        owner_lock = body.index("state.supervisor.lock().await")
        revalidation = body.index("agent_status_locked")
        self.assertLess(owner_lock, revalidation)
        self.assertIn("control_fence_matches", body)
        self.assertIn("set_control_revision", body)

    def test_release_resolution_remains_outside_owner_lock(self) -> None:
        self.assertIn("async fn resolve_release_outside_lock", self.source)
        self.assertIn("tokio::task::spawn_blocking", self.source)
        roster = section(
            self.source,
            "SupervisordMethod::Start { fence, release_id }",
            "SupervisordMethod::Drain { fence }",
        )
        self.assertIn("resolve_release_outside_lock", roster)


if __name__ == "__main__":
    unittest.main()
