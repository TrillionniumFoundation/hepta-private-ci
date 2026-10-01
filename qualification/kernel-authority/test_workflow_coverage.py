"""Standard-library checks for security-critical workflow triggers and identity."""
import fnmatch
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/kernel-authority-production-closure.yml'


def event_paths(text, event):
    match = re.search(r'^  ' + event + r':\n(.*?)(?=^  [a-z_]+:|^permissions:)', text, re.M | re.S)
    if not match:
        return []
    return re.findall(r"^      - '([^']+)'$", match.group(1), re.M)


class WorkflowCoverageTests(unittest.TestCase):
    def test_lightweight_source_gates_cover_every_mapped_path_and_build_input(self):
        manifest = json.loads((ROOT / 'qualification/kernel-authority/convergence_manifest.json').read_text())
        critical = manifest['trackedSourcePaths'] + [
            'codex-rs/state/src/sqlite.rs',
            'codex-rs/hepta-supervisor/src/restart_state.rs',
            'codex-rs/hepta-bao-adapter/src/https_consumer.rs',
            'codex-rs/hepta-intelligence/src/canonical.rs',
            'codex-rs/app-server-client/src/remote.rs',
            'codex-rs/ext/hepta-prompt/src/lib.rs',
            'MODULE.bazel.lock',
            'defs.bzl',
            '.github/actions/hepta-synthetic-merge/action.yml',
        ]
        for name in ('kernel-authority-convergence.yml', 'kernel-authority-evidence-gate.yml'):
            text = (ROOT / '.github/workflows' / name).read_text()
            for event in ('push', 'pull_request'):
                patterns = event_paths(text, event)
                self.assertTrue(patterns, (name, event))
                for path in critical:
                    self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns),
                                    (name, event, path))

    def test_every_authority_and_changed_host_file_triggers_both_events(self):
        text = WORKFLOW.read_text()
        critical = [
            'codex-rs/hepta-contracts/src/authority_lease.rs',
            'codex-rs/hepta-contracts/src/final_use.rs',
            'codex-rs/hepta-contracts/src/final_use_store.rs',
            'codex-rs/hepta-contracts/src/final_use_control.rs',
            'codex-rs/hepta-contracts/src/authority_runtime_clock.rs',
            'codex-rs/hepta-agentd/src/authority_feed_clock.rs',
            'codex-rs/hepta-agentd/src/authority_effect_tasks.rs',
            'codex-rs/hepta-agentd/tests/authority_effect_process_restart.rs',
            'codex-rs/hepta-automation/src/authorized_effect.rs',
            'codex-rs/Cargo.lock',
            'CALLERS.toml',
            'qa/b4-no-bypass/KERNEL_AUTHORITY_EXTENSION_API.json',
            'qualification/kernel-authority/product_process_recovery.py',
            'qualification/kernel-authority/status_manifest.json',
        ]
        for event in ('push', 'pull_request'):
            paths = event_paths(text, event)
            self.assertTrue(paths)
            for path in critical:
                self.assertTrue(
                    any(fnmatch.fnmatchcase(path, pattern) for pattern in paths),
                    (event, path),
                )

    def test_read_only_qualification_and_post_merge_source(self):
        text = WORKFLOW.read_text()
        self.assertIn(
            'branches: [main, work/kernel-authority-convergence-20260925]',
            text,
        )
        self.assertIn('contents: read', text)
        self.assertNotIn('contents: write', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('run_native_checks.py', text)
        self.assertIn('fromJSON(needs.identity.outputs.modes)', text)
        self.assertIn("modes='[\"exact-head\"]'", text)
        self.assertNotIn('git push', text)
        self.assertNotIn('--fix', text)

    def test_two_process_recovery_is_part_of_the_total_gate(self):
        text = WORKFLOW.read_text()
        self.assertIn(
            'lane: [trust-bundle, product-pilot, product-process, performance]',
            text,
        )
        self.assertIn('product-process)', text)
        self.assertIn('test_product_process_recovery.py', text)
        self.assertIn('product_process_recovery.py', text)
        self.assertIn('--test authority_effect_process_restart', text)
        self.assertIn('cargo fmt --check -p codex-hepta-agentd', text)
        self.assertIn('-- -D warnings', text)
        self.assertIn('needs: [identity, qualify]', text)
        self.assertIn('test "$QUALIFY_RESULT" = success', text)


if __name__ == '__main__':
    unittest.main()
