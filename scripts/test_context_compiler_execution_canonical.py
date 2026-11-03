"""Real-Git stage boundaries with a fake native executor, not Rust qualification."""

import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import context_compiler_candidate as candidate
import context_compiler_canonical as canonical


HARNESS_BYTES = (Path(__file__).resolve().parents[1] / canonical.HARNESS).read_bytes()


def fixture_results():
    fixtures = []
    for name in (
        "unsorted-v1",
        "exact-predecessor-successor",
        "effect-capability-idempotency",
    ):
        digest = "a" * 64
        receipt = {
            "circuit_digest": digest,
            "taskflow_definition_digest": digest,
            "authority_granted": False,
        }
        fixtures.append(
            {
                "name": name,
                "circuit_digest": digest,
                "taskflow_definition_digest": digest,
                "candidate_json_bytes": list(
                    json.dumps({"circuit_digest": digest}).encode()
                ),
                "compilation_receipt_json_bytes": list(json.dumps(receipt).encode()),
            }
        )
    return json.dumps(
        {"schema": "hepta.neural-circuit-canonical-fixtures.v1", "fixtures": fixtures}
    ).encode()


class CanonicalStageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root = self.workspace / "candidate"
        self.root.mkdir()
        self.output = self.workspace / "evidence"
        self.production = Path("codex-rs/hepta-automation/src/production.rs")
        (self.root / self.production).parent.mkdir(parents=True)
        (self.root / canonical.HARNESS).parent.mkdir(parents=True)
        (self.root / canonical.HARNESS).parent.joinpath("existing.rs").write_text(
            "old test\n"
        )
        (self.root / self.production).write_text("old production\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.baseline = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        (self.root / self.production).write_text("new production\n")
        (self.root / canonical.HARNESS).write_bytes(HARNESS_BYTES)
        self.git("add", ".")
        self.git("commit", "-qm", "candidate")
        self.head = self.git("rev-parse", "HEAD")
        self.stage_roots = []
        for name, value in (
            ("BASELINE_COMMIT", self.baseline),
            ("BASELINE_TREE", self.tree),
        ):
            patcher = patch.object(canonical, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, *args):
        return candidate.git(self.root, *args)

    def fake_native(self, root, stage, target):
        self.stage_roots.append(root)
        expected = (
            "old production\n" if stage.name == "baseline" else "new production\n"
        )
        self.assertEqual((root / self.production).read_text(), expected)
        if stage.name == "baseline":
            self.assertNotEqual(root, self.root)
            self.assertTrue((root / ".git").is_dir())
            self.assertEqual(
                (root / canonical.HARNESS).read_bytes(),
                canonical.baseline_harness(HARNESS_BYTES),
            )
        else:
            self.assertEqual((root / canonical.HARNESS).read_bytes(), HARNESS_BYTES)
        (stage / "results.json").write_bytes(fixture_results())
        return ["fake-native-executor-for-python-regression-only"]

    def qualify(self, stage, executor=None):
        with patch.object(
            canonical, "run_native", side_effect=executor or self.fake_native
        ):
            canonical.qualify(self.root, self.output, stage)

    def test_native_stages_bind_old_production_and_preserve_primary_git(self):
        refs = self.git("show-ref")
        self.qualify("baseline")
        self.assertFalse(self.stage_roots[0].exists())
        self.qualify("candidate")
        self.assertEqual(self.git("show-ref"), refs)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        candidate.clean(self.root)
        for stage in ("baseline", "candidate"):
            path = self.output / "canonical-compatibility" / stage
            evidence = json.loads((path / "evidence.json").read_text())
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(
                (path / "candidate-source-before.json").read_bytes(),
                (path / "candidate-source-after.json").read_bytes(),
            )
        self.assertTrue(evidence["byteForByteMatch"])

    def test_harness_only_changes_marked_adapter_and_new_import(self):
        old = canonical.baseline_harness(HARNESS_BYTES)
        self.assertEqual(canonical.sha256(old), canonical.BASELINE_HARNESS_SHA256)
        for source in (HARNESS_BYTES, old):
            prefix, body = source.decode().split(canonical.BEGIN)
            _, suffix = body.split(canonical.END)
            normalized = prefix.replace(canonical.IMPORT, "") + suffix
            if source == HARNESS_BYTES:
                expected = normalized
            else:
                self.assertEqual(normalized, expected)
        with self.assertRaisesRegex(ValueError, "pin mismatch"):
            canonical.baseline_harness(HARNESS_BYTES + b"// unexpected change\n")

    def test_missing_baseline_never_executes_candidate(self):
        with (
            patch.object(canonical, "run_native") as native,
            self.assertRaises(FileNotFoundError),
        ):
            canonical.qualify(self.root, self.output, "candidate")
        native.assert_not_called()

    def test_missing_or_inconsistent_baseline_identity_fails_before_native(self):
        for field, value in (
            ("BASELINE_COMMIT", "0" * 40),
            ("BASELINE_TREE", "0" * 40),
        ):
            with (
                patch.object(canonical, field, value),
                patch.object(canonical, "run_native") as native,
            ):
                with self.assertRaises(ValueError):
                    canonical.qualify(self.root, self.output, "baseline")
                native.assert_not_called()

    def test_candidate_harness_must_be_committed(self):
        self.git("rm", "--cached", canonical.HARNESS.as_posix())
        with self.assertRaises(ValueError):
            self.qualify("baseline")

    def test_failed_baseline_cannot_be_reused(self):
        def fail(root, stage, target):
            raise ValueError("simulated native failure")

        with self.assertRaises(ValueError):
            self.qualify("baseline", fail)
        with self.assertRaisesRegex(ValueError, "baseline execution missing"):
            self.qualify("candidate")

    def test_production_mutation_is_retained_as_failed_evidence(self):
        def mutate(root, stage, target):
            self.fake_native(root, stage, target)
            (root / self.production).write_text("changed production\n")

        with self.assertRaisesRegex(ValueError, "baseline production"):
            self.qualify("baseline", mutate)
        path = self.output / "canonical-compatibility/baseline"
        self.assertEqual(
            json.loads((path / "evidence.json").read_text())["status"], "failed"
        )
        self.assertNotEqual(
            (path / "baseline-production-before.json").read_bytes(),
            (path / "baseline-production-after.json").read_bytes(),
        )
        candidate.clean(self.root)

    def test_changed_candidate_identity_rejects_previous_baseline(self):
        self.qualify("baseline")
        (self.root / self.production).write_text("another candidate\n")
        self.git("add", ".")
        self.git("commit", "-qm", "another candidate")
        with self.assertRaisesRegex(ValueError, "baseline evidence identity"):
            self.qualify("candidate")

    def test_byte_difference_fails_even_when_json_is_equivalent(self):
        self.qualify("baseline")

        def different(root, stage, target):
            self.fake_native(root, stage, target)
            with (stage / "results.json").open("ab") as stream:
                stream.write(b"\n")

        with self.assertRaisesRegex(ValueError, "byte-for-byte"):
            self.qualify("candidate", different)

    def test_native_command_requires_exactly_one_real_summary_and_named_pass(self):
        stage = self.workspace / "native"
        stage.mkdir()
        valid = f"PASS [0.01s] codex-hepta-automation::neural_circuit_canonical {canonical.NATIVE_TEST}\nSummary [0.01s] 1 test run: 1 passed\n".encode()
        for output, succeeds in (
            (valid, True),
            (valid + valid, False),
            (b"Summary [0.01s] 1 test run: 1 passed\n", False),
            (valid.replace(b"1 test run: 1 passed", b"2 tests run: 2 passed"), False),
        ):
            process = Mock(stdout=io.BytesIO(output))
            process.wait.return_value = 0
            with (
                patch.object(
                    canonical.subprocess, "Popen", return_value=process
                ) as launch,
                patch.object(canonical.sys, "stdout", Mock(buffer=io.BytesIO())),
            ):
                if succeeds:
                    canonical.run_native(self.root, stage, self.workspace / "target")
                else:
                    with self.assertRaises(ValueError):
                        canonical.run_native(
                            self.root, stage, self.workspace / "target"
                        )
                self.assertEqual(
                    launch.call_args.args[0][:7],
                    [
                        "just",
                        "test",
                        "--locked",
                        "-p",
                        "codex-hepta-automation",
                        "--test",
                        "neural_circuit_canonical",
                    ],
                )
                self.assertIs(launch.call_args.kwargs["start_new_session"], False)

    def test_interruption_retains_initial_failed_evidence_and_partial_log(self):
        def interrupted(root, stage, target):
            self.assertEqual(
                json.loads((stage / "evidence.json").read_text())["status"], "failed"
            )
            (stage / "native.log").write_text("partial native progress\n")
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.qualify("baseline", interrupted)
        stage = self.output / "canonical-compatibility/baseline"
        self.assertEqual(
            json.loads((stage / "evidence.json").read_text())["status"], "failed"
        )
        self.assertEqual(
            (stage / "native.log").read_text(), "partial native progress\n"
        )

    @unittest.skipUnless(
        sys.platform.startswith("linux"), "Linux workflow process group"
    )
    def test_outer_termination_reaches_native_and_grandchild_without_passed_evidence(
        self,
    ):
        stage = self.output / "canonical-compatibility/baseline"
        native = self.workspace / "fake_native.py"
        grandchild = """
import os, signal, sys
from pathlib import Path
stage = Path(sys.argv[1])
def terminated(signum, frame):
    (stage / "grandchild-terminated").write_text(str(signum))
    raise SystemExit(128 + signum)
signal.signal(signal.SIGTERM, terminated)
(stage / "grandchild-ready").write_text(str(os.getpgrp()))
signal.pause()
"""
        native.write_text(
            "import json, os, signal, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "stage = Path(os.environ['HEPTA_CANONICAL_FIXTURE_OUTPUT']).parent\n"
            "def terminated(signum, frame):\n"
            "    (stage / 'native-terminated').write_text(str(signum))\n"
            "    raise SystemExit(128 + signum)\n"
            "signal.signal(signal.SIGTERM, terminated)\n"
            f"child = subprocess.Popen([sys.executable, '-c', {grandchild!r}, str(stage)])\n"
            "deadline = time.monotonic() + 5\n"
            "while not (stage / 'grandchild-ready').exists():\n"
            "    if time.monotonic() > deadline: raise RuntimeError('child not ready')\n"
            "    time.sleep(0.01)\n"
            "(stage / 'ready.json').write_text(json.dumps({"
            "'nativeGroup': os.getpgrp(), 'childGroup': os.getpgid(child.pid)}))\n"
            "print('partial-native-progress\\n' + 'x' * 131072, flush=True)\n"
            "signal.pause()\n"
        )
        outer = (
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(Path(canonical.__file__).parent)!r})\n"
            "import context_compiler_canonical as c\n"
            f"c.BASELINE_COMMIT = {self.baseline!r}\n"
            f"c.BASELINE_TREE = {self.tree!r}\n"
            f"c.NATIVE_ARGV = [sys.executable, {str(native)!r}]\n"
            f"c.qualify(Path({str(self.root)!r}), Path({str(self.output)!r}), 'baseline')\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", outer],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        groups = {process.pid}
        try:
            deadline = time.monotonic() + 10
            while (
                not (stage / "ready.json").exists()
                or not (stage / "native.log").exists()
                or (stage / "native.log").stat().st_size == 0
            ):
                if process.poll() is not None or time.monotonic() > deadline:
                    self.fail("native process group did not become ready")
                time.sleep(0.01)
            observed = json.loads((stage / "ready.json").read_text())
            groups.update(observed.values())
            self.assertEqual(
                observed, {"nativeGroup": process.pid, "childGroup": process.pid}
            )
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            deadline = time.monotonic() + 5
            while not all(
                (stage / name).exists()
                for name in ("native-terminated", "grandchild-terminated")
            ):
                if time.monotonic() > deadline:
                    self.fail("termination did not reach both descendants")
                time.sleep(0.01)
            self.assertEqual(
                json.loads((stage / "evidence.json").read_text())["status"], "failed"
            )
            self.assertIn(
                b"partial-native-progress", (stage / "native.log").read_bytes()
            )
            self.assertFalse((stage / "results.json").exists())
        finally:
            # These groups belong only to the test-owned session above.
            for group in groups:
                if group == os.getpgrp():
                    continue
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
