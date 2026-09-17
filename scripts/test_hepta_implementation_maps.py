import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("hepta-implementation-maps.py")
SPEC = importlib.util.spec_from_file_location("hepta_implementation_maps", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MAPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAPS)


class ImplementationMapBlobEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.old_root = MAPS.ROOT
        MAPS.ROOT = self.root

    def tearDown(self):
        MAPS.ROOT = self.old_root
        self.temp.cleanup()

    def write(self, rel: str, content: str) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return subprocess.run(
            ["git", "hash-object", rel],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def test_bound_file_evidence_accepts_exact_blob_and_symbol(self):
        blob = self.write("src/caller.rs", "fn finalize_cognitive_context() {}\n")
        failures = []
        MAPS.verify_bound_files(
            "cognitive.read",
            "product caller",
            [
                {
                    "path": "src/caller.rs",
                    "blobSha": blob,
                    "symbol": "finalize_cognitive_context",
                }
            ],
            failures,
        )
        self.assertEqual(failures, [])

    def test_bound_file_evidence_rejects_code_drift(self):
        old_blob = self.write("src/caller.rs", "fn final_use() {}\n")
        self.write("src/caller.rs", "fn final_use() { changed(); }\n")
        failures = []
        MAPS.verify_bound_files(
            "cognitive.read",
            "source evidence",
            [
                {
                    "path": "src/caller.rs",
                    "blobSha": old_blob,
                    "symbol": "final_use",
                }
            ],
            failures,
        )
        self.assertTrue(any("stale source evidence blob" in item for item in failures))

    def test_bound_file_evidence_rejects_missing_symbol(self):
        blob = self.write("src/caller.rs", "fn unrelated() {}\n")
        failures = []
        MAPS.verify_bound_files(
            "cognitive.read",
            "product caller",
            [
                {
                    "path": "src/caller.rs",
                    "blobSha": blob,
                    "symbol": "finalize_cognitive_context",
                }
            ],
            failures,
        )
        self.assertTrue(any("missing product caller symbol" in item for item in failures))

    def test_bound_file_evidence_rejects_duplicate_paths(self):
        blob = self.write("src/caller.rs", "fn final_use() {}\n")
        entry = {
            "path": "src/caller.rs",
            "blobSha": blob,
            "symbol": "final_use",
        }
        failures = []
        MAPS.verify_bound_files(
            "cognitive.read",
            "product caller",
            [entry, dict(entry)],
            failures,
        )
        self.assertTrue(any("invalid/duplicate product caller path" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
