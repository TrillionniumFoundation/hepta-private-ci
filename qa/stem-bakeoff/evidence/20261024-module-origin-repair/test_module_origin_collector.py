import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from module_origin_collector import collect_module_origins


class OriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def collect(self, value):
        module = types.ModuleType('fixture')
        module.__file__ = value
        return collect_module_origins({'fixture': module}, self.root)

    def test_real_source_hash(self):
        path = self.root / 'module.py'
        path.write_bytes(b'actual source')
        result = self.collect(str(path))
        self.assertEqual(result['source_module_origins']['fixture'], {
            'path': 'module.py', 'bytes': 13,
            'sha256': hashlib.sha256(b'actual source').hexdigest()})
        self.assertFalse(result['complete_dynamic_import_attestation'])

    def test_relative_never_reads_even_matching_file(self):
        (self.root / '_ops.py').write_text('not the virtual module')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('must not read')):
            result = self.collect('_ops.py')
        self.assertEqual(result['source_module_origins'], {})
        self.assertEqual(result['module_origins']['fixture']['kind'], 'relative_or_virtual')

    def test_no_dynamic_getattr(self):
        module = types.ModuleType('dynamic')
        def explode(name):
            raise AssertionError(name)
        module.__getattr__ = explode
        result = collect_module_origins({'dynamic': module}, self.root)
        self.assertEqual(result['module_origins']['dynamic']['kind'], 'no_file_attribute')

    def test_missing_source_is_error(self):
        with self.assertRaises(FileNotFoundError):
            self.collect(str(self.root / 'missing.py'))

    def test_unreadable_source_is_error(self):
        path = self.root / 'source.py'
        path.write_text('x')
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.collect(str(path))

    def test_nonregular_source_is_error(self):
        with self.assertRaises(ValueError):
            self.collect(str(self.root))

    def test_external_is_not_hashed(self):
        result = self.collect('/external/not-read.py')
        self.assertEqual(result['source_module_origins'], {})
        self.assertEqual(result['module_origins']['fixture']['kind'], 'external_absolute_unhashed')

    def test_invalid_attribute_is_explicit(self):
        self.assertEqual(self.collect(7)['module_origins']['fixture']['kind'], 'non_path_file_attribute')

    def test_source_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as outer:
            target = Path(outer) / 'other.py'
            target.write_text('x')
            link = self.root / 'escape.py'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                self.collect(str(link))


if __name__ == '__main__':
    unittest.main()
