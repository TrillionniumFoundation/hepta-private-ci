#!/usr/bin/env python3
"""Real Git regressions for Lane D scope without weakening owner contracts."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-lane-d-semantic-conformance.py")
SPEC = importlib.util.spec_from_file_location("lane_d_scope", SCRIPT)
assert SPEC and SPEC.loader
LANE_D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LANE_D)


class LaneDChangeScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        self.root.mkdir()
        self.event_path = Path(directory.name) / "event.json"
        self.git("init", "-q")
        self.git("config", "user.name", "Lane D regression")
        self.git("config", "user.email", "lane-d-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        for module, crate in zip(
            LANE_D.MODULES, ("hepta-objective", "hepta-ndu", "hepta-control-plane")
        ):
            root = f"codex-rs/{crate}"
            self.write(f"{root}/src/component.rs", "pub fn run() {}\n")
            self.write(f"{root}/src/component_tests.rs", "fn run_regression() {}\n")
            self.write(
                LANE_D.MAPS[module],
                json.dumps(
                    {
                        "module": module,
                        "authorityDelta": "none",
                        "sourceRoot": root,
                        "operations": [
                            {
                                "sourcePath": f"{root}/src/component.rs",
                                "nativeSymbol": "crate::run",
                                "tests": [
                                    {
                                        "path": f"{root}/src/component_tests.rs",
                                        "symbol": "run_regression",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            )
        initial = self.commit("owner contracts")
        self.git("switch", "-q", "-c", "old-side")
        self.write("other-lane/old.txt", "historical")
        self.commit("old unrelated lane")
        self.git("switch", "-q", "-c", "target", initial)
        self.write("target.txt", "target")
        self.commit("old target change")
        self.git("merge", "--no-ff", "--no-edit", "old-side")
        self.base = self.git("rev-parse", "HEAD")
        self.git("switch", "-q", "-c", "candidate")
        self.write("codex-rs/hepta-ndu/src/new_policy.rs", "pub fn new_policy() {}")
        self.write("other-lane/current.txt", "parallel lane")
        self.head = self.commit("current multi-lane source")
        self.event = {
            "pull_request": {"base": {"sha": self.base}, "head": {"sha": self.head}}
        }

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=True
        ).stdout.strip()

    def write(self, path: str, contents: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def check(self, base: str | None = None) -> dict:
        self.event_path.write_text(json.dumps(self.event), encoding="utf-8")
        stdout = io.StringIO()
        with (
            mock.patch.object(LANE_D, "ROOT", self.root),
            mock.patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_PATH": str(self.event_path),
                    "GITHUB_EVENT_NAME": "pull_request",
                },
                clear=True,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(
                LANE_D.verify_changes(self.base if base is None else base), 0
            )
        return json.loads(stdout.getvalue())

    def test_current_multi_lane_delta_keeps_owner_scope_and_exact_identity(
        self,
    ) -> None:
        result = self.check()
        self.assertEqual(
            result["laneDChangedPaths"], ["codex-rs/hepta-ndu/src/new_policy.rs"]
        )
        self.assertEqual(result["otherLaneChangedPaths"], 1)
        self.assertEqual(result["sourceHead"], self.head)
        self.assertEqual(result["baseHead"], self.base)
        self.assertEqual(result["ownerMapsVerified"], list(LANE_D.MODULES))
        self.assertFalse(result["authorityGranted"])

    def test_target_only_updates_after_divergence_do_not_enter_source_delta(
        self,
    ) -> None:
        self.git("switch", "-q", "target")
        self.write("codex-rs/hepta-objective/src/target_only.rs", "target-only")
        advanced = self.commit("target advances independently")
        self.git("switch", "-q", "candidate")
        self.event["pull_request"]["base"]["sha"] = advanced
        self.assertEqual(
            self.check(advanced)["laneDChangedPaths"],
            ["codex-rs/hepta-ndu/src/new_policy.rs"],
        )

    def test_other_lane_only_pr_still_checks_all_d_owner_maps(self) -> None:
        self.git("checkout", "--detach", self.base)
        self.write("other-lane/only.txt", "foreign change")
        self.event["pull_request"]["head"]["sha"] = self.commit("other lane only")
        self.assertEqual(self.check()["changedPaths"], 0)
        source = self.root / "codex-rs/hepta-objective/src/component.rs"
        source.unlink()
        self.event["pull_request"]["head"]["sha"] = self.commit(
            "registered owner removed"
        )
        with self.assertRaisesRegex(SystemExit, "missing source"):
            self.check()

    def test_stale_base_or_head_and_dirty_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "base differs"):
            self.check(self.head)
        self.event["pull_request"]["head"]["sha"] = self.base
        with self.assertRaisesRegex(SystemExit, "checkout is not"):
            self.check()
        self.event["pull_request"]["head"]["sha"] = self.head
        self.write("codex-rs/hepta-objective/src/component.rs", "uncommitted")
        with self.assertRaises(subprocess.CalledProcessError):
            self.check()

    def test_d_native_symbol_failure_is_not_hidden_by_scope_filter(self) -> None:
        self.write("codex-rs/hepta-ndu/src/component.rs", "pub fn renamed() {}")
        self.event["pull_request"]["head"]["sha"] = self.commit("break owner contract")
        with self.assertRaisesRegex(SystemExit, "missing native symbol"):
            self.check()

    def test_map_cannot_reassign_source_outside_declared_owner(self) -> None:
        path = LANE_D.MAPS["objective.compiler"]
        mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
        self.write("other-lane/impostor.rs", "pub fn run() {}")
        mapping["operations"][0]["sourcePath"] = "other-lane/impostor.rs"
        self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("escape owner")
        with self.assertRaisesRegex(SystemExit, "source escapes owner root"):
            self.check()
        mapping["sourceRoot"] = "../outside"
        self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("escape root")
        with self.assertRaisesRegex(SystemExit, "invalid owner root"):
            self.check()

    def test_cli_retains_real_self_test_entrypoint(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "self-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout)["status"], "PASS_HEPTA_LANE_D_SELF_TEST"
        )


if __name__ == "__main__":
    unittest.main()
