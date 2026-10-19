from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-lane-b-path-guard.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_path_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class LaneBPathGuardTests(unittest.TestCase):
    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "repo"
        (root / "qualification/lane-b").mkdir(parents=True)
        (root / "docs/modules/lane.owner").mkdir(parents=True)
        (root / "docs/modules/external.owner").mkdir(parents=True)
        (root / "lane").mkdir()
        (root / "external").mkdir()
        (root / "tests").mkdir()
        (root / "lane/owner.py").write_text("def owner_entry():\n    pass\n", encoding="utf-8")
        (root / "external/callee.py").write_text(
            "def external_callee():\n    pass\n", encoding="utf-8"
        )
        (root / "tests/test_owner.py").write_text("def test_owner():\n    pass\n", encoding="utf-8")
        truth = {
            "modules": [
                {
                    "module": "lane.owner",
                    "mapPath": "docs/modules/lane.owner/IMPLEMENTATION_MAP.json",
                }
            ]
        }
        (root / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json").write_text(
            json.dumps(truth), encoding="utf-8"
        )
        owner_map = {
            "module": "lane.owner",
            "resolvedRoots": ["lane"],
            "operations": [
                {
                    "operationId": "operate",
                    "ownerEntrypoint": {
                        "role": "owner_entrypoint",
                        "path": "lane/owner.py",
                        "symbol": "owner_entry",
                        "buildTarget": "lane-owner",
                    },
                    "delegatedCallees": [
                        {
                            "role": "delegated_callee",
                            "ownerModule": "external.owner",
                            "path": "external/callee.py",
                            "symbol": "external_callee",
                            "buildTarget": "external-owner",
                        }
                    ],
                    "tests": [
                        {
                            "path": "tests/test_owner.py",
                            "command": "python3 tests/test_owner.py",
                        }
                    ],
                }
            ],
        }
        (root / "docs/modules/lane.owner/IMPLEMENTATION_MAP.json").write_text(
            json.dumps(owner_map), encoding="utf-8"
        )
        external_map = {
            "module": "external.owner",
            "resolvedRoots": ["external"],
        }
        (root / "docs/modules/external.owner/IMPLEMENTATION_MAP.json").write_text(
            json.dumps(external_map), encoding="utf-8"
        )
        return temporary, root

    def test_cross_lane_owner_is_resolved_without_lane_membership_expansion(self) -> None:
        temporary, root = self.fixture()
        with temporary:
            self.assertEqual(GUARD.verify(root), 0)

    def test_unknown_cross_lane_owner_fails_closed(self) -> None:
        temporary, root = self.fixture()
        with temporary:
            owner_path = root / "docs/modules/lane.owner/IMPLEMENTATION_MAP.json"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["operations"][0]["delegatedCallees"][0]["ownerModule"] = "missing.owner"
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            with self.assertRaisesRegex(GUARD.Invalid, "missing path"):
                GUARD.verify(root)

    def test_cross_lane_map_identity_mismatch_fails_closed(self) -> None:
        temporary, root = self.fixture()
        with temporary:
            path = root / "docs/modules/external.owner/IMPLEMENTATION_MAP.json"
            path.write_text(
                json.dumps({"module": "other.owner", "resolvedRoots": ["external"]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GUARD.Invalid, "map identity"):
                GUARD.verify(root)

    def test_cross_lane_owner_root_escape_fails_closed(self) -> None:
        temporary, root = self.fixture()
        with temporary:
            path = root / "docs/modules/external.owner/IMPLEMENTATION_MAP.json"
            path.write_text(
                json.dumps({"module": "external.owner", "resolvedRoots": ["../external"]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GUARD.Invalid, "invalid repository-relative path"):
                GUARD.verify(root)

    def test_unsafe_owner_module_identity_fails_closed(self) -> None:
        temporary, root = self.fixture()
        with temporary:
            owner_path = root / "docs/modules/lane.owner/IMPLEMENTATION_MAP.json"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["operations"][0]["delegatedCallees"][0]["ownerModule"] = "../external.owner"
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            with self.assertRaisesRegex(GUARD.Invalid, "invalid module identity"):
                GUARD.verify(root)


if __name__ == "__main__":
    unittest.main()
