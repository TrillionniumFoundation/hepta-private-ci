from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-objective-spec-consistency.py")
SPEC = importlib.util.spec_from_file_location("objective_spec_consistency", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ObjectiveSpecConsistencyTests(unittest.TestCase):
    def test_repository_contract_is_consistent(self) -> None:
        result = MODULE.verify()
        self.assertEqual(result["status"], "PASS_OBJECTIVE_NORMATIVE_CONSISTENCY")
        self.assertFalse(result["productionImplementationProved"])
        self.assertFalse(result["releaseIssued"])

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema": 1, "schema": 2}', encoding="utf-8")
            with self.assertRaises(MODULE.ConsistencyError):
                MODULE.load_json(path)

    def test_manifest_rejects_release_truth(self) -> None:
        manifest = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["staticTruth"]["released"] = True
        with self.assertRaises(MODULE.ConsistencyError):
            MODULE.validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
