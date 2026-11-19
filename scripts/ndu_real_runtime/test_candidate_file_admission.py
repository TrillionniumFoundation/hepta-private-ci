"""The host rejects a candidate sidecar replaced during file admission."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .candidate_runtime import CandidateRuntime, read_audit
from .test_candidate_runtime import BINDINGS, OBSERVATION, SCOPE, STOP, profile


class CandidateFileAdmissionTests(unittest.TestCase):
    def _assert_rejected_replacement(self, *, symlink):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "actor"
            directory.mkdir()
            runtime = CandidateRuntime(profile(), SCOPE, BINDINGS)
            binding = runtime.record(
                directory, {"step": 0, "observation": OBSERVATION}, STOP
            )
            path = directory / binding["path"]
            original_bytes = path.read_bytes()
            replacement = root / "replacement.json"
            replacement.write_bytes(original_bytes)
            original_lstat = Path.lstat
            replaced = False

            def replace_after_observation(target, *args, **kwargs):
                nonlocal replaced
                observed = original_lstat(target, *args, **kwargs)
                if target == path and not replaced:
                    replaced = True
                    if symlink:
                        path.unlink()
                        path.symlink_to(replacement)
                    else:
                        os.replace(replacement, path)
                return observed

            with patch.object(Path, "lstat", new=replace_after_observation):
                with self.assertRaises(ValueError):
                    read_audit(directory, binding, {"step": 0})
            self.assertTrue(replaced)
            self.assertEqual(path.read_bytes(), original_bytes)
            if symlink:
                self.assertEqual(replacement.read_bytes(), original_bytes)

    def test_symlink_swap_after_file_observation_is_rejected(self):
        self._assert_rejected_replacement(symlink=True)

    def test_regular_inode_swap_with_identical_bytes_is_rejected(self):
        self._assert_rejected_replacement(symlink=False)


if __name__ == "__main__":
    unittest.main()
