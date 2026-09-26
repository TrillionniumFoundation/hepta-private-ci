"""Exercise the declared commands with stub binaries, not Rust qualification.

The real execution recorder, Git identities, shell pipelines and output paths
are used. This proves that a lint failure is retained without hiding the tests
and that the evidence files do not dirty either candidate checkout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from hepta_workflow_commands import workflow_commands

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-intuition-qualification.yml"


def lanes() -> dict[str, str]:
    text = WORKFLOW.read_text()
    source, merge = text.split("\n  merge-candidate:", 1)
    return {"source-head": source.split("\n  source-head:", 1)[1], "base-merge": merge}


class IntuitionWorkflowEvidenceTests(unittest.TestCase):
    def test_commands_remain_independent_and_exact_in_both_lanes(self):
        for lane, text in lanes().items():
            with self.subTest(lane=lane):
                commands = [
                    c
                    for c in workflow_commands(text)
                    if "../scripts/hepta_ci_exec.py" in c
                ]
                self.assertEqual(len(commands), 9)
                outputs = [c[c.index("--output") + 1] for c in commands]
                self.assertEqual(len(outputs), len(set(outputs)))
                self.assertTrue(
                    all(p.startswith("$HEPTA_INTUITION_EVIDENCE/") for p in outputs)
                )
                tests = [c for c in commands if "just" in c]
                self.assertEqual(len(tests), 2)
                self.assertEqual(tests[0][tests[0].index("--minimum-tests") + 1], "1")
                self.assertIn("--retries", tests[0])
                product = next(c for c in tests if "codex-hepta-agentd" in c)
                self.assertIn("--retries", product)
                self.assertIn("--lib", product)
                self.assertIn("test(intelligence_product)", " ".join(product))
                self.assertNotIn("continue-on-error", text)
                for step in text.split("      - name:")[1:]:
                    if "../scripts/hepta_ci_exec.py" in step:
                        self.assertIn(
                            "if: ${{ !cancelled() && steps.identity.outcome == 'success' }}",
                            step,
                        )
                self.assertIn("if: ${{ always() }}", text)
                self.assertIn(
                    "path: ${{ runner.temp }}/intuition-${{ env.HEPTA_CI_LANE }}/", text
                )
                self.assertNotIn("runner.temp", text.split("    steps:", 1)[0])
                self.assertIn(
                    'echo "HEPTA_INTUITION_EVIDENCE=$RUNNER_TEMP/intuition-$HEPTA_CI_LANE" >> "$GITHUB_ENV"',
                    text,
                )
                if lane == "base-merge":
                    self.assertIn(
                        'echo "TESTED_SHA=$EXPECTED_SHA" >> "$GITHUB_ENV"', text
                    )
                    self.assertIn("${{ steps.synthetic.outputs.sha }}", text)
                else:
                    self.assertIn(
                        "TESTED_SHA: ${{ github.event.pull_request.head.sha || github.sha }}",
                        text,
                    )

    def test_lint_failure_keeps_real_receipts_and_later_measurements_on_both_identities(
        self,
    ):
        for lane, text in lanes().items():
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                (repo / "scripts").mkdir()
                (repo / "codex-rs").mkdir()
                shutil.copyfile(
                    ROOT / "scripts/hepta_ci_exec.py", repo / "scripts/hepta_ci_exec.py"
                )
                env = dict(os.environ)
                for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
                    env.pop(key, None)
                env.update(
                    GIT_AUTHOR_NAME="Workflow Test",
                    GIT_COMMITTER_NAME="Workflow Test",
                    GIT_AUTHOR_EMAIL="test@example.invalid",
                    GIT_COMMITTER_EMAIL="test@example.invalid",
                )

                def git(*args):
                    return subprocess.check_output(
                        ["git", *args], cwd=repo, env=env, text=True
                    ).strip()

                git("init", "-q")
                git("add", ".")
                git("commit", "-qm", "base")
                base = git("rev-parse", "HEAD")
                (repo / "candidate").write_text("source candidate\n")
                git("add", ".")
                git("commit", "-qm", "source")
                source = git("rev-parse", "HEAD")
                tested = source
                if lane == "base-merge":
                    tree = git("merge-tree", "--write-tree", base, source)
                    tested = git(
                        "commit-tree", tree, "-p", base, "-p", source, "-m", "synthetic"
                    )
                    git("checkout", "--detach", tested)
                binaries = root / "bin"
                binaries.mkdir()
                # The stubs simulate exit/output behavior, not successful Rust work.
                stubs = {
                    "cargo": '#!/bin/sh\nif [ "$1" = clippy ]; then echo "fixture lint failure"; exit 17; fi\nprintf "metric,value\\nfixture,1\\n"\n',
                    "just": '#!/bin/sh\nprintf "Summary [0.01s] 1 test run: 1 passed, 0 skipped\\n"\n',
                    "rustc": '#!/bin/sh\necho "fixture rustc"\n',
                    "lscpu": '#!/bin/sh\necho "fixture cpu"\n',
                    "uname": '#!/bin/sh\necho "fixture host"\n',
                }
                for name, content in stubs.items():
                    path = binaries / name
                    path.write_text(content)
                    path.chmod(0o755)
                evidence = root / "evidence"
                env.update(
                    SOURCE_SHA=source,
                    TESTED_SHA=tested,
                    BASE_SHA=base,
                    HEPTA_CI_LANE=lane,
                    HEPTA_INTUITION_EVIDENCE=str(evidence),
                    PATH=str(binaries) + os.pathsep + env["PATH"],
                )
                commands = [
                    c
                    for c in workflow_commands(text)
                    if "../scripts/hepta_ci_exec.py" in c
                ]
                for command in commands:
                    # Shell expands the output argument; the inner bash expands its
                    # own variables in the same way as the declared folded scalar.
                    command = [
                        value.replace("$HEPTA_INTUITION_EVIDENCE", str(evidence))
                        for value in command
                    ]
                    result = subprocess.run(
                        command,
                        cwd=repo / "codex-rs",
                        env=env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    expected = 17 if "clippy" in command else 0
                    self.assertEqual(result.returncode, expected, result.stdout)
                receipts = {
                    p.stem: json.loads(p.read_text()) for p in evidence.glob("*.json")
                }
                self.assertEqual(len(receipts), 9)
                self.assertEqual(receipts["clippy"]["status"], "failed")
                self.assertEqual(receipts["tests"]["observed_passed_tests"], 1)
                self.assertEqual(receipts["product-tests"]["observed_passed_tests"], 1)
                for name, record in receipts.items():
                    self.assertEqual(
                        record["status"], "failed" if name == "clippy" else "passed"
                    )
                    self.assertEqual(record["before"]["commit"], tested)
                    self.assertEqual(record["before"], record["after"])
                    self.assertFalse(record["before"]["dirty"])
                    self.assertTrue((evidence / record["log_file"]).is_file())
                self.assertTrue((evidence / "kernel-fast-gate.csv").is_file())
                self.assertTrue((evidence / "authenticated-fast-gate.csv").is_file())
                self.assertEqual(git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
