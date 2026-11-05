#!/usr/bin/env python3
"""Negative checks for real lane execution, merge identity, and generated navigation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from check_ci_contract import (ROOT, validate, check_inline_source_pins, CONTINUITY_BUILD, CONTINUITY_TRANSITIONS,
                               MODEL_OBSERVATION_BLOCK, RUST_ALL_TARGETS, RUST_DOCS, SIGNED_STATE_PYTHON,
                               ZERO_RUN_STEP, ZERO_COMPARE_STEP, ONE_ZERO_RUN_STEP,
                               ONE_ZERO_COMPARE_STEP, MAINTENANCE_RUN_STEP,
                               MAINTENANCE_COMPARE_STEP, REJECTION_RUN_STEP, REJECTION_COMPARE_STEP,
                               PAIRED_WORK_ORACLE, ZERO_WORK_ORACLE, MODEL_WINDOW_ORACLE,
                               EVALUATION_QUORUM_ORACLE, check_independent_conformance,
                               MODEL_EVOLUTION_ORACLES, COST_BOUNDARY_READERS,
                               ORIGINAL_CAMPAIGN_READER,
                               NATIVE_RELEASE_BLOCK, NATIVE_GROWTH_RELEASE_BLOCK, NATIVE_GROWTH_V2_RELEASE_BLOCK,
                               GSC2_SYNTHETIC_ORACLE,
                               NODE_EXAMPLE_BUILD, ACCOUNT_ARCHIVE_ORACLE, ACCOUNT_EXECUTION_ORACLE)
from check_cross_arch_cost import (COST_JOB_OVERHEAD_SECONDS, COST_JOB_TIMEOUT_MINUTES,
                                   cost_job_budget_seconds, rejection_job_budget_seconds)
from report_current_implementation import DESTINATION, markdown, projection, validate as current_validate


SYNTHETIC_GROWTH_PIPELINE = r'''python3() {
  if test "${1:-}" = -B && test "${2:-}" = formal/pon-nakamoto-v1/check_gsc2_native_readback.py; then
    test "$#" = 8
    test "$3" = --artifact-dir
    test "$4" = "$TRNM_CI_RECEIPT_DIR/native-growth-reference"
    test "$5" = --source-root
    test "$6" = "$(pwd -P)"
    test "$7" = --minimum-accounts
    test "$8" = 65537
    printf '%s\n' '{"scope":"synthetic shell control only, not a SQLite or native-growth observation"}'
    return "${TRNM_TEST_READBACK_STATUS:-0}"
  fi
  command python3 "$@"
}
synthetic_growth_native() {
  test "$TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY" = "$TRNM_CI_RECEIPT_DIR/native-growth-reference"
  mkdir "$TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY"
  printf '%s\n' 'running 1 test' 'test store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen ... ok' 'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s'
}
synthetic_growth_v2_native() {
  test "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR" = "$TRNM_CI_RECEIPT_DIR/native-growth-v2"
  mkdir "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR"
  printf '%s\n' '{"scope":"synthetic shell control only, not a native growth observation"}' > "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR/native.json"
  printf '%s\n' 'running 1 test' 'test store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen ... ok' 'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s'
}
'''


class InlineSourcePinTests(unittest.TestCase):
    def test_actual_workflow_guards_bind_current_bytes(self):
        self.assertGreater(check_inline_source_pins(ROOT), 0)

    def test_stale_missing_and_bypassed_literal_guards_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='trnm-inline-source-') as directory:
            root = Path(directory)
            (root / '.github/workflows').mkdir(parents=True)
            source = root / 'source.rs'
            raw = b'const WORK: bool = true;\n'
            source.write_bytes(raw)
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw,
                                usedforsecurity=False).hexdigest()
            guard = f'          test "$(git hash-object source.rs)" = {blob}\n'
            workflow = root / '.github/workflows/control.yml'
            workflow.write_text(guard)
            self.assertEqual(check_inline_source_pins(root), 1)
            source.write_bytes(raw.replace(b'true', b'TRUE'))
            with self.assertRaisesRegex(ValueError, 'inline source pin differs'):
                check_inline_source_pins(root)
            source.unlink()
            with self.assertRaisesRegex(ValueError, 'missing regular inline source'):
                check_inline_source_pins(root)
            source.write_bytes(raw)
            workflow.write_text(guard.rstrip() + ' || true\n')
            with self.assertRaisesRegex(ValueError, 'unsupported inline source guard'):
                check_inline_source_pins(root)

    def test_recent_log_inventory_retains_absence_and_source_failure(self):
        text = (ROOT / '.github/workflows/pon-recent-batch-acceptance.yml').read_text()
        section = text.split('      - name: Recheck unchanged exact source and hash all native logs\n', 1)[1]
        self.assertTrue(section.startswith('        if: always()\n'))
        script = section.split('        run: |\n', 1)[1].split('\n      - ', 1)[0]
        script = '\n'.join(line[10:] for line in script.splitlines()) + '\n'
        for source_status, logs in ((0, {}), (0, {'first.log': b'actual bytes\n',
                                              'with space.log': b'failed native attempt\n'}),
                                    (7, {}), (7, {'failed.log': b'failure retained\n'})):
            with self.subTest(source_status=source_status, logs=list(logs)), \
                    tempfile.TemporaryDirectory(prefix='trnm-recent-log-test-') as directory:
                output = Path(directory) / 'retained'
                output.mkdir()
                for name, data in logs.items():
                    (output / name).write_bytes(data)
                # Only the source verifier is substituted. The actual workflow
                # shell handles no logs, real file bytes and a failed verifier.
                prefix = 'python3() { return ' + str(source_status) + '; }\n'
                env = dict(os.environ, OUT=str(output), SOURCE_KIND='head',
                           EXPECTED_HEAD='1' * 40)
                result = subprocess.run(['bash', '-c', prefix + script], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, source_status, result.stderr)
                inventory = json.loads((output / 'log-inventory.json').read_text())
                self.assertEqual(inventory['retained_log_files'], len(logs))
                self.assertEqual(inventory['source_identity_exit_code'], source_status)
                self.assertEqual(inventory['status'], 'logs-retained' if logs else 'no-logs-retained')
                self.assertFalse(inventory['native_execution_established_by_inventory'])
                self.assertEqual(inventory['qualification'], 'unknown')
                checksums = (output / 'logs.sha256').read_text().splitlines()
                self.assertEqual(len(checksums), len(logs))
                for name, data in logs.items():
                    self.assertIn(hashlib.sha256(data).hexdigest() + '  ' + str(output / name), checksums)
                self.assertTrue((output / 'SCOPE.txt').is_file())


class EvaluationQuorumLaneTests(unittest.TestCase):
    """Check the real lane without copying unrelated retained evidence."""

    def setUp(self):
        self.script = (ROOT / 'scripts/ci/ci_job.sh').read_text()
        self.lanes = {'repository-truth', 'protocol-contract', 'fuzz-smoke',
                      'rust-baseline', 'external-evidence-contract'}

    def test_actual_lane_preserves_quorum_reference_and_retained_vector_checks(self):
        check_independent_conformance(self.script, self.lanes)

    def test_cell_host_native_handoff_cannot_skip_build_or_use_an_unbound_binary(self):
        commands = (
            '    cargo build --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-data-availability --bin trnm-cell\n',
            '    trnm_cell_handoff_binary="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/trnm-cell")"\n',
            '    test -x "$trnm_cell_handoff_binary"\n',
            '    TRNM_CELL_BIN="$trnm_cell_handoff_binary" python3 scripts/ci/test_llm_cell_host_handoff.py -v\n',
        )
        for command in commands:
            self.assertEqual(self.script.count(command), 1)
            for replacement in ('', command * 2, '    if false; then\n' + command + '    fi\n',
                                '    true # ' + command.lstrip(), command.rstrip() + ' || true\n'):
                with self.subTest(command=command, replacement=replacement):
                    with self.assertRaises(ValueError):
                        check_independent_conformance(self.script.replace(command, replacement), self.lanes)
        unbound = self.script.replace('TRNM_CELL_BIN="$trnm_cell_handoff_binary" ', '')
        with self.assertRaises(ValueError):
            check_independent_conformance(unbound, self.lanes)

    def test_current_readers_and_runtime_controls_cannot_be_missing_duplicated_stubbed_or_moved(self):
        # Independent inventory: removing a required command from the checker
        # must not silently remove that command's negative coverage as well.
        paths = (
            'scripts/ci/test_pon_w1_cost_matrix_reader.py',
            'scripts/ci/test_pon_w1_reused_cost_reader_v3.py',
            'scripts/ci/test_run_w1_reused_cost_v3.py',
            'scripts/ci/test_pon_public_v3_policy_read.py',
            'scripts/ci/test_llm_cell_handoff_deadline.py',
            'scripts/test_llm_runtime_rss_owner.py',
            'scripts/test_llm_runtime_exit_observation.py',
            'scripts/test_llm_runtime_stop.py',
            'scripts/test_llm_inherited_runtime.py',
            'scripts/test_llm_neural_read_worker.py',
            'scripts/test_llm_python_runtime_contract.py',
        )
        for path in paths:
            command = '    python3 ' + path + '\n'
            self.assertEqual(self.script.count(command), 1)
            changes = {
                'missing': self.script.replace(command, ''),
                'duplicate': self.script.replace(command, command * 2),
                'true stub': self.script.replace(command, command.replace('python3 ', 'true # python3 ')),
                'comment': self.script.replace(command, '    # ' + command.lstrip()),
                'wrong lane': self.script.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command),
                'other-lane duplicate': self.script.replace('  fuzz-smoke)\n', '  fuzz-smoke)\n  ' + command.lstrip()),
            }
            for label, changed in changes.items():
                with self.subTest(path=path, change=label), self.assertRaises(ValueError):
                    check_independent_conformance(changed, self.lanes)

    def test_current_runtime_controls_must_follow_pilot_and_parent_material(self):
        parent = '    python3 scripts/test_llm_parent_material.py\n'
        for path in ('scripts/test_llm_runtime_rss_owner.py',
                     'scripts/test_llm_runtime_exit_observation.py',
                     'scripts/test_llm_runtime_stop.py',
                     'scripts/test_llm_inherited_runtime.py',
                     'scripts/test_llm_neural_read_worker.py',
                     'scripts/test_llm_python_runtime_contract.py'):
            command = '    python3 ' + path + '\n'
            early = self.script.replace(command, '').replace(parent, command + parent)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'runtime owner'):
                check_independent_conformance(early, self.lanes)

    def test_current_runtime_controls_cannot_split_parent_material_and_parent_step(self):
        parent_step = '    python3 scripts/test_llm_runtime_parent_step.py\n'
        for path in ('scripts/test_llm_runtime_rss_owner.py',
                     'scripts/test_llm_runtime_exit_observation.py',
                     'scripts/test_llm_runtime_stop.py',
                     'scripts/test_llm_inherited_runtime.py',
                     'scripts/test_llm_neural_read_worker.py',
                     'scripts/test_llm_python_runtime_contract.py'):
            command = '    python3 ' + path + '\n'
            early = self.script.replace(command, '').replace(parent_step, command + parent_step)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'runtime owner'):
                check_independent_conformance(early, self.lanes)

    def test_gsc2_synthetic_reader_cannot_be_removed_duplicated_commented_or_moved(self):
        for replacement in ['', GSC2_SYNTHETIC_ORACLE * 2,
                            '    # ' + GSC2_SYNTHETIC_ORACLE.lstrip(),
                            GSC2_SYNTHETIC_ORACLE.replace('python3 ', 'true # python3 '),
                            GSC2_SYNTHETIC_ORACLE.replace('$(pwd -P)', '/tmp/stale-source'),
                            GSC2_SYNTHETIC_ORACLE.replace(' --source-root "$(pwd -P)"', '')]:
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, 'GSC2 synthetic'):
                check_independent_conformance(self.script.replace(GSC2_SYNTHETIC_ORACLE, replacement), self.lanes)
        moved = self.script.replace(GSC2_SYNTHETIC_ORACLE, '').replace(
            '  repository-truth)\n', '  repository-truth)\n' + GSC2_SYNTHETIC_ORACLE)
        with self.assertRaisesRegex(ValueError, 'GSC2 synthetic'):
            check_independent_conformance(moved, self.lanes)
        early = self.script.replace(GSC2_SYNTHETIC_ORACLE, '').replace(
            NODE_EXAMPLE_BUILD, GSC2_SYNTHETIC_ORACLE + NODE_EXAMPLE_BUILD)
        with self.assertRaisesRegex(ValueError, 'GSC2 synthetic'):
            check_independent_conformance(early, self.lanes)

    def test_native_growth_every_guard_and_command_is_mandatory_once_and_in_rust_lane(self):
        for command in NATIVE_GROWTH_RELEASE_BLOCK.splitlines(keepends=True):
            for replacement in ['', command * 2, '      # ' + command.lstrip(),
                                command.replace(command.lstrip(), 'true # ' + command.lstrip())]:
                with self.subTest(command=command, replacement=replacement), self.assertRaises(ValueError):
                    check_independent_conformance(self.script.replace(command, replacement), self.lanes)
            moved = self.script.replace(command, '').replace('  protocol-contract)\n',
                '  protocol-contract)\n' + command)
            with self.subTest(command=command, mutation='moved'), self.assertRaises(ValueError):
                check_independent_conformance(moved, self.lanes)

    def test_native_growth_cannot_lower_threshold_relabel_test_or_reuse_export(self):
        changes = [('--minimum-accounts 65537', '--minimum-accounts 65536'),
                   ('--minimum-accounts 65537', '--minimum-accounts 64'),
                   ('--minimum-accounts 65537', ''),
                   ('native_growth_reference_65537_signed_accounts_and_cold_reopen',
                    'native_growth_reference_64_signed_accounts_and_cold_reopen'),
                   ('TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY=', 'WRONG_GROWTH_EXPORT='),
                   ('/native-growth-reference"', '/previous-growth-reference"'),
                   ('/native-growth-reference-release.log"', '/previous-growth.log"'),
                   ('--source-root "$(pwd -P)"', '--source-root /tmp/stale-source'),
                   (' --offline ', ' '), (' --locked ', ' '), (' --nocapture ', ' '),
                   (' -p trnm-pon-node ', ' -p trnm-protocol '),
                   ('2>&1 | tee ', '2>&1 || tee ')]
        for before, after in changes:
            changed = NATIVE_GROWTH_RELEASE_BLOCK.replace(before, after)
            self.assertNotEqual(changed, NATIVE_GROWTH_RELEASE_BLOCK)
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                check_independent_conformance(self.script.replace(NATIVE_GROWTH_RELEASE_BLOCK, changed), self.lanes)

    def test_bounded_native_growth_requires_each_guard_and_exact_export_binding(self):
        for command in NATIVE_GROWTH_V2_RELEASE_BLOCK.splitlines(keepends=True):
            for replacement in ['', command * 2, '      # ' + command.lstrip()]:
                with self.subTest(command=command, replacement=replacement), self.assertRaises(ValueError):
                    check_independent_conformance(self.script.replace(command, replacement), self.lanes)
            moved = self.script.replace(command, '').replace('  protocol-contract)\n',
                '  protocol-contract)\n' + command)
            with self.subTest(command=command, mutation='moved'), self.assertRaises(ValueError):
                check_independent_conformance(moved, self.lanes)
        for before, after in [
            ('TRNM_NATIVE_GROWTH_V2_EXPORT_DIR=', 'WRONG_GROWTH_EXPORT='),
            ('/native-growth-v2"', '/previous-growth-v2"'),
            ('/native-growth-v2-release.log"', '/previous-growth-v2.log"'),
            ('native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen',
             'native_growth_reference_65537_signed_accounts_and_cold_reopen'),
        ]:
            changed = NATIVE_GROWTH_V2_RELEASE_BLOCK.replace(before, after)
            self.assertNotEqual(changed, NATIVE_GROWTH_V2_RELEASE_BLOCK)
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                check_independent_conformance(self.script.replace(NATIVE_GROWTH_V2_RELEASE_BLOCK, changed), self.lanes)

    def test_bounded_native_growth_cannot_accept_a_passing_transcript_without_its_export(self):
        # The synthetic producer tests shell/export failure propagation, not Rust.
        with tempfile.TemporaryDirectory(prefix='growth-v2-export-shell-') as temporary:
            root = Path(temporary) / 'receipt with spaces'
            root.mkdir()
            prelude = ('set -euo pipefail\n' + SYNTHETIC_GROWTH_PIPELINE +
                       'cargo() { synthetic_growth_v2_native; rm "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR/native.json"; }\n'
                       'trnm_native_receipt_root="$TRNM_CI_RECEIPT_DIR"\n')
            result = subprocess.run(['bash', '-c', prelude + NATIVE_GROWTH_V2_RELEASE_BLOCK +
                'touch "$TRNM_CI_RECEIPT_DIR/incorrect-success"\n'], cwd=ROOT,
                env={'PATH': '/usr/bin:/bin', 'TRNM_CI_RECEIPT_DIR': str(root)},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue((root / 'native-growth-v2-release.log').is_file())
            self.assertFalse((root / 'incorrect-success').exists())

    def test_native_growth_libtest_check_must_precede_sqlite_readback(self):
        lines = NATIVE_GROWTH_RELEASE_BLOCK.splitlines(keepends=True)
        for indices in [(4, 5), (5, 8)]:
            changed = lines.copy()
            first, second = indices
            changed[first], changed[second] = changed[second], changed[first]
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                check_independent_conformance(self.script.replace(NATIVE_GROWTH_RELEASE_BLOCK,
                    ''.join(changed)), self.lanes)
        moved = self.script.replace(NATIVE_GROWTH_RELEASE_BLOCK, '').replace(
            '  protocol-contract)\n', '  protocol-contract)\n' + NATIVE_GROWTH_RELEASE_BLOCK)
        with self.assertRaises(ValueError):
            check_independent_conformance(moved, self.lanes)
        duplicated = self.script.replace('  fuzz-smoke)\n',
            '  fuzz-smoke)\n' + NATIVE_GROWTH_RELEASE_BLOCK)
        with self.assertRaises(ValueError):
            check_independent_conformance(duplicated, self.lanes)

    def test_growth_sqlite_readback_failure_remains_a_shell_failure(self):
        # Synthetic cargo/checker exercise only pipeline plumbing and failure
        # propagation. The actual SQLite oracle has separate native/synthetic CI.
        with tempfile.TemporaryDirectory(prefix='growth-readback-shell-') as temporary:
            root = Path(temporary) / 'receipt with spaces'
            root.mkdir()
            prelude = ('set -euo pipefail\n' + SYNTHETIC_GROWTH_PIPELINE +
                       'cargo() { synthetic_growth_native; }\n'
                       'trnm_native_receipt_root="$TRNM_CI_RECEIPT_DIR"\n')
            result = subprocess.run(['bash', '-c', prelude + NATIVE_GROWTH_RELEASE_BLOCK +
                'touch "$TRNM_CI_RECEIPT_DIR/incorrect-success"\n'], cwd=ROOT,
                env={'PATH': '/usr/bin:/bin', 'TRNM_CI_RECEIPT_DIR': str(root),
                     'TRNM_TEST_READBACK_STATUS': '19'}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 19, result.stderr)
            self.assertTrue((root / 'native-growth-reference-release.log').is_file())
            self.assertTrue((root / 'native-growth-reference/readback.json').is_file())
            self.assertFalse((root / 'incorrect-success').exists())

    def test_reward_budget_controls_cannot_be_omitted_duplicated_or_moved(self):
        command = '    python3 formal/pon-nakamoto-v1/test_reward_budget_oracle.py\n'
        original = (ROOT / 'scripts/ci/ci_job.sh').read_text()
        for label, changed in [('omitted', original.replace(command, '')),
                               ('duplicated', original.replace(command, command * 2)),
                               ('moved', original.replace(command, '').replace(
                                   '  fuzz-smoke)\n', '  fuzz-smoke)\n' + command))]:
            with self.subTest(change=label), self.assertRaisesRegex(ValueError, 'reward budget'):
                check_independent_conformance(changed, self.lanes)

    def test_parent_material_checks_cannot_be_omitted_duplicated_or_moved(self):
        for command in ('    python3 scripts/test_llm_parent_material.py\n',
                        '    python3 scripts/test_llm_runtime_parent_step.py\n'):
            for changed in [self.script.replace(command, ''),
                            self.script.replace(command, '    true # omitted parent preflight\n'),
                            self.script.replace(command, command * 2),
                            self.script.replace(command, '').replace('  fuzz-smoke)\n',
                                '  fuzz-smoke)\n' + command)]:
                with self.subTest(command=command, changed=changed), self.assertRaisesRegex(ValueError, 'parent material'):
                    check_independent_conformance(changed, self.lanes)

    def test_parent_commands_cannot_be_skipped_by_false_shell_branch(self):
        # Only a synthetic failing shell function runs; no model/native command.
        for command in ('    python3 scripts/test_llm_parent_material.py\n',
                        '    python3 scripts/test_llm_runtime_parent_step.py\n'):
            skipped = '    if false; then\n' + command + '    fi\n'
            with self.subTest(command=command):
                with self.assertRaisesRegex(ValueError, 'straight-line command sequence'):
                    check_independent_conformance(self.script.replace(command, skipped), self.lanes)
                prelude = ('set -euo pipefail\n'
                           'python3() { printf "synthetic parent test called\\n"; return 19; }\n')
                normal = subprocess.run(['bash', '-c', prelude + command +
                    'printf "synthetic lane continued\\n"\n'],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(normal.returncode, 19, normal.stderr)
                self.assertEqual(normal.stdout, 'synthetic parent test called\n')
                bypass = subprocess.run(['bash', '-c', prelude + skipped +
                    'printf "synthetic lane continued\\n"\n'],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(bypass.returncode, 0, bypass.stderr)
                self.assertEqual(bypass.stdout, 'synthetic lane continued\n')

    def test_parent_commands_cannot_have_failures_swallowed_by_shell_condition(self):
        # Bash suppresses errexit in an if condition despite the original set -e.
        for command in ('    python3 scripts/test_llm_parent_material.py\n',
                        '    python3 scripts/test_llm_runtime_parent_step.py\n'):
            conditional = '    if\n' + command + '    then\n      :\n    fi\n'
            with self.subTest(command=command):
                with self.assertRaisesRegex(ValueError, 'straight-line command sequence'):
                    check_independent_conformance(self.script.replace(command, conditional), self.lanes)
                prelude = ('set -euo pipefail\n'
                           'python3() { printf "synthetic parent test called\\n"; return 19; }\n')
                normal = subprocess.run(['bash', '-c', prelude + command +
                    'printf "synthetic lane continued\\n"\n'],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(normal.returncode, 19, normal.stderr)
                self.assertEqual(normal.stdout, 'synthetic parent test called\n')
                bypass = subprocess.run(['bash', '-c', prelude + conditional +
                    'printf "synthetic lane continued\\n"\n'],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(bypass.returncode, 0, bypass.stderr)
                self.assertEqual(bypass.stdout,
                                 'synthetic parent test called\nsynthetic lane continued\n')

    def test_selected_lane_cannot_be_wrapped_in_an_outer_shell_condition(self):
        start = self.script.index('case "${1:?required job}" in\n')
        prefix, dispatch = self.script[:start], self.script[start:]
        for changed in (prefix + 'if false; then\n' + dispatch + 'fi\n',
                        prefix + 'if\n' + dispatch + 'then :; fi\n'):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'lane dispatch'):
                check_independent_conformance(changed, self.lanes)

    def test_useful_cell_relation_controls_cannot_be_removed_skipped_duplicated_or_moved(self):
        for name in ('test_useful_cell_numeric_v1.py', 'test_useful_cell_relation_v1.py'):
            command = ("    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p '"
                       + name + "' -v\n")
            self.assertEqual(self.script.count(command), 1)
            variants = {
                'removed': self.script.replace(command, ''),
                'stubbed': self.script.replace(command, '    true # omitted useful relation\n'),
                'duplicated': self.script.replace(command, command * 2),
                'skipped': self.script.replace(command, '    if false; then\n' + command + '    fi\n'),
                'swallowed': self.script.replace(command, command.rstrip() + ' || true\n'),
                'moved': self.script.replace(command, '').replace('  fuzz-smoke)\n',
                                                                  '  fuzz-smoke)\n' + command),
            }
            for label, script in variants.items():
                with self.subTest(test=name, mutation=label), self.assertRaises(ValueError):
                    check_independent_conformance(script, self.lanes)

    def test_original_campaign_reader_keeps_original_pins_and_lane(self):
        for replacement in ['', ORIGINAL_CAMPAIGN_READER * 2,
                            ORIGINAL_CAMPAIGN_READER.replace('python3', 'true # python3'),
                            ORIGINAL_CAMPAIGN_READER.replace('--retained-subset', ''),
                            ORIGINAL_CAMPAIGN_READER.replace('9e705ccf75b7318dcc4bda4815956f58beb10e72', '0' * 40)]:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                check_independent_conformance(self.script.replace(ORIGINAL_CAMPAIGN_READER, replacement), self.lanes)
        moved = self.script.replace(ORIGINAL_CAMPAIGN_READER, '').replace(
            '  fuzz-smoke)\n', '  fuzz-smoke)\n' + ORIGINAL_CAMPAIGN_READER)
        with self.assertRaises(ValueError):
            check_independent_conformance(moved, self.lanes)

    def test_new_evolution_and_cost_checks_cannot_be_removed_skipped_duplicated_or_moved(self):
        for block in [MODEL_EVOLUTION_ORACLES, COST_BOUNDARY_READERS]:
            for command in block.splitlines(keepends=True):
                for replacement in ['', command * 2, command.replace('python3', 'true # python3')]:
                    with self.subTest(command=command, replacement=replacement):
                        with self.assertRaises(ValueError):
                            check_independent_conformance(self.script.replace(command, replacement), self.lanes)
                moved = self.script.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
                with self.assertRaises(ValueError):
                    check_independent_conformance(moved, self.lanes)

    def test_native_daa_reader_requires_fresh_full_work_export_and_actual_digest(self):
        lines = [line + '\n' for line in self.script.splitlines()
                 if 'TRNM_DAA_EVIDENCE_DIR' in line]
        self.assertEqual(len(lines), 6)
        for command in lines:
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    check_independent_conformance(self.script.replace(command, ''), self.lanes)
        changed = self.script.replace('sha256sum "$TRNM_DAA_EVIDENCE_DIR/daa-bounds.json"',
                                      'printf stale-prior-report')
        with self.assertRaises(ValueError):
            check_independent_conformance(changed, self.lanes)

    def test_cost_counterexamples_require_their_real_input_arguments(self):
        for command in [COST_BOUNDARY_READERS.splitlines(keepends=True)[0],
                        '      python3 scripts/ci/test_pon_daa_schedule_reader.py --raw-dir "$TRNM_DAA_EVIDENCE_DIR"\n']:
            for replacement in [command.split(' --raw-dir')[0] + '\n',
                                command.split(' --raw-dir')[0] + ' --raw-dir /tmp/stale-other-run\n']:
                with self.subTest(command=command, replacement=replacement):
                    with self.assertRaises(ValueError):
                        check_independent_conformance(self.script.replace(command, replacement), self.lanes)

    def test_quorum_checks_cannot_be_removed_duplicated_skipped_or_rewrite_vectors(self):
        for command in EVALUATION_QUORUM_ORACLE.splitlines(keepends=True):
            for replacement in ['', '    true # omitted quorum reference\n', command * 2,
                                command.replace('python3', 'true # python3'),
                                command.rstrip('\n') + ' --write\n']:
                with self.subTest(command=command, replacement=replacement):
                    with self.assertRaisesRegex(ValueError, 'evaluation quorum oracle'):
                        check_independent_conformance(self.script.replace(command, replacement), self.lanes)

    def test_quorum_checks_cannot_move_to_another_lane_or_reverse_verification(self):
        commands = EVALUATION_QUORUM_ORACLE.splitlines(keepends=True)
        changed = [self.script.replace(EVALUATION_QUORUM_ORACLE, ''.join(reversed(commands)))]
        for command in [*commands, EVALUATION_QUORUM_ORACLE]:
            changed.append(self.script.replace(command, '').replace(
                '  fuzz-smoke)\n', '  fuzz-smoke)\n' + command))
        for script in changed:
            with self.subTest(script=script):
                with self.assertRaisesRegex(ValueError, 'evaluation quorum oracle'):
                    check_independent_conformance(script, self.lanes)


class W1ReuseV3LaneTests(unittest.TestCase):
    """Small real source-owner controls; no native work/cost observation."""

    def test_v3_lane_is_additive_and_keeps_all_four_exact_source_cells(self):
        report = validate(ROOT)
        self.assertEqual(report['native_cost_architectures'], 2)
        self.assertEqual(report['w1_actual_reuse_v3_cells'], 4)
        text = (ROOT / '.github/workflows/trnm-required-baseline.yml').read_text()
        self.assertEqual(text.count('  cross-arch-w1-reuse-v3:\n'), 1)
        self.assertEqual(text.count('run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_w1_reused_cost_v3.py'), 1)

    def test_v3_cannot_skip_rename_rebudget_or_substitute_local_observation(self):
        from check_ci_contract import W1_REUSE_V3_JOB, check_w1_reuse_v3
        for old, new in (
            ('arch: [x64, arm64]', 'arch: [x64]'),
            ('source: [head, prospective-merge]', 'source: [head]'),
            ('      fail-fast: false', '      fail-fast: true'),
            ('    timeout-minutes: 155', '    timeout-minutes: 180'),
            ("    if: github.event_name == 'pull_request'", '    if: false'),
            ('--expected-base "$TRNM_EXPECTED_BASE_SHA" ', ''),
            ('--expected-merge "$TRNM_EXPECTED_SOURCE_SHA"', '--expected-merge "$TRNM_EXPECTED_CANDIDATE_SHA"'),
            ('--output "$RUNNER_TEMP/ci-observations/source-after.json"', '--output /tmp/old-source.json'),
            ('run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_w1_reused_cost_v3.py', 'run: true # python3 scripts/ci/run_w1_reused_cost_v3.py'),
            ('env -u CARGO_INCREMENTAL python3', 'python3'),
            ('env -u CARGO_INCREMENTAL python3', 'env -u CARGO_INCREMENTAL -u RUSTFLAGS python3'),
            ('run_w1_reused_cost_v3.py --arch', 'run_w1_reused_cost_v3.py --local --arch'),
            ('run: bash scripts/project-preflight.sh --audit', 'run: true # bash scripts/project-preflight.sh --audit'),
            ('      - name: Check original repository boundary before native V3 build\n        run: bash scripts/project-preflight.sh --audit\n', ''),
            ('rustup toolchain install 1.95.0', 'rustup toolchain install stable'),
            ('        if: always()\n', ''),
            ('name: w1-reuse-v3-${{ matrix.source }}-', 'name: cost-'),
            ('          if-no-files-found: error', '          if-no-files-found: ignore'),
        ):
            with self.subTest(old=old, new=new):
                self.assertIn(old, W1_REUSE_V3_JOB)
                with self.assertRaisesRegex(ValueError, 'four exact W1 V3'):
                    check_w1_reuse_v3(W1_REUSE_V3_JOB.replace(old, new, 1).split('\n', 1)[1])
        for changed in ('', W1_REUSE_V3_JOB * 2):
            with self.assertRaises(ValueError):
                check_w1_reuse_v3(changed)

    def test_actual_v3_source_shell_binds_head_ordered_merge_and_unchanged_bytes(self):
        import json
        import os
        import re
        import textwrap

        workflow = (ROOT / '.github/workflows/trnm-required-baseline.yml').read_text()
        block = workflow.split('  cross-arch-w1-reuse-v3:\n', 1)[1].split('\n  cross-arch-cost-consistency:', 1)[0]
        commands = re.findall(r'        run: \|\n(.*?)(?=      - name:)', block, re.S)
        before, after = [textwrap.dedent(value) for value in commands if 'verify_ci_source.py' in value]
        with tempfile.TemporaryDirectory(prefix='w1-v3-source-shell-') as temporary:
            directory = Path(temporary)
            checkout, output = directory / 'repo', directory / 'receipts'
            (checkout / 'scripts/ci').mkdir(parents=True)
            output.mkdir()
            shutil.copyfile(ROOT / 'scripts/ci/verify_ci_source.py', checkout / 'scripts/ci/verify_ci_source.py')

            def git(*args):
                return subprocess.check_output(['git', *args], cwd=checkout, text=True, stderr=subprocess.DEVNULL).strip()

            git('init', '-q', '-b', 'base')
            git('config', 'user.name', 'W1 V3 source test')
            git('config', 'user.email', 'source-test@example.invalid')
            (checkout / 'actual').write_text('base\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'candidate')
            (checkout / 'actual').write_text('candidate\n')
            git('commit', '-am', 'candidate', '-q')
            head = git('rev-parse', 'HEAD')
            env = dict(os.environ, RUNNER_TEMP=str(output), PYTHONDONTWRITEBYTECODE='1',
                       TRNM_COST_SOURCE_KIND='head', TRNM_EXPECTED_CANDIDATE_SHA=head,
                       TRNM_EXPECTED_BASE_SHA=base, TRNM_EXPECTED_SOURCE_SHA=head)

            def run(command):
                return subprocess.run(['bash', '-euo', 'pipefail', '-c', command], cwd=checkout,
                                      env=env, text=True, capture_output=True)

            self.assertEqual(run(before).returncode, 0)
            initial = json.loads((output / 'ci-observations/source-before.json').read_text())
            self.assertEqual(initial['tested_commit'], head)
            self.assertTrue(initial['tracked_worktree_verified'])
            (checkout / 'actual').write_text('tampered\n')
            self.assertNotEqual(run(after).returncode, 0)
            git('checkout', '--', 'actual')
            self.assertEqual(run(after).returncode, 0)
            git('checkout', '-q', 'base')
            git('merge', '--no-ff', '-qm', 'actual ordered merge', 'candidate')
            merge = git('rev-parse', 'HEAD')
            env.update(TRNM_COST_SOURCE_KIND='prospective-merge', TRNM_EXPECTED_SOURCE_SHA=merge)
            self.assertEqual(run(before).returncode, 0)
            merged = json.loads((output / 'ci-observations/source-before.json').read_text())
            self.assertEqual(merged['tested_commit'], merge)
            self.assertEqual(merged['candidate'], head)
            self.assertEqual(merged['base'], base)
            env['TRNM_EXPECTED_BASE_SHA'] = head
            self.assertNotEqual(run(after).returncode, 0)
            env['TRNM_EXPECTED_BASE_SHA'] = base
            self.assertEqual(run(after).returncode, 0)


class CiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='trnm-ci-contract-')
        cls.root = Path(cls.temporary.name) / 'source'
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns('.git', 'target', '__pycache__', 'artifacts'))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def rejected(self, path, before, after):
        path = self.root / path
        original = path.read_text()
        self.assertIn(before, original)
        try:
            path.write_text(original.replace(before, after, 1))
            with self.assertRaises(ValueError):
                validate(self.root)
        finally:
            path.write_text(original)

    def test_current_execution_contract(self):
        self.assertEqual(validate(self.root)['merge_lanes'], 5)
        current_validate(self.root)

    def test_zero_native_execution_cannot_be_removed_skipped_or_replaced(self):
        for replacement in ['', ZERO_RUN_STEP.replace('        if: always()\n', ''),
                            ZERO_RUN_STEP.replace('run: env -u CARGO_INCREMENTAL python3', 'run: true # python3'),
                            ZERO_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3', 'python3'),
                            ZERO_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3',
                                                  'env -u CARGO_INCREMENTAL -u RUSTFLAGS python3')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', ZERO_RUN_STEP, replacement)

    def test_zero_native_execution_and_comparison_require_explicit_current_version(self):
        for command in [ZERO_RUN_STEP, ZERO_COMPARE_STEP]:
            for selector in ['', ' --zero-version 1', ' --zero-version 3',
                             ' --zero-version 2 --zero-version 1']:
                with self.subTest(command=command, selector=selector):
                    self.rejected('.github/workflows/trnm-required-baseline.yml', command,
                                  command.replace(' --zero-version 2', selector))

    def test_architecture_budget_covers_generation_rejection_and_termination_margin(self):
        self.assertEqual(rejection_job_budget_seconds(), 1195)
        self.assertEqual(cost_job_budget_seconds() - COST_JOB_OVERHEAD_SECONDS, 6480 + 1195)
        self.assertGreaterEqual(COST_JOB_TIMEOUT_MINUTES * 60, cost_job_budget_seconds())
        for minutes in [30, 60, 90, 108, 120, 135, 150]:
            with self.subTest(minutes=minutes):
                self.rejected('.github/workflows/trnm-required-baseline.yml',
                              '    timeout-minutes: 155\n', f'    timeout-minutes: {minutes}\n')

    def test_complete_rust_budget_must_be_present_once_in_head(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        original = '    timeout-minutes: 180\n'
        for replacement in ['', '    timeout-minutes: 45\n', '    timeout-minutes: 90\n',
                            original + original]:
            with self.subTest(replacement=replacement):
                self.rejected(path, original, replacement)

    def test_merge_rust_budget_must_match_head_without_expanding_other_lanes(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        original = "    timeout-minutes: ${{ matrix.lane == 'rust-baseline' && 180 || 45 }}\n"
        for replacement in ['', '    timeout-minutes: 45\n', '    timeout-minutes: 180\n',
                            original.replace('180 || 45', '90 || 45'),
                            original.replace('==', '!='), original.replace('180 || 45', '45 || 180'),
                            original.replace("'rust-baseline'", "'protocol-contract'"), original + original]:
            with self.subTest(replacement=replacement):
                self.rejected(path, original, replacement)

    def test_rejection_run_and_comparison_require_actual_ordered_bound_execution(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        for previous, step in [(MAINTENANCE_RUN_STEP, REJECTION_RUN_STEP),
                               (MAINTENANCE_COMPARE_STEP, REJECTION_COMPARE_STEP)]:
            for replacement in ['', step.replace('        if: always()\n', ''),
                                step.replace('run: python3', 'run: true # python3'), step + step]:
                with self.subTest(step=step, replacement=replacement):
                    self.rejected(path, step, replacement)
            self.rejected(path, previous + step, step + previous)
        for option in ['--expected-source "$TRNM_EXPECTED_SOURCE_SHA"',
                       '--expected-run "$GITHUB_RUN_ID"', '--expected-attempt "$GITHUB_RUN_ATTEMPT"']:
            self.rejected(path, REJECTION_COMPARE_STEP, REJECTION_COMPARE_STEP.replace(' ' + option, ''))

    def test_rejection_parser_negatives_execute_once_in_repository_truth(self):
        path = 'scripts/ci/ci_job.sh'
        command = '    python3 scripts/ci/test_work_rejection_report.py\n'
        for replacement in ['', '    true # omitted rejection checks\n', command + command]:
            self.rejected(path, command, replacement)
        original = (self.root / path).read_text()
        changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
        self.rejected(path, original, changed)

    def test_rejection_comparison_output_uses_actual_job_environment(self):
        workflow = (self.root / '.github/workflows/trnm-required-baseline.yml').read_text()
        job = workflow.split('  cross-arch-cost-consistency:\n', 1)[1].split('\n  prospective-merge:', 1)[0]
        commands = [line.strip().removeprefix('run: ') for line in job.splitlines()
                    if line.strip().startswith('run: python3 scripts/pon_work_rejection_report.py --compare ')]
        self.assertEqual(len(commands), 1)
        runner = str(self.root.parent / 'actual runner temp')
        # This job gets RUNNER_TEMP from Actions; it does not initialize the
        # cost-runner-only TRNM_CI_RECEIPT_DIR. Execute real shell expansion of
        # the checked-in command without launching a collector or writing files.
        env = {'PATH': '/usr/bin:/bin', 'RUNNER_TEMP': runner,
               'TRNM_EXPECTED_SOURCE_SHA': 'a' * 40, 'GITHUB_RUN_ID': '1',
               'GITHUB_RUN_ATTEMPT': '1'}
        def expand(command):
            return subprocess.run(['bash', '-u', '-c', 'set -- ' + command + '; printf "%s\\n" "$@"'],
                                  env=env, capture_output=True, text=True, timeout=10)
        actual = expand(commands[0])
        self.assertEqual(actual.returncode, 0, actual.stderr)
        arguments = actual.stdout.splitlines()
        self.assertEqual(arguments.count('--out'), 1)
        self.assertEqual(arguments[arguments.index('--out') + 1],
                         str(Path(runner) / 'ci-observations/work-rejection-comparison'))
        self.assertIn('path: ${{ runner.temp }}/ci-observations/', job)
        broken = expand(commands[0].replace('$RUNNER_TEMP/ci-observations/work-rejection-comparison',
                                           '$TRNM_CI_RECEIPT_DIR/work-rejection-comparison'))
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn('TRNM_CI_RECEIPT_DIR', broken.stderr)

    def test_maintenance_native_execution_cannot_be_removed_skipped_or_substituted(self):
        for replacement in ['', MAINTENANCE_RUN_STEP.replace('        if: always()\n', ''),
                            MAINTENANCE_RUN_STEP.replace('run: env -u CARGO_INCREMENTAL python3', 'run: true # python3'),
                            MAINTENANCE_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3', 'python3'),
                            MAINTENANCE_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3',
                                                         'env -u CARGO_INCREMENTAL -u RUSTFLAGS python3'),
                            MAINTENANCE_RUN_STEP.replace(' --suite maintenance-paired', ' --suite one-zero-locality')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', MAINTENANCE_RUN_STEP, replacement)

    def test_maintenance_comparison_cannot_be_removed_skipped_or_substituted(self):
        for replacement in ['', MAINTENANCE_COMPARE_STEP.replace('        if: always()\n', ''),
                            MAINTENANCE_COMPARE_STEP.replace('run: python3', 'run: true # python3'),
                            MAINTENANCE_COMPARE_STEP.replace(' --suite maintenance-paired', ' --suite one-zero-locality')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', MAINTENANCE_COMPARE_STEP, replacement)

    def test_maintenance_execution_and_comparison_preserve_sequential_failure_collection(self):
        for first, second in [(ONE_ZERO_RUN_STEP, MAINTENANCE_RUN_STEP),
                              (ONE_ZERO_COMPARE_STEP, MAINTENANCE_COMPARE_STEP)]:
            with self.subTest(step=second):
                self.rejected('.github/workflows/trnm-required-baseline.yml', first + second, second + first)
                self.rejected('.github/workflows/trnm-required-baseline.yml', second, second + second)

    def test_maintenance_suite_cannot_move_into_the_wrong_job(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        original = (self.root / path).read_text()
        for step, destination in [(MAINTENANCE_RUN_STEP, MAINTENANCE_COMPARE_STEP),
                                  (MAINTENANCE_COMPARE_STEP, MAINTENANCE_RUN_STEP)]:
            with self.subTest(step=step):
                changed = original.replace(step, '').replace(destination, destination + step)
                self.rejected(path, original, changed)

    def test_maintenance_negative_checks_execute_once_in_repository_truth(self):
        path = 'scripts/ci/ci_job.sh'
        command = '    python3 scripts/ci/test_maintenance_cost.py\n'
        for replacement in ['', '    true # omitted maintenance checks\n', command + command]:
            with self.subTest(replacement=replacement):
                self.rejected(path, command, replacement)
        original = (self.root / path).read_text()
        changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
        self.rejected(path, original, changed)

    def test_zero_comparison_cannot_be_removed_or_replaced_by_old_suite(self):
        for replacement in ['', ZERO_COMPARE_STEP.replace(' --suite zero-locality', ''),
                            ZERO_COMPARE_STEP.replace('        if: always()\n', ''),
                            ZERO_COMPARE_STEP.replace('run: python3', 'run: true # python3')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', ZERO_COMPARE_STEP, replacement)

    def test_zero_suite_cannot_move_into_the_wrong_job(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        original = (self.root / path).read_text()
        for step, destination in [(ZERO_RUN_STEP, ZERO_COMPARE_STEP), (ZERO_COMPARE_STEP, ZERO_RUN_STEP)]:
            with self.subTest(step=step):
                changed = original.replace(step, '').replace(destination, destination + step)
                self.rejected(path, original, changed)

    def test_zero_negative_checks_must_run_once_in_repository_truth(self):
        path = 'scripts/ci/ci_job.sh'
        command = '    python3 scripts/ci/test_zero_locality_cost.py\n'
        for replacement in ['', '    true # omitted zero checker tests\n', command + command]:
            with self.subTest(replacement=replacement):
                self.rejected(path, command, replacement)
        original = (self.root / path).read_text()
        changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
        self.rejected(path, original, changed)

    def test_one_zero_native_execution_cannot_be_removed_skipped_or_replaced(self):
        for replacement in ['', ONE_ZERO_RUN_STEP.replace('        if: always()\n', ''),
                            ONE_ZERO_RUN_STEP.replace('run: env -u CARGO_INCREMENTAL python3', 'run: true # python3'),
                            ONE_ZERO_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3', 'python3'),
                            ONE_ZERO_RUN_STEP.replace('env -u CARGO_INCREMENTAL python3',
                                                      'env -u CARGO_INCREMENTAL -u RUSTFLAGS python3'),
                            ONE_ZERO_RUN_STEP.replace(' --suite one-zero-locality', ' --suite zero-locality')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', ONE_ZERO_RUN_STEP, replacement)

    def test_one_zero_comparison_cannot_be_removed_skipped_or_relabelled(self):
        for replacement in ['', ONE_ZERO_COMPARE_STEP.replace('        if: always()\n', ''),
                            ONE_ZERO_COMPARE_STEP.replace('run: python3', 'run: true # python3'),
                            ONE_ZERO_COMPARE_STEP.replace(' --suite one-zero-locality', ' --suite zero-locality')]:
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', ONE_ZERO_COMPARE_STEP, replacement)

    def test_one_zero_suite_cannot_move_to_the_wrong_job(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        original = (self.root / path).read_text()
        for step, destination in [(ONE_ZERO_RUN_STEP, ONE_ZERO_COMPARE_STEP),
                                  (ONE_ZERO_COMPARE_STEP, ONE_ZERO_RUN_STEP)]:
            with self.subTest(step=step):
                changed = original.replace(step, '').replace(destination, destination + step)
                self.rejected(path, original, changed)

    def test_one_zero_execution_and_comparison_keep_their_separate_sequential_steps(self):
        for first, second in [(ZERO_RUN_STEP, ONE_ZERO_RUN_STEP),
                              (ZERO_COMPARE_STEP, ONE_ZERO_COMPARE_STEP)]:
            with self.subTest(step=second):
                self.rejected('.github/workflows/trnm-required-baseline.yml', first + second, second + first)
                self.rejected('.github/workflows/trnm-required-baseline.yml', second, second + second)

    def test_one_zero_negative_checks_must_run_once_in_repository_truth(self):
        path = 'scripts/ci/ci_job.sh'
        command = '    python3 scripts/ci/test_one_zero_locality_cost.py\n'
        for replacement in ['', '    true # omitted one-zero checker tests\n', command + command]:
            with self.subTest(replacement=replacement):
                self.rejected(path, command, replacement)
        original = (self.root / path).read_text()
        changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
        self.rejected(path, original, changed)

    def test_finite_tests_cannot_replace_fuzz_invocation(self):
        self.rejected('scripts/ci/ci_job.sh', '    python3 scripts/ci/run_fuzz_smoke.py\n', '')

    def test_config_file_is_not_dependency_execution(self):
        self.rejected('scripts/ci/ci_job.sh', '    python3 scripts/ci/run_supply_chain.py\n', '')

    def test_native_storage_migration_and_multiproof_oracles_follow_actual_workspace(self):
        path = 'scripts/ci/ci_job.sh'
        text = (self.root / path).read_text()
        lines = [line + '\n' for line in text.splitlines()
                 if line.startswith('      python3 formal/pon-nakamoto-v1/') and
                 any(name in line for name in ['native_authenticated_storage_oracle.py',
                                               'account_multiproof_oracle.py'])]
        self.assertEqual(len(lines), 5)
        for line in lines:
            for replacement in ['', line.replace('python3 ', 'true # python3 '), line + line]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected(path, line, replacement)
        for selector in ['TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR',
                         'TRNM_AUTHENTICATED_MIGRATION_EXPORT', 'TRNM_ACCOUNT_MULTIPROOF_VECTORS']:
            self.rejected(path, 'export ' + selector + '=', 'export OMITTED_' + selector + '=')
        self.rejected(path, '--migration-source "$TRNM_AUTHENTICATED_MIGRATION_EXPORT/source.sqlite" ', '')

    def test_public_campaign_must_execute_and_preserve_its_report(self):
        self.rejected('scripts/ci/ci_job.sh',
                      '    python3 scripts/run_public_v3_service_campaign.py --out ',
                      '    true # omitted campaign output ')

    def test_continuity_oracle_cannot_be_removed_or_replaced_with_true(self):
        for replacement in ['', '    true # omitted continuity transitions\n']:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', CONTINUITY_TRANSITIONS, replacement)

    def test_continuity_oracle_requires_actual_built_binary(self):
        self.rejected('scripts/ci/ci_job.sh', CONTINUITY_BUILD, '')
        self.rejected('scripts/ci/ci_job.sh', 'realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuity_transition_vectors"',
                      'printf %s /old/unverified/continuity_transition_vectors')

    def test_continuity_oracle_cannot_move_to_another_lane(self):
        original = (self.root / 'scripts/ci/ci_job.sh').read_text()
        changed = original.replace(CONTINUITY_TRANSITIONS, '').replace('  fuzz-smoke)\n',
                                                                             '  fuzz-smoke)\n' + CONTINUITY_TRANSITIONS)
        self.rejected('scripts/ci/ci_job.sh', original, changed)

    def test_paired_work_oracle_cannot_be_removed_skipped_or_reuse_historical_output(self):
        for replacement in ['', '    true # omitted paired work oracle\n',
                            PAIRED_WORK_ORACLE.replace('realpath -e', 'printf %s'),
                            PAIRED_WORK_ORACLE.replace('/paired-work"', '/old-paired-work"'),
                            PAIRED_WORK_ORACLE + PAIRED_WORK_ORACLE]:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', PAIRED_WORK_ORACLE, replacement)

    def test_zero_work_oracle_requires_current_release_binary_fresh_output_and_full_execution(self):
        for replacement in ['', '    true # omitted zero native/scalar byte comparison\n',
                            ZERO_WORK_ORACLE.replace('realpath -e', 'printf %s'),
                            ZERO_WORK_ORACLE.replace('TRNM_ZERO_WORK=', 'TRNM_PAIRED_WORK='),
                            ZERO_WORK_ORACLE.replace('TRNM_ZERO_WORK_OUTPUT=', 'OMITTED_OUTPUT='),
                            ZERO_WORK_ORACLE.replace('/zero-work"', '/prior-zero-work"'),
                            ZERO_WORK_ORACLE.replace('pon_zero_io', 'pon_paired_io'),
                            ZERO_WORK_ORACLE * 2]:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', ZERO_WORK_ORACLE, replacement)
        original = (self.root / 'scripts/ci/ci_job.sh').read_text()
        changed = original.replace(ZERO_WORK_ORACLE, '').replace('  fuzz-smoke)\n',
                                                                  '  fuzz-smoke)\n' + ZERO_WORK_ORACLE)
        self.rejected('scripts/ci/ci_job.sh', original, changed)
        self.rejected('scripts/ci/ci_job.sh', PAIRED_WORK_ORACLE + ZERO_WORK_ORACLE,
                      ZERO_WORK_ORACLE + PAIRED_WORK_ORACLE)

    def test_paired_and_model_window_oracles_cannot_move_to_another_lane(self):
        original = (self.root / 'scripts/ci/ci_job.sh').read_text()
        for command in [PAIRED_WORK_ORACLE, MODEL_WINDOW_ORACLE]:
            changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
            with self.subTest(command=command):
                self.rejected('scripts/ci/ci_job.sh', original, changed)

    def test_model_window_history_oracle_must_execute_once(self):
        for replacement in ['', '    true # omitted model-window checks\n', MODEL_WINDOW_ORACLE * 2]:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', MODEL_WINDOW_ORACLE, replacement)

    def test_archive_oracle_requires_release_build_and_both_actual_checks(self):
        for replacement in ['', '    true # omitted native archive and oracle\n',
                            ACCOUNT_ARCHIVE_ORACLE.splitlines(keepends=True)[0],
                            ACCOUNT_ARCHIVE_ORACLE.splitlines(keepends=True)[1],
                            ACCOUNT_ARCHIVE_ORACLE * 2]:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', ACCOUNT_ARCHIVE_ORACLE, replacement)
        self.rejected('scripts/ci/ci_job.sh', NODE_EXAMPLE_BUILD, '')
        self.rejected('scripts/ci/ci_job.sh', NODE_EXAMPLE_BUILD + ACCOUNT_ARCHIVE_ORACLE,
                      ACCOUNT_ARCHIVE_ORACLE + NODE_EXAMPLE_BUILD)

    def test_archive_oracle_and_negative_checks_cannot_move_to_another_lane(self):
        path = 'scripts/ci/ci_job.sh'
        original = (self.root / path).read_text()
        for command in [ACCOUNT_ARCHIVE_ORACLE, '    python3 scripts/ci/test_account_archive_conformance.py\n']:
            changed = original.replace(command, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + command)
            with self.subTest(command=command):
                self.rejected(path, original, changed)

    def test_account_execution_oracles_require_release_build_and_all_actual_checks(self):
        for replacement in ['', '    true # omitted account execution and oracle\n',
                            *ACCOUNT_EXECUTION_ORACLE.splitlines(keepends=True),
                            ACCOUNT_EXECUTION_ORACLE * 2]:
            with self.subTest(replacement=replacement):
                self.rejected('scripts/ci/ci_job.sh', ACCOUNT_EXECUTION_ORACLE, replacement)
        for command in ACCOUNT_EXECUTION_ORACLE.splitlines(keepends=True):
            with self.subTest(missing=command):
                self.rejected('scripts/ci/ci_job.sh', command, '')
        self.rejected('scripts/ci/ci_job.sh', NODE_EXAMPLE_BUILD, '')
        self.rejected('scripts/ci/ci_job.sh', ACCOUNT_ARCHIVE_ORACLE + ACCOUNT_EXECUTION_ORACLE,
                      ACCOUNT_EXECUTION_ORACLE + ACCOUNT_ARCHIVE_ORACLE)

    def test_account_execution_and_receipt_controls_cannot_move_or_duplicate(self):
        path = 'scripts/ci/ci_job.sh'
        original = (self.root / path).read_text()
        command = '    python3 scripts/ci/test_run_account_execution_conformance.py\n'
        for replacement in ['', '    true # omitted execution receipt checks\n', command + command]:
            with self.subTest(replacement=replacement):
                self.rejected(path, command, replacement)
        for moved in [ACCOUNT_EXECUTION_ORACLE, command]:
            changed = original.replace(moved, '').replace('  fuzz-smoke)\n', '  fuzz-smoke)\n' + moved)
            with self.subTest(command=moved):
                self.rejected(path, original, changed)

    def test_both_model_oracles_cannot_be_removed_or_replaced_with_true(self):
        for filename in ['test_model_composition_oracle.py', 'test_model_composition.py']:
            command = '      python3 formal/pon-nakamoto-v1/' + filename + ' -v\n'
            for replacement in ['', '      true # omitted model oracle\n']:
                with self.subTest(filename=filename, replacement=replacement):
                    self.rejected('scripts/ci/ci_job.sh', command, replacement)

    def test_model_observations_require_unique_directory_and_run_selector(self):
        for command in ['      test ! -e "$TRNM_MODEL_COMPOSITION_VECTORS"\n',
                        '      test ! -L "$TRNM_MODEL_COMPOSITION_VECTORS"\n',
                        '      export TRNM_MODEL_COMPOSITION_RUN_ID="$(python3 -c \'import secrets; print(secrets.token_hex(32))\')"\n']:
            with self.subTest(command=command):
                self.rejected('scripts/ci/ci_job.sh', command, '')

    def test_signed_state_oracle_requires_fresh_native_outputs_and_actual_checks(self):
        for command in [
                '      export TRNM_AUTHENTICATED_STATE_VECTORS="$trnm_model_receipt_root/authenticated-state/native.json"\n',
                '      test ! -e "$trnm_model_receipt_root/authenticated-state"\n',
                '      test ! -L "$trnm_model_receipt_root/authenticated-state"\n',
                '      python3 formal/pon-nakamoto-v1/test_authenticated_state_archive_oracle.py -v\n',
                '      python3 formal/pon-nakamoto-v1/authenticated_state_archive_oracle.py "$TRNM_AUTHENTICATED_STATE_VECTORS" "$trnm_model_receipt_root/authenticated-state/native.sqlite" --output "$trnm_model_receipt_root/authenticated-state/oracle.json"\n']:
            for replacement in ['', '      true # omitted signed-state observation\n']:
                with self.subTest(command=command, replacement=replacement):
                    self.rejected('scripts/ci/ci_job.sh', command, replacement)

    def test_signed_state_oracle_dependencies_are_installed_in_both_rust_lanes(self):
        workflow = '.github/workflows/trnm-required-baseline.yml'
        for replacement in ['', SIGNED_STATE_PYTHON.replace('--only-binary=:all:', '--no-deps'),
                            SIGNED_STATE_PYTHON.replace('          echo "$RUNNER_TEMP/pon-state-env/bin" >> "$GITHUB_PATH"\n', '')]:
            with self.subTest(replacement=replacement):
                self.rejected(workflow, SIGNED_STATE_PYTHON, replacement)
        self.rejected(workflow,
                      "if: matrix.lane == 'protocol-contract' || matrix.lane == 'external-evidence-contract' || matrix.lane == 'rust-baseline'",
                      "if: matrix.lane == 'protocol-contract' || matrix.lane == 'external-evidence-contract'")

    def test_obligation_export_and_both_reader_controls_are_mandatory_and_fresh(self):
        path = 'scripts/ci/ci_job.sh'
        lines = [
            '      export TRNM_OBLIGATION_RANGE_VECTORS="$trnm_model_receipt_root/obligation-range/native.json"\n',
            '      test ! -e "$trnm_model_receipt_root/obligation-range"\n',
            '      test ! -L "$trnm_model_receipt_root/obligation-range"\n',
            '      mkdir "$trnm_model_receipt_root/obligation-range"\n',
            '      python3 formal/pon-nakamoto-v1/test_obligation_range_oracle.py -v\n',
            '      python3 formal/pon-nakamoto-v1/obligation_range_oracle.py "$TRNM_OBLIGATION_RANGE_VECTORS" --output "$trnm_model_receipt_root/obligation-range/oracle.json"\n',
        ]
        for line in lines:
            for replacement in ['', '      true # omitted obligation range gate\n', line * 2]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected(path, line, replacement)
        self.rejected(path, lines[0], lines[0].replace('TRNM_OBLIGATION_RANGE_VECTORS=', 'WRONG_VECTORS='))
        self.rejected(path, lines[-1], lines[-1].replace('"$TRNM_OBLIGATION_RANGE_VECTORS"', '"/old/native.json"'))

    def test_zero_prefix_export_is_unique_to_workspace_then_independently_recomputed(self):
        path = 'scripts/ci/ci_job.sh'
        lines = [
            '      export TRNM_ZERO_PAIRED_PREFIX_OUTPUT="$trnm_model_receipt_root/zero-paired-prefix"\n',
            '      test ! -e "$TRNM_ZERO_PAIRED_PREFIX_OUTPUT"\n',
            '      test ! -L "$TRNM_ZERO_PAIRED_PREFIX_OUTPUT"\n',
            '      unset TRNM_ZERO_PAIRED_PREFIX_OUTPUT\n',
            '      python3 formal/pon-nakamoto-v1/test_zero_work.py --verify-prefix-export "$trnm_model_receipt_root/zero-paired-prefix" --output "$trnm_model_receipt_root/zero-paired-prefix-python"\n',
        ]
        for line in lines:
            for replacement in ['', '      true # omitted zero prefix gate\n', line * 2]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected(path, line, replacement)
        self.rejected(path, lines[0], lines[0].replace('TRNM_ZERO_PAIRED_PREFIX_OUTPUT=', 'WRONG_OUTPUT='))
        self.rejected(path, lines[2], lines[2] + '      mkdir "$TRNM_ZERO_PAIRED_PREFIX_OUTPUT"\n')
        self.rejected(path, lines[-1], lines[-1].replace('/zero-paired-prefix"', '/old-prefix"'))
        self.rejected(path, lines[-1], lines[-1].replace('/zero-paired-prefix-python"', '/zero-paired-prefix"'))

    def test_workspace_stdout_capture_is_mandatory_fresh_and_failure_preserving(self):
        lines = [line + '\n' for line in MODEL_OBSERVATION_BLOCK.splitlines()
                 if 'workspace-tests.log' in line]
        self.assertEqual(len(lines), 3)
        for line in lines:
            for replacement in ['', line * 2, line.replace('workspace-tests.log', 'old-workspace.log')]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected('scripts/ci/ci_job.sh', line, replacement)
        self.rejected('scripts/ci/ci_job.sh', lines[-1], lines[-1].replace('2>&1 | tee ', '2>&1 || tee '))

    def test_workspace_capture_executes_real_shell_and_retains_failure_output(self):
        # Actual shell processes with an explicitly synthetic cargo command,
        # not a native Rust or complete-workspace execution claim.
        block = '\n'.join(line for line in MODEL_OBSERVATION_BLOCK.splitlines()
                          if 'workspace-tests.log' in line) + '\n'
        with tempfile.TemporaryDirectory(prefix='workspace-capture-') as directory:
            root = Path(directory) / 'receipt with spaces'
            root.mkdir()
            env = {'PATH': '/usr/bin:/bin', 'TRNM_TEST_RECEIPT': str(root)}
            prelude = 'set -euo pipefail\ntrnm_model_receipt_root="$TRNM_TEST_RECEIPT"\n'
            failed = subprocess.run(['bash', '-c', prelude +
                "cargo() { printf '%s\n' 'synthetic stdout'; printf '%s\n' 'synthetic stderr' >&2; return 7; }\n" +
                block + 'touch "$TRNM_TEST_RECEIPT/incorrect-success"\n'], env=env,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(failed.returncode, 7, failed.stderr)
            log = root / 'workspace-tests.log'
            self.assertIn('synthetic stdout', log.read_text())
            self.assertIn('synthetic stderr', log.read_text())
            self.assertFalse((root / 'incorrect-success').exists())
            before = log.read_bytes()
            stale = subprocess.run(['bash', '-c', prelude +
                'cargo() { touch "$TRNM_TEST_RECEIPT/incorrect-start"; }\n' + block],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(stale.returncode, 0)
            self.assertEqual(log.read_bytes(), before)
            self.assertFalse((root / 'incorrect-start').exists())
            log.unlink()
            sink_failure = subprocess.run(['bash', '-c', prelude +
                'cargo() { return 0; }\ntee() { return 9; }\n' + block],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(sink_failure.returncode, 9)

    def test_full_capacity_and_account_verification_execute_exact_release_tests_sequentially(self):
        path = 'scripts/ci/ci_job.sh'
        commands = [line + '\n' for line in NATIVE_RELEASE_BLOCK.splitlines() if ' cargo test ' in line]
        self.assertEqual(len(commands), 4)
        for line in commands:
            for replacement in ['', line.replace('cargo test ', 'true # cargo test '),
                                line.replace(' --release ', ' '), line.replace(' --exact ', ' '),
                                line.replace(' --ignored ', ' '), line.replace('--test-threads=1', '--test-threads=4'),
                                line.replace('2>&1 | tee ', '2>&1 || tee '), line * 2]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected(path, line, replacement)
        self.rejected(path, commands[0], commands[0].replace(
            'native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover',
            'native_authenticated_signed_growth_branches_reopen_and_compact_queries'))
        self.rejected(path, commands[-1], commands[-1].replace('TRNM_NATIVE_ACCOUNT_VERIFY_COST_DIRECTORY=', 'WRONG_OUTPUT='))
        self.rejected(path, commands[-1], commands[-1].replace('/native-account-verification-cost"', '/old-cost"'))
        swapped = NATIVE_RELEASE_BLOCK.replace(commands[0], 'RELEASE_CONTROL_PLACEHOLDER\n')
        swapped = swapped.replace(commands[1], commands[0]).replace('RELEASE_CONTROL_PLACEHOLDER\n', commands[1])
        self.rejected(path, NATIVE_RELEASE_BLOCK, swapped)
        self.rejected(path, NATIVE_RELEASE_BLOCK, NATIVE_RELEASE_BLOCK * 2)

    def test_release_test_execution_checks_cannot_be_removed_relabelled_or_reordered(self):
        checks = [line for line in NATIVE_RELEASE_BLOCK.splitlines(keepends=True)
                  if 'python3 scripts/ci/check_required_native_test.py ' in line]
        self.assertEqual(len(checks), 4)
        for line in checks:
            for replacement in ['', line.replace('python3 ', 'true # python3 '), line * 2,
                                line.replace(' --test ', ' --test other::'),
                                line.replace('/native-', '/previous-native-')]:
                with self.subTest(line=line, replacement=replacement):
                    self.rejected('scripts/ci/ci_job.sh', line, replacement)
            previous = NATIVE_RELEASE_BLOCK.split(line)[0].splitlines(keepends=True)[-1]
            self.rejected('scripts/ci/ci_job.sh', previous + line, line + previous)

    def test_release_control_paths_cannot_reuse_or_overwrite_prior_observations(self):
        for line in NATIVE_RELEASE_BLOCK.splitlines(keepends=True):
            if 'test ! -e ' in line or 'test ! -L ' in line:
                with self.subTest(line=line):
                    self.rejected('scripts/ci/ci_job.sh', line, '')

    def test_release_control_pipeline_keeps_actual_shell_failure_and_output(self):
        # Exercise the exact shell block using an explicitly synthetic failing
        # cargo function. This checks pipeline failure retention, not a Rust run.
        with tempfile.TemporaryDirectory(prefix='trnm-release-pipeline-') as temporary:
            for failed_case in ['capacity', 'growth-v2', 'account']:
                root = Path(temporary) / ('receipt with spaces ' + failed_case)
                harness = '''set -euo pipefail
cargo() {
  case "$*" in
    *native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover*)
      printf '%s\\n' 'synthetic capacity stdout'
      printf '%s\\n' 'synthetic capacity stderr' >&2
      if test "$TRNM_TEST_FAILURE" = capacity; then return 7; fi
      printf '%s\\n' 'running 1 test' 'test account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover ... ok' 'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s' ;;
    *native_growth_reference_65537_signed_accounts_and_cold_reopen*)
      synthetic_growth_native ;;
    *native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen*)
      printf '%s\\n' 'synthetic bounded-growth stdout'
      printf '%s\\n' 'synthetic bounded-growth stderr' >&2
      if test "$TRNM_TEST_FAILURE" = growth-v2; then return 11; fi
      synthetic_growth_v2_native ;;
    *native_complete_account_verification_cost*)
      test "$TRNM_NATIVE_ACCOUNT_VERIFY_COST_DIRECTORY" = "$TRNM_CI_RECEIPT_DIR/native-account-verification-cost"
      printf '%s\\n' 'synthetic account stdout'
      printf '%s\\n' 'synthetic account stderr' >&2
      return 9 ;;
    *) return 97 ;;
  esac
}
'''
                result = subprocess.run(['bash', '-c', SYNTHETIC_GROWTH_PIPELINE + harness + NATIVE_RELEASE_BLOCK], cwd=self.root,
                                        env={'PATH': '/usr/bin:/bin', 'TRNM_CI_RECEIPT_DIR': str(root),
                                             'TRNM_TEST_FAILURE': failed_case},
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, {'capacity': 7, 'growth-v2': 11, 'account': 9}[failed_case], result.stderr)
                self.assertIn('synthetic capacity stdout', (root / 'native-capacity-release.log').read_text())
                self.assertIn('synthetic capacity stderr', (root / 'native-capacity-release.log').read_text())
                account = root / 'native-account-verification-cost.log'
                if failed_case in ['capacity', 'growth-v2']:
                    self.assertFalse(account.exists())
                else:
                    self.assertIn('synthetic account stdout', account.read_text())
                    self.assertIn('synthetic account stderr', account.read_text())
                if failed_case != 'capacity':
                    growth = root / 'native-growth-v2-release.log'
                    self.assertIn('synthetic bounded-growth stdout', growth.read_text())
                    self.assertIn('synthetic bounded-growth stderr', growth.read_text())

    def test_release_pipeline_rejects_successful_zero_ignored_wrong_or_incomplete_runs(self):
        # Synthetic libtest transcripts test the real shell/checker integration,
        # not the native capacity or account algorithms.
        harness = r'''set -euo pipefail
cargo() {
  case "$*" in
    *native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover*)
      stage=capacity
      name=account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover ;;
    *native_growth_reference_65537_signed_accounts_and_cold_reopen*)
      stage=growth
      name=store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen
      test "$TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY" = "$TRNM_CI_RECEIPT_DIR/native-growth-reference"
      mkdir "$TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY" ;;
    *native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen*)
      stage=growth-v2
      name=store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen
      test "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR" = "$TRNM_CI_RECEIPT_DIR/native-growth-v2"
      mkdir "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR"
      printf '%s\n' '{"scope":"synthetic shell control only"}' > "$TRNM_NATIVE_GROWTH_V2_EXPORT_DIR/native.json" ;;
    *native_complete_account_verification_cost*)
      stage=account
      name=account_archive_prototype::native_primitive_tests::native_complete_account_verification_cost ;;
    *) return 97 ;;
  esac
  printf '%s\n' "$stage" >> "$TRNM_TEST_CALLS"
  mode=pass
  if test "$stage" = "$TRNM_TEST_STAGE"; then mode="$TRNM_TEST_MODE"; fi
  if test "$mode" = zero; then
    printf '%s\n' 'running 0 tests' 'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s'
    return 0
  fi
  if test "$mode" = wrong; then name=wrong::test; fi
  printf '%s\n' 'running 1 test'
  printf 'test %s ... ok\n' "$name"
  if test "$mode" = incomplete; then return 0; fi
  if test "$mode" = ignored; then
    printf '%s\n' 'test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 9 filtered out; finished in 0.00s'
  else
    printf '%s\n' 'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s'
  fi
  if test "$mode" = nonzero; then return 23; fi
  return 0
}
'''
        with tempfile.TemporaryDirectory(prefix='trnm-release-outcomes-') as temporary:
            stages = ['capacity', 'growth', 'growth-v2', 'account']
            for stage in stages:
                for mode in ['pass', 'zero', 'ignored', 'wrong', 'incomplete', 'nonzero']:
                    with self.subTest(stage=stage, mode=mode):
                        output = Path(temporary) / f'{stage} {mode}'
                        calls = Path(temporary) / f'{stage}-{mode}.calls'
                        result = subprocess.run(['bash', '-c', SYNTHETIC_GROWTH_PIPELINE + harness + NATIVE_RELEASE_BLOCK],
                            cwd=self.root, env={'PATH': '/usr/bin:/bin',
                                'TRNM_CI_RECEIPT_DIR': str(output), 'TRNM_TEST_CALLS': str(calls),
                                'TRNM_TEST_STAGE': stage, 'TRNM_TEST_MODE': mode},
                            capture_output=True, text=True, timeout=10)
                        expected = 0 if mode == 'pass' else 23 if mode == 'nonzero' else 1
                        self.assertEqual(result.returncode, expected, result.stderr)
                        expected_calls = stages if mode == 'pass' else stages[:stages.index(stage) + 1]
                        self.assertEqual(calls.read_text().splitlines(), expected_calls)
                        self.assertTrue((output / 'native-capacity-release.log').is_file())
                        self.assertEqual((output / 'native-account-verification-cost.log').exists(),
                                         len(expected_calls) == 4)

    def test_model_observation_block_cannot_move_to_another_lane(self):
        original = (self.root / 'scripts/ci/ci_job.sh').read_text()
        changed = original.replace(MODEL_OBSERVATION_BLOCK, '').replace('  fuzz-smoke)\n',
                                                                              '  fuzz-smoke)\n' + MODEL_OBSERVATION_BLOCK)
        self.rejected('scripts/ci/ci_job.sh', original, changed)

    def test_model_oracles_must_precede_documentation_tests(self):
        self.rejected('scripts/ci/ci_job.sh', MODEL_OBSERVATION_BLOCK + NATIVE_RELEASE_BLOCK + RUST_DOCS,
                      RUST_DOCS + MODEL_OBSERVATION_BLOCK + NATIVE_RELEASE_BLOCK)

    def test_model_exports_cannot_leak_into_doc_or_clippy_commands(self):
        self.rejected('scripts/ci/ci_job.sh', '    )\n' + RUST_DOCS, RUST_DOCS + '    )\n')
        self.rejected('scripts/ci/ci_job.sh', '    )\n' + RUST_DOCS,
                      '    )\n    export TRNM_MODEL_COMPOSITION_VECTORS=/old/data\n' + RUST_DOCS)

    def test_workspace_test_cannot_be_replaced_skipped_or_duplicated(self):
        command = '      ' + RUST_ALL_TARGETS + ' 2>&1 | tee "$trnm_model_receipt_root/workspace-tests.log"\n'
        self.rejected('scripts/ci/ci_job.sh', command, '      true\n')
        self.rejected('scripts/ci/ci_job.sh', command, '      if false; then\n' + command + '      fi\n')
        self.rejected('scripts/ci/ci_job.sh', RUST_DOCS, '    ' + RUST_ALL_TARGETS + '\n' + RUST_DOCS)

    def test_merge_lane_cannot_test_head_instead(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '      TRNM_EXPECTED_SOURCE_SHA: ${{ github.sha }}',
                      '      TRNM_EXPECTED_SOURCE_SHA: ${{ github.event.pull_request.head.sha }}')

    def test_merge_lane_requires_all_actual_lanes(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      'lane: [repository-truth, protocol-contract, fuzz-smoke, external-evidence-contract]',
                      'lane: [repository-truth]')

    def test_merge_identity_is_not_itself_an_execution_pass(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      'run: bash scripts/ci/ci_job.sh "${{ matrix.lane }}"',
                      'run: python3 scripts/ci/check_repository.py')

    def test_required_rust_fanins_cannot_skip_ignore_or_invent_shards(self):
        path = '.github/workflows/trnm-required-baseline.yml'
        for worker in ['rust-baseline-shards', 'prospective-rust-shards']:
            for before, after in [
                ('    needs: ' + worker + '\n', ''),
                ('TRNM_RUST_SHARD_RESULT: ${{ needs.' + worker + '.result }}', 'TRNM_RUST_SHARD_RESULT: success')]:
                with self.subTest(before=before):
                    self.rejected(path, before, after)
        for before, after in [
            ('    if: always()\n    runs-on: ubuntu-24.04\n    timeout-minutes: 180',
             '    if: success()\n    runs-on: ubuntu-24.04\n    timeout-minutes: 180'),
            ("${{ always() && github.event_name == 'pull_request' }}", "github.event_name == 'pull_request'"),
            ('shard: [runtime, quality]', 'shard: [runtime]'),
            ('name: prospective-merge (rust-baseline)', 'name: unrelated-rust'),
            ('      - name: Run retained Rust shard\n        run:', '      - name: Run retained Rust shard\n        if: false\n        run:'),
            ('--dependency-result "$TRNM_RUST_SHARD_RESULT"', '--dependency-result success'),
            ('          path: |\n            ${{ runner.temp }}/ci-observations/rust-shard.json\n            ${{ runner.temp }}/ci-observations/rust-shard.sh\n',
             '          path: ${{ runner.temp }}/ci-observations/\n'),
            ('rust-shard-head-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}-*', 'rust-shard-head-*'),
            ('rust-shard-prospective-merge-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}-*', 'rust-shard-prospective-merge-*')]:
            with self.subTest(before=before):
                self.rejected(path, before, after)

    def test_failure_cannot_be_marked_ignorable(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '  fuzz-smoke:\n', '  fuzz-smoke:\n    continue-on-error: true\n')

    def test_arm_label_cannot_be_replaced_with_an_x64_runner(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '            runner: ubuntu-24.04-arm', '            runner: ubuntu-24.04')

    def test_architecture_label_is_not_native_cost_execution(self):
        command = 'run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_cross_arch_cost.py --arch "${{ matrix.arch }}"'
        for replacement in ('run: python3 scripts/ci/check_ci_contract.py',
                            command.replace('env -u CARGO_INCREMENTAL python3', 'python3'),
                            command.replace('env -u CARGO_INCREMENTAL python3',
                                            'env -u CARGO_INCREMENTAL -u RUSTFLAGS python3')):
            with self.subTest(replacement=replacement):
                self.rejected('.github/workflows/trnm-required-baseline.yml', command, replacement)

    def test_architecture_failure_cannot_cancel_the_other_observation(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '      fail-fast: false', '      fail-fast: true')

    def test_cross_architecture_checker_requires_retained_actual_artifacts(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '          merge-multiple: false', '          merge-multiple: true')

    def test_cross_architecture_comparison_cannot_use_a_prior_attempt(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      '          pattern: cost-*-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}',
                      '          pattern: cost-*')

    def test_cross_architecture_comparison_must_execute(self):
        self.rejected('.github/workflows/trnm-required-baseline.yml',
                      'run: python3 scripts/ci/check_cross_arch_cost.py --artifacts ',
                      'run: true # omitted comparison ')

    def test_cross_architecture_negative_checks_must_execute(self):
        self.rejected('scripts/ci/ci_job.sh', '    python3 scripts/ci/test_cross_arch_cost.py\n', '')

    def test_tool_install_is_pinned(self):
        self.rejected('scripts/ci/tool-versions.env', 'TRNM_FUZZ_TOOLCHAIN=nightly-2026-10-01',
                      'TRNM_FUZZ_TOOLCHAIN=nightly')

    def test_fuzz_cannot_silently_use_newer_shared_crypto_dependencies(self):
        packages = tomllib.loads((self.root / 'tests/fuzz/Cargo.lock').read_text())['package']
        version = next(p['version'] for p in packages if p['name'] == 'ed25519-dalek')
        self.rejected('tests/fuzz/Cargo.lock',
                      f'name = "ed25519-dalek"\nversion = "{version}"',
                      'name = "ed25519-dalek"\nversion = "99.0.0"')

    def test_fuzz_cannot_omit_required_local_serialization_edges(self):
        path = self.root / 'tests/fuzz/Cargo.lock'
        text = path.read_text()
        start = text.index('name = "trnm-data-availability"')
        end = text.index('[[package]]', start)
        package = text[start:end]
        for dependency in ('serde', 'serde_json'):
            with self.subTest(dependency=dependency):
                changed = package.replace(' "' + dependency + '",\n', '')
                self.assertNotEqual(package, changed)
                self.rejected('tests/fuzz/Cargo.lock', package, changed)

    def test_summary_is_derived_and_cannot_promote_a_manual_claim(self):
        path = self.root / DESTINATION
        original = path.read_text()
        try:
            path.write_text(original + '\nAll modules accepted.\n')
            with self.assertRaises(ValueError):
                current_validate(self.root)
            path.write_text(markdown(projection(self.root)))
            current_validate(self.root)
        finally:
            path.write_text(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
