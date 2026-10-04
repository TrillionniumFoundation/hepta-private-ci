"""Run handoff workflow inputs and inventory commands against real Git history."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-deployment-handoff.yml"


class DeploymentHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-handoff-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.runner = Path(temporary.name) / "runner"
        self.root.mkdir()
        self.runner.mkdir()
        self.workflow = WORKFLOW.read_text()
        self.git("init", "-q")
        self.git("config", "user.name", "handoff-test")
        self.git("config", "user.email", "handoff-test@example.invalid")
        files = {
            "docs/modules/MODULES.json": {"modules": []},
            "docs/cns/CNS_ARCHITECTURE.json": {"organs": []},
            "docs/data/DATA_AUTHORITY.json": {"domains": []},
        }
        for path, value in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value))
        inventory = Path("tools/hepta-engineering-control/deployment_inventory.py")
        (self.root / inventory).parent.mkdir(parents=True)
        shutil.copyfile(ROOT / inventory, self.root / inventory)
        self.git("add", ".")
        self.git("commit", "-qm", "initial source")
        self.initial = self.git("rev-parse", "HEAD")
        (self.root / "source").write_text("source addition\n")
        self.git("add", "source")
        self.git("commit", "-qm", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.initial)
        (self.root / "target").write_text("target addition\n")
        self.git("add", "target")
        self.git("commit", "-qm", "target")
        self.target = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def script(self, name):
        block = self.workflow.split(f"      - name: {name}\n", 1)[1]
        block = block.split("\n      - ", 1)[0].split("        run: |\n", 1)[1]
        return "\n".join(line[10:] for line in block.splitlines())

    def resolve(self, expression, context):
        # Evaluate the workflow's simple Actions fallback expressions, so an
        # event-only binding cannot pass tests by receiving hand-written SHAs.
        for key in expression.split(" || "):
            value = context.get(key.strip(), "")
            if value:
                return value
        return ""

    def inputs(self, context):
        environment = {}
        for key in ("SOURCE_SHA", "BASE_SHA"):
            expression = re.search(
                rf"^      {key}: \$\{{\{{ (.+) \}}\}}$", self.workflow, re.M
            ).group(1)
            environment[key] = self.resolve(expression, context)
        matrix = re.search(
            r"lane: \$\{\{ fromJSON\(\((.*?)\) == \((.*?)\) && '(.*?)' \|\| '(.*?)'\) \}\}",
            self.workflow,
        )
        self.assertIsNotNone(matrix, "test must interpret the actual lane expression")
        left, right, same, different = matrix.groups()
        lanes = json.loads(
            same
            if self.resolve(left, context) == self.resolve(right, context)
            else different
        )
        return environment, lanes

    def run_lane(self, environment, lane):
        self.git("checkout", "--detach", environment["SOURCE_SHA"])
        env_file = self.runner / "env"
        env_file.write_text("")
        environment = {
            **os.environ,
            **environment,
            "HANDOFF_LANE": lane,
            "GITHUB_ENV": str(env_file),
            "RUNNER_TEMP": str(self.runner),
        }
        result = subprocess.run(
            [
                "bash",
                "-c",
                self.script("Bind exact source and actual-base synthetic merge"),
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        environment.update(
            line.split("=", 1) for line in env_file.read_text().splitlines()
        )
        result = subprocess.run(
            ["bash", "-c", self.script("Generate exact committed inventory")],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.runner / "deployment-inventory.json").read_text())

    def test_dispatch_defaults_to_current_commit_without_synthetic_merge(self):
        environment, lanes = self.inputs({"github.sha": self.target})
        self.assertEqual(lanes, ["source-head"])
        record = self.run_lane(environment, lanes[0])
        self.assertEqual(record["sourceCommit"], self.target)
        self.assertEqual(record["baseCommit"], self.target)

    def test_dispatch_and_reusable_explicit_inputs_override_event(self):
        for event in ("workflow_call", "workflow_dispatch"):
            with self.subTest(event=event):
                trigger = self.workflow.split(f"  {event}:\n", 1)[1]
                trigger = re.split(
                    r"^  [a-z_]+:|^[a-z]+:", trigger, maxsplit=1, flags=re.M
                )[0]
                self.assertIn("      source_sha:\n", trigger)
                self.assertIn("      base_sha:\n", trigger)
                environment, lanes = self.inputs(
                    {
                        "inputs.source_sha": self.source,
                        "inputs.base_sha": self.target,
                        "github.event.pull_request.head.sha": self.initial,
                        "github.event.pull_request.base.sha": self.initial,
                        "github.sha": self.initial,
                    }
                )
                self.assertEqual(
                    environment, {"SOURCE_SHA": self.source, "BASE_SHA": self.target}
                )
                self.assertEqual(lanes, ["source-head", "synthetic-merge"])
                for lane in lanes:
                    record = self.run_lane(environment, lane)
                    if lane == "source-head":
                        self.assertEqual(record["sourceCommit"], self.source)
                        self.assertEqual(record["baseCommit"], self.initial)
                    else:
                        self.assertEqual(record["baseCommit"], self.target)
                        self.assertEqual(
                            self.git("show", "-s", "--format=%P", "HEAD"),
                            f"{self.target} {self.source}",
                        )
                        self.assertTrue((self.root / "source").is_file())
                        self.assertTrue((self.root / "target").is_file())

    def test_reusable_pull_request_inherits_both_event_commits(self):
        environment, lanes = self.inputs(
            {
                "github.event.pull_request.head.sha": self.source,
                "github.event.pull_request.base.sha": self.target,
                "github.sha": self.initial,
            }
        )
        self.assertEqual(
            environment, {"SOURCE_SHA": self.source, "BASE_SHA": self.target}
        )
        self.assertEqual(lanes, ["source-head", "synthetic-merge"])
        for lane in lanes:
            record = self.run_lane(environment, lane)
            self.assertFalse(record["runtimeAuthority"])

    def test_invalid_or_missing_base_cannot_generate_an_inventory(self):
        self.git("checkout", "--detach", self.source)
        for base in ("", "main", "f" * 40):
            with self.subTest(base=base):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        self.script(
                            "Bind exact source and actual-base synthetic merge"
                        ),
                    ],
                    cwd=self.root,
                    env={
                        **os.environ,
                        "SOURCE_SHA": self.source,
                        "BASE_SHA": base,
                        "HANDOFF_LANE": "source-head",
                        "GITHUB_ENV": str(self.runner / "env"),
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.runner / "env").exists())


if __name__ == "__main__":
    unittest.main()
