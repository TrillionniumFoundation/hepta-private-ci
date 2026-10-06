import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hepta_fixed_bazel as fixed
import hepta_bazel_cache_pilot as pilot


class FixedQualificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.bep = self.directory / 'events.json'
        self.labels = fixed.GROUPS['windows-delete-diagnostic']

    def events(self):
        return [{'id': {'testSummary': {'label': label}},
                 'testSummary': {'overallStatus': 'PASSED', 'totalRunCount': 1}}
                for label in self.labels]

    def write(self, events):
        self.bep.write_text(''.join(json.dumps(event) + '\n' for event in events))

    def test_exact_fixed_targets_fresh_actions_pass(self):
        self.write(self.events())
        result = fixed.verify_bep(self.bep, self.labels)
        self.assertEqual(set(result['targets']), set(self.labels))
        self.assertEqual(len(result['bep_sha256']), 64)

    def test_missing_partial_zero_cached_and_failed_targets_reject(self):
        for mutation in ('none', 'partial', 'zero', 'cached', 'failed', 'duplicate', 'wrong'):
            with self.subTest(mutation=mutation):
                events = self.events()
                if mutation == 'none': events = []
                elif mutation == 'partial': events.pop()
                elif mutation == 'zero': events[0]['testSummary']['totalRunCount'] = 0
                elif mutation == 'cached': events[0]['testSummary']['totalNumCached'] = 1
                elif mutation == 'failed': events[0]['testSummary']['overallStatus'] = 'FAILED'
                elif mutation == 'duplicate': events.append(events[0])
                elif mutation == 'wrong': events[0]['id']['testSummary']['label'] = '//unrelated:test'
                self.write(events)
                with self.assertRaises(ValueError): fixed.verify_bep(self.bep, self.labels)

    def test_queue_controls_and_integration_each_require_fresh_results(self):
        self.labels = fixed.GROUPS['windows-queue-diagnostic']
        self.write(self.events())
        self.assertEqual(set(fixed.verify_bep(self.bep, self.labels)['targets']), set(self.labels))
        for missing in self.labels:
            self.write([event for event in self.events()
                        if event['id']['testSummary']['label'] != missing])
            with self.assertRaises(ValueError):
                fixed.verify_bep(self.bep, self.labels)

    def test_containment_keeps_boundary_repro_and_support_reporting_targets(self):
        self.labels = fixed.GROUPS['windows-legacy-containment']
        self.assertEqual(self.labels, (
            '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests',
            '//codex-rs/sandboxing:sandboxing-unit-tests',
        ))
        self.write(self.events())
        self.assertEqual(set(fixed.verify_bep(self.bep, self.labels)['targets']), set(self.labels))
        for missing in self.labels:
            self.write([event for event in self.events()
                        if event['id']['testSummary']['label'] != missing])
            with self.assertRaises(ValueError):
                fixed.verify_bep(self.bep, self.labels)

    def test_flaky_outcome_is_retained_not_hidden(self):
        events = self.events(); events[0]['testSummary']['overallStatus'] = 'FLAKY'
        self.write(events)
        result = fixed.verify_bep(self.bep, self.labels)
        self.assertEqual(result['targets'][self.labels[0]]['overallStatus'], 'FLAKY')
        self.assertEqual(result['flaky_targets'], [self.labels[0]])

    def test_oversized_line_and_expired_reader_reject(self):
        self.bep.write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'bounded'): fixed.verify_bep(self.bep, self.labels)
        self.write(self.events())
        with patch.object(fixed.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(ValueError, 'deadline'): fixed.verify_bep(self.bep, self.labels)

    def test_delayed_setup_reduces_native_budget(self):
        self.assertEqual(fixed.budget_minutes(100, 100), 45)
        self.assertEqual(fixed.budget_minutes(100, 701), 34)
        for now in (2800, 2750, 99, float('nan')):
            with self.assertRaises(ValueError): fixed.budget_minutes(100, now)

    @patch.dict(fixed.os.environ, {"HEPTA_BAZEL_BASH": r"C:\Program Files\Git\bin\bash.exe"})
    def test_windows_commands_share_exact_native_platform_and_no_cached_tests(self):
        for group in ('windows-delete-diagnostic', 'windows-queue-diagnostic', 'windows-legacy-containment'):
            command = fixed.windows_command(group, self.directory)
            self.assertIn('--windows-msvc-host-platform', command)
            self.assertIn('--platforms=//:windows_x86_64_msvc', command)
            self.assertIn('--nocache_test_results', command)
            self.assertEqual('--keep_going' in command, group == 'windows-legacy-containment')
            self.assertEqual('--test_output=all' in command, group == 'windows-legacy-containment')
            self.assertEqual(command[-len(fixed.GROUPS[group]):], list(fixed.GROUPS[group]))
            self.assertNotIn("//codex-rs/core:core-unit-tests", command)
            self.assertNotIn("//codex-rs/windows-sandbox-rs:windows-sandbox-rs-helper_manifest-test", command)
            self.assertNotIn('//...', command)
        self.assertEqual(fixed.GROUPS['windows-queue-diagnostic'], (
            '//codex-rs/core/tests/common:common-unit-tests',
            '//codex-rs/ext/queue:queue-queue_service-test',
        ))
        with self.assertRaises(ValueError): fixed.windows_command('linux-supervisor', self.directory)

    def test_bare_or_relative_bash_is_rejected_even_with_path_available(self):
        for value in ('', 'bash', 'bash.exe', r'bin\bash.exe', r'C:\Windows\System32\wsl.exe'):
            with self.subTest(value=value), patch.dict(fixed.os.environ, {'HEPTA_BAZEL_BASH': value, 'PATH': r'C:\Windows\System32'}):
                with self.assertRaisesRegex(ValueError, 'absolute Actions Git Bash'):
                    fixed.windows_command('windows-delete-diagnostic', self.directory)

    def test_absolute_msys_shell_without_exe_keeps_its_directory(self):
        with patch.dict(fixed.os.environ, {'HEPTA_BAZEL_BASH': r'C:\Program Files\Git\usr\bin\bash'}):
            command = fixed.windows_command('windows-delete-diagnostic', self.directory)
        self.assertEqual(command[0], r'C:\Program Files\Git\usr\bin\bash.exe')

    def test_containment_step_passes_the_actual_running_shell(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/bazel.yml').read_text()
        self.assertEqual(text.count('export HEPTA_BAZEL_BASH="$(cygpath -w "$BASH")"'), 1)

    def test_linux_command_is_only_supervisor(self):
        command = pilot.native_command(Path('/source'), self.directory)
        self.assertEqual(command[-1:], list(fixed.GROUPS['linux-supervisor']))
        self.assertNotIn('//...', command)
        self.assertIn('--nocache_test_results', command)

    def test_bounded_raw_bep_tail_survives_invalid_json(self):
        self.bep.write_bytes(b'prefix' * 100 + b'failed target details')
        output = self.directory / 'tail.jsonl'
        result = fixed.retain_bep_tail(self.bep, output, maximum_bytes=40)
        self.assertTrue(result['tail_truncated'])
        self.assertTrue(result['may_begin_mid_record'])
        self.assertEqual(result['captured_bytes'], 40)
        self.assertTrue(output.read_bytes().endswith(b'failed target details'))

    def test_atomic_receipt_failure_preserves_running_record(self):
        receipt = self.directory / 'receipt.json'
        receipt.write_text('{"status":"running"}')
        with patch.object(fixed.os, 'replace', side_effect=OSError('interrupted replacement')):
            with self.assertRaises(OSError): fixed.replace_receipt(receipt, {'status': 'passed'})
        self.assertEqual(json.loads(receipt.read_text())['status'], 'running')
        fixed.replace_receipt(receipt, {'status': 'failed'})
        self.assertEqual(json.loads(receipt.read_text())['status'], 'failed')

    def test_concurrency_isolates_scoped_groups_from_ordinary(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/bazel.yml').read_text()
        group = next(line for line in text.splitlines() if line.startswith('  group: concurrency-group::'))
        suffix = "${{ inputs.qualification-group != '' && inputs.qualification-group != 'full' && format('::diagnostic-{0}', inputs.qualification-group) || '' }}"
        self.assertTrue(group.endswith(suffix))
        ordinary = group.removesuffix(suffix)
        self.assertIn("github.ref_name == 'main' && format('::{0}', github.run_id)", ordinary)
        resolved = {choice: ordinary + ('::diagnostic-' + choice if choice not in ('', 'full') else '')
                    for choice in ('', 'full', 'linux-supervisor', 'windows-platform')}
        self.assertEqual(resolved[''], resolved['full'])
        self.assertEqual(len(set(resolved.values())), 3)

    def test_workflow_full_default_and_no_cache_upload(self):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/bazel.yml'
        text = workflow.read_text()
        self.assertIn('default: full', text)
        self.assertIn("inputs.qualification-group == '' || inputs.qualification-group == 'full'", text)
        diagnostic = text[text.index('  fixed-linux-supervisor:'):]
        self.assertNotIn('actions/cache/save', diagnostic)
        self.assertNotIn('actions/cache/restore', diagnostic)
        self.assertNotIn('secrets.', diagnostic)
        self.assertNotIn('matrix:', diagnostic)
        self.assertIn('reject-unknown-diagnostic:', diagnostic)
        self.assertIn('fromJSON(steps.delete-budget.outputs.minutes)', diagnostic)
        self.assertNotIn('steps.queue-budget', diagnostic)
        self.assertIn('--group windows-legacy-containment', diagnostic)


if __name__ == '__main__':
    unittest.main()
