#!/usr/bin/env python3
"""Counterexamples for false responsibility and stale-source evidence attribution."""
from __future__ import annotations
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from report_module_evidence import (
    ROOT, MATURITY, check_symbol, match_sources, observed_selector,
    python_symbols, validate_contract,
)


class ResponsibilityBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pon-responsibility-')
        cls.root = Path(cls.temp.name) / 'source'
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns(
            '.git', 'target', '__pycache__', '.pytest_cache', 'node_modules'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def mutate(self, change):
        path = self.root / MATURITY
        raw = path.read_bytes()
        try:
            value = json.loads(raw)
            change(value)
            path.write_text(json.dumps(value))
            with self.assertRaises((ValueError, KeyError)):
                validate_contract(self.root)
        finally:
            path.write_bytes(raw)

    def test_actual_bindings_are_not_execution(self):
        result = validate_contract(self.root)
        self.assertTrue(result['bindings_consistent'])
        self.assertFalse(result['tests_executed_by_this_checker'])
        self.assertFalse(result['acceptance_granted'])

    def test_missing_procedure_owner_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'].pop())

    def test_duplicate_owner_does_not_fill_a_gap(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'].__setitem__(1,
                    copy.deepcopy(d['modules'][0]['responsibilities'][0])))

    def test_reusable_component_cannot_fill_ordinary_product_entry(self):
        self.mutate(lambda d: d['modules'][3]['responsibilities'][0].update(
            ordinary_product_entrypoint={'path': 'formal/pon-nakamoto-v1/ledger.py', 'symbol': 'Ledger.make'}))

    def test_specified_owner_cannot_claim_controlled_entry(self):
        self.mutate(lambda d: d['modules'][5]['responsibilities'][1].update(
            implementation_kind='specified-not-integrated'))

    def test_missing_callable_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0]['runtime_symbols'][0].update(symbol='accept_all'))

    def test_native_method_must_belong_to_named_impl(self):
        with self.assertRaises(ValueError):
            check_symbol(self.root, {'path': 'trillionnium/crates/trnm-protocol/src/pon_wire.rs',
                                     'symbol': 'Header::unsigned'})

    def test_source_path_escape_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0]['runtime_symbols'][0].update(path='../outside.py'))

    def test_unknown_implementation_kind_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0].update(implementation_kind='production-ready'))

    def test_invented_test_class_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0].update(
            evidence_selectors=['formal/pon-nakamoto-v1/test_contracts.py::Invented.test_header_mutations_bind_all_fields']))

    def test_duplicate_test_does_not_create_more_evidence(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0]['evidence_selectors'].append(
            d['modules'][0]['responsibilities'][0]['evidence_selectors'][0]))

    def test_missing_backend_or_scope_rejects(self):
        self.mutate(lambda d: d['modules'][0]['responsibilities'][0].update(remaining=''))

    def test_missing_manifest_rejects(self):
        self.mutate(lambda d: d['evidence_packages']['e3'].update(manifest='evidence/absent.json'))

    def test_archive_path_does_not_become_new_measured_commit(self):
        d = json.loads((self.root / MATURITY).read_text())
        archive = d['evidence_packages']['v1']['source_archive']['commit']
        m = json.loads((self.root / d['evidence_packages']['v1']['manifest']).read_text())
        self.assertNotEqual(archive, m['implementation_commit'])

    def test_m08_names_actual_distinct_phases(self):
        d = json.loads((self.root / MATURITY).read_text())
        m = next(x for x in d['modules'] if x['id'] == 'M08')
        a, b = m['responsibilities']
        self.assertEqual(a['runtime_symbols'][0]['symbol'], 'Ledger.activate')
        self.assertEqual(b['runtime_symbols'][0]['symbol'], 'Ledger._recover_intent')
        self.assertIsNone(a['ordinary_product_entrypoint'])
        self.assertIsNone(b['ordinary_product_entrypoint'])


