#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("hepta-implementation-maps.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("hepta_implementation_maps", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MAPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAPS)


class ImplementationHeadVerificationTests(unittest.TestCase):
    def test_declared_owner_root_drift_fails_closed(self):
        failures: list[str] = []
        row = {"implementationHead": {"commit": "source-head"}}

        def object_id(ref: str, path: str) -> str:
            self.assertEqual(path, "codex-rs/hepta-fleet")
            return "old-tree" if ref == "source-head" else "new-tree"

        with (
            mock.patch.object(MAPS, "git", return_value="commit-tree"),
            mock.patch.object(MAPS, "git_object_id", side_effect=object_id),
        ):
            MAPS.verify_implementation_head(
                "runtime.fleet", row, ["codex-rs/hepta-fleet"], failures
            )

        self.assertEqual(
            failures,
            [
                "runtime.fleet: source drift after implementation head: "
                "codex-rs/hepta-fleet"
            ],
        )

    def test_composed_consumer_or_lock_drift_fails_closed(self):
        failures: list[str] = []
        row = {
            "implementationHead": {"commit": "source-head", "tree": "commit-tree"},
            "sourceComposition": {
                "consumer": {"path": "codex-rs/hepta-supervisor/src/supervisor.rs"},
                "workspaceLock": {"path": "codex-rs/Cargo.lock"},
            },
        }

        def object_id(ref: str, path: str) -> str:
            if path == "codex-rs/hepta-fleet":
                return "fleet-tree"
            if path == "codex-rs/hepta-supervisor/src/supervisor.rs":
                return "consumer-old" if ref == "source-head" else "consumer-new"
            if path == "codex-rs/Cargo.lock":
                return "lock-old" if ref == "source-head" else "lock-new"
            raise AssertionError(path)

        with (
            mock.patch.object(MAPS, "git", return_value="commit-tree"),
            mock.patch.object(MAPS, "git_object_id", side_effect=object_id),
        ):
            MAPS.verify_implementation_head(
                "runtime.fleet", row, ["codex-rs/hepta-fleet"], failures
            )

        self.assertEqual(
            failures,
            [
                "runtime.fleet: composed source drift after implementation head: "
                "codex-rs/hepta-supervisor/src/supervisor.rs",
                "runtime.fleet: composed source drift after implementation head: "
                "codex-rs/Cargo.lock",
            ],
        )


if __name__ == "__main__":
    unittest.main()
