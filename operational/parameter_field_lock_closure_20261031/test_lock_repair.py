"""Small synthetic tests of scope, exact edge restoration, and failure propagation."""

import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import lock_repair as repair
import run_validation as validation


SOURCE = "registry+https://example.invalid/index"


def package(name, version, dependencies=()):
    text = (
        "[[package]]\nname = "
        + json.dumps(name)
        + "\nversion = "
        + json.dumps(version)
        + "\nsource = "
        + json.dumps(SOURCE)
        + '\nchecksum = "same"\n'
    )
    if dependencies:
        text += (
            "dependencies = [\n"
            + "".join(" " + json.dumps(d) + ",\n" for d in dependencies)
            + "]\n"
        )
    return (text + "\n").encode()


def fixture():
    tail = package("target", "1.0.0") + package("target", "2.0.0")
    original = b"version = 4\n\n" + package("parent", "1.0.0", ["target 1.0.0"]) + tail
    candidate = b"version = 4\n\n" + package("parent", "1.0.0", ["target 2.0.0"]) + tail
    candidate += package("unrelated", "1.0.0", ["target 2.0.0"])
    rule = {
        "parent": ["parent", "1.0.0", SOURCE],
        "old_edges": [["target", "1.0.0", SOURCE]],
        "candidate_edges": [["target", "2.0.0", SOURCE]],
    }
    return original, candidate, [rule]


class RestorationTests(unittest.TestCase):
    def test_restores_only_one_parent_and_preserves_all_other_bytes(self):
        original, candidate, rules = fixture()
        result = repair.reconcile(original, candidate, rules)
        self.assertEqual(
            result, original + package("unrelated", "1.0.0", ["target 2.0.0"])
        )
        self.assertEqual(
            len(repair.package_map(result)), len(repair.package_map(candidate))
        )

    def test_rejects_missing_old_target_identity(self):
        original, candidate, rules = fixture()
        candidate = candidate.replace(package("target", "1.0.0"), b"")
        with self.assertRaisesRegex(ValueError, "old dependency is absent"):
            repair.reconcile(original, candidate, rules)

    def test_rejects_duplicate_parent_rules(self):
        original, candidate, rules = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate restoration parent"):
            repair.reconcile(original, candidate, rules + rules)

    def test_rejects_nondependency_changes(self):
        original, candidate, rules = fixture()
        candidate = candidate.replace(b'checksum = "same"', b'checksum = "changed"', 1)
        with self.assertRaisesRegex(ValueError, "nondependency parent fields"):
            repair.reconcile(original, candidate, rules)

    def test_rejects_unexpected_candidate_edges(self):
        original, candidate, rules = fixture()
        rules[0]["candidate_edges"] = rules[0]["old_edges"]
        with self.assertRaisesRegex(ValueError, "restoration edge identity"):
            repair.reconcile(original, candidate, rules)

    def test_rejects_duplicate_package_identities_and_ambiguous_edges(self):
        original, candidate, _ = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate Cargo package"):
            repair.package_map(original + package("target", "1.0.0"))
        with self.assertRaisesRegex(ValueError, "ambiguous or absent"):
            repair.graph(candidate.replace(b'"target 2.0.0"', b'"target"', 1))

    def test_accounts_for_implicit_root_retargeting(self):
        parent = package("parent", "1.0.0", ["target"])
        delta = repair.graph_delta(
            parent + package("target", "1.0.0"), parent + package("target", "2.0.0")
        )
        self.assertEqual(len(delta["retained_parent_edge_changes"]), 1)
        self.assertIn(
            "target 1.0.0", delta["retained_parent_edge_changes"][0]["removed_edges"][0]
        )

    def test_tree_normalization_changes_only_lock_identity(self):
        old, new, other = "11" * 20, "22" * 20, "33" * 20
        tree = (
            b"100644 Cargo.lock\0"
            + bytes.fromhex(new)
            + b"100644 Cargo.toml\0"
            + bytes.fromhex(other)
        )
        expected = tree.replace(bytes.fromhex(new), bytes.fromhex(old), 1)
        expected = hashlib.sha1(
            b"tree " + str(len(expected)).encode() + b"\0" + expected
        ).hexdigest()
        self.assertEqual(validation.normalized_tree(tree, old, new), expected)
        changed = tree[:-20] + bytes.fromhex("44" * 20)
        self.assertNotEqual(validation.normalized_tree(changed, old, new), expected)
        with self.assertRaisesRegex(ValueError, "committed Cargo.lock"):
            validation.normalized_tree(tree, old, "ff" * 20)


