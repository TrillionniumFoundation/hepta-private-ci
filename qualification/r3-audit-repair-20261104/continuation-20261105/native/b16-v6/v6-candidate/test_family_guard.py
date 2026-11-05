"""Pure Python controls for the conditional family exception; no native builds."""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from b16_capacity import cache_and_capacity
from b16_family import catalog_layout, digest, helper_layout, metadata_projection
from b16_family import normal_helper_layout, validate_foundation_reuse
from b16_family import verify_catalog, verify_helpers, verify_metadata, verify_normal_helpers
from b16_guard import record
from b16_native import HELPERS


class FamilyGateTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            'workspace_root': '/owned/source/codex-rs', 'target_directory': '/owned/target',
            'workspace_members': ['state'], 'workspace_default_members': ['state'],
            'resolve': {'nodes': [{'id': 'state', 'features': ['existing'], 'deps': []}]},
            'packages': [{'id': 'state', 'manifest_path': '/owned/source/codex-rs/state/Cargo.toml',
                          'features': {'existing': []}, 'targets': [{'name': 'state', 'kind': ['lib']}]}],
        }
        self.catalog = {'rust-build-meta': {'target-directory': '/owned/target', 'base-output-directories': ['dev-small']},
            'rust-suites': {'state': {'binary-name': 'state', 'package-name': 'codex-state', 'package-id': 'state',
                'kind': 'lib', 'build-platform': 'target', 'binary-path': '/owned/target/dev-small/deps/state-exact'}}}
        self.normal = [{'target': 'helper', 'package_id': 'helper-id', 'features': ['real'],
                        'path': '/owned/target/dev-small/helper'}]
        self.helpers = [{'path': '/owned/target/dev-small/helper'}]
        self.family = {
            'complete_metadata_projection_sha256': digest(metadata_projection(self.metadata)),
            'complete_rust_build_meta_sha256': digest(self.catalog['rust-build-meta']),
            'complete_catalog_layout': catalog_layout(self.catalog),
            'normal_six_helper_layout': normal_helper_layout(self.normal, '/owned/target'),
            'complete_helper_relative_paths': helper_layout(self.helpers, '/owned/target'),
        }

    def test_full_metadata_target_and_feature_drift_are_rejected(self):
        verify_metadata(self.family, self.metadata)
        for kind in ['target', 'active', 'declared']:
            changed = copy.deepcopy(self.metadata)
            if kind == 'target':
                changed['packages'][0]['targets'].append({'name': 'extra', 'kind': ['bin']})
            elif kind == 'active':
                changed['resolve']['nodes'][0]['features'].append('new-active')
            else:
                changed['packages'][0]['features']['new-declared'] = []
            with self.subTest(kind=kind), self.assertRaisesRegex(RuntimeError, 'full targets'):
                verify_metadata(self.family, changed)

    def test_complete_catalog_rejects_new_empty_or_relocated_unit(self):
        verify_catalog(self.family, self.catalog)
        for kind in ['extra-empty', 'relocated', 'other-platform']:
            changed = copy.deepcopy(self.catalog)
            if kind == 'extra-empty':
                changed['rust-suites']['extra'] = copy.deepcopy(changed['rust-suites']['state'])
                changed['rust-suites']['extra']['testcases'] = {}
            elif kind == 'relocated':
                changed['rust-suites']['state']['binary-path'] = '/owned/target/dev-small/deps/state-newhash'
            else:
                changed['rust-build-meta']['target-platform'] = 'another-target'
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                verify_catalog(self.family, changed)

    def test_normal_features_and_same_basename_helper_path_drift_are_rejected(self):
        verify_normal_helpers(self.family, self.normal, '/owned/target')
        verify_helpers(self.family, self.helpers, '/owned/target')
        changed = copy.deepcopy(self.normal)
        changed[0]['features'].append('unapproved')
        with self.assertRaisesRegex(RuntimeError, 'normal-helper'):
            verify_normal_helpers(self.family, changed, '/owned/target')
        with self.assertRaisesRegex(RuntimeError, 'helper output paths'):
            verify_helpers(self.family, [{'path': '/owned/target/other-profile/helper'}], '/owned/target')

    def test_exception_rejects_driver_and_manifest_changes_before_filesystem_probes(self):
        with self.assertRaisesRegex(RuntimeError, 'foundation-only'):
            validate_foundation_reuse({'authorized_epoch': 'driver'}, {}, {}, [], {})
        family = dict(self.family, payload_sha256='approved', foundation_delta_order=['source'],
                      foundation_source_paths=['codex-rs/state/src/sqlite.rs'])
        with mock.patch('b16_family.load_family', return_value=family):
            with self.assertRaisesRegex(RuntimeError, 'exact 16'):
                validate_foundation_reuse({'authorized_epoch': 'foundation', 'approved_payload_sha256': 'approved'},
                    self.metadata, {'deltas': {'source': {'files': [{'path': 'codex-rs/state/Cargo.toml'}]}}},
                    [{'kind': 'apply', 'delta': 'source'}], {})

    def test_22GB_boundary_is_fresh_and_cannot_apply_to_driver(self):
        with tempfile.TemporaryDirectory(prefix='hepta-b16-family-guard-') as temporary:
            root = Path(temporary)
            target, source = root / 'target', root / 'source'
            target.mkdir()
            source.mkdir()
            names = sorted({name for bins in HELPERS.values() for name in bins} |
                           {'codex', 'codex-hepta-agentd', 'apply_patch', 'codex-linux-sandbox'})
            helpers = [{'path': str(target / name), 'bytes': 1, 'sha256': 'a' * 64} for name in names]
            receipt = root / 'artifact.json'
            receipt.write_text(json.dumps({'source': '1' * 40, 'cargo_profile': 'dev-small', 'nextest_profile': 'local',
                'packages': ['codex-state'], 'helpers_after_catalog_before_just': helpers,
                'test_binaries_after_catalog_before_just': [{'path': str(target / 'state-unit'), 'bytes': 1, 'sha256': 'b' * 64}]}))
            binding = {'last_tested_A_artifacts': record(receipt), 'last_tested_A_tree': '1' * 40,
                'final_A_tree': '2' * 40, 'last_tested_A_to_final_A_review': 'fixture-only',
                'authorized_epoch': 'foundation', 'A_helper_basename_roster': names,
                'target_directory': str(target), 'final_A_target_directory': str(target),
                'source_directory': str(source), 'evidence_directory': str(root / 'unused-evidence'),
                'bazel_cache_directory': str(root / 'unused-cache'), 'min_free_bytes': 8000000000,
                'capacity_plan': {'additional_executable_families': 0, 'other_cargo_growth_bytes': 12000000000,
                    'bazel_growth_bytes': 0, 'evidence_growth_bytes': 2000000000, 'estimate_review_reference': 'fixture-only'}}
            metadata = {'workspace_members': ['state'], 'packages': [{'id': 'state', 'name': 'codex-state'}]}
            # The complete physical-family validator is deliberately isolated here;
            # its real inputs are independently checked by build_proposal.py.
            with mock.patch('b16_capacity.validate_foundation_reuse', return_value={'fixture': True}) as family_check:
                with mock.patch('b16_capacity.shutil.disk_usage', return_value=types.SimpleNamespace(free=22000000000)):
                    result = cache_and_capacity(binding, metadata, {}, [])
                    self.assertEqual(result['required_free_bytes'], 22000000000)
                with mock.patch('b16_capacity.shutil.disk_usage', return_value=types.SimpleNamespace(free=21999999999)):
                    with self.assertRaisesRegex(RuntimeError, 'insufficient reviewed growth budget'):
                        cache_and_capacity(binding, metadata, {}, [])
                self.assertEqual(family_check.call_count, 2)
                binding['authorized_epoch'] = 'driver'
                with self.assertRaisesRegex(RuntimeError, 'at least one additional executable family'):
                    cache_and_capacity(binding, metadata, {}, [])
                self.assertEqual(family_check.call_count, 2)
            self.assertFalse((root / 'unused-cache').exists())
            self.assertFalse((root / 'unused-evidence').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
