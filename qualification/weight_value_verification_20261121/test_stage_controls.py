"""Synthetic lifecycle controls plus the original four reader controls; no private inputs."""
import argparse
import ast
import copy
import importlib
import os
from pathlib import Path
import py_compile
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fit_journal import FitJournal
from run_verification import budget_check, install_wrappers
from source_loader import PinnedSourceLoader, load_original
from stage_contract import (FITS, ORIGINAL_READER_SHA, SOURCE_FILES, check_binding_reuse,
                            function_bindings, load_json, pin, save_new)
from supervise_verification import child_result_check
import supervise_verification

REAL_READER = None


def synthetic_journal(output, primary_failure=False):
    reader = SimpleNamespace(COUNTS=dict(own_graphs=0, original_recursive_worlds=0,
        TRAIN_hidden_calls=0, CONF_hidden_calls=0, independent_policy_DPs=0))
    def main_fit(*args):
        reader.COUNTS['own_graphs'] += 64
        reader.COUNTS['TRAIN_hidden_calls'] += 1
        return {}, {'synthetic': True}
    def confirm_fit(*args):
        reader.COUNTS['own_graphs'] += 16
        reader.COUNTS['CONF_hidden_calls'] += 16
        reader.COUNTS['original_recursive_worlds'] += 16
        return {'iid': {}, 'ood': {}}, {'iid': [{}] * 8, 'ood': [{}] * 8}
    def primary(*args):
        if primary_failure:
            raise ValueError('synthetic primary mismatch')
    contract = {'original': {'protocol': {'synthetic': True}, 'prior_failure': {'synthetic': True}},
                'source_pins': {'synthetic': True}}
    journal = FitJournal(reader, {'main_fit_check': main_fit,
        'confirmation_fit_check': confirm_fit, 'primary_check': primary},
        contract, {'synthetic_contract': True}, output)
    protocol = {'input_specs': {str(fit): {'synthetic': True} for fit in FITS}}
    return journal, protocol


def enter_fit(journal, protocol, fit):
    journal.main_fit(protocol, fit, {'synthetic': True})
    journal.confirmation_fit(protocol, fit, {}, {'iid': {}, 'ood': {}})


def synthetic_parent_results(root):
    output = root / 'output'
    (output / 'fits').mkdir(parents=True)
    contract = {'source_pins': {'synthetic': True},
                'original': {'prior_failure': {'synthetic': True}, 'protocol': {'sha256': 'a' * 64}}}
    identity = {'synthetic_contract': True}
    fits = []
    for fit in FITS:
        fits.append(save_new(output / 'fits' / ('fit_' + str(fit) + '.json'),
            dict(schema='hepta-verification-fit-complete-v1', status='FIT_COMPLETE', fit=fit,
                 stage_contract_pin=identity, new_source_pins=contract['source_pins'],
                 original_CONF_tail_checks_completed=True)))
    counts = dict(own_graphs=400, original_recursive_worlds=80)
    raw = save_new(output / 'READER_RESULTS.json',
        dict(status='PASS', protocol_sha256='a' * 64, counts=counts))
    result = dict(schema='hepta-verification-only-child-results-v1', status='VERIFIED_PENDING_PARENT',
        stage_contract_pin=identity, source_pins=contract['source_pins'],
        original_failed_reader=contract['original']['prior_failure'],
        full_PASS_requires_parent_process_COMPLETED=True,
        original_raw_result_alone_is_not_new_stage_acceptance=True, production_admission=False,
        mathematical_thresholds_unchanged=True, bindings_reuse_checked=True,
        original_global_source_phase_entropy_exclusion_primary_checks_completed=True,
        new_candidates=0, new_publics=0, new_quality_comparisons=0,
        fit_receipts=fits, raw_original_reader_results_pin=raw, counts=counts)
    save_new(output / 'STAGE_RESULTS.json', result)
    return contract, identity