class RunnerTests(unittest.TestCase):
    def execute(
        self,
        metadata_exit=0,
        metadata_timeout=False,
        integrity=None,
        final_timeout=False,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            output = Path(directory) / "evidence"
            calls = []

            def capture(command, cwd, target, label, **kwargs):
                calls.append(command)
                is_metadata = command[:2] == ["cargo", "metadata"]
                data = (
                    b"{}"
                    if is_metadata
                    else (command[0] + " 1.95.0 (fixture)\n").encode()
                )
                (target / (label + ".out")).write_bytes(data)
                (target / (label + ".tail")).write_bytes(b"")
                return {
                    "exit_code": metadata_exit if is_metadata else 0,
                    "timed_out": metadata_timeout if is_metadata else False,
                    "streams": {
                        "stdout": {
                            "complete": True,
                            "prefix": {"path": label + ".out"},
                            "tail": {"path": label + ".tail"},
                        }
                    },
                }

            context = (
                integrity
                if integrity is not None
                else [{"input": "same"}, {"input": "same"}]
            )
            clock, verification_calls = [0.0], [0]
            values = iter(context) if isinstance(context, list) else None

            def verify(_constraints):
                verification_calls[0] += 1
                if verification_calls[0] == 2 and final_timeout:
                    clock[0] = validation.BUDGETS["metadata"] + 1
                if values is None:
                    raise context
                return next(values)

            with (
                patch.object(validation, "ROOT", root),
                patch.object(validation, "git", return_value=b"a" * 40 + b"\n"),
                patch.object(validation, "verify_sources", side_effect=verify),
                patch.object(
                    validation.time, "monotonic", side_effect=lambda: clock[0]
                ),
                patch.object(validation.platform, "system", return_value="Linux"),
                patch.object(validation.platform, "machine", return_value="x86_64"),
                patch.object(
                    validation,
                    "load_dependency",
                    side_effect=[types.SimpleNamespace(capture=capture), object()],
                ) as loader,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = validation.run(
                    argparse.Namespace(
                        output_dir=output, phase="metadata", expected_machine="x86_64"
                    ),
                    {"source_base": "b" * 40},
                )
                loads = loader.call_count
            return code, json.loads((output / "receipt.json").read_text()), calls, loads

    def test_resolver_failure_cannot_pass(self):
        code, receipt, calls, _ = self.execute(metadata_exit=101)
        self.assertEqual(code, 1)
        self.assertFalse(receipt["validation_passed"])
        self.assertFalse(receipt["qualification"])
        self.assertEqual(
            calls[-1], ["cargo", "metadata", "--locked", "--format-version=1"]
        )
        self.assertTrue(receipt["source_and_locks_unchanged"])

    def test_success_is_engineering_only_and_timeout_is_failure(self):
        code, receipt, _, _ = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(receipt["validation_passed"])
        self.assertFalse(receipt["qualification"])
        self.assertFalse(receipt["dependency_graph_approved"])
        self.assertTrue(receipt["graph_review_required"])
        code, receipt, _, _ = self.execute(metadata_timeout=True)
        self.assertEqual(code, 1)
        self.assertFalse(receipt["validation_passed"])

    def test_final_source_change_overrides_successful_command(self):
        code, receipt, _, _ = self.execute(
            integrity=[{"input": "old"}, {"input": "changed"}]
        )
        self.assertEqual(code, 1)
        self.assertFalse(receipt["validation_passed"])
        self.assertTrue(receipt["phase_commands_passed"])

    def test_initial_integrity_failure_prevents_runtime_loading(self):
        code, receipt, calls, loads = self.execute(
            integrity=ValueError("frozen source mismatch")
        )
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertEqual(loads, 0)
        self.assertFalse(receipt["validation_passed"])

    def test_final_integrity_work_counts_toward_phase_deadline(self):
        code, receipt, _, _ = self.execute(final_timeout=True)
        self.assertEqual(code, 1)
        self.assertTrue(receipt["phase_commands_passed"])
        self.assertTrue(receipt["source_and_locks_unchanged"])
        self.assertFalse(receipt["validation_passed"])
        self.assertIn("aggregate phase deadline", receipt["errors"][-1])


if __name__ == "__main__":
    unittest.main()
