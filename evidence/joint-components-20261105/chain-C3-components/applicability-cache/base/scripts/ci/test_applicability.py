#!/usr/bin/env python3
"""Counterexamples to stale profiles and promoted navigation/CI evidence."""
import ast
from copy import deepcopy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from check_applicability import (
    ROOT, REGISTRY, NATIVE_STORAGE_ENTRY, NATIVE_STORAGE_PROFILE, NATIVE_STORAGE_TESTS,
    EVALUATION_QUORUM_PROFILE, EVALUATION_QUORUM_TESTS, validate_evaluation_quorum_profile,
    MODEL_EVOLUTION_PROFILE, MODEL_TASK_WINDOWS_PROFILE, CELL_P2P_PROFILE,
    MODEL_AND_CELL_TESTS, validate_model_and_cell_profile,
    NATIVE_CONTINUATION_PROFILES, validate_native_continuation_profile,
    validate, markdown, profile_table,
)
from report_module_evidence import check_test_selector


class NativeContinuationApplicabilityTests(unittest.TestCase):
    """Source navigation must not substitute old domains or grant acceptance."""

    def setUp(self):
        profiles = json.loads((ROOT / REGISTRY).read_text())['profiles']
        self.profiles = [row for row in profiles if row['id'] in NATIVE_CONTINUATION_PROFILES]
        self.assertEqual(len(self.profiles), 2)

    def test_actual_owners_and_all_native_recovery_controls_are_bound(self):
        for profile in self.profiles:
            validate_native_continuation_profile(profile)
            for selector in profile['tests']:
                check_test_selector(ROOT, selector)

    def test_growth_cannot_reuse_old_profile_or_local_budget_claim_consensus(self):
        for original in self.profiles:
            for field, value in (
                ('configuration', 'config/pon/continuity-v1.json'),
                ('consensus_revision', 12), ('modules', ['M07']),
                ('entrypoint', {'path': 'trillionnium/crates/trnm-pon-node/src/store.rs',
                                'symbol': 'Node::open'}),
            ):
                profile = deepcopy(original)
                profile[field] = value
                with self.subTest(profile=original['id'], field=field), self.assertRaises(ValueError):
                    validate_native_continuation_profile(profile)

    def test_no_required_native_control_can_disappear(self):
        for original in self.profiles:
            for selector in NATIVE_CONTINUATION_PROFILES[original['id']]['tests']:
                profile = deepcopy(original)
                profile['tests'].remove(selector)
                with self.subTest(selector=selector), self.assertRaises(ValueError):
                    validate_native_continuation_profile(profile)

    def test_navigation_cannot_be_promoted_to_an_execution_receipt(self):
        for original in self.profiles:
            for field, value in (('evidence_class', 'local-execution'),
                                 ('receipt', {'result': 'PASS'})):
                profile = deepcopy(original)
                profile[field] = value
                with self.subTest(profile=original['id'], field=field), self.assertRaises(ValueError):
                    validate_native_continuation_profile(profile)


