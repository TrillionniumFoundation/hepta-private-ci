"""Synthetic verifier fixtures, not execution of the artifact Rust runtime."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import hepta_artifact_convergence as c


def stream():
    text = "sample,phase,payload_bytes,microseconds\n"
    return (text + "".join(f"{n},{phase},7,{n + 1}\n" for n in range(4) for phase in c.PHASES)).encode()


class Measurements(unittest.TestCase):
    def test_valid_nearest_rank_fixture(self):
        value = c.measurements(stream())
        self.assertFalse(value["productionSloProved"])
        self.assertEqual(value["phases"]["publish"],
                         {"count": 4, "p50_us": 2, "p95_us": 4, "p99_us": 4, "max_us": 4})

    def test_missing_and_duplicate_cells_rejected(self):
        lines = stream().splitlines(keepends=True)
        for raw in (b"".join(lines[:-1]), stream() + lines[-1]):
            with self.assertRaises(ValueError):
                c.measurements(raw)

    def test_numbers_workload_and_encoding_rejected(self):
        for raw in (stream().replace(b",7,", b",8,", 1),
                    stream().replace(b",1\n", b",-1\n", 1),
                    stream().replace(b",1\n", b",01\n", 1),
                    stream().replace(b"\n", b"\r\n"), b"x" * 32769):
            with self.assertRaises(ValueError):
                c.measurements(raw)

    def test_unknown_shape_rejected(self):
        for raw in (stream().replace(b"publish", b"unknown"),
                    stream().replace(b"microseconds", b"milliseconds"),
                    stream().replace(b",7,1\n", b",7,1,extra\n", 1)):
            with self.assertRaises(ValueError):
                c.measurements(raw)


class Mapping(unittest.TestCase):
    def fixture(self):
        return {"module": "learning.artifacts", "sourceBase": {"commit": "old"},
                "claimBoundary": {"activation": False}, "repositoryControlledGaps": ["keep"],
                "operations": [{"operation": "publish", "nativeSymbol": "LearningArtifactOwnerService::publish",
                                "sourcePath": "old.rs", "tests": ["old_test"]}]}

    def test_preserves_provenance_claims_and_obligations(self):
        before = self.fixture()
        saved = copy.deepcopy(before)
        result = c.update_mapping(before)
        self.assertEqual(before, saved)
        for key in ("sourceBase", "claimBoundary", "repositoryControlledGaps"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(result["operations"][0]["tests"], ["old_test"])
        self.assertEqual(result["operations"][0]["sourcePath"], c.OBS)
        self.assertEqual(c.update_mapping(result), result)

    def test_duplicates_and_conflicting_symbols_rejected(self):
        before = self.fixture()
        before["operations"] *= 2
        with self.assertRaises(ValueError):
            c.update_mapping(before)
        before = c.update_mapping(self.fixture())
        before["operations"][-1]["nativeSymbol"] = "forged"
        with self.assertRaises(ValueError):
            c.update_mapping(before)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"activation":false,"activation":true}', object_pairs_hook=c.distinct_json)


class GitIndex(unittest.TestCase):
    def test_actual_git_identity_and_worktree_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            paths = {path for _, _, path, _ in c.OPERATIONS}
            paths.add(c.TEST)
            for path in paths:
                file = root / path
                file.parent.mkdir(parents=True, exist_ok=True)
                symbols = [symbol.rsplit("::", 1)[-1] for _, symbol, source_path, _ in c.OPERATIONS if source_path == path]
                file.write_text("// synthetic source\n" + "\n".join(f"fn {symbol}() {{}}" for symbol in symbols))
            (root / c.TEST).write_text("\n".join(f"fn {test}() {{}}" for _, _, _, tests in c.OPERATIONS for test in tests))
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "synthetic"], cwd=root, check=True)
            source = c.git(root, "rev-parse", "HEAD")
            result = c.delivery_index(root, source)
            self.assertEqual(result["sourceCommit"], source)
            self.assertFalse(result["nativeQualificationProvedByThisIndex"])
            self.assertFalse(result["productionActivation"])
            with self.assertRaises(ValueError):
                c.delivery_index(root, "0" * 40)
            (root / c.OBS).write_text("changed")
            with self.assertRaises(ValueError):
                c.delivery_index(root, source)


if __name__ == "__main__":
    unittest.main()
