"""Real-source, fail-closed original CPython selected upstream-test regressions."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from memory_original_upstream_replay import (
    MODULE_SHA,
    PHASES,
    PROFILE,
    SRC_MODULE,
    SRC_TEST,
    TEST_SHA,
    WORKER_SHA256,
    execute,
    independent_check,
    independent_rescore,
    method_provenance,
)
from memory_original_upstream_worker import CASES, SCHEMA
from real_source_reader_probe import canonical, digest, real_source


class OriginalSelectedUpstreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src, reopen = os.environ.get('MEMORY_REAL_SOURCE_ZIP'), os.environ.get('MEMORY_REOPEN_ZIP')
        if not src or not reopen:
            raise RuntimeError('both original SHA-pinned Git archives are mandatory')
        cls.source_zip, cls.reopen_zip = Path(src), Path(reopen)
        cls.original = real_source(cls.source_zip, cls.reopen_zip)
        cls.worker = Path(__file__).with_name('memory_original_upstream_worker.py')
        cls.checked = execute(cls.original)
        cls.provenance = method_provenance(cls.original[1][SRC_TEST])

    def test_real_original_success_and_fault_rollback(self):
        r = self.checked
        self.assertEqual(r['schema'], PROFILE)
        self.assertEqual(r['original_module_sha256'], MODULE_SHA)
        self.assertEqual(r['original_test_file_sha256'], TEST_SHA)
        self.assertEqual(r['frozen_test_worker_sha256'], WORKER_SHA256)
        self.assertEqual(r['unique_original_test_methods'], 14)
        self.assertEqual(r['total_original_test_invocations'], 70)
        self.assertEqual(r['injected_behavioral_faults_detected'], 2)
        self.assertEqual(r['clean_process_rollback_controls_passed'], 2)
        self.assertEqual(r['baseline_original_tests_passed'], 14)
        self.assertEqual([x['passed'] for x in r['executions']], [14, 13, 13, 14, 14])
        self.assertEqual([x['failed'] for x in r['executions']],
                         [[], ['HeaderTests.test_putheader'], ['BasicTest.test_send'], [], []])

    def test_real_methods_unmodified_and_pinned(self):
        self.assertEqual(len(self.provenance), len(CASES))
        self.assertEqual(set(x['case'] for x in self.provenance),
                         {a + '.' + b for a, b in CASES})
        self.assertEqual({x['start_line'] for x in self.provenance},
                         {x['start_line'] for x in self.checked['predeclared_original_upstream_tests']})
        self.assertTrue(all(len(x['method_sha256']) == 64 for x in self.provenance))
        self.assertTrue(self.checked['original_source_and_tests_unchanged'])
        self.assertFalse(self.checked['original_upstream_test_methods_rewritten'])

    def test_real_report_reproducible_in_five_new_subprocesses(self):
        self.assertEqual(execute(self.original), self.checked)

    def test_no_new_pretrained_or_production_promotion(self):
        r = self.checked
        self.assertIsNone(r['real_program_bug_repair_success'])
        self.assertIsNone(r['learned_memory_task_gain'])
        self.assertIsNone(r['complete_lifecycle_tco'])
        self.assertEqual(r['independent_future_task_families'], 0)
        self.assertEqual(r['pretrained_model_calls'], 0)
        self.assertFalse(r['original_upstream_full_suite_executed'])
        self.assertFalse(r['production_qualified'])
        self.assertTrue(r['fault_detection_is_not_autonomous_repair'])

    def test_wrong_original_module_rejected(self):
        files, blobs = self.original
        changed = dict(blobs)
        changed[SRC_MODULE] = b'# mutated' + blobs[SRC_MODULE]
        with self.assertRaisesRegex(ValueError, 'original evaluation Git snapshot mutated'):
            execute((files, changed))

    def test_wrong_original_test_rejected(self):
        files, blobs = self.original
        changed = dict(blobs)
        changed[SRC_TEST] = blobs[SRC_TEST].replace(b'test_putheader', b'test_butheader', 1)
        with self.assertRaisesRegex(ValueError, 'original evaluation Git snapshot mutated'):
            execute((files, changed))

    def test_wrong_inventory_partition_rejected(self):
        files, blobs = self.original
        changed = copy.deepcopy(files)
        next(x for x in changed if (x['repo'], x['path']) == SRC_TEST)['partition'] = 'train'
        with self.assertRaisesRegex(ValueError, 'original evaluation Git snapshot mutated'):
            execute((changed, blobs))

    def test_missing_source_member_rejected(self):
        files, blobs = self.original
        changed = dict(blobs)
        del changed[SRC_TEST]
        with self.assertRaisesRegex(ValueError, 'original evaluation Git snapshot mutated'):
            execute((files, changed))

    def test_pinned_worker_source_tamper_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            replacement = Path(tmp) / 'worker.py'
            replacement.write_bytes(self.worker.read_bytes() + b'\n# tampered\n')
            with self.assertRaisesRegex(ValueError, 'worker differs'):
                execute(self.original, worker_path=replacement)

    def test_pinned_worker_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            replacement = Path(tmp) / 'worker.py'
            replacement.symlink_to(self.worker)
            with self.assertRaisesRegex(ValueError, 'worker differs'):
                execute(self.original, worker_path=replacement)

    def test_upstream_test_ast_name_mutation_rejected(self):
        original = self.original[1][SRC_TEST]
        mutated = original.replace(b'    def test_send(self):', b'    def test_sendXself:', 1)
        with self.assertRaisesRegex(ValueError, 'upstream unit-test SHA mismatch'):
            method_provenance(mutated)

    def test_missing_original_test_receipt_refused(self):
        rec = self._local_worker('none')
        rec['passed'].pop()
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_self_reported_success_refused(self):
        rec = self._local_worker('corrupt-send')
        rec['passed'].append('BasicTest.test_send')
        rec['failed'] = []
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'send-fault', self.provenance)

    def test_fake_fault_profile_refused(self):
        rec = self._local_worker('none')
        rec['fault'] = 'corrupt-send'
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_full_suite_success_refused(self):
        rec = self._local_worker('none')
        rec['entire_original_upstream_test_suite_executed'] = True
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_original_tests_rewritten_refused(self):
        rec = self._local_worker('none')
        rec['tests_rewritten_to_pass'] = True
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_independent_test_source_provenance_refused(self):
        rec = self._local_worker('none')
        rec['original_test_method_sources'][0]['method_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_pretrained_reader_refused(self):
        rec = self._local_worker('none')
        rec['pretrained_reader_calls'] = 36
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_fake_network_access_refused(self):
        rec = self._local_worker('none')
        rec['network_permitted'] = True
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'baseline', self.provenance)

    def test_wrong_expected_failure_rejected(self):
        rec = self._local_worker('corrupt-header')
        rec['failed'] = ['BasicTest.test_send']
        with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
            independent_check(rec, 'header-fault', self.provenance)

    def test_no_overwrite_on_real_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.json'
            journals = Path(tmp) / 'journals'
            cli = [sys.executable, str(Path(__file__).with_name('memory_original_upstream_replay.py')),
                   'run', '--source-zip', str(self.source_zip),
                   '--reopen-zip', str(self.reopen_zip),
                   '--journals', str(journals), '--output', str(output)]
            first = subprocess.run(cli, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)},
                                   text=True, capture_output=True, timeout=40)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(output.read_bytes(), canonical(self.checked) + b"\n")
            original = output.read_bytes()
            second = subprocess.run(cli, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)},
                                    text=True, capture_output=True, timeout=40)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            scored = Path(tmp) / 'scored.json'
            score = cli.copy()
            score[2] = 'score'
            score[-1] = str(scored)
            third = subprocess.run(score, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)},
                                   text=True, capture_output=True, timeout=40)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(scored.read_bytes(), original)

    def test_reopen_original_raw_journals_and_score_without_generating(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            report = execute(self.original, journal_dir=journal)
            self.assertEqual(report, independent_rescore(self.original, journal))
            self.assertEqual(set(p.name for p in journal.iterdir()),
                             {phase + '.json' for phase in PHASES})

    def test_original_journal_missing_rejected_by_scorer(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            (journal / 'send-fault.json').unlink()
            with self.assertRaisesRegex(ValueError, 'complete original five-phase'):
                independent_rescore(self.original, journal)

    def test_original_journal_extra_file_rejected_by_scorer(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            (journal / 'unregistered.json').write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'complete original five-phase'):
                independent_rescore(self.original, journal)

    def test_original_journal_rewritten_status_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            fault = journal / 'header-fault.json'
            value = json.loads(fault.read_bytes())
            value['failed'] = []
            value['passed'].append('HeaderTests.test_putheader')
            fault.write_bytes(canonical(value) + b'\n')
            with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
                independent_rescore(self.original, journal)

    def test_original_journal_rehashed_method_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            fault = journal / 'baseline.json'
            value = json.loads(fault.read_bytes())
            value['original_test_method_sources'][0]['method_sha256'] = 'f' * 64
            fault.write_bytes(canonical(value) + b'\n')
            with self.assertRaisesRegex(ValueError, 'execution or fault detection changed'):
                independent_rescore(self.original, journal)

    def test_original_journal_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            fault = journal / 'baseline.json'
            raw = fault.read_bytes()
            fault.write_bytes(raw.replace(b'{', b'{"schema":"duplicate",', 1))
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                independent_rescore(self.original, journal)

    def test_original_journal_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            source = journal / 'baseline.json'
            other = journal.parent / 'receipt-outside.json'
            other.write_bytes(source.read_bytes())
            source.unlink()
            source.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'original receipt file'):
                independent_rescore(self.original, journal)

    def test_original_journal_invalid_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal'
            execute(self.original, journal_dir=journal)
            files, blobs = self.original
            changed = dict(blobs)
            changed[SRC_MODULE] = b'bad' + blobs[SRC_MODULE]
            with self.assertRaisesRegex(ValueError, 'original evaluator source files changed'):
                independent_rescore((files, changed), journal)

    def _local_worker(self, fault):
        # Test using actual worker receipts, not an invented hand-crafted record.
        folder = Path(__file__).parents[2]
        module = folder / 'pinned_original_http_client.py'
        tests = folder / 'pinned_original_test_httplib.py'
        if not (module.exists() and tests.exists()):
            with tempfile.TemporaryDirectory() as td:
                m, t = Path(td) / 'pinned_original_http_client.py', Path(td) / 'pinned_original_test_httplib.py'
                m.write_bytes(self.original[1][SRC_MODULE])
                t.write_bytes(self.original[1][SRC_TEST])
                return self._run_worker(m, t, fault)
        return self._run_worker(module, tests, fault)

    def _run_worker(self, m, t, fault):
        got = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.worker),
                              str(m), str(t), fault], text=True, capture_output=True, timeout=20)
        self.assertEqual(got.returncode, 0, got.stderr)
        return json.loads(got.stdout)


if __name__ == '__main__':
    unittest.main()
