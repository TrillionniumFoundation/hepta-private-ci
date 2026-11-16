"""P0/P2: prospective C2 source freeze, no old job or model execution."""
import tempfile
import subprocess
import sys
import json
from pathlib import Path
from unittest import TestCase, mock

import c2_runner
import c2_durable
from c2_boundary import Ineligible
from c2_io import identity
from c2_program_freeze import REQUIRED_FILES, collect_manifest, publish_manifest


class ProgramManifestFreezeTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'c2_successor_v1'
        self.recovery = self.root.parent / 'recovery_v1'
        self.root.mkdir()
        self.recovery.mkdir()
        self.durable = self.recovery / 'c2_durable.py'
        self.durable.write_bytes(b'publisher-v1')
        for name in REQUIRED_FILES:
            (self.root / name).write_bytes(('source:' + name).encode())

    def bind(self):
        with mock.patch.object(c2_runner, '__file__', str(self.root / 'c2_runner.py')):
            with mock.patch.object(c2_durable, '__file__', str(self.durable)):
                return c2_runner.bind_program(self.root / 'PROGRAM-MANIFEST.json')

    def test_no_implicit_manifest_or_authorization(self):
        preview = collect_manifest(self.root)
        self.assertEqual(preview['scientific_admission'], 'HOLD_NO_GO')
        self.assertFalse((self.root / 'PROGRAM-MANIFEST.json').exists())

    def test_partial_candidate_has_no_publication(self):
        (self.root / 'CONTRACT.json').unlink()
        with self.assertRaises(Ineligible):
            publish_manifest(self.root)
        self.assertFalse((self.root / 'PROGRAM-MANIFEST.json').exists())

    def test_cli_missing_contract_reports_hold_without_writing(self):
        (self.root / 'CONTRACT.json').unlink()
        import c2_program_freeze
        completed = subprocess.run(
            [sys.executable, '-B', str(Path(c2_program_freeze.__file__)),
             '--candidate-dir', str(self.root)],
            check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'HOLD_NO_GO')
        self.assertFalse((self.root / 'PROGRAM-MANIFEST.json').exists())

    def test_missing_publisher_is_fail_closed(self):
        self.durable.unlink()
        with self.assertRaises(Ineligible):
            publish_manifest(self.root)
        self.assertFalse((self.root / 'PROGRAM-MANIFEST.json').exists())

    def test_symlinked_publisher_is_fail_closed(self):
        original = self.recovery / 'real.py'
        self.durable.rename(original)
        self.durable.symlink_to(original)
        with self.assertRaises(Ineligible):
            collect_manifest(self.root)

    def test_actual_bind_program_accepts_only_exact_preview_bytes(self):
        manifest, receipt = publish_manifest(self.root)
        self.assertEqual(receipt, identity(self.root / 'PROGRAM-MANIFEST.json'))
        self.assertEqual(manifest['scientific_admission'], 'HOLD_NO_GO')
        closure = self.bind()
        self.assertIn(str(self.durable.resolve()), closure)
        self.assertEqual(closure[str(self.durable.resolve())], manifest['dependencies']['recovery_v1/c2_durable.py'])

    def test_mutation_after_freeze_is_rejected_by_actual_runner(self):
        publish_manifest(self.root)
        (self.root / 'c2_io.py').write_bytes(b'altered after source freeze')
        with self.assertRaises(Ineligible):
            self.bind()

    def test_manifest_create_once_not_overwritten(self):
        publish_manifest(self.root)
        with self.assertRaises(FileExistsError):
            publish_manifest(self.root)
        self.bind()

    # Regression: exact digest binding cannot rehabilitate an ambiguous or
    # symlinked source/manifest or grant an undeclared execution scope.
    def test_manifest_requires_exact_status_and_schema(self):
        manifest, _ = publish_manifest(self.root)
        path = self.root / 'PROGRAM-MANIFEST.json'
        for key, value in (
            ('scientific_admission', 'GO'),
            ('execution_authorized', True),
            ('schema', 'legacy-unversioned'),
        ):
            with self.subTest(field=key):
                variant = dict(manifest)
                variant[key] = value
                path.write_text(json.dumps(variant), encoding='utf-8')
                with self.assertRaises(Ineligible):
                    self.bind()

    def test_manifest_rejects_missing_schema_and_extra_file(self):
        manifest, _ = publish_manifest(self.root)
        path = self.root / 'PROGRAM-MANIFEST.json'
        without_schema = dict(manifest)
        without_schema.pop('schema')
        path.write_text(json.dumps(without_schema), encoding='utf-8')
        with self.assertRaises(Ineligible):
            self.bind()
        (self.root / 'unreviewed.py').write_text('pass\n', encoding='utf-8')
        with_extra = dict(manifest)
        with_extra['files'] = dict(manifest['files'])
        with_extra['files']['unreviewed.py'] = identity(self.root / 'unreviewed.py')
        path.write_text(json.dumps(with_extra), encoding='utf-8')
        with self.assertRaises(Ineligible):
            self.bind()

    def test_manifest_rejects_duplicate_root_key(self):
        manifest, _ = publish_manifest(self.root)
        text = json.dumps(manifest)
        self.assertIn('"schema":', text)
        text = text.replace('"schema":', '"schema": "attacker-override", "schema":', 1)
        (self.root / 'PROGRAM-MANIFEST.json').write_text(text, encoding='utf-8')
        with self.assertRaises(Ineligible):
            self.bind()

    def test_manifest_rejects_nonfinite_metadata(self):
        manifest, _ = publish_manifest(self.root)
        manifest['cost_claim'] = float('nan')
        (self.root / 'PROGRAM-MANIFEST.json').write_text(
            json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(Ineligible):
            self.bind()

    def test_manifest_rejects_source_symlink_to_matching_bytes(self):
        manifest, _ = publish_manifest(self.root)
        path = self.root / 'c2_io.py'
        path.unlink()
        path.symlink_to(self.root / 'c2_recording.py')
        manifest['files']['c2_io.py'] = identity(self.root / 'c2_recording.py')
        (self.root / 'PROGRAM-MANIFEST.json').write_text(
            json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(Ineligible):
            self.bind()

    def test_manifest_rejects_manifest_symlink(self):
        publish_manifest(self.root)
        old = self.root / 'PROGRAM-MANIFEST.json'
        alternate = self.root / 'alias.json'
        old.rename(alternate)
        old.symlink_to(alternate)
        with self.assertRaises(Ineligible):
            self.bind()
