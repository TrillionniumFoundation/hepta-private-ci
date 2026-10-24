import json
from pathlib import Path
import tempfile
import unittest

from operational_cohort_plan import canonical
from prospective_runtime_plan import build_plan, exact_pins, sha


class RuntimePlanTests(unittest.TestCase):
    def fixture(self, root, requirements):
        metadata = root / "upstream/projects/sanic/bugs/5/requirements.txt"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(requirements)
        source = root / "source-plan.json"
        source.write_bytes(canonical({"bugs": [{"project": "sanic", "bug_id": 5,
            "group_id": "bugsinpy/sanic/5", "metadata_files": {
                "requirements.txt": {"sha256": sha(metadata)}}}]}))
        interpreter = root / "python"
        interpreter.write_bytes(b"pinned interpreter fixture")
        return source, metadata, interpreter

    def test_metadata_wins_and_target_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, interpreter = self.fixture(root, "pytest==5.4.3\nsanic==0.7.0\nwebsockets==6.0\n")
            result = build_plan(source, root / "upstream", interpreter, root / "plan.json")
            profile = next(iter(result["profiles"].values()))
            self.assertIn("pytest==5.4.3", profile["requirements"])
            self.assertIn("websockets==6.0", profile["requirements"])
            self.assertFalse(any(x.startswith("sanic==") for x in profile["requirements"]))
            self.assertEqual(set(result["group_profiles"]), {"bugsinpy/sanic/5"})

    def test_changed_metadata_rejected_before_plan_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, metadata, interpreter = self.fixture(root, "pytest==5.4.3\n")
            metadata.write_text("pytest==5.2.1\n")
            with self.assertRaisesRegex(ValueError, "pin changed"):
                build_plan(source, root / "upstream", interpreter, root / "plan.json")
            self.assertFalse((root / "plan.json").exists())

    def test_requirement_injection_and_conflict_rejected(self):
        for text in ("pytest>=5", "pytest==5.4.3 --index-url https://example.invalid",
                     "pytest==5.4.3\nPyTest==5.2.1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                exact_pins(text)


if __name__ == "__main__":
    unittest.main()
