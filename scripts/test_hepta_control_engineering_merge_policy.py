from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("hepta_control_engineering_merge_policy.py")


def load_module():
    spec = importlib.util.spec_from_file_location("hepta_ce_merge_policy", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControlEngineeringMergePolicyTests(unittest.TestCase):
    def test_review_must_be_non_author_approved_and_bound_to_current_head(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reviews.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": 1,
                            "state": "APPROVED",
                            "commit_id": "a" * 40,
                            "submitted_at": "2026-09-27T00:00:00Z",
                            "user": {"login": "reviewer"},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            value = module.verify_review(path, head="a" * 40, author="author")
            self.assertEqual(value["approvals"][0]["login"], "reviewer")
            with self.assertRaises(SystemExit):
                module.verify_review(path, head="b" * 40, author="author")
            with self.assertRaises(SystemExit):
                module.verify_review(path, head="a" * 40, author="reviewer")


if __name__ == "__main__":
    unittest.main()
