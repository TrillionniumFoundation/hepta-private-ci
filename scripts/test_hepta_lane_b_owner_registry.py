"""Canonical cross-lane owners come from the registry, never prose or lane labels."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "lane_b_owner_guard", Path(__file__).with_name("hepta-lane-b-path-guard.py")
)
assert SPEC and SPEC.loader
lane = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lane)


class CrossLaneOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("codex-rs/agent/src/lib.rs", "pub struct Agent;\n")
        self.write("codex-rs/ledger/src/lib.rs", "pub struct RunStart;\n")
        self.write("codex-rs/foreign/src/lib.rs", "pub struct RunStart;\n")
        self.registry = {
            "modules": [
                {"id": "runtime.agentd", "rootBindings": [{"path": "codex-rs/agent"}]},
                {
                    "id": "learning.ledger",
                    "rootBindings": [{"path": "codex-rs/ledger"}],
                },
            ]
        }
        self.map = {
            "module": "runtime.agentd",
            "resolvedRoots": ["codex-rs/agent"],
            "operations": [
                {
                    "ownerEntrypoint": {
                        "role": "owner_entrypoint",
                        "path": "codex-rs/agent/src/lib.rs",
                        "symbol": "pub struct Agent",
                        "buildTarget": "agent",
                    },
                    "delegatedCallees": [
                        {
                            "role": "delegated_callee",
                            "ownerModule": "learning.ledger",
                            "path": "codex-rs/ledger/src/lib.rs",
                            "symbol": "pub struct RunStart",
                            "buildTarget": "ledger",
                        }
                    ],
                    "tests": [
                        {
                            "path": "codex-rs/agent/src/lib.rs",
                            "command": "just test -p agent",
                        }
                    ],
                }
            ],
        }
        self.write(
            "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
            json.dumps(
                {
                    "modules": [
                        {"module": "runtime.agentd", "mapPath": "maps/agent.json"}
                    ]
                }
            ),
        )

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def verify(self):
        self.write("docs/modules/MODULES.json", json.dumps(self.registry))
        self.write("maps/agent.json", json.dumps(self.map))
        with contextlib.redirect_stdout(io.StringIO()):
            return lane.verify(self.root)

    def test_registered_owner_outside_lane_has_a_real_bounded_source(self):
        self.assertEqual(self.verify(), 0)
        self.map["operations"][0]["delegatedCallees"][0]["path"] = (
            "codex-rs/foreign/src/lib.rs"
        )
        with self.assertRaisesRegex(lane.Invalid, "delegate-root escape"):
            self.verify()

    def test_unknown_or_duplicate_owner_does_not_acquire_source_ownership(self):
        self.registry["modules"].pop()
        with self.assertRaisesRegex(lane.Invalid, "unregistered delegated owner"):
            self.verify()
        self.registry["modules"].append(self.registry["modules"][0])
        with self.assertRaisesRegex(lane.Invalid, "duplicate registered owner"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
