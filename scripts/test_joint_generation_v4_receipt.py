"""Local receipt binding checks; no model-quality or trusted-builder claims."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.joint_generation_v4_receipt import (
    InvocationCost,
    SOURCE_PATHS,
    artifact_binding,
    build_attestation,
    source_binding,
)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "--quiet")
        for name in SOURCE_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture source " + name + "\n")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Receipt Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        )
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            check=True,
            text=True,
        ).stdout

    def test_expected_commit_requires_actual_clean_dependency_bytes(self):
        original = source_binding(self.root, self.commit)
        dependency = (
            "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"
        )
        self.git("update-index", "--skip-worktree", dependency)
        (self.root / dependency).write_text("different actual core bytes\n")
        changed = source_binding(self.root)
        self.assertEqual(changed["required_source_changes"], [dependency])
        self.assertNotEqual(
            changed["source_inventory_sha256"], original["source_inventory_sha256"]
        )
        with self.assertRaises(ValueError):
            source_binding(self.root, self.commit)
        with self.assertRaises(ValueError):
            source_binding(self.root, "0" * 40)

    def test_missing_native_source_is_not_an_implicit_empty_binding(self):
        native = (
            self.root / "codex-rs/hepta-infer-worker-host/src/joint_generation/state.rs"
        )
        native.unlink()
        with self.assertRaises(FileNotFoundError):
            source_binding(self.root)

    def test_head_movement_cannot_mix_commit_tree_and_dependency_inventory(self):
        first_tree = self.git("rev-parse", self.commit + "^{tree}").strip()
        dependency = self.root / SOURCE_PATHS[0]
        dependency.write_text("second committed source\n")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Receipt Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "second",
        )
        second = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "--quiet", "--detach", self.commit)
        real_run = subprocess.run

        def move_after_resolving_head(command, **kwargs):
            result = real_run(command, **kwargs)
            if command[-2:] == ["rev-parse", "HEAD"]:
                real_run(
                    [
                        "git",
                        "-C",
                        str(self.root),
                        "checkout",
                        "--quiet",
                        "--detach",
                        second,
                    ],
                    check=True,
                )
            return result

        with patch(
            "scripts.joint_generation_v4_receipt.subprocess.run",
            side_effect=move_after_resolving_head,
        ):
            observed = source_binding(self.root)
        self.assertEqual(
            (observed["commit"], observed["tree"]), (self.commit, first_tree)
        )
        self.assertFalse(observed["required_sources_match_commit"])
        self.assertEqual(observed["required_source_changes"], [SOURCE_PATHS[0]])

    def test_build_statement_is_bound_but_never_promoted_to_build_proof(self):
        source = source_binding(self.root, self.commit)
        binary = self.root / "native-fixture"
        binary.write_bytes(b"fixture bytes, not an executable")
        executable = artifact_binding(binary)
        statement = {
            "schema": "hepta.joint-v4.local-build-attestation.v1",
            "source_commit": source["commit"],
            "source_tree": source["tree"],
            "source_inventory_sha256": source["source_inventory_sha256"],
            "binary_sha256": executable["sha256"],
            "command": ["fixture-compiler", "fixture-source"],
            "compiler_version": "fixture-only",
            "exit_code": 0,
        }
        path = self.root / "build.json"
        path.write_text(json.dumps(statement))
        bound = build_attestation(path, source, executable)
        self.assertEqual(bound["status"], "matching_local_attestation")
        self.assertFalse(bound["source_build_proven"])
        binary.write_bytes(b"different fixture bytes")
        with self.assertRaises(ValueError):
            build_attestation(path, source, artifact_binding(binary))

    def test_enclosing_cost_counts_reaped_child_cpu_without_phase_sums(self):
        meter = InvocationCost()
        subprocess.run(
            [sys.executable, "-c", "sum(x*x for x in range(100000))"], check=True
        )
        result = meter.finish()
        self.assertGreater(result["wall_seconds"], 0)
        self.assertGreater(result["cpu_reaped_children_seconds"], 0)
        self.assertAlmostEqual(
            result["cpu_self_and_reaped_children_seconds"],
            result["cpu_self_seconds"] + result["cpu_reaped_children_seconds"],
        )
        self.assertFalse(result["nested_phase_clocks_summed"])
        self.assertIsNone(result["energy_joules"])
        self.assertIsNone(result["provider_charges"])

    def test_attestation_digest_and_statement_use_one_read(self):
        source = source_binding(self.root, self.commit)
        binary = self.root / "binary-fixture"
        binary.write_bytes(b"fixture")
        executable = artifact_binding(binary)
        statement = {
            "schema": "hepta.joint-v4.local-build-attestation.v1",
            "source_commit": source["commit"],
            "source_tree": source["tree"],
            "source_inventory_sha256": source["source_inventory_sha256"],
            "binary_sha256": executable["sha256"],
            "exit_code": 0,
            "command": ["fixture-compiler"],
            "compiler_version": "fixture-only",
        }
        path = self.root / "build.json"
        raw = json.dumps(statement).encode()
        path.write_bytes(raw)
        reads, original_read = [], Path.read_bytes

        def read_once(candidate):
            if candidate == path:
                reads.append(candidate)
                return raw if len(reads) == 1 else b"{}"
            return original_read(candidate)

        with patch.object(Path, "read_bytes", read_once):
            result = build_attestation(path, source, executable)
        self.assertEqual(len(reads), 1)
        self.assertEqual(result["statement"], statement)
        self.assertEqual(result["artifact"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_diagnostic_failed_original_is_preserved_on_retry(self):
        from scripts import joint_generation_v4_diagnostic as diagnostic

        binary = self.root / "binary-fixture"
        binary.write_bytes(b"fixture")
        output = self.root / "first-attempt"
        source = {"commit": self.commit, "required_sources_match_commit": True}

        def fail_after_partial_output(directory, _binary, _report):
            (directory / "partial.bin").write_bytes(b"original failed attempt")
            raise RuntimeError("intentional diagnostic fixture failure")

        with (
            patch.object(diagnostic, "source_binding", return_value=source),
            patch.object(
                diagnostic, "_execute", side_effect=fail_after_partial_output
            ) as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                diagnostic.run(output, binary, expected_source_commit=self.commit)
            before = (output / "diagnostic.json").read_bytes()
            self.assertEqual(json.loads(before)["status"], "failed")
            self.assertGreater(json.loads(before)["invocation_cost"]["wall_seconds"], 0)
            with self.assertRaises(FileExistsError):
                diagnostic.run(output, binary, expected_source_commit=self.commit)
            self.assertEqual(execute.call_count, 1)
        self.assertEqual((output / "diagnostic.json").read_bytes(), before)
        self.assertEqual(
            (output / "partial.bin").read_bytes(), b"original failed attempt"
        )

    def test_expected_commit_gate_and_interrupt_are_recorded_before_propagation(self):
        from scripts import joint_generation_v4_diagnostic as diagnostic

        binary = self.root / "binary-fixture"
        binary.write_bytes(b"fixture")
        source = {"commit": self.commit, "required_sources_match_commit": True}
        output = self.root / "mismatch"
        with (
            patch.object(diagnostic, "source_binding", return_value=source),
            patch.object(diagnostic, "_execute") as execute,
        ):
            with self.assertRaisesRegex(ValueError, "Expected source commit"):
                diagnostic.run(output, binary, expected_source_commit="0" * 40)
            execute.assert_not_called()
        self.assertEqual(
            json.loads((output / "diagnostic.json").read_bytes())["status"], "failed"
        )
        output = self.root / "interrupt"
        with (
            patch.object(diagnostic, "source_binding", return_value=source),
            patch.object(
                diagnostic,
                "_execute",
                side_effect=KeyboardInterrupt("fixture interrupt"),
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                diagnostic.run(output, binary, expected_source_commit=self.commit)
        result = json.loads((output / "diagnostic.json").read_bytes())
        self.assertEqual(result["status"], "interrupted")
        self.assertIn("KeyboardInterrupt", result["failure"])
        self.assertFalse(result["invocation_cost"]["complete_cost_claimed"])

    def test_failed_native_call_keeps_original_request_and_observed_streams(self):
        from scripts import joint_generation_v4_diagnostic as diagnostic
        from scripts.joint_generation_v4_io import DeliveryObservation

        binary = self.root / "binary-fixture"
        binary.write_bytes(b"fixture")
        output = self.root / "native-attempt"
        output.mkdir()
        owner = DeliveryObservation(1, 0, 10000, 10000, b"\x01" * 32)
        completed = subprocess.CompletedProcess(
            [str(binary)], 2, b"partial response", b"fixture failure"
        )
        with (
            patch.object(diagnostic, "public_packet", return_value=b"public-fixture"),
            patch.object(diagnostic.subprocess, "run", return_value=completed),
        ):
            with self.assertRaisesRegex(AssertionError, "fixture failure"):
                diagnostic.native_episode(
                    None, {}, owner, b"weights-fixture", binary, output
                )
        receipt = json.loads((output / "native-call-0000.json").read_bytes())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["returncode"], 2)
        self.assertTrue(receipt["streams_observed"])
        for key, expected in (
            ("stdout", b"partial response"),
            ("stderr", b"fixture failure"),
        ):
            self.assertEqual(Path(receipt[key]["path"]).read_bytes(), expected)
            self.assertFalse(receipt[key]["truncated"])
        self.assertTrue(
            Path(receipt["request"]["path"]).read_bytes().startswith(b"HJREQV02")
        )


if __name__ == "__main__":
    unittest.main()
