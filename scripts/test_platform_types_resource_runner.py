"""Real runner/gate and real Git; only native measurement is a synthetic fixture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_platform_types_resource_gate import fixture

ROOT = Path(__file__).resolve().parents[1]


class ResourceRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.root = self.work / "source"
        scripts = self.root / "scripts"
        scripts.mkdir(parents=True)
        for name in ("run_platform_types_resource_qualification.sh",
                     "platform_types_resource_gate.py", "test_platform_types_resource_gate.py"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
        for path in ("codex-rs/hepta-types/src/bin/platform-types-semantic-bench.rs",
                     "codex-rs/hepta-types/src/bin/semantic_bench_support/allocator.rs",
                     "codex-rs/Cargo.toml", "subject.txt"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("synthetic runner fixture; never compiled\n")
        (self.root / ".gitignore").write_text("__pycache__/\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Runner regression fixture")
        self.git("config", "user.email", "runner@example.invalid")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.out = self.work / "evidence"
        self.out.mkdir()
        self.raw = self.work / "synthetic-raw.json"
        self.raw.write_text(json.dumps(fixture()))
        tools = self.work / "bin"
        tools.mkdir()
        cargo = tools / "cargo"
        cargo.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, subprocess, sys\n"
            "print('SYNTHETIC measurement fixture, not native execution', flush=True)\n"
            "failure = os.environ.get('TEST_RESOURCE_FAILURE', '')\n"
            "if failure == 'benchmark': sys.exit(17)\n"
            "value = json.loads(pathlib.Path(os.environ['TEST_RESOURCE_RAW']).read_text())\n"
            "if failure == 'invalid': value['rows'][0]['elapsedNs'] = 0\n"
            "pathlib.Path(sys.argv[-1]).write_text(json.dumps(value))\n"
            "root = pathlib.Path(os.environ['TEST_RESOURCE_ROOT'])\n"
            "if failure == 'dirty': (root / 'subject.txt').write_text('changed')\n"
            "if failure == 'head': subprocess.run(['git', '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-qm', 'drift'], cwd=root, check=True)\n"
        )
        cargo.chmod(0o755)
        rustc = tools / "rustc"
        rustc.write_text("#!/bin/sh\nprintf '%s\\n' 'synthetic rustc identity; not a compiler'\n")
        rustc.chmod(0o755)
        python = tools / "python3"
        python.write_text(
            "#!/bin/sh\n"
            f"{shlex.quote(sys.executable)} \"$@\"\n"
            "rc=$?\n"
            'if [ "$1" = scripts/platform_types_resource_gate.py ] && '
            '[ "$TEST_RESOURCE_FAILURE" = after-gate ] && [ "$rc" = 0 ]; then\n'
            '  printf changed >> "$TEST_RESOURCE_ROOT/subject.txt"\n'
            "fi\nexit \"$rc\"\n"
        )
        python.chmod(0o755)
        self.env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                        TEST_RESOURCE_ROOT=str(self.root), TEST_RESOURCE_RAW=str(self.raw),
                        TEST_RESOURCE_FAILURE="", PYTHONDONTWRITEBYTECODE="1")
        for name in ("PLATFORM_TYPES_RESOURCE_BASELINE", "PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO"):
            self.env.pop(name, None)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def execute(self, failure=""):
        env = dict(self.env, TEST_RESOURCE_FAILURE=failure)
        return subprocess.run(["bash", str(self.root / "scripts/run_platform_types_resource_qualification.sh"), str(self.out)],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=90)

    def test_success_is_exact_and_explicitly_not_host_acceptance(self):
        process = self.execute()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads((self.out / "report.json").read_text())
        self.assertEqual(report["sourceHead"], self.head)
        self.assertEqual(report["raw"], fixture())
        self.assertFalse(report["targetHostQualified"])
        self.assertFalse(report["independentAcceptance"])
        self.assertEqual(json.loads((self.out / "status.json").read_text())["status"], "passed")
        self.assertFalse((self.out / ".resource-qualification-lock").exists())

    def test_failed_benchmark_invalidates_previous_success(self):
        self.assertEqual(self.execute().returncode, 0)
        process = self.execute("benchmark")
        self.assertEqual(process.returncode, 17, process.stdout + process.stderr)
        self.assertFalse((self.out / "report.json").exists())
        self.assertFalse((self.out / "raw.json").exists())
        status = json.loads((self.out / "status.json").read_text())
        self.assertEqual((status["status"], status["stage"]), ("failed", "benchmark"))
        self.assertIn("SYNTHETIC", (self.out / "benchmark.log").read_text())

    def test_invalid_measurement_never_publishes_pass(self):
        (self.out / "report.json").write_text("old success")
        process = self.execute("invalid")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse((self.out / "report.json").exists())
        self.assertTrue((self.out / "raw.json").is_file())
        self.assertEqual(json.loads((self.out / "status.json").read_text())["stage"], "gate")

    def test_source_changes_at_measurement_and_final_fence_reject(self):
        for failure in ("dirty", "head", "after-gate"):
            with self.subTest(failure=failure):
                self.git("reset", "--hard", self.head)
                process = self.execute(failure)
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertFalse((self.out / "report.json").exists())
                self.assertFalse(list(self.out.glob(".resource-report-*.json")))
                self.assertEqual(json.loads((self.out / "status.json").read_text())["status"], "failed")

    def test_baseline_cannot_alias_an_output(self):
        baseline = self.work / "baseline.json"
        baseline.write_text("retained baseline")
        os.link(baseline, self.out / "report.json")
        self.env["PLATFORM_TYPES_RESOURCE_BASELINE"] = str(baseline)
        self.assertNotEqual(self.execute().returncode, 0)
        self.assertEqual(baseline.read_text(), "retained baseline")
        self.assertFalse((self.out / "benchmark.log").exists())

    def test_baseline_inside_output_is_not_deleted(self):
        baseline = self.out / "report.json"
        baseline.write_text("retained baseline")
        self.env["PLATFORM_TYPES_RESOURCE_BASELINE"] = str(baseline)
        self.assertNotEqual(self.execute().returncode, 0)
        self.assertEqual(baseline.read_text(), "retained baseline")

    def test_busy_directory_is_not_mutated(self):
        (self.out / ".resource-qualification-lock").mkdir()
        (self.out / "report.json").write_text("other attempt")
        self.assertNotEqual(self.execute().returncode, 0)
        self.assertEqual((self.out / "report.json").read_text(), "other attempt")
        self.assertTrue((self.out / ".resource-qualification-lock").exists())

    def test_threshold_without_baseline_rejects_before_benchmark(self):
        (self.out / "report.json").write_text("old success")
        self.env["PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO"] = "1.15"
        self.assertNotEqual(self.execute().returncode, 0)
        self.assertFalse((self.out / "report.json").exists())
        self.assertFalse((self.out / "benchmark.log").exists())


if __name__ == "__main__":
    unittest.main()