class ExactObservationTests(unittest.TestCase):
    selector = 'formal/pon-nakamoto-v1/test_contracts.py::CodecTests.test_example'

    def record(self, **changes):
        row = {'command': ['python3', 'formal/pon-nakamoto-v1/test_contracts.py'],
               'returncode': 0, 'timed_out': False,
               '_log_text': 'test_example (__main__.CodecTests.test_example) ... ok\n\nRan 1 test in 0.1s\n\nOK\n'}
        row.update(changes)
        return row

    def test_exact_file_class_method_observed(self):
        self.assertTrue(observed_selector(self.selector, [self.record()]))

    def test_same_named_method_in_other_file_is_not_evidence(self):
        self.assertFalse(observed_selector(self.selector, [self.record(command=['python3', 'other_test.py'])]))

    def test_same_method_other_class_is_not_evidence(self):
        self.assertFalse(observed_selector(self.selector, [self.record(
            _log_text=self.record()['_log_text'].replace('CodecTests', 'OtherTests'))]))

    def test_failed_process_cannot_supply_passing_selector(self):
        self.assertFalse(observed_selector(self.selector, [self.record(returncode=1)]))

    def test_boolean_exit_code_is_not_integer_success(self):
        self.assertFalse(observed_selector(self.selector, [self.record(returncode=False)]))

    def test_timed_out_process_is_not_success(self):
        self.assertFalse(observed_selector(self.selector, [self.record(timed_out=True)]))

    def test_skipped_test_is_not_observed_pass(self):
        self.assertFalse(observed_selector(self.selector, [self.record(
            _log_text=self.record()['_log_text'].replace('... ok', "... skipped 'not run'"))]))

    def test_missing_suite_summary_is_not_success(self):
        self.assertFalse(observed_selector(self.selector, [self.record(
            _log_text='test_example (__main__.CodecTests.test_example) ... ok\n')]))

    def test_other_registered_selector_remains_unobserved(self):
        self.assertFalse(observed_selector(self.selector.replace('test_example', 'test_new'), [self.record()]))

    def test_native_selector_is_not_guessed_from_test_name(self):
        self.assertFalse(observed_selector('trillionnium/crates/x/src/lib.rs::test_example', [self.record()]))


class RustImplementationOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pon-rust-owner-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'owner.rs'

    def bind(self, text, symbol='Owner::run'):
        self.path.write_text(text)
        check_symbol(self.root, {'path': 'owner.rs', 'symbol': symbol})

    def test_anonymous_lifetime_inherent_owner(self):
        self.bind("impl Owner<'_> { pub fn run(&mut self) {} }")

    def test_declared_lifetime_and_nested_type_arguments(self):
        self.bind("impl<'a, T> Owner<'a, Vec<Option<T>>> { pub fn run(&self) {} }")

    def test_generic_owner_where_bound_and_function_arrow(self):
        self.bind("impl<T: Fn() -> Vec<u8>> Owner<T> where T: Fn() -> Vec<u8> { fn run(&self) {} }")

    def test_later_inherent_block_can_own_method(self):
        self.bind("impl Owner<'_> { fn other(&self) {} } impl Owner<'_> { fn run(&self) {} }")

    def test_comments_and_char_literals_cannot_end_the_owning_body(self):
        self.bind("impl Owner<'_> { fn other(&self) { let a = '}'; let b = '\\u{7b}'; /* } /* { */ */ } fn run(&self) {} }")

    def test_comment_and_string_impls_do_not_bind(self):
        for text in ["// impl Owner<'_> { fn run() {} }", "/* impl Owner<T> { fn run() {} } */",
                     'const S: &str = "impl Owner<T> { fn run() {} }";',
                     'const S: &str = r###"impl Owner<T> { fn run() {} }"###;']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.bind(text)

    def test_method_lookalikes_in_comments_and_strings_do_not_bind(self):
        for content in ['// fn run() {}\n', '/* fn run() {} */',
                        'const S: &str = "fn run() {}";', 'const S: &str = r#"fn run() {}"#;']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.bind("impl Owner<'_> { " + content + ' }')

    def test_wrong_owner_and_generic_argument_lookalikes_do_not_bind(self):
        for text in ["impl WrongOwner<'_> { fn run() {} }", 'impl Wrapper<Owner> { fn run() {} }',
                     'impl<Owner> Wrapper<Owner> { fn run() {} }', 'impl OwnerExtra { fn run() {} }']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.bind(text)

    def test_trait_implementation_is_not_an_inherent_owner(self):
        for text in ['impl<T> SomeTrait for Owner<T> { fn run() {} }',
                     'impl Owner for Other { fn run() {} }']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.bind(text)

    def test_other_body_or_free_function_cannot_fill_missing_method(self):
        for text in ["impl Owner<'_> {} impl Other { fn run() {} }", "impl Owner<'_> {} fn run() {}",
                     "impl Owner<'_> { fn outer() { fn run() {} } }",
                     "impl Owner<'_> { fn outer() { impl Other { fn run() {} } } }"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.bind(text)

    def test_unbalanced_generic_or_impl_cannot_capture_later_function(self):
        for text in ['impl Owner<Vec<T> { fn run() {} }', "impl Owner<'_> { fn run() {}"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.bind(text)


class SourceApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pon-evidence-source-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = 'formal/pon-nakamoto-v1/a.py'
        self.b = 'formal/pon-nakamoto-v1/dependency.py'
        for p, data in [(self.a, b'a = 1\n'), (self.b, b'b = 1\n')]:
            file = self.root / p
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        self.inputs = {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in (self.a, self.b)}

    def compare(self, subjects=None, runtime=None):
        return match_sources(self.root, self.inputs, subjects or [self.a],
                             runtime if runtime is not None else {self.a, self.b})

    def test_unchanged_recorded_subject_and_runtime(self):
        result = self.compare()
        self.assertTrue(result['subject_bytes_match'])
        self.assertTrue(result['complete_recorded_runtime_matches'])

    def test_changed_dependency_does_not_hide_behind_subject_match(self):
        (self.root / self.b).write_text('b = 2\n')
        result = self.compare()
        self.assertTrue(result['subject_bytes_match'])
        self.assertFalse(result['complete_recorded_runtime_matches'])
        self.assertEqual(result['changed_runtime_inputs'], [self.b])

    def test_added_runtime_invalidates_complete_match(self):
        new = 'formal/pon-nakamoto-v1/new.py'
        (self.root / new).write_text('x = 1\n')
        result = self.compare(runtime={self.a, self.b, new})
        self.assertFalse(result['complete_recorded_runtime_matches'])
        self.assertEqual(result['runtime_inventory_added'], [new])

    def test_removed_runtime_invalidates_complete_match(self):
        result = self.compare(runtime={self.a})
        self.assertFalse(result['complete_recorded_runtime_matches'])
        self.assertEqual(result['runtime_inventory_removed'], [self.b])

    def test_absent_subject_is_not_assumed_covered(self):
        result = self.compare(subjects=['scripts/new_owner.py'])
        self.assertFalse(result['subject_bytes_match'])
        self.assertEqual(result['unrecorded_subjects'], ['scripts/new_owner.py'])

    def test_report_does_not_rewrite_original_hashes(self):
        expected = dict(self.inputs)
        (self.root / self.a).write_text('a = 2\n')
        self.assertFalse(self.compare()['subject_bytes_match'])
        self.assertEqual(self.inputs, expected)

    def test_no_subject_is_not_a_positive_identity_claim(self):
        result = match_sources(self.root, self.inputs, [], {self.a, self.b})
        self.assertFalse(result['subject_bytes_match'])

    def test_empty_recorded_runtime_cannot_be_current(self):
        result = match_sources(self.root, {}, [], set())
        self.assertFalse(result['complete_recorded_runtime_matches'])

    def test_class_and_method_source_bindings_are_distinct(self):
        symbols = python_symbols('class Owner:\n    def run(self): pass\n')
        self.assertIn('Owner', symbols)
        self.assertIn('Owner.run', symbols)
        self.assertNotIn('Other.run', symbols)


class NativeSelectorTests(unittest.TestCase):
    def test_exact_package_target_and_success_are_required(self):
        selector='trillionnium/crates/trnm-pon-node/tests/native_node.rs::test_recover'
        row={'command':['cargo','test','--offline','--locked','--manifest-path','trillionnium/Cargo.toml',
             '-p','trnm-pon-node','--test','native_node','--','--nocapture'], 'returncode':0,
             'timed_out':False,'_log_text':'Running tests/native_node.rs (target)\ntest test_recover ... ok\ntest result: ok. 1 passed; 0 failed;\n'}
        self.assertTrue(observed_selector(selector,[row]))
        for key,value in [('returncode',1),('timed_out',True),('command',['cargo','test','--workspace'])]:
            self.assertFalse(observed_selector(selector,[{**row,key:value}]))
        self.assertFalse(observed_selector(selector,[{**row,'_log_text':row['_log_text'].replace('test_recover','test_other')}]))
        output='Running tests/native_node.rs (target)\ntest test_recover ... actual child exit86 at intent\nok\ntest result: ok. 1 passed; 0 failed;\n'
        self.assertTrue(observed_selector(selector,[{**row,'_log_text':output}]))
        self.assertFalse(observed_selector(selector,[{**row,'_log_text':output.replace('\nok\n','\nFAILED\n')}]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