class EvaluationQuorumApplicabilityTests(unittest.TestCase):
    """Exercise new profile identity without copying historical receipt trees."""

    def setUp(self):
        profiles = json.loads((ROOT / REGISTRY).read_text())['profiles']
        self.profile = next(row for row in profiles if row['id'] == EVALUATION_QUORUM_PROFILE)

    def test_current_quorum_profile_binds_real_native_and_independent_tests(self):
        validate_evaluation_quorum_profile(self.profile)
        self.assertEqual(self.profile['evidence_class'], 'source-binding')
        self.assertIsNone(self.profile['receipt'])
        for path, names in EVALUATION_QUORUM_TESTS.items():
            for name in names:
                check_test_selector(ROOT, path + '::' + name)

    def test_quorum_profile_cannot_reuse_legacy_configuration_or_claim_another_owner(self):
        for field, value in [
            ('configuration', 'config/pon/public-evaluation-native-v1.json'),
            ('consensus_revision', 6), ('revision_pointer', 'consensus_revision'),
            ('entrypoint', {'path': 'trillionnium/crates/trnm-mvcc-fee/src/public_evaluation.rs',
                            'symbol': 'freeze'}),
            ('document', 'docs/protocol/pon-nakamoto-v1/details/PUBLIC_EVALUATION_LIFECYCLE.md'),
            ('modules', ['M11']),
        ]:
            with self.subTest(field=field):
                profile = deepcopy(self.profile)
                profile[field] = value
                with self.assertRaises(ValueError):
                    validate_evaluation_quorum_profile(profile)

    def test_quorum_profile_cannot_drop_any_native_or_reference_control(self):
        for selector in self.profile['tests']:
            with self.subTest(selector=selector):
                profile = deepcopy(self.profile)
                profile['tests'].remove(selector)
                with self.assertRaisesRegex(ValueError, 'independent oracle controls required'):
                    validate_evaluation_quorum_profile(profile)


class ModelAndCellApplicabilityTests(unittest.TestCase):
    """Preserve actual new owners without relabelling old profiles or receipts."""

    def setUp(self):
        profiles = json.loads((ROOT / REGISTRY).read_text())['profiles']
        self.profiles = {row['id']: row for row in profiles if row['id'] in MODEL_AND_CELL_TESTS}

    def test_explicit_profiles_name_actual_native_and_independent_controls(self):
        for profile in self.profiles.values():
            validate_model_and_cell_profile(profile)
            self.assertEqual(profile['evidence_class'], 'source-binding')
            self.assertIsNone(profile['receipt'])
            for selector in profile['tests']:
                check_test_selector(ROOT, selector)

    def test_evolution_and_task_windows_cannot_inherit_revision15_or_offline_history(self):
        for identifier in (MODEL_EVOLUTION_PROFILE, MODEL_TASK_WINDOWS_PROFILE):
            for field, value in [
                ('configuration', 'config/pon/public-evaluation-quorum-v2.json'),
                ('consensus_revision', 15), ('consensus_revision', None),
                ('revision_pointer', 'genesis_overrides.consensus_revision'),
                ('document', 'docs/protocol/pon-nakamoto-v1/details/MODEL_OPERATIONS_ACCEPTANCE_V1.md'),
                ('entrypoint', {'path': 'formal/pon-nakamoto-v1/model_window_history.py',
                                'symbol': 'verify_window'}),
                ('modules', ['M11']),
            ]:
                with self.subTest(identifier=identifier, field=field):
                    profile = deepcopy(self.profiles[identifier])
                    profile[field] = value
                    with self.assertRaises(ValueError):
                        validate_model_and_cell_profile(profile)

    def test_cell_bytes_cannot_claim_consensus_or_model_installation_owner(self):
        for field, value in [
            ('configuration', 'config/pon/model-evolution-v5.json'),
            ('consensus_revision', 16), ('revision_pointer', 'consensus_revision'),
            ('entrypoint', {'path': 'trillionnium/crates/trnm-pon-node/src/main.rs', 'symbol': 'run'}),
            ('document', 'docs/development/specs/pon/MODEL_EVOLUTION_V5.md'),
            ('modules', ['M09', 'M15']),
        ]:
            with self.subTest(field=field):
                profile = deepcopy(self.profiles[CELL_P2P_PROFILE])
                profile[field] = value
                with self.assertRaises(ValueError):
                    validate_model_and_cell_profile(profile)

    def test_no_parent_no_gain_owner_pin_or_slow_peer_control_can_be_dropped(self):
        for identifier, original in self.profiles.items():
            for selector in original['tests']:
                with self.subTest(identifier=identifier, selector=selector):
                    profile = deepcopy(original)
                    profile['tests'].remove(selector)
                    with self.assertRaisesRegex(ValueError, 'negative and native control coverage'):
                        validate_model_and_cell_profile(profile)


class ApplicabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pon-applicability-')
        cls.root = Path(cls.temp.name) / 'source'
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns(
            '.git', 'target', '__pycache__', '.pytest_cache', 'node_modules'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reject(self, change, path=REGISTRY):
        p = self.root / path
        raw = p.read_bytes()
        try:
            data = json.loads(raw)
            change(data)
            p.write_text(json.dumps(data))
            with self.assertRaises((ValueError, KeyError)):
                validate(self.root)
        finally:
            p.write_bytes(raw)

    def test_current_table_binds_all_procedures_without_execution(self):
        result = validate(self.root)
        self.assertEqual(len(result['procedures']), 39)
        self.assertEqual({r['module'] for r in result['procedures']}, {f'M{i:02}' for i in range(18)})
        self.assertFalse(result['tests_executed_by_this_checker'])
        self.assertFalse(result['acceptance_granted'])
        self.assertIn('M05.ReconsiderAfterReorg', markdown(result))

    def test_wrong_profile_revision_rejects(self):
        self.reject(lambda d: d['profiles'][3].update(consensus_revision=8))

    def test_missing_profile_rejects(self):
        self.reject(lambda d: d['profiles'].pop())

    def test_duplicate_profile_rejects(self):
        self.reject(lambda d: d['profiles'].append(d['profiles'][0]))

    def test_missing_doc_rejects(self):
        self.reject(lambda d: d['profiles'][0].update(document='docs/missing.md'))

    def test_missing_entry_rejects(self):
        self.reject(lambda d: d['profiles'][0]['entrypoint'].update(symbol='not_an_entry'))

    def test_source_binding_cannot_be_promoted_to_measurement(self):
        self.reject(lambda d: d['profiles'][0].update(evidence_class='local-execution'))

    def test_source_binding_cannot_invent_receipt(self):
        self.reject(lambda d: d['profiles'][0].update(receipt='current-head-pass'))

    def test_claimed_ci_pass_rejects(self):
        self.reject(lambda d: d['delivery'].update(hosted_head_status='PASS'))

    def test_claimed_merge_pass_rejects(self):
        self.reject(lambda d: d['delivery'].update(prospective_merge_status='PASS'))

    def test_stale_snapshot_package_count_rejects(self):
        self.reject(lambda d: d.update(workspace_packages=24), 'docs/development/CURRENT_SNAPSHOT_V1.json')

    def test_local_policy_cannot_claim_consensus_revision(self):
        self.reject(lambda d: d['profiles'][-1].update(consensus_revision=10))

    def reject_native_profile_with_current_table(self, change, message):
        """Regenerating navigation must not conceal a changed storage contract."""
        registry = self.root / REGISTRY
        authority = self.root / 'docs/architecture/TRNM_DOCUMENTATION_AUTHORITY_V1.md'
        original_registry, original_authority = registry.read_bytes(), authority.read_bytes()
        try:
            data = json.loads(original_registry)
            profile = next(p for p in data['profiles'] if p['id'] == NATIVE_STORAGE_PROFILE)
            change(profile, data)
            registry.write_text(json.dumps(data))
            start, end = '<!-- applicability-table:start -->', '<!-- applicability-table:end -->'
            before, rest = original_authority.decode().split(start, 1)
            _, after = rest.split(end, 1)
            authority.write_text(before + start + '\n' + profile_table(data['profiles']) +
                                 '\n' + end + after)
            with self.assertRaisesRegex(ValueError, message):
                validate(self.root)
        finally:
            registry.write_bytes(original_registry)
            authority.write_bytes(original_authority)

    def test_native_authenticated_profile_is_explicit_local_source_navigation(self):
        result = validate(self.root)
        self.assertEqual(len(result['profiles']), 24)
        profile = next(p for p in result['profiles'] if p['id'] == NATIVE_STORAGE_PROFILE)
        self.assertEqual(profile['entrypoint'], NATIVE_STORAGE_ENTRY)
        for field in ('configuration', 'revision_pointer', 'consensus_revision', 'receipt'):
            self.assertIsNone(profile[field])
        self.assertEqual(profile['evidence_class'], 'source-binding')
        for path, symbols in NATIVE_STORAGE_TESTS.items():
            self.assertTrue({path + '::' + symbol for symbol in symbols} <= set(profile['tests']))
        self.assertFalse(result['acceptance_granted'])
        self.assertFalse(result['tests_executed_by_this_checker'])

    def test_native_profile_cannot_reuse_existing_consensus_configuration(self):
        def change(profile, data):
            configured = next(p for p in data['profiles'] if p['configuration'] is not None)
            for field in ('configuration', 'revision_pointer', 'consensus_revision'):
                profile[field] = configured[field]
        self.reject_native_profile_with_current_table(change, 'storage is local')

    def test_native_profile_cannot_substitute_valid_legacy_opener(self):
        self.reject_native_profile_with_current_table(
            lambda p, _: p['entrypoint'].update(symbol='Node::open'), 'explicit opener')

    def test_native_profile_requires_cli_migration_and_independent_storage_controls(self):
        for path in NATIVE_STORAGE_TESTS:
            with self.subTest(path=path):
                self.reject_native_profile_with_current_table(
                    lambda p, _, path=path: p.update(
                        tests=[s for s in p['tests'] if not s.startswith(path + '::')]),
                    'control selector coverage')

    def test_native_profile_cannot_substitute_standalone_archive_document(self):
        self.reject_native_profile_with_current_table(
            lambda p, _: p.update(document=
                'docs/protocol/pon-nakamoto-v1/details/AUTHENTICATED_STATE_ARCHIVE_V1.md'),
            'contract identity')

    def test_native_profile_retains_storage_recovery_and_evidence_owners(self):
        self.reject_native_profile_with_current_table(
            lambda p, _: p['modules'].remove('M08'), 'responsibility coverage')

    def test_duplicate_profile_controls_do_not_count_as_additional_coverage(self):
        self.reject_native_profile_with_current_table(
            lambda p, _: p['tests'].append(p['tests'][0]), 'duplicate profile test')

    def test_compact_rejection_and_storage_python_controls_bind_every_real_test(self):
        rows = validate(self.root)['procedures']
        row = next(r for r in rows if r['operation'] == 'M17.QualifyExecutedCampaign')
        selectors = set(row['evidence_selectors'])
        for path, count in [
            ('formal/pon-nakamoto-v1/test_account_multiproof_oracle.py', 28),
            ('formal/pon-nakamoto-v1/test_native_authenticated_storage_oracle.py', 29),
            ('formal/pon-nakamoto-v1/test_obligation_range_oracle.py', 13),
            ('scripts/ci/test_work_rejection_report.py', 92),
        ]:
            tree = ast.parse((self.root / path).read_text())
            expected = {path + '::' + cls.name + '.' + method.name
                        for cls in tree.body if isinstance(cls, ast.ClassDef)
                        for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and method.name.startswith('test_')}
            self.assertEqual(len(expected), count, path)
            self.assertTrue(expected <= selectors, path)
        for path, symbol in [
            ('formal/pon-nakamoto-v1/native_authenticated_storage_oracle.py', 'compare_migration'),
            ('formal/pon-nakamoto-v1/account_multiproof_oracle.py', 'root_for_updates'),
            ('formal/pon-nakamoto-v1/obligation_range_oracle.py', 'check_observation'),
            ('formal/pon-nakamoto-v1/obligation_range_oracle.py', 'native_negative_controls'),
            ('scripts/pon_work_rejection_report.py', 'verify'),
        ]:
            self.assertIn({'path': path, 'symbol': symbol}, row['runtime_symbols'])
        self.assertIsNone(row['ordinary_product_entrypoint'])

    def test_factor_and_public_queue_bind_real_tests_without_execution(self):
        result = validate(self.root)
        profiles = {p['id']: p for p in result['profiles']}
        self.assertEqual(profiles['integer-factor-v2']['consensus_revision'], 11)
        self.assertIsNone(profiles['public-intake-v3-r10']['consensus_revision'])
        row = next(r for r in result['procedures']
                   if r['operation'] == 'M10.SubmitFactorContribution')
        self.assertEqual(len([s for s in row['evidence_selectors'] if s.startswith(
            'trillionnium/crates/trnm-pon-node/tests/integer_factor_candidate_v2.rs::')]), 4)
        native = {s for s in profiles[MODEL_EVOLUTION_PROFILE]['tests'] if s.startswith((
            'trillionnium/crates/trnm-mvcc-fee/', 'trillionnium/crates/trnm-pon-node/'))}
        self.assertTrue(native <= set(row['evidence_selectors']))
        self.assertEqual(row['evidence_class'], 'source-binding')
        self.assertFalse(result['tests_executed_by_this_checker'])
        self.assertFalse(result['acceptance_granted'])

    def test_helper_is_not_a_test_even_when_callable(self):
        with self.assertRaises(ValueError):
            check_test_selector(self.root, 'trillionnium/crates/trnm-pon-node/tests/local_mempool.rs::signature')

    def test_commented_or_string_literal_test_is_not_executable(self):
        path = self.root / 'fake_test.rs'
        try:
            for text in ['// #[test]\n// fn test_fake() {}',
                         '/* outer /* inner */ #[test] fn test_fake() {} */',
                         'const S: &str = r#"#[test] fn test_fake() {}"#;']:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    check_test_selector(self.root, 'fake_test.rs::test_fake')
        finally:
            path.unlink(missing_ok=True)

    def test_stale_documented_profile_revision_rejects(self):
        path = self.root / 'docs/architecture/TRNM_DOCUMENTATION_AUTHORITY_V1.md'
        original = path.read_text()
        try:
            path.write_text(original.replace(', revision9', ', revision8'))
            with self.assertRaisesRegex(ValueError, 'table drift'):
                validate(self.root)
        finally:
            path.write_text(original)

    def test_native_m06_execution_and_delta_name_actual_node_owner(self):
        rows = validate(self.root)['procedures']
        for operation in ['M06.ExecuteCandidate', 'M06.DeriveBranchDelta']:
            row = next(r for r in rows if r['operation'] == operation)
            self.assertEqual(row['controlled_entrypoint']['symbol'], 'Node::admit')
            self.assertEqual(row['persistence_owner']['symbol'], 'Node::open')
            self.assertIsNone(row['ordinary_product_entrypoint'])
            self.assertTrue(any('derived_commitment.rs::' in t for t in row['evidence_selectors']))

    def test_native_m05_reconciliation_is_explicit_not_ordinary_product(self):
        rows = validate(self.root)['procedures']
        row = next(r for r in rows if r['operation'] == 'M05.ReconsiderAfterReorg')
        self.assertEqual(row['controlled_entrypoint']['symbol'], 'Node::pool_status')
        self.assertEqual(row['runtime_symbols'][0]['symbol'], 'Node::pool_reconcile')
        self.assertIsNone(row['ordinary_product_entrypoint'])
        self.assertEqual(set(row['evidence_selectors']), {
            'trillionnium/crates/trnm-pon-node/tests/local_mempool.rs::queued_facts_reopen_exact_raws_real_typed_gate_and_funding_nonce_dependencies',
            'trillionnium/crates/trnm-pon-node/tests/local_mempool.rs::retained_groups_restore_after_real_heavier_fork_and_terminal_prune_is_monotonic',
            'trillionnium/crates/trnm-pon-node/src/store/mempool.rs::native_reconcile_and_submission_apply_each_retained_transaction_once_per_operation',
            'trillionnium/crates/trnm-pon-node/src/store/mempool.rs::signature_cache_survives_cancellation_and_unwind_without_publishing_suffix',
        })


if __name__ == '__main__':
    unittest.main(verbosity=2)
