"""Isolated Git/Python guard controls; no native Rust execution."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest

from b16_guard import SourceGuard, identity, record, validate_binding
from b16_oracles import ordered, qualify
from b16_runner import negative_with_finally

HERE = Path(__file__).resolve().parent


class GitGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-b16-runner-isolated-")
        self.root = Path(self.temp.name)
        self.repo, self.out = self.root / "repo", self.root / "evidence"
        self.repo.mkdir()
        self.out.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        self.git(["init", "-q"])
        for path, content in {"codex-rs/a.rs": "original\n", "codex-rs/Cargo.lock": "original lock\n", "MODULE.bazel.lock": "module lock\n"}.items():
            p = self.repo / path
            p.parent.mkdir(exist_ok=True)
            p.write_text(content)
        self.git(["add", "."])
        self.git(["-c", "user.name=Isolated guard fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "test fixture only"])
        self.head = self.git(["rev-parse", "HEAD"]).strip()
        self.tree = self.git(["rev-parse", "HEAD^{tree}"]).strip()
        self.binding = {"source_directory": str(self.repo), "initial_tree": self.tree,
                        "ordinary_head": self.head, "ordinary_index": record(self.repo / ".git/index"),
                        "locks": {p: record(self.repo / p) for p in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")}}
        self.sources, self.deltas = {}, {}
        for name, before, after in [("negative", "original\n", "counterfactual\n"),
                                    ("restore", "counterfactual\n", "repaired\n")]:
            a, b = identity(before.encode()), identity(after.encode())
            self.sources[b["blob"]] = {**b, "text": after}
            self.deltas[name] = {"label": name, "files": [{"path": "codex-rs/a.rs", "mode": "100644",
                                 "before_blob": a["blob"], "after_blob": b["blob"], "bytes": b["bytes"], "sha256": b["sha256"]}]}
        self.guard = SourceGuard(self.binding, {"deltas": self.deltas}, self.sources, self.out, self.env)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True).stdout

    def test_exact_delta_preserves_ordinary_head_index_and_locks(self):
        self.guard.apply("negative")
        self.guard.apply("restore")
        self.guard.guard("final-fixture")
        self.assertEqual((self.repo / "codex-rs/a.rs").read_text(), "repaired\n")
        self.assertEqual(record(self.repo / ".git/index"), self.binding["ordinary_index"])
        self.assertEqual(self.git(["rev-parse", "HEAD"]).strip(), self.head)

    def test_drift_rejected_before_overwriting(self):
        (self.repo / "codex-rs/a.rs").write_text("independent A change\n")
        with self.assertRaisesRegex(RuntimeError, "source drift"):
            self.guard.apply("negative")
        self.assertEqual((self.repo / "codex-rs/a.rs").read_text(), "independent A change\n")

    def test_invalid_negative_restores_exact_approved_source_but_raises(self):
        def invalid(_):
            raise RuntimeError("wrong physical endpoint")
        native = types.SimpleNamespace(g=self.guard, run_scope=invalid)
        operation = {"id": "fixture-negative", "before": ["negative"], "restore": "restore", "scopes": [{}]}
        with self.assertRaisesRegex(RuntimeError, "wrong physical endpoint"):
            negative_with_finally(native, operation)
        self.assertEqual((self.repo / "codex-rs/a.rs").read_text(), "repaired\n")
        receipt = json.loads((self.out / "fixture-negative-finally-receipt.json").read_text())
        self.assertFalse(receipt["causal_gate_passed"])
        self.assertFalse(receipt["next_phase_permitted"])
        self.assertIsNone(receipt["restore_error"])

    def test_finally_refuses_foreign_source_change(self):
        def dirty(_):
            (self.repo / "codex-rs/a.rs").write_text("external owner mutation\n")
            raise RuntimeError("test failed")
        native = types.SimpleNamespace(g=self.guard, run_scope=dirty)
        with self.assertRaisesRegex(RuntimeError, "restoration refused"):
            negative_with_finally(native, {"id": "dirty-negative", "before": ["negative"], "restore": "restore", "scopes": [{}]})
        self.assertEqual((self.repo / "codex-rs/a.rs").read_text(), "external owner mutation\n")

    def test_generator_only_accepts_declared_lock_paths(self):
        (self.repo / "codex-rs/Cargo.lock").write_text("real generated lock\n")
        self.guard.accept_generated_locks("fixture-lock", ("codex-rs/Cargo.lock",))
        self.guard.guard("fixture-lock-final")
        (self.repo / "codex-rs/a.rs").write_text("unexpected generator source\n")
        with self.assertRaisesRegex(RuntimeError, "non-permitted source"):
            self.guard.accept_generated_locks("bad-generator", ("codex-rs/Cargo.lock",))

    def test_new_path_symlink_escape_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.repo / "escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.guard.check_path("escape/owned.rs")
        self.assertEqual(list(outside.iterdir()), [])


class CausalParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hepta-b16-oracle-source-")
        cls.fixed = Path(cls.temp.name)
        manifest = json.loads((HERE / "payload-manifest.json").read_text())
        objects = {}
        for part in manifest["payloads"]:
            objects.update(json.loads((HERE / part["path"]).read_text()))
        for path, blob in manifest["final_partial_source_map"].items():
            p = cls.fixed / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(objects[blob]["text"].encode())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_unbound_template_cannot_validate(self):
        with self.assertRaisesRegex(RuntimeError, "explicit reviewed final_A_tree"):
            validate_binding({"final_A_tree": None}, "irrelevant")

    def test_worker_negative_needs_post_probe_blocked_gate_and_exact_panic(self):
        text = ("owned lifetime checkpoint=cancelled_inside_native_open\n"
                "physical custody expected=Held result=Ok(())\n"
                "owned lifetime checkpoint=gate_status=0\n"
                "thread 'x' (123) panicked at src/options/connection_lifetime_tests.rs:114:28:\n"
                "unexpected physical lock result: Ok(())\n")
        case = {"result": "FAIL", "name": "options::connection_lifetime::tests::cancellation_during_native_open_keeps_resource_custody", "captured": text}
        self.assertTrue(qualify("driver-worker", case, self.fixed)["qualified"])
        for bad in [text.replace("gate_status=0", "gate_status=2"), text.replace(":114:", ":83:"),
                    text.replace("result=Ok(())", "result=Err(WouldBlock)"),
                    text.replace("owned lifetime checkpoint=cancelled_inside_native_open\n", "")]:
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                qualify("driver-worker", {**case, "captured": bad}, self.fixed)

    def test_anchor_must_fail_second_probe_after_real_initial_contention(self):
        text = ("connection_custody: physical_connection_rows=1\n"
                "connection_custody: competing_exclusive_acquired=false\n"
                "connection_custody: commit_hook_removed=true native_close_started=false\n"
                "connection_custody: physical_connection_rows=1\n"
                "connection_custody: competing_exclusive_acquired=true\n"
                "thread 'x' (123) panicked at hepta-memory/src/objective_sender_connection_custody_tests.rs:20:5:\n")
        case = {"result": "FAIL", "name": "production_writer::objective_sender::connection_custody_tests::commit_hook_teardown_keeps_custody_until_native_connection_close", "captured": text}
        self.assertTrue(qualify("anchor", case, self.fixed)["qualified"])
        for bad in [text.replace("acquired=false", "acquired=true"), text.replace(":20:", ":92:"),
                    text.replace("connection_custody: commit_hook_removed=true native_close_started=false\n", "")]:
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                qualify("anchor", {**case, "captured": bad}, self.fixed)

    def test_markers_cannot_be_reordered_or_embedded_in_source_text(self):
        for text in ["second\nfirst\n", 'eprintln!("first");\nsecond\n', "first\nnot second\n"]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                ordered(text, ["first", "second"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
