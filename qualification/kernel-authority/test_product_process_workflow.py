from __future__ import annotations

import fnmatch
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kernel-authority-product-process-recovery.yml"


def event_paths(text: str, event: str) -> list[str]:
    match = re.search(
        r"^  " + event + r":\n(.*?)(?=^  [a-z_]+:|^permissions:)",
        text,
        re.M | re.S,
    )
    if not match:
        return []
    return re.findall(r"^      - '([^']+)'$", match.group(1), re.M)


class ProductProcessWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_all_product_process_dependencies_trigger_push_and_pull_request(self) -> None:
        critical = (
            "codex-rs/hepta-contracts/src/authority_runtime_clock.rs",
            "codex-rs/hepta-contracts/src/final_use.rs",
            "codex-rs/hepta-contracts/src/final_use_store.rs",
            "codex-rs/hepta-fleet/src/authority_port.rs",
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "codex-rs/hepta-agentd/src/automation_effect_host_tests.rs",
            "codex-rs/hepta-agentd/src/authority_feed_clock.rs",
            "codex-rs/hepta-agentd/src/authority_effect_tasks.rs",
            "codex-rs/hepta-agentd/src/runtime.rs",
            "codex-rs/hepta-agentd/tests/authority_effect_process_restart.rs",
            "codex-rs/hepta-automation/src/authorized_effect.rs",
            "codex-rs/model-provider/src/lib.rs",
            "codex-rs/Cargo.lock",
            "qualification/kernel-authority/product_process_recovery.py",
            "qualification/kernel-authority/test_product_process_recovery.py",
            "qualification/kernel-authority/test_product_process_workflow.py",
        )
        for event in ("push", "pull_request"):
            paths = event_paths(self.workflow, event)
            self.assertTrue(paths, event)
            for path in critical:
                self.assertTrue(
                    any(fnmatch.fnmatchcase(path, pattern) for pattern in paths),
                    (event, path),
                )

    def test_workflow_is_read_only_and_candidate_bound(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertNotIn("git push", self.workflow)
        self.assertEqual(self.workflow.count("persist-credentials: false"), 2)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn('test "$source" = "$EVENT_SOURCE"', self.workflow)
        self.assertIn('test -z "$(git status --porcelain)"', self.workflow)

    def test_exact_head_and_synthetic_merge_are_both_total_gate_requirements(self) -> None:
        self.assertIn("mode: [exact-head, synthetic-merge]", self.workflow)
        self.assertIn("needs: [identity, qualify]", self.workflow)
        self.assertIn('test "$QUALIFY_RESULT" = success', self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("if-no-files-found: error", self.workflow)

    def test_parser_and_exact_target_are_checked_before_execution(self) -> None:
        workflow_test = self.workflow.rindex(
            "python3 -B qualification/kernel-authority/test_product_process_workflow.py"
        )
        parser_test = self.workflow.rindex(
            "python3 -B qualification/kernel-authority/test_product_process_recovery.py"
        )
        fmt = self.workflow.index("cargo fmt --check -p codex-hepta-agentd")
        clippy = self.workflow.index("--test authority_effect_process_restart -- -D warnings")
        execution = self.workflow.rindex(
            "python3 -B qualification/kernel-authority/product_process_recovery.py"
        )
        self.assertLess(workflow_test, parser_test)
        self.assertLess(parser_test, fmt)
        self.assertLess(fmt, clippy)
        self.assertLess(clippy, execution)
        self.assertIn("python3 -B", self.workflow)
        self.assertIn(
            '--identity "$RUNNER_TEMP/kernel-authority-product-process/identity.json"',
            self.workflow,
        )

    def test_no_queued_or_partial_run_can_satisfy_the_gate(self) -> None:
        self.assertIn("Require exact-head and synthetic-merge recovery", self.workflow)
        self.assertIn('test "$IDENTITY_RESULT" = success', self.workflow)
        self.assertIn('test "$QUALIFY_RESULT" = success', self.workflow)
        self.assertIn('test "${#SOURCE}" -eq 40', self.workflow)
        self.assertIn('test "${#SOURCE_TREE}" -eq 40', self.workflow)
        self.assertIn('test "${#BASE}" -eq 40', self.workflow)


if __name__ == "__main__":
    unittest.main()
