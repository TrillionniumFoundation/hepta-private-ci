"""Replay the actual CI recorder with old/new workflow identity environments.

Disposable Git checkouts and event contexts are synthetic. This verifies command
dispatch and provenance rejection locally, not a hosted Actions or native pass.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
runner = root / "scripts/hepta_ci_exec.py"
old = yaml.safe_load((output / "shared-framework-before.yml").read_text())
new = yaml.safe_load((root / ".github/workflows/hepta-shared-framework.yml").read_text())
keys = ("SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE", "BASE_SHA")
results = []
with tempfile.TemporaryDirectory(prefix="cell-source-binding-") as directory:
    repo = Path(directory) / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE).decode().strip()

    git("init", "-q")
    git("config", "user.name", "source-binding-fixture")
    git("config", "user.email", "source-binding-fixture@example.invalid")
    git("config", "commit.gpgsign", "false")
    (repo / "test_probe.py").write_text(
        "import os, unittest\nfrom pathlib import Path\n"
        "class DispatchProbe(unittest.TestCase):\n"
        "    def test_original_command_executes(self):\n"
        "        path = Path(os.environ['BOUND_PROBE_MARKER'])\n"
        "        path.write_text('executed')\n"
        "        self.assertEqual(path.read_text(), 'executed')\n"
    )
    git("add", ".")
    git("commit", "-qm", "bound probe")
    head = git("rev-parse", "HEAD")
    for name, workflow, event_sha, pr_head, dirty, passes in (
        ("original-missing-bindings", old, head, None, False, False),
        ("push", new, head, None, False, True),
        ("manual", new, head, None, False, True),
        ("pull-request-head", new, "a" * 40, head, False, True),
        ("wrong-event-source", new, "a" * 40, None, False, False),
        ("dirty-source", new, head, None, True, False),
    ):
        env = {key: value for key, value in os.environ.items() if key not in keys}
        for key, value in workflow["env"].items():
            if value == "${{ github.event.pull_request.head.sha || github.sha }}":
                value = pr_head or event_sha
            elif value == "${{ github.sha }}":
                value = event_sha
            elif "${{" in value:
                raise ValueError("unsupported event expression in fixture")
            env[key] = value
        marker = output / (name + ".marker")
        env["BOUND_PROBE_MARKER"] = str(marker)
        untracked = repo / "untracked"
        if dirty:
            untracked.write_text("different source")
        result = output / (name + ".json")
        command = [sys.executable, str(runner), "--minimum-tests", "1", "--output", str(result),
                   "--", sys.executable, "-B", "-m", "unittest", "discover", "-v"]
        run = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
        (output / (name + ".stdout.log")).write_text(run.stdout)
        (output / (name + ".stderr.log")).write_text(run.stderr)
        record = json.loads(result.read_text())
        assert (run.returncode == 0) == passes, record
        assert marker.exists() == passes, record
        if passes:
            assert record["source_sha"] == record["tested_sha"] == head, record
            assert record["before"] == record["after"], record
            assert record["observed_passed_tests"] == 1, record
        else:
            assert record["status"] == "rejected" and record["command_exit_code"] is None, record
        results.append({"case": name, "exit_code": run.returncode, "status": record["status"],
                        "command_dispatched": marker.exists(), "error": record.get("error")})
        untracked.unlink(missing_ok=True)
report = {"kind": "synthetic-event-real-recorder", "results": results,
          "runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
          "workflow_sha256": hashlib.sha256((root / ".github/workflows/hepta-shared-framework.yml").read_bytes()).hexdigest(),
          "hosted_run_verified": False, "native_execution_verified": False}
(output / "BINDING_REPLAY.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
