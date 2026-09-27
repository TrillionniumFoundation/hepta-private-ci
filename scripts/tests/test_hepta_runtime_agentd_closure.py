from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "hepta_runtime_agentd_closure.py"
SPEC = importlib.util.spec_from_file_location("hepta_runtime_agentd_closure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeAgentdClosureTests(unittest.TestCase):
    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative, contract in MODULE.SOURCE_REQUIREMENTS.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            chunks: list[str] = []
            ordered = list(contract["ordered"])
            chunks.extend(ordered)
            chunks.extend(needle for needle in contract["required"] if needle not in ordered)
            path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
        return temporary

    def test_complete_fixture_passes(self) -> None:
        with self.fixture() as temporary:
            results = MODULE.verify_source_files(Path(temporary))
            self.assertEqual(len(results), len(MODULE.SOURCE_REQUIREMENTS))
            self.assertTrue(all(result["result"] == "success" for result in results))

    def test_missing_invariant_fails(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            relative = "codex-rs/hepta-agentd/src/runtime.rs"
            path = root / relative
            path.write_text("ProcessRuntimeCodexExecutorV1::cancel_installed_runs\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required invariant"):
                MODULE.verify_source_files(root)

    def test_legacy_global_operation_lock_fails(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            relative = "codex-rs/hepta-agentd/src/runtime_codex_executor.rs"
            path = root / relative
            path.write_text(path.read_text(encoding="utf-8") + "operation_lock: Mutex<()>\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden legacy invariant"):
                MODULE.verify_source_files(root)

    def test_effect_boundary_order_is_enforced(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            relative = "codex-rs/hepta-agentd/src/runtime_codex_executor_process_base.rs"
            path = root / relative
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "mark_dispatch_fenced(paths, manifest)?\nlet mut child = command.spawn()?",
                    "let mut child = command.spawn()?\nmark_dispatch_fenced(paths, manifest)?",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid invariant order"):
                MODULE.verify_source_files(root)

    def test_self_uds_rollback_is_forbidden(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            relative = "codex-rs/hepta-agentd/src/run_start_authority.rs"
            path = root / relative
            path.write_text(path.read_text(encoding="utf-8") + "AgentdClient::new\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden legacy invariant"):
                MODULE.verify_source_files(root)


if __name__ == "__main__":
    unittest.main()
