import copy
import json
import unittest

from matrix_dependency_gate import audit, find_path, version, ADVISORY_ANYMAP, ADVISORY_CRYPTO


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.workspace = {
            'workspace': {'dependencies': {'matrix-sdk': {'version': '0.18.0', 'features': ['e2e-encryption', 'sqlite'], 'default-features': False}}},
            'patch': {'crates-io': {'matrix-sdk-sqlite': {'path': 'third_party/matrix-sdk-sqlite-0.18.0'}}},
        }
        self.lock = {'package': [
            {'name':'codex-hepta-matrixd','version':'0.0.0', 'dependencies':['codex-hepta-matrix-sdk','matrix-sdk']},
            {'name':'codex-hepta-matrix-sdk','version':'0.0.0','dependencies':['matrix-sdk']},
            {'name':'matrix-sdk','version':'0.18.0','dependencies':['matrix-sdk-base','matrix-sdk-sqlite','anymap2']},
            {'name':'matrix-sdk-base','version':'0.18.0','dependencies':['matrix-sdk-crypto']},
            {'name':'matrix-sdk-crypto','version':'0.18.0','dependencies':[]},
            {'name':'matrix-sdk-sqlite','version':'0.18.0','dependencies':['matrix-sdk-crypto']},
            {'name':'anymap2','version':'0.13.0','dependencies':[]},
        ]}
        self.deny={'advisories': {'ignore': []}, 'graph': {'exclude': []}}
        self.toolchain={'toolchain': {'channel':'1.95.0'}}
        self.sdk_manifest={'dependencies': {'matrix-sdk': {'workspace':True}}}
        self.matrixd_manifest={'dev-dependencies': {'matrix-sdk': {'workspace': True}}}

    def result(self):
        return audit(self.workspace, self.lock, self.deny, self.toolchain, self.sdk_manifest, self.matrixd_manifest)

    def test_current_lock_proves_both_advisories_and_exact_root_paths(self):
        r=self.result()
        self.assertIn(ADVISORY_CRYPTO,r['blocking_prerequisites'])
        self.assertIn(ADVISORY_ANYMAP,r['blocking_prerequisites'])
        self.assertEqual(r['dependency_paths']['anymap2'],['codex-hepta-matrixd','matrix-sdk','anymap2'])
        self.assertEqual(r['dependency_paths']['matrix-sdk-crypto'], ['codex-hepta-matrixd','matrix-sdk','matrix-sdk-base','matrix-sdk-crypto'])
        self.assertFalse(r['production_authorized'])

    def test_019_version_only_still_rejected_by_anymap_and_msrvs(self):
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='0.19.1'
        for p in self.lock['package']:
            if p['name'].startswith('matrix-sdk'):
                p['version']='0.19.1'
        r=self.result()
        self.assertNotIn(ADVISORY_CRYPTO,r['blocking_prerequisites'])
        self.assertIn(ADVISORY_ANYMAP,r['blocking_prerequisites'])
        self.assertIn('MATRIX_019_RUST_MSRV_INCOMPATIBLE',r['blocking_prerequisites'])
        self.assertIn('MATRIX_SQLITE_PATCH_RELEASE_MISMATCH',r['blocking_prerequisites'])

    def test_019_with_anymap3_and_version_aligned_patch_passes_static_only(self):
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='=0.19.1'
        self.workspace['patch']['crates-io']['matrix-sdk-sqlite']['path']='third_party/matrix-sdk-sqlite-0.19.1'
        self.toolchain['toolchain']['channel']='1.96.0'
        for p in self.lock['package']:
            if p['name'].startswith('matrix-sdk'):
                p['version']='0.19.1'
            if p['name']=='matrix-sdk':
                p['dependencies']=[x.replace('anymap2','anymap3') for x in p['dependencies']]
            if p['name']=='anymap2':
                p['name']='anymap3'
        r=self.result()
        self.assertTrue(r['static_prerequisites_passed'],r['blocking_prerequisites'])
        self.assertFalse(r['cargo_deny_verified'])
        self.assertFalse(r['matrix_e2ee_verified'])
        self.assertFalse(r['production_authorized'])

    def test_cargo_strict_equals_pin_matches_safe_019_lock_without_waiver(self):
        # Cargo's '=0.19.1' is more restrictive than the plain 0.19.1
        # original research notation. It is neither a range nor a lock drift.
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='=0.19.1'
        self.workspace['patch']['crates-io'].clear()
        self.toolchain['toolchain']['channel']='1.96.0'
        for pkg in self.lock['package']:
            if pkg['name'].startswith('matrix-sdk'):
                pkg['version']='0.19.1'
            if pkg['name']=='matrix-sdk':
                pkg['dependencies']=[value.replace('anymap2','anymap3')
                                     for value in pkg['dependencies']]
            if pkg['name']=='anymap2':
                pkg['name']='anymap3'
                pkg['version']='1.1.0'
        report=self.result()
        self.assertTrue(report['static_prerequisites_passed'],report['blocking_prerequisites'])
        self.assertEqual(report['matrix_sdk_requested_version'],'=0.19.1')
        self.assertFalse(report['cargo_deny_verified'])
        self.assertFalse(report['matrix_e2ee_verified'])
        self.assertFalse(report['production_authorized'])
        # An exact manifest declaration MUST still match Cargo.lock.
        self.lock['package'][2]['version']='0.18.0'
        self.assertIn('MATRIX_SDK_WORKSPACE_LOCK_MISMATCH',
                      self.result()['blocking_prerequisites'])

    def test_caret_compatible_requirement_is_not_a_security_pin(self):
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='0.19.1'
        self.workspace['patch']['crates-io']['matrix-sdk-sqlite']['path']=(
            'third_party/matrix-sdk-sqlite-0.19.1')
        self.toolchain['toolchain']['channel']='1.96.0'
        for item in self.lock['package']:
            if item['name'].startswith('matrix-sdk'):
                item['version']='0.19.1'
            if item['name']=='matrix-sdk':
                item['dependencies']=[x.replace('anymap2','anymap3')
                                      for x in item['dependencies']]
            if item['name']=='anymap2':
                item['name']='anymap3'
        self.assertIn('MATRIX_SDK_CARGO_REQUIREMENT_NOT_EXACT',
                      self.result()['blocking_prerequisites'])

    def test_cargo_ranges_and_double_equals_do_not_become_exact_pins(self):
        self.assertEqual(version('=0.19.1'),(0,19,1))
        for value in ('==0.19.1','>=0.19.1','~0.19.1','^0.19.1','0.19.*'):
            with self.assertRaises(ValueError):
                version(value)

    def test_advisory_ignore_makes_security_check_fail(self):
        self.deny['advisories']['ignore']=[{'id':ADVISORY_CRYPTO,'reason':'pretend'}]
        self.assertIn('FORBIDDEN_ADVISORY_IGNORE:'+ADVISORY_CRYPTO, self.result()['blocking_prerequisites'])
        self.deny['advisories']['ignore']=[ADVISORY_ANYMAP]
        self.assertIn('FORBIDDEN_ADVISORY_IGNORE:'+ADVISORY_ANYMAP, self.result()['blocking_prerequisites'])

    def test_matrix_graph_pruning_does_not_prove_safety(self):
        self.deny['graph']['exclude']=['matrix-sdk 0.18.0']
        self.assertIn('FORBIDDEN_MATRIX_GRAPH_PRUNE',self.result()['blocking_prerequisites'])

    def test_disabling_e2ee_or_sqlite_is_not_an_upgrade(self):
        for feat in ('e2e-encryption','sqlite'):
            clone=copy.deepcopy(self.workspace)
            clone['workspace']['dependencies']['matrix-sdk']['features'].remove(feat)
            r=audit(clone,self.lock,self.deny,self.toolchain,self.sdk_manifest,self.matrixd_manifest)
            self.assertIn('REQUIRED_E2EE_SQLITE_FEATURES_REDUCED',r['blocking_prerequisites'])
        self.workspace['workspace']['dependencies']['matrix-sdk']['default-features']=True
        self.assertIn('REQUIRED_E2EE_SQLITE_FEATURES_REDUCED',self.result()['blocking_prerequisites'])

    def test_sdk_manifest_cannot_be_removed_to_clear_cargo_deny(self):
        self.sdk_manifest['dependencies'].clear()
        self.assertIn('MATRIX_PRODUCTION_ADAPTER_UNPINNED',self.result()['blocking_prerequisites'])
        self.matrixd_manifest['dev-dependencies'].clear()
        self.assertIn('MATRIX_E2EE_CONFORMANCE_DEPENDENCY_REMOVED',self.result()['blocking_prerequisites'])

    def test_inconsistent_lock_or_invalid_version_rejected(self):
        self.lock['package'][2]['version']='0.17.0'
        self.assertIn('MATRIX_SDK_WORKSPACE_LOCK_MISMATCH',self.result()['blocking_prerequisites'])
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='latest'
        self.assertIn('MATRIX_SDK_VERSION_NOT_FIXED',self.result()['blocking_prerequisites'])

    def test_sqlite_patch_drop_needs_explicit_new_wal_review(self):
        self.workspace['patch']['crates-io'].clear()
        self.assertIn('MATRIX_018_SQLITE_WAL_RESET_PATCH_MISSING',self.result()['blocking_prerequisites'])

    def test_version_parser_fails_open_ended_versions(self):
        for candidate in ('*','0.19.x','^0.19.1','1.95-beta'):
            with self.assertRaises(ValueError):
                version(candidate)

    def test_graph_does_not_report_unrelated_crate_as_matrix_path(self):
        g={'root':{'matrix-sdk'},'other':{'anymap2'},'matrix-sdk':{'matrix-sdk-crypto'},'matrix-sdk-crypto':set()}
        self.assertIsNone(find_path(g,'root','anymap2'))
        self.assertEqual(find_path(g,'root','matrix-sdk-crypto'),['root','matrix-sdk','matrix-sdk-crypto'])

    def test_duplicate_lock_package_version_detected(self):
        self.lock['package'].append({'name':'matrix-sdk','version':'0.19.1','dependencies':[]})
        self.assertIn('MATRIX_SDK_LOCK_AMBIGUOUS_OR_MISSING',self.result()['blocking_prerequisites'])

    def test_report_has_no_production_authorization_even_if_clean(self):
        result=self.result()
        document=json.loads(json.dumps(result))
        self.assertFalse(document['production_authorized'])
        self.assertIs(document['cargo_deny_verified'], False)


if __name__ == '__main__':
    unittest.main()