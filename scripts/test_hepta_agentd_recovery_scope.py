"""Exercise the actual recovery-step shell against the selected source test inventory.

This checks selector wiring and fail-closed shell behavior, not Rust execution.
The hosted nextest invocations remain the executable qualification boundary.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-gap-agentd-process.yml"
GROUPS = {
    "production_writer::": (
        "codex-rs/hepta-memory/src/production_writer.rs",
        {
            "restart_reopens_exact_bound_lease_and_replays_queue",
            "crash_after_target_send_reopens_as_indeterminate_and_cannot_redispatch",
            "active_lease_cannot_reopen_under_a_different_grant_with_same_token",
            "final_use_is_consumed_at_target_entry_and_binding_mismatch_never_calls_target",
            "recovery_does_not_release_production_lease_with_peer_pending",
        },
    ),
    "production_cognitive_source_target::tests::": (
        "codex-rs/hepta-memory/src/production_cognitive_source_target_tests.rs",
        {
            "destination_recomputes_full_semantics_and_deduplicates_exact_replay",
            "predecessor_mismatch_is_deterministic_not_applied_inside_destination_transaction",
            "full_durable_final_use_slice_reconciles_lost_ack_without_redispatch",
        },
    ),
}


class RecoveryScopeTests(unittest.TestCase):
    def inventory(self):
        inventory = {}
        for scope, (path, contracts) in GROUPS.items():
            source = (ROOT / path).read_text()
            names = set(
                re.findall(
                    r"#\[(?:tokio::)?test\]\s*(?:async\s+)?fn\s+(\w+)\s*\(",
                    source,
                )
            )
            self.assertTrue(contracts <= names, sorted(contracts - names))
            inventory["test(" + scope + ")"] = len(names)
        return inventory

    def execute(self, empty_selector=""):
        text = WORKFLOW.read_text()
        step = text.split(
            "      - name: Exercise actual optional retirement and durable destination recovery\n",
            1,
        )[1].split("      - name:", 1)[0]
        shell = "\n".join(
            line[10:] for line in step.split("        run: |\n", 1)[1].splitlines()
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "just"
            binary.write_text(
                """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with pathlib.Path(os.environ['CALLS']).open('a') as handle:
    handle.write(json.dumps(args) + '\\n')
if 'codex-hepta-memory' in args:
    selector = args[args.index('-E') + 1] if '-E' in args else ''
    count = json.loads(os.environ['INVENTORY']).get(selector, 0)
    if selector == os.environ['EMPTY_SELECTOR']:
        count = 0
    if not count:
        print('error: no tests to run', file=sys.stderr)
        raise SystemExit(4)
    print(f'Summary: {count} tests run: {count} passed')
"""
            )
            binary.chmod(0o755)
            calls = root / "calls.jsonl"
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(root) + os.pathsep + os.environ["PATH"],
                    "CALLS": str(calls),
                    "INVENTORY": json.dumps(self.inventory()),
                    "EMPTY_SELECTOR": empty_selector,
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_recovery_step_selects_both_existing_contract_groups(self):
        result, calls = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        memory = [args for args in calls if "codex-hepta-memory" in args]
        self.assertEqual(
            [args[args.index("-E") + 1] for args in memory], list(self.inventory())
        )
        for args in memory:
            self.assertIn("--locked", args)
            self.assertIn("--lib", args)
            self.assertIn("--test-threads=1", args)
            self.assertNotIn("--no-tests", args)
        self.assertIn("optional_module_restart", calls[0])
        self.assertIn("retirement_recovery", calls[1])

    def test_each_missing_group_still_fails_the_step(self):
        for selector in self.inventory():
            with self.subTest(selector=selector):
                result, calls = self.execute(empty_selector=selector)
                self.assertEqual(result.returncode, 4)
                self.assertIn("error: no tests to run", result.stderr)
                self.assertIn("-E", calls[-1])
                self.assertEqual(calls[-1][calls[-1].index("-E") + 1], selector)


if __name__ == "__main__":
    unittest.main()
