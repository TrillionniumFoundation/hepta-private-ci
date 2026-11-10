"""Exercise exact-source/current-base binding without contacting GitHub."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
MARKER = "      - name: Freeze current PR base against exact source\n"
BASE_REF = "codex/cell127-cost-magnitude-guard-20261110-run5"
SOURCE = "c" * 40
EVENT_BASE = "a" * 40
CURRENT_BASE = "b" * 40


def command():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.index(MARKER) < workflow.index(
        "      - name: Fetch exact qualification history\n"
    )
    assert "base-sha: ${{ steps.current_pr_base.outputs.sha || env.BASE_SHA }}" in workflow
    block = workflow.split(MARKER, 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


class CurrentPRBaseSnapshotTests(unittest.TestCase):
    def execute(self, *, source=SOURCE, base_ref=BASE_REF, base=CURRENT_BASE, status=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / "gh"
            gh.write_text(
                "#!/bin/sh\n"
                'test "$1" = api || exit 91\n'
                'test "$2" = repos/example/repo/pulls/5836 || exit 92\n'
                'test "$GH_STATUS" = 0 || exit "$GH_STATUS"\n'
                'cat "$PR_PAYLOAD"\n',
                encoding="utf-8",
            )
            gh.chmod(0o700)
            payload = root / "pr.json"
            payload.write_text(
                json.dumps(
                    {"head": {"sha": source}, "base": {"sha": base, "ref": base_ref}}
                ),
                encoding="utf-8",
            )
            env_path = root / "github-env"
            output_path = root / "github-output"
            env = {
                **os.environ,
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "PR_PAYLOAD": str(payload),
                "GH_STATUS": str(status),
                "RUNNER_TEMP": str(root),
                "REPO": "example/repo",
                "PR_NUMBER": "5836",
                "BASE_REF": BASE_REF,
                "SOURCE_SHA": SOURCE,
                "BASE_SHA": EVENT_BASE,
                "GITHUB_ENV": str(env_path),
                "GITHUB_OUTPUT": str(output_path),
            }
            result = subprocess.run(
                ["bash", "-c", command()],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            record = root / "hepta-command-records/pr-base-snapshot/binding.json"
            return (
                result,
                env_path.read_text() if env_path.exists() else None,
                output_path.read_text() if output_path.exists() else None,
                json.loads(record.read_text()) if record.exists() else None,
            )

    def test_stale_event_base_refreshes_only_for_the_same_source_and_base_ref(self):
        result, env, output, record = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env, f"BASE_SHA={CURRENT_BASE}\n")
        self.assertEqual(output, f"sha={CURRENT_BASE}\n")
        self.assertEqual(record["event_base"], EVENT_BASE)
        self.assertEqual(record["current_base"], CURRENT_BASE)
        self.assertFalse(record["event_base_is_current"])

    def test_changed_head_must_fail_without_exporting_new_identity(self):
        result, env, output, record = self.execute(source="d" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(env)
        self.assertIsNone(output)
        self.assertIsNone(record)

    def test_changed_base_branch_must_fail(self):
        result, env, output, _ = self.execute(base_ref="unknown/branch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(env)
        self.assertIsNone(output)

    def test_non_sha_base_and_api_failure_must_fail(self):
        for params in ({"base": "not-a-sha"}, {"status": 9}):
            with self.subTest(params=params):
                result, env, output, _ = self.execute(**params)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(env)
                self.assertIsNone(output)


if __name__ == "__main__":
    unittest.main()
