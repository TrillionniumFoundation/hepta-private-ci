"""P0 regression: the unadopted C2 successor must bind its durable code dependency.

Synthetic manifests only; no live C2 campaign, checkpoint, model, or original path touched.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import c2_runner
import c2_durable
from c2_boundary import Ineligible
from c2_io import identity


REQUIRED = (
    'c2_runner.py', 'c2_io.py', 'c2_recording.py', 'c2_boundary.py',
    'c2_controller.py', 'POSTERIOR-POLICY.json',
    'OPTIMIZATION-POSTERIOR-POLICY-v2.json', 'CONTRACT.json'
)


class ProgramDependencyClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.successor = base / 'c2_successor_v1'
        self.recovery = base / 'recovery_v1'
        self.successor.mkdir()
        self.recovery.mkdir()
        for name in REQUIRED:
            (self.successor / name).write_bytes(('fixture:' + name).encode())
        self.durable = self.recovery / 'c2_durable.py'
        self.durable.write_bytes(b'original-durable-module')
        self.manifest = self.successor / 'PROGRAM-MANIFEST.json'

    def write_manifest(self, *, include_dependency):
        info = {'files': {name: identity(self.successor / name) for name in REQUIRED}}
        if include_dependency:
            info['dependencies'] = {'recovery_v1/c2_durable.py': identity(self.durable)}
        self.manifest.write_text(json.dumps(info))
        return info

    def gate(self):
        with mock.patch.object(c2_runner, '__file__', str(self.successor / 'c2_runner.py')):
            return c2_runner.bind_program(self.manifest)

    def test_no_recovery_durable_digest_must_fail_closed(self):
        self.write_manifest(include_dependency=False)
        with self.assertRaises(Ineligible):
            self.gate()

    def test_mutated_recovery_durable_code_must_fail_closed(self):
        self.write_manifest(include_dependency=True)
        self.durable.write_bytes(b'changed-after-frozen-manifest')
        with self.assertRaises(Ineligible):
            self.gate()


    def test_matching_durable_bytes_and_module_origin_enter_input_closure(self):
        self.write_manifest(include_dependency=True)
        with mock.patch.object(c2_durable, '__file__', str(self.durable)):
            sources = self.gate()
        self.assertEqual(sources[str(self.durable.resolve())], identity(self.durable))

    def test_shadowed_durable_import_must_fail_closed(self):
        self.write_manifest(include_dependency=True)
        with mock.patch.object(c2_durable, '__file__', str(self.successor / 'c2_io.py')):
            with self.assertRaises(Ineligible):
                self.gate()


if __name__ == '__main__':
    unittest.main()
