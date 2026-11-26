import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import runtime_codex_receipt_v2 as receipt


class SourceQualificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records = self.root / 'records'
        self.records.mkdir()
        self.candidate = receipt.identity('a' * 40, 'a' * 40, 'b' * 40, None,
                                          'source-head', ['c' * 40])
        for name, (floor, command) in receipt.PLAN.items():
            log = self.records / (name + '.log')
            log.write_text('terminal command log\n', encoding='utf-8')
            identity = dict(commit='a' * 40, tree='b' * 40, parents=['c' * 40], dirty=False)
            value = dict(schema_version=1, source_sha='a' * 40,
                         tested_sha='a' * 40, lane='source-head', before=identity,
                         after=copy.deepcopy(identity), command=command,
                         minimum_tests=floor, status='passed', exit_code=0,
                         observed_passed_tests=floor, observed_failed_tests=0,
                         log_file=log.name, log_sha256=receipt.digest(log),
                         log_bytes=log.stat().st_size)
            self.write(name, value)

    def write(self, name, value):
        (self.records / (name + '.json')).write_bytes(receipt.canonical(value))

    def change(self, name='worker-host', **fields):
        value = receipt.read_json(self.records / (name + '.json'))
        value.update(fields)
        self.write(name, value)

    def result(self):
        return receipt.evaluate(self.records, self.candidate)

    def test_complete_inventory_is_source_only(self):
        result = self.result()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['claims']['sourceQualification'])
        self.assertTrue(all(result['claims'][key] is False for key in receipt.FORBIDDEN))

    def test_missing_product_cannot_hide_behind_other_passes(self):
        (self.records / 'product-e2e.json').unlink()
        self.change(observed_passed_tests=100000)
        self.assertEqual(self.result()['status'], 'failed')

    def test_unexpected_record_fails_closed(self):
        (self.records / 'extra.json').write_text('{}')
        self.assertEqual(self.result()['unexpectedRecords'], ['extra.json'])
        self.assertEqual(self.result()['status'], 'failed')

    def test_cancelled_skipped_running_failed_and_timeout_are_not_passes(self):
        for status in ('cancelled', 'skipped', 'running', 'failed', 'timed_out'):
            with self.subTest(status=status):
                self.change(status=status, exit_code=0)
                self.assertEqual(self.result()['status'], 'failed')

    def test_nonzero_exit_is_not_hidden_by_passed_status(self):
        self.change(exit_code=1)
        self.assertEqual(self.result()['status'], 'failed')

    def test_empty_test_binary_cannot_pass(self):
        self.change(observed_passed_tests=0)
        self.assertEqual(self.result()['status'], 'failed')

    def test_wrong_command_is_not_equivalent_to_tests(self):
        self.change(command=['printf', '100 tests passed'])
        self.assertEqual(self.result()['status'], 'failed')

    def test_test_floor_cannot_be_lowered(self):
        self.change(minimum_tests=0)
        self.assertEqual(self.result()['status'], 'failed')

    def test_bool_cannot_impersonate_count_or_exit_code(self):
        for key in ('minimum_tests', 'observed_passed_tests', 'observed_failed_tests', 'log_bytes', 'exit_code'):
            with self.subTest(key=key):
                path = self.records / 'worker-host.json'
                old = path.read_bytes()
                self.change(**{key: False})
                self.assertEqual(self.result()['status'], 'failed')
                path.write_bytes(old)

    def test_foreign_commit_or_lane_is_rejected(self):
        for key, value in (('source_sha', 'c' * 40), ('tested_sha', 'c' * 40), ('lane', 'base-merge')):
            with self.subTest(key=key):
                path = self.records / 'worker-host.json'
                old = path.read_bytes()
                self.change(**{key: value})
                self.assertEqual(self.result()['status'], 'failed')
                path.write_bytes(old)

    def test_worktree_mutation_is_rejected(self):
        self.change(after=dict(commit='a' * 40, tree='b' * 40, parents=['c' * 40], dirty=True))
        self.assertEqual(self.result()['status'], 'failed')

    def test_log_tampering_is_detected(self):
        (self.records / 'worker-host.log').write_text('different log')
        self.assertEqual(self.result()['status'], 'failed')

    def test_log_length_tampering_is_detected(self):
        self.change(log_bytes=0)
        self.assertEqual(self.result()['status'], 'failed')

    def test_log_traversal_and_absolute_paths_are_rejected(self):
        for value in ('../secret', '/tmp/secret', '..\\secret', '.', '..'):
            with self.subTest(path=value):
                self.change(log_file=value)
                self.assertEqual(self.result()['status'], 'failed')

    def test_symlink_log_is_rejected(self):
        log = self.records / 'worker-host.log'
        target = self.root / 'outside.log'
        target.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(target)
        self.assertEqual(self.result()['status'], 'failed')

    def test_duplicate_json_keys_are_rejected(self):
        path = self.records / 'worker-host.json'
        path.write_text('{"schema_version":1,"schema_version":1}')
        self.assertEqual(self.result()['status'], 'failed')

    def test_target_host_lane_cannot_be_self_certified(self):
        with self.assertRaises(ValueError):
            receipt.identity('a' * 40, 'a' * 40, 'b' * 40, None, 'target-host', [])

    def test_merge_parent_order_is_exact(self):
        receipt.identity('a' * 40, 'd' * 40, 'b' * 40, 'c' * 40,
                         'base-merge', ['c' * 40, 'a' * 40])
        with self.assertRaises(ValueError):
            receipt.identity('a' * 40, 'd' * 40, 'b' * 40, 'c' * 40,
                             'base-merge', ['a' * 40, 'c' * 40])

    def test_receipt_recomputed_from_records_not_its_self_report(self):
        value = self.result()
        value['generatedAt'] = '2026-09-27T00:00:00+00:00'
        value['workflow'] = {}
        path = self.root / 'receipt.json'
        path.write_bytes(receipt.canonical(value))
        receipt.verify_contents(path, self.records)
        value['claims']['realProviderQualified'] = True
        path.write_bytes(receipt.canonical(value))
        with self.assertRaises(ValueError):
            receipt.verify_contents(path, self.records)

    def test_failed_receipt_is_valid_diagnostic_not_qualification(self):
        self.change(status='cancelled', exit_code=137)
        value = self.result()
        value.update(generatedAt='2026-09-27T00:00:00+00:00', workflow={})
        path = self.root / 'receipt.json'
        path.write_bytes(receipt.canonical(value))
        verified = receipt.verify_contents(path, self.records)
        self.assertEqual(verified['status'], 'failed')
        self.assertFalse(verified['claims']['sourceQualification'])

    def test_noncanonical_or_unknown_receipt_fields_are_rejected(self):
        value = self.result()
        value.update(generatedAt='2026-09-27T00:00:00+00:00', workflow={})
        path = self.root / 'receipt.json'
        path.write_text(json.dumps(value, indent=2))
        with self.assertRaises(ValueError):
            receipt.verify_contents(path, self.records)
        value['production'] = True
        path.write_bytes(receipt.canonical(value))
        with self.assertRaises(ValueError):
            receipt.verify_contents(path, self.records)


if __name__ == '__main__':
    unittest.main()
