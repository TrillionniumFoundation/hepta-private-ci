import copy
import json
import unittest

from matrix_dependency_gate import (
    ADVISORY_ANYMAP,
    ADVISORY_CRYPTO,
    ADVISORY_UNSAFE_YAML,
    audit,
    find_path,
    version,
)


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
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='0.19.1'
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

    def _candidate_without_known_static_advisory(self):
        # This is a deliberately artificial lock graph used to probe a
        # *prerequisite checker*. It is NOT a resolved Cargo dependency graph
        # or a certificate of patched Matrix encryption.
        self.workspace['workspace']['dependencies']['matrix-sdk']['version']='0.19.1'
        self.workspace['patch']['crates-io']['matrix-sdk-sqlite']['path']='third_party/matrix-sdk-sqlite-0.19.1'
        self.toolchain['toolchain']['channel']='1.96.0'
        for package in self.lock['package']:
            if package['name'].startswith('matrix-sdk'):
                package['version']='0.19.1'
            if package['name']=='matrix-sdk':
                package['dependencies']=[
                    dep.replace('anymap2','anymap3') for dep in package['dependencies']]
            if package['name']=='anymap2':
                package['name']='anymap3'

    def test_static_prerequisite_never_claims_actual_advisory_remediation(self):
        self._candidate_without_known_static_advisory()
        r=self.result()
        self.assertTrue(r['static_prerequisites_passed'],r['blocking_prerequisites'])
        self.assertTrue(r['static_graph_advisory_candidates_clean'])
        self.assertIs(r['security_advisories_resolved'], False)
        self.assertIs(r['cargo_deny_verified'], False)
        self.assertIs(r['matrix_e2ee_verified'], False)

    def test_crypto_only_upgrade_cannot_hide_old_base_or_sqlite(self):
        self._candidate_without_known_static_advisory()
        for component in ('matrix-sdk-base', 'matrix-sdk-sqlite', 'matrix-sdk-crypto'):
            changed=copy.deepcopy(self.lock)
            for package in changed['package']:
                if package['name']==component:
                    package['version']='0.18.0'
            r=audit(self.workspace,changed,self.deny,self.toolchain,self.sdk_manifest,self.matrixd_manifest)
            self.assertIn('MATRIX_FAMILY_RELEASE_MISMATCH:'+component,r['blocking_prerequisites'])
            self.assertFalse(r['static_prerequisites_passed'])
            self.assertIs(r['security_advisories_resolved'],False)

    def test_orphaned_or_duplicated_sdk_family_components_cannot_pass(self):
        self._candidate_without_known_static_advisory()
        for component in ('matrix-sdk-base','matrix-sdk-sqlite','matrix-sdk-crypto'):
            missing=copy.deepcopy(self.lock)
            missing['package']=[p for p in missing['package'] if p['name']!=component]
            r=audit(self.workspace,missing,self.deny,self.toolchain,self.sdk_manifest,self.matrixd_manifest)
            self.assertIn('MATRIX_FAMILY_COMPONENT_MISSING_OR_AMBIGUOUS:'+component,r['blocking_prerequisites'])
            duplicated=copy.deepcopy(self.lock)
            entry=next(p for p in duplicated['package'] if p['name']==component)
            duplicated['package'].append(copy.deepcopy(entry))
            r=audit(self.workspace,duplicated,self.deny,self.toolchain,self.sdk_manifest,self.matrixd_manifest)
            self.assertIn('MATRIX_FAMILY_COMPONENT_MISSING_OR_AMBIGUOUS:'+component,r['blocking_prerequisites'])

    def test_unreachable_base_sqlite_or_crypto_is_not_a_valid_sdk_upgrade(self):
        self._candidate_without_known_static_advisory()
        for component in ('matrix-sdk-base','matrix-sdk-sqlite','matrix-sdk-crypto'):
            detached=copy.deepcopy(self.lock)
            for p in detached['package']:
                p['dependencies']=[x for x in p.get('dependencies',[])
                                   if x != component]
            r=audit(self.workspace,detached,self.deny,self.toolchain,self.sdk_manifest,self.matrixd_manifest)
            self.assertIn('MATRIX_FAMILY_DEPENDENCY_PATH_MISSING:'+component,
                          r['blocking_prerequisites'])
            self.assertFalse(r['static_prerequisites_passed'])

    def test_direct_test_sdk_edge_cannot_disguise_detached_production_adapter(self):
        self._candidate_without_known_static_advisory()
        # Matrixd directly uses Matrix SDK in native E2EE test code, so the
        # old name-only root path was satisfied even if production lost its
        # mandatory codex-hepta-matrix-sdk adapter.
        self.assertTrue(self.result()['static_prerequisites_passed'])
        row = next(p for p in self.lock['package']
                   if p['name'] == 'codex-hepta-matrixd')
        row['dependencies'].remove('codex-hepta-matrix-sdk')
        report = self.result()
        self.assertIn('MATRIX_PRODUCT_ADAPTER_DEPENDENCY_MISSING',
                      report['blocking_prerequisites'])
        self.assertEqual(report['dependency_paths']['matrix-sdk'],
                         ['codex-hepta-matrixd', 'matrix-sdk'])
        self.assertFalse(report['static_prerequisites_passed'])
        self.assertFalse(report['production_authorized'])

    def test_production_adapter_must_link_real_sdk_and_crypto(self):
        self._candidate_without_known_static_advisory()
        row = next(p for p in self.lock['package']
                   if p['name'] == 'codex-hepta-matrix-sdk')
        row['dependencies'].remove('matrix-sdk')
        report = self.result()
        self.assertIn('MATRIX_PRODUCT_ADAPTER_SDK_EDGE_MISSING',
                      report['blocking_prerequisites'])
        self.assertIn('MATRIX_PRODUCT_ADAPTER_E2EE_PATH_MISSING',
                      report['blocking_prerequisites'])
        self.assertIsNone(report['production_adapter_paths']['adapter_to_crypto'])
        self.assertFalse(report['static_graph_advisory_candidates_clean'])

    def test_e2ee_test_manifest_and_lock_must_agree(self):
        self._candidate_without_known_static_advisory()
        row = next(p for p in self.lock['package']
                   if p['name'] == 'codex-hepta-matrixd')
        row['dependencies'].remove('matrix-sdk')
        report = self.result()
        self.assertIn('MATRIX_E2EE_CONFORMANCE_LOCK_EDGE_MISSING',
                      report['blocking_prerequisites'])
        # Production remains linked, but dropped native E2EE test coverage
        # still prevents declaring even the static prerequisite complete.
        self.assertEqual(report['production_adapter_paths']['adapter_to_sdk'],
                         ['codex-hepta-matrix-sdk', 'matrix-sdk'])
        self.assertFalse(report['static_prerequisites_passed'])

    def test_duplicate_or_missing_product_roots_cannot_merge_lock_edges(self):
        self._candidate_without_known_static_advisory()
        for name in ('codex-hepta-matrixd', 'codex-hepta-matrix-sdk'):
            duplicate = copy.deepcopy(self.lock)
            victim = next(p for p in duplicate['package'] if p['name'] == name)
            duplicate['package'].append(copy.deepcopy(victim))
            report = audit(self.workspace, duplicate, self.deny, self.toolchain,
                           self.sdk_manifest, self.matrixd_manifest)
            self.assertIn('MATRIX_PRODUCT_ROOT_MISSING_OR_AMBIGUOUS:' + name,
                          report['blocking_prerequisites'])
            missing = copy.deepcopy(self.lock)
            missing['package'] = [p for p in missing['package'] if p['name'] != name]
            report = audit(self.workspace, missing, self.deny, self.toolchain,
                           self.sdk_manifest, self.matrixd_manifest)
            self.assertIn('MATRIX_PRODUCT_ROOT_MISSING_OR_AMBIGUOUS:' + name,
                          report['blocking_prerequisites'])

    def test_advisory_ignore_makes_security_check_fail(self):
        self.deny['advisories']['ignore']=[{'id':ADVISORY_CRYPTO,'reason':'pretend'}]
        self.assertIn('FORBIDDEN_ADVISORY_IGNORE:'+ADVISORY_CRYPTO, self.result()['blocking_prerequisites'])
        self.deny['advisories']['ignore']=[ADVISORY_ANYMAP]
        self.assertIn('FORBIDDEN_ADVISORY_IGNORE:'+ADVISORY_ANYMAP, self.result()['blocking_prerequisites'])

    def test_unsafe_yaml_parser_is_an_independent_release_blocker(self):
        candidate = copy.deepcopy(self.lock)
        candidate['package'].append({
            'name': 'unsafe-libyaml',
            'version': '0.2.11',
            'dependencies': [],
        })
        report = audit(self.workspace, candidate, self.deny, self.toolchain,
                       self.sdk_manifest, self.matrixd_manifest)
        self.assertIn(ADVISORY_UNSAFE_YAML, report['blocking_prerequisites'])
        self.assertFalse(report['static_prerequisites_passed'])
        self.deny['advisories']['ignore'] = [
            {'id': ADVISORY_UNSAFE_YAML, 'reason': 'pretend'}
        ]
        report = audit(self.workspace, candidate, self.deny, self.toolchain,
                       self.sdk_manifest, self.matrixd_manifest)
        self.assertIn('FORBIDDEN_ADVISORY_IGNORE:' + ADVISORY_UNSAFE_YAML,
                      report['blocking_prerequisites'])

    def test_matrix_graph_pruning_does_not_prove_safety(self):
        self.deny['graph']['exclude']=['matrix-sdk 0.18.0']
        self.assertIn('FORBIDDEN_MATRIX_GRAPH_PRUNE',self.result()['blocking_prerequisites'])

    def test_pruning_matrix_consumer_root_cannot_hide_crypto_advisories(self):
        # Removing the consuming package prunes the complete transitive graph,
        # even without spelling matrix-sdk or anymap2 in the exclusion.
        for package in ('codex-hepta-matrixd', 'anymap3', 'rusqlite',
                        'sqlx', 'libsqlite3-sys'):
            self.deny['graph']['exclude']=[package]
            self.assertIn('FORBIDDEN_MATRIX_GRAPH_PRUNE',
                          self.result()['blocking_prerequisites'])
        self.deny['graph']['exclude']=[]

    def test_platform_scoped_deny_or_suppressed_defaults_are_not_global_security(self):
        self.deny['graph']['targets']=['wasm32-unknown-unknown']
        self.assertIn('FORBIDDEN_MATRIX_TARGET_FILTER',
                      self.result()['blocking_prerequisites'])
        self.deny['graph'].pop('targets')
        self.deny['graph']['no-default-features']=True
        self.assertIn('FORBIDDEN_MATRIX_DEFAULT_FEATURE_SUPPRESSION',
                      self.result()['blocking_prerequisites'])

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
