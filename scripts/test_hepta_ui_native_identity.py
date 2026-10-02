"""Execute the actual qualification identity step against isolated Git history."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_hepta_ui_native_workflow import bash_executable
from test_hepta_ui_native_workflow import shell_step


class QualificationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native identity ")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / "repo"
        self.root.mkdir()
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "source.rs").write_text("baseline\n", encoding="utf-8")
        self.base = self.commit("baseline")
        self.base_ref = "work/native-qualification-fixture"
        (self.root / "source.rs").write_text("implementation\n", encoding="utf-8")
        checker = self.root / "scripts/check_hepta_ui_native_convergence.py"
        checker.parent.mkdir()
        # This fixture isolates event/Git binding; source-contract validation is
        # covered separately by the real convergence checker regression suite.
        checker.write_text(
            "import sys\nfrom pathlib import Path\n"
            "Path(sys.argv[2]).write_text('fixture source check\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.implementation = self.commit("implementation")
        self.write_json(
            "apps/hepta-native/CANDIDATE.json",
            {"implementationSourceSha": self.implementation},
        )
        self.write_json(
            "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
            {"orderedParents": {"base": self.base}},
        )
        self.candidate = self.commit("qualification metadata")

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, encoding="utf-8"
        ).strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def event(self):
        return {
            "pull_request": {
                "head": {"sha": self.candidate},
                "base": {"ref": self.base_ref, "sha": self.base},
            }
        }

    def bind(self, event=None, event_name="pull_request", candidate=None):
        event_path = self.directory / "event.json"
        event_path.write_text(
            json.dumps(self.event() if event is None else event), encoding="utf-8"
        )
        return subprocess.run(
            [
                bash_executable(),
                "-c",
                shell_step(
                    "Bind exact head, fixed ordered-parent merge and implementation"
                ),
            ],
            cwd=self.root,
            env={
                **os.environ,
                "BASE_SHA": self.base,
                "BASE_REF": self.base_ref,
                "GITHUB_EVENT_NAME": event_name,
                "GITHUB_EVENT_PATH": event_path.as_posix(),
                "GITHUB_SHA": candidate or self.candidate,
                "GITHUB_OUTPUT": (self.directory / "output").as_posix(),
                "RUNNER_TEMP": self.directory.as_posix(),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_exact_event_records_one_parent_candidate_and_implementation(self):
        result = self.bind()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.directory / "output").read_text().splitlines(),
            [
                f"candidate={self.candidate}",
                f"base={self.base}",
                f"implementation={self.implementation}",
            ],
        )
        self.assertEqual(self.git("rev-parse", "HEAD"), self.candidate)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertTrue((self.directory / "ui-native-source-evidence.json").is_file())

    def test_changed_event_base_sha_fails_before_any_output(self):
        event = self.event()
        event["pull_request"]["base"]["sha"] = self.implementation
        result = self.bind(event)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base SHA differs", result.stderr)
        self.assertFalse((self.directory / "output").exists())

    def test_wrong_event_base_ref_cannot_use_the_same_sha(self):
        event = self.event()
        event["pull_request"]["base"]["ref"] = "main"
        result = self.bind(event)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base ref differs", result.stderr)

    def test_missing_event_base_cannot_fall_back_to_workflow_sha(self):
        event = self.event()
        del event["pull_request"]["base"]
        result = self.bind(event)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base ref differs", result.stderr)

    def test_missing_pull_request_identity_cannot_fall_back(self):
        result = self.bind({})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a pull-request identity", result.stderr)

    def test_symbolic_head_ref_is_not_an_immutable_candidate(self):
        event = self.event()
        event["pull_request"]["head"]["sha"] = "HEAD"
        result = self.bind(event)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate is not an immutable commit SHA", result.stderr)

    def test_manifest_cannot_substitute_another_parent(self):
        self.write_json(
            "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
            {"orderedParents": {"base": self.implementation}},
        )
        self.candidate = self.commit("foreign manifest base")
        result = self.bind()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest base differs", result.stderr)
        self.assertFalse((self.directory / "output").exists())

    def test_unrelated_implementation_commit_is_rejected(self):
        unrelated = self.git(
            "commit-tree", self.git("rev-parse", "HEAD^{tree}"), "-m", "unrelated"
        )
        self.write_json(
            "apps/hepta-native/CANDIDATE.json", {"implementationSourceSha": unrelated}
        )
        self.candidate = self.commit("unrelated source anchor")
        result = self.bind()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "output").exists())

    def test_parallel_implementation_cannot_qualify_candidate(self):
        parallel = self.git(
            "commit-tree",
            self.git("rev-parse", "HEAD^{tree}"),
            "-p",
            self.candidate,
            "-m",
            "parallel implementation",
        )
        self.write_json(
            "apps/hepta-native/CANDIDATE.json", {"implementationSourceSha": parallel}
        )
        self.candidate = self.commit("parallel source anchor")
        result = self.bind()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "output").exists())

    def test_dispatch_uses_exact_selected_sha_and_pinned_manifest(self):
        result = self.bind({}, event_name="workflow_dispatch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            f"candidate={self.candidate}", (self.directory / "output").read_text()
        )

    def test_unsupported_event_does_not_borrow_a_candidate(self):
        result = self.bind(event_name="push")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("event is not pull_request or workflow_dispatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
