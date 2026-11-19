"""Independent postseal reviewer must run without training or ML frameworks."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PostsealIsolation(unittest.TestCase):
    def test_stdlib_only_python_S_import_fails_if_trainer_imports(self):
        directory = Path(__file__).resolve().parent
        source = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import v10_granite_score\n"
            "for name in ('torch', 'safetensors', 'transformers', 'v10_granite_reader'):\n"
            "    if name in sys.modules: raise SystemExit('training dependency imported: ' + name)\n"
            "if not callable(v10_granite_score.review): raise SystemExit('review not available')\n"
        )
        p = subprocess.run([sys.executable, '-S', '-c', source, str(directory)],
                           text=True, capture_output=True, check=False)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_file_digest_independent_and_byte_sensitive(self):
        import v10_granite_score
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / 'train-receipt.json'
            file.write_bytes(b'{"source":"a"}\n')
            first = v10_granite_score.sha_file(file)
            self.assertEqual(first, hashlib.sha256(file.read_bytes()).hexdigest())
            file.write_bytes(b'{"source":"b"}\n')
            self.assertNotEqual(first, v10_granite_score.sha_file(file))


if __name__ == '__main__':
    unittest.main()
