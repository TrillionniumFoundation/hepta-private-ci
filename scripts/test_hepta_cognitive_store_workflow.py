"""Execute the actual workflow binding shell, then the existing command recorder."""

import os
from pathlib import Path
import re
import subprocess
import unittest

import test_hepta_ci_exec as fixtures

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/hepta-cognitive-store-qualification.yml"


def binding_steps():
    text = WORKFLOW.read_text()
    jobs = re.split(r"(?m)^  (native|performance):\n", text)[1:]
    steps = {}
    for job, body in zip(jobs[::2], jobs[1::2]):
        match = re.search(
            r"      - name: Bind exact tested source\n.*?        run: \|\n((?:          [^\n]*\n)+)",
            body,
            re.DOTALL,
        )
        if match is None:
            raise AssertionError(f"{job} lacks a real source binding step")
        steps[job] = "".join(line[10:] for line in match[1].splitlines(keepends=True))
    if set(steps) != {"native", "performance"}:
        raise AssertionError("both jobs must bind their executable candidate")
    return steps


class WorkflowIdentityTests(fixtures.GitExecutionFixture):
    def bind(self, job, tested, lane):
        env_file = self.root / f"{job}-{lane}.env"
        shell = binding_steps()[job].replace("${{ matrix.lane }}", lane)
        result = subprocess.run(
            ["bash", "-c", shell],
            cwd=self.repo,
            env={**os.environ, "TESTED_SHA": tested, "RUNNER_TEMP": str(self.root), "GITHUB_ENV": str(env_file)},
            capture_output=True, text=True, timeout=10,
        )
        exported = dict(line.split("=", 1) for line in env_file.read_text().splitlines()) if env_file.exists() else {}
        return result, exported

    def test_both_source_jobs_export_identity_to_a_fresh_command_step(self):
        for job in binding_steps():
            with self.subTest(job=job):
                self.result.unlink(missing_ok=True)
                result, exported = self.bind(job, self.source, "source-head")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(exported, {"TESTED_SHA": self.source, "HEPTA_CI_LANE": "source-head"})
                command = self.execute(**exported)
                self.assertEqual(command.returncode, 0, command.stdout + command.stderr)
                self.assertEqual(self.receipt()["status"], "passed")

    def test_both_merge_jobs_export_the_merge_not_the_source_identity(self):
        base = self.source
        (self.repo / "input").write_text("successor\n")
        self.git("commit", "-qam", "source")
        self.source = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        merged = self.git("commit-tree", tree, "-p", base, "-p", self.source, "-m", "synthetic")
        self.git("checkout", "--detach", merged)
        for job in binding_steps():
            with self.subTest(job=job):
                self.result.unlink(missing_ok=True)
                result, exported = self.bind(job, merged, "base-merge")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(exported["TESTED_SHA"], merged)
                command = self.execute(BASE_SHA=base, **exported)
                self.assertEqual(command.returncode, 0, command.stdout + command.stderr)
                self.assertEqual(self.receipt()["lane"], "base-merge")

    def test_wrong_checkout_never_exports_a_test_identity(self):
        for job in binding_steps():
            with self.subTest(job=job):
                result, exported = self.bind(job, "f" * 40, "source-head")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(exported, {})


if __name__ == "__main__":
    unittest.main()