class StageControls(unittest.TestCase):
    def test_pending_fit_is_persisted_only_at_post_tail_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            journal, protocol = synthetic_journal(root)
            enter_fit(journal, protocol, 11)
            self.assertEqual(journal.receipts, [])
            self.assertFalse((root / 'fits').exists())
            budget_check(journal, time.perf_counter())
            record = load_json(journal.receipts[0]['path'])
            self.assertEqual((record['status'], record['fit'], record['counts_delta']),
                ('FIT_COMPLETE', 11, dict(own_graphs=80, original_recursive_worlds=16,
                 TRAIN_hidden_calls=1, CONF_hidden_calls=16, independent_policy_DPs=0)))

    def test_tail_failure_does_not_emit_pending_fit(self):
        tree = ast.parse(Path(REAL_READER.__file__).read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        loops = [node for node in ast.walk(main) if isinstance(node, ast.For) and
                 isinstance(node.target, ast.Name) and node.target.id == 'fit' and
                 isinstance(node.iter, ast.Name) and node.iter.id == 'FITS']
        self.assertEqual(len(loops), 1)
        original_loop = compile(ast.Module(body=[copy.deepcopy(loops[0])], type_ignores=[]),
                                REAL_READER.__file__, 'exec')
        for invalid in (True, False):
            with self.subTest(invalid_tail=invalid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                journal, protocol = synthetic_journal(root)
                phases, main_rows, conf_rows = {}, {}, {}
                for fit in (11, 23):
                    key = 'main_' + str(fit)
                    phases[key] = dict(started_utc='2026-11-21T00:00:01+00:00',
                                       completed_utc='2026-11-21T00:00:02+00:00')
                    main_rows[str(fit)] = {'phase_records': {'SELECT': key}}
                    conf_rows[str(fit)] = {}
                    for domain in ('iid', 'ood'):
                        key = str(fit) + '_' + domain
                        late = invalid and fit == 11 and domain == 'ood'
                        phases[key] = {'completed_utc': '2026-11-21T00:00:' + ('21' if late else '18') + '+00:00'}
                        conf_rows[str(fit)][domain] = {'phase_record_pin': key}
                namespace = dict(FITS=(11, 23), protocol=protocol, COUNTS=journal.reader.COUNTS,
                    main_result=dict(fits=main_rows, created_utc='2026-11-21T00:00:00+00:00',
                                     completed_utc='2026-11-21T00:00:10+00:00'),
                    conf=dict(fits=conf_rows, completed_utc='2026-11-21T00:00:20+00:00'),
                    selection={'fits': {'11': {}, '23': {}}}, diagnostics={'fits': {'11': {}, '23': {}}},
                    seal_time=None, diagnostic_time=None, ctx=None, queue={}, protocol_sha='synthetic',
                    identities={}, main_summaries={}, confirm_summaries={}, recursive={}, main_DPs=0, conf_DPs=0,
                    read_pin=phases.__getitem__, require=REAL_READER.require, iso=REAL_READER.iso,
                    main_fit_check=journal.main_fit, confirmation_fit_check=journal.confirmation_fit,
                    budget=lambda: budget_check(journal, time.perf_counter()))
                if invalid:
                    with self.assertRaisesRegex(ValueError, 'complete CONF phases'):
                        exec(original_loop, namespace)
                    self.assertEqual(journal.receipts, [])
                    self.assertEqual(journal.pending['fit'], 11)
                    self.assertFalse((root / 'fits').exists())
                else:
                    exec(original_loop, namespace)
                    self.assertEqual([load_json(p['path'])['fit'] for p in journal.receipts], [11])
                    self.assertEqual(journal.pending['fit'], 23)

    def test_expired_budget_retains_completed_fit_before_stopping(self):
        with tempfile.TemporaryDirectory() as temp:
            journal, protocol = synthetic_journal(Path(temp))
            enter_fit(journal, protocol, 11)
            with patch('run_verification.time.process_time', return_value=175.0):
                with self.assertRaises(TimeoutError):
                    budget_check(journal, time.perf_counter())
            self.assertEqual(len(journal.receipts), 1)
            self.assertEqual(load_json(journal.receipts[0]['path'])['status'], 'FIT_COMPLETE')

    def test_exclusive_receipt_and_missing_fit_prevent_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            journal, protocol = synthetic_journal(root)
            enter_fit(journal, protocol, 11)
            journal.flush('primary_after_original_CONF_tail')
            original = Path(journal.receipts[0]['path']).read_bytes()
            with self.assertRaises(FileExistsError):
                save_new(journal.receipts[0]['path'], {'replaced': True})
            self.assertEqual(Path(journal.receipts[0]['path']).read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'five completed fits'):
                journal.primary([], {})

    def test_primary_failure_preserves_fits_without_stage_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            journal, protocol = synthetic_journal(root, primary_failure=True)
            for fit in FITS:
                enter_fit(journal, protocol, fit)
            with self.assertRaisesRegex(ValueError, 'primary mismatch'):
                journal.primary([], {})
            self.assertEqual(len(journal.receipts), 5)
            with self.assertRaisesRegex(ValueError, 'original primary checks required'):
                journal.finish({'status': 'PASS'})
            self.assertFalse((root / 'STAGE_RESULTS.json').exists())

    def test_pinned_loader_ignores_valid_stale_bytecode_and_rejects_source_change(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'synthetic_original.py'
            source.write_text('value = 9\n')
            prior = source.stat()
            py_compile.compile(str(source), doraise=True)
            source.write_text('value = 3\n')
            os.utime(source, ns=(prior.st_atime_ns, prior.st_mtime_ns))
            loader = PinnedSourceLoader(pin(source))
            module = ModuleType('synthetic_original')
            loader.exec_module(module)
            self.assertEqual(module.value, 3)
            source.write_text('value = 7\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                loader.exec_module(ModuleType('changed_original'))

    def test_original_math_objects_are_preserved_and_rebinding_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            before = function_bindings(REAL_READER)
            original, replacements, _ = install_wrappers(REAL_READER, {}, {}, Path(temp))
            try:
                self.assertIs(REAL_READER.main, before['main'])
                self.assertIs(REAL_READER.radius_check, before['radius_check'])
                REAL_READER.close_number = lambda *args: None
                with self.assertRaisesRegex(ValueError, 'function binding changed'):
                    check_binding_reuse(REAL_READER, original, replacements)
            finally:
                for name, function in before.items():
                    setattr(REAL_READER, name, function)

    def test_parent_rejects_missing_or_modified_fit_and_failure_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract, identity = synthetic_parent_results(root)
            child_result_check(root, contract, identity)
            path = root / 'output/fits/fit_71.json'
            raw = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'exclusive fit inventory'):
                child_result_check(root, contract, identity)
            path.write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'pinned bytes changed'):
                child_result_check(root, contract, identity)
            path.write_bytes(raw)
            save_new(root / 'STAGE_FAILED.json', {'synthetic_failure': True})
            with self.assertRaisesRegex(ValueError, 'failed child cannot pass'):
                child_result_check(root, contract, identity)

    def test_existing_attempt_is_rejected_before_any_child_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = {name: pin(Path(__file__).parent / name) for name in SOURCE_FILES}
            contract = {'source_pins': sources, 'attempt_root': str(root),
                        'environment': {'executable_pin': pin(os.sys.executable)}}
            with patch('supervise_verification.check_contract', return_value=(contract, {})), \
                    patch('supervise_verification.subprocess.Popen') as popen:
                with self.assertRaises(FileExistsError):
                    supervise_verification.main(SimpleNamespace(contract=root / 'synthetic.json'))
                popen.assert_not_called()


def main():
    global REAL_READER
    parser = argparse.ArgumentParser()
    parser.add_argument('--original-source', type=Path, required=True)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    source_root = args.original_source.resolve()
    original_pins = {path.name: pin(path) for path in source_root.glob('*.py')}
    if original_pins['verify_records.py']['sha256'] != ORIGINAL_READER_SHA:
        raise ValueError('original reader source differs from frozen parent')
    REAL_READER = load_original(original_pins)
    controls = importlib.import_module('test_reader_controls')
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(StageControls),
                               unittest.defaultTestLoader.loadTestsFromTestCase(controls.ReaderControls)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = dict(schema='hepta-verification-synthetic-suite-v1',
        status='PASS' if result.wasSuccessful() and result.testsRun == 13 and not result.skipped else 'FAILED',
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        real_model_or_array_inputs=False, new_real_scientific_calls=0,
        source_pins={name: pin(Path(__file__).parent / name) for name in SOURCE_FILES},
        original_reader_source_pin=original_pins['verify_records.py'],
        scope='Nine new synthetic lifecycle/source controls plus four unchanged original reader controls; no private models,arrays,teacher,protocol or results.')
    if args.result is not None:
        save_new(args.result, record)
    print(__import__('json').dumps(record, sort_keys=True), flush=True)
    return 0 if record['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
