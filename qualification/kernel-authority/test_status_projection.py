"""Projection and real temporary-Git anchor regressions, not product evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('authority_status_generator', Path(__file__).with_name('generate_status.py'))
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


def row(port='ModulePort::kernel.authority::runtime.fleet'):
    return dict(id=port, sourcePaths=['src/owner.rs'], note='fixture source composition only',
                contractDefined=True, sourceCompositionPresent=True,
                normalProductInvocationProved=False, exactCandidateExecutionProved=False,
                targetHostQualified=False, independentAcceptance=False)


class PortProjectionTests(unittest.TestCase):
    def test_exact_closed_target_set(self):
        value = row()
        STATUS.validate_port_rows([value], {value['id']})
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_port_rows([value], {value['id'], 'ModulePort::kernel.authority::browser.servo'})
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_port_rows([value, value], {value['id']})

    def test_source_existence_is_not_execution_or_acceptance(self):
        for field in STATUS.PORT_FIELDS[2:]:
            value = row()
            value[field] = True
            with self.subTest(field=field), self.assertRaises(STATUS.StatusError):
                STATUS.validate_port_rows([value], {value['id']})

    def test_strict_boolean_and_source_mapping(self):
        for field, replacement in (('contractDefined', 1), ('sourceCompositionPresent', False),
                                   ('sourcePaths', []), ('targetHostQualified', 0)):
            value = row()
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(STATUS.StatusError):
                STATUS.validate_port_rows([value], {value['id']})

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(STATUS.StatusError):
            json.loads('{"activation":false,"activation":true}', object_pairs_hook=STATUS.unique_pairs)


class SourceAnchorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'qualification fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'src').mkdir()
        (self.root / 'src/owner.rs').write_text('// fixture, not the real authority\n')
        (self.root / 'TECHNICAL.md').write_text('`ModulePort::kernel.authority::runtime.fleet`\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'fixture source anchor')
        self.manifest = json.loads(Path(__file__).with_name('status_manifest.json').read_text())
        self.manifest.update(
            sourceAnchor={'commit': self.git('rev-parse', 'HEAD'), 'tree': self.git('rev-parse', 'HEAD^{tree}')},
            technicalGuide='TECHNICAL.md', declaredRoots=['src'], trackedPaths=['src/owner.rs'],
            operations=[dict(operation='fixture_owner', nativeSymbol='Owner::verify', sourcePath='src/owner.rs',
                             state='fixture_only', authority='none', designOperation='verify', mappingClass='fixture',
                             tests=[], delegatedCallees=[])],
            productCallers=[dict(id='fixture.caller', nativeSymbol='Owner::verify', sourcePath='src/owner.rs',
                                state='fixture_only', tests=[])], targetPorts=[row()],
        )
        self.root_patch = patch.object(STATUS, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, text=True, capture_output=True).stdout.strip()

    def test_exact_anchor_validates_and_all_views_bind_one_identity(self):
        anchor, paths = STATUS.validate_manifest(self.manifest)
        self.assertEqual(paths, ['TECHNICAL.md', 'src/owner.rs'])
        rendered = STATUS.render_projections(self.manifest, anchor)
        self.assertEqual(len(rendered), 8)
        for path, content in rendered.items():
            if path.suffix == '.json':
                value = json.loads(content)
                self.assertEqual(value['sourceBase'], anchor)
            else:
                self.assertIn(anchor['commit'].encode(), content)
        self.assertNotIn(b'Repository source closure is implemented', rendered[STATUS.OUTPUTS['currentImplementation']])

    def test_dirty_mapped_source_rejected(self):
        (self.root / 'src/owner.rs').write_text('// changed but not committed\n')
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_manifest(self.manifest)

    def test_projection_retains_exact_git_objects_without_execution_claims(self):
        (self.root / 'tests').mkdir()
        (self.root / 'tests/recovery.rs').write_text('// separate recovery evidence\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'add separately mapped recovery source')
        self.manifest['operations'][0]['tests'] = ['tests/recovery.rs']
        self.manifest['sourceAnchor'] = {
            'commit': self.git('rev-parse', 'HEAD'),
            'tree': self.git('rev-parse', 'HEAD^{tree}'),
        }
        anchor, _ = STATUS.validate_manifest(self.manifest)
        rendered = STATUS.render_projections(self.manifest, anchor)
        value = json.loads(rendered[STATUS.OUTPUTS['implementationMap']])
        expected_paths = ['TECHNICAL.md', 'src', 'src/owner.rs', 'tests/recovery.rs']
        self.assertEqual(value['sourceObjects'], [
            {'path': path, 'object': self.git('rev-parse', f'HEAD:{path}')}
            for path in expected_paths
        ])
        self.assertFalse(value['productionImplementation'])
        self.assertTrue(all(value['claimBoundary'][field] is False for field in STATUS.EXECUTION_CLAIMS))

    def test_committed_source_after_anchor_requires_rebinding(self):
        (self.root / 'src/owner.rs').write_text('// a new source revision\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'new source')
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_manifest(self.manifest)
        self.manifest['sourceAnchor'] = {'commit': self.git('rev-parse', 'HEAD'), 'tree': self.git('rev-parse', 'HEAD^{tree}')}
        STATUS.validate_manifest(self.manifest)

    def test_wrong_tree_and_nonancestor_are_rejected(self):
        wrong = copy.deepcopy(self.manifest)
        wrong['sourceAnchor']['tree'] = '0' * 40
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_manifest(wrong)
        self.git('checkout', '-q', '--orphan', 'unrelated')
        self.git('commit', '-q', '-m', 'unrelated history')
        with self.assertRaises(subprocess.CalledProcessError):
            STATUS.validate_manifest(self.manifest)

    def test_self_granted_production_and_unsafe_path_rejected(self):
        self.manifest['claimBoundary']['productionImplementation'] = True
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_manifest(self.manifest)
        self.manifest['claimBoundary']['productionImplementation'] = False
        self.manifest['operations'][0]['sourcePath'] = '../escape.rs'
        with self.assertRaises(STATUS.StatusError):
            STATUS.validate_manifest(self.manifest)


if __name__ == '__main__':
    unittest.main()
