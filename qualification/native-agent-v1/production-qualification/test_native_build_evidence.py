"""Dependency/source provenance gates, without running Rust or a provider."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from native_build_evidence import (POLICY_VERSION, PROJECTION_VERSION, metadata_contract,
    object_digest, patch_configuration, source_snapshot)


class BuildEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.owner = self.root / "owner"
        self.runtime = self.root / "runtime"
        for directory in (self.owner, self.runtime):
            directory.mkdir()
            subprocess.run(["git", "init", "-q", str(directory)], check=True)
            (directory / "README").write_text("controlled provenance test repository\n")
            subprocess.run(["git", "-C", str(directory), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(directory), "-c", "user.name=Fixture", "-c",
                "user.email=fixture@example.invalid", "commit", "-qm", "controlled baseline"], check=True)
        self.revision = subprocess.check_output(["git", "-C", str(self.runtime), "rev-parse", "HEAD"], text=True).strip()
        native = self.owner / "codex-rs/hepta-native-agent"
        (native / "src").mkdir(parents=True)
        (native / "Cargo.toml").write_text('[package]\nname="codex-hepta-native-agent"\nversion="0.1.0"\n')
        (native / "src/context_policy.rs").write_text(f'pub const CONTEXT_POLICY_VERSION: &str = "{POLICY_VERSION}";\n')
        (native / "src/context_projection.rs").write_text(f'pub const CONTEXT_PROJECTION_VERSION: &str = "{PROJECTION_VERSION}";\n')
        (native / "src/events.rs").write_text("// current event contract fixture\n")
        (self.runtime / "Cargo.toml").write_text('[package]\nname="hepta-runtime"\nversion="0.1.0"\n')
        runtime = {"id": "path+runtime#hepta-runtime@0.1.0", "name": "hepta-runtime", "version": "0.1.0",
            "source": None, "manifest_path": str(self.runtime / "Cargo.toml")}
        native = {"id": "path+native#codex-hepta-native-agent@0.1.0", "name": "codex-hepta-native-agent",
            "version": "0.1.0", "source": None, "manifest_path": str(native / "Cargo.toml")}
        self.metadata = {"graphs": {label: {"packages": copy.deepcopy([native, runtime])} for label in ("runner", "owner")}}
        self.config = self.root / "runtime-patch.toml"
        self.config.write_text('[patch."https://github.com/TrillionniumFoundation/hepta-runtime.git"]\n'
            f'hepta-runtime = {{ path = {json.dumps(str(self.runtime))} }}\n')

    def contract(self):
        return metadata_contract(self.metadata, self.owner, self.revision, self.runtime)

    def snapshot(self):
        return source_snapshot(self.owner, self.metadata, self.revision, self.runtime, self.config)

    def test_same_runtime_path_in_both_real_graphs_is_required(self):
        local, runtime = self.contract()
        self.assertEqual([p["name"] for p in local], ["codex-hepta-native-agent"])
        self.assertEqual(len(runtime), 1)
        self.metadata["graphs"]["owner"]["packages"][1]["manifest_path"] = str(self.root / "different/Cargo.toml")
        with self.assertRaisesRegex(ValueError, "declared runtime path"):
            self.contract()

    def test_same_named_nested_runtime_cannot_replace_the_repository_root(self):
        for label in ("runner", "owner"):
            self.metadata["graphs"][label]["packages"][1]["manifest_path"] = str(self.runtime / "nested/Cargo.toml")
        with self.assertRaisesRegex(ValueError, "declared runtime path"):
            self.contract()

    def test_directory_symlink_requires_binding_its_source_contents(self):
        target = self.root / "unbound_source"
        target.mkdir()
        (target / "native.rs").write_text("// content outside the observed package tree\n")
        (self.owner / "codex-rs/hepta-native-agent/src/linked").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "directory symlink"):
            self.snapshot()

    def test_duplicate_runtime_even_at_same_version_is_rejected(self):
        duplicate = copy.deepcopy(self.metadata["graphs"]["runner"]["packages"][1])
        duplicate["id"] = "git+old-runtime#hepta-runtime@0.1.0"
        duplicate["source"] = "git+https://github.com/TrillionniumFoundation/hepta-runtime.git#" + "1" * 40
        self.metadata["graphs"]["runner"]["packages"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.contract()

    def test_runtime_subcrate_cannot_escape_to_an_old_git_revision(self):
        self.metadata["graphs"]["owner"]["packages"].append({"id": "old-execution-core", "name": "hepta-runtime-execution-core",
            "version": "0.1.0", "manifest_path": str(self.root / "old-runtime/core/Cargo.toml"),
            "source": "git+https://github.com/TrillionniumFoundation/hepta-runtime.git#" + "2" * 40})
        with self.assertRaisesRegex(ValueError, "bypassed"):
            self.contract()

    def test_old_native_checkout_is_not_a_current_path_build(self):
        self.metadata["graphs"]["runner"]["packages"][0]["manifest_path"] = str(self.root / "old-native/Cargo.toml")
        with self.assertRaisesRegex(ValueError, "current native-agent"):
            self.contract()

    def test_dirty_native_and_runtime_source_are_bound_by_content(self):
        before = self.snapshot()
        self.assertIn("Cargo.toml", before["runtime_repository"]["dirty_files"])
        (self.runtime / "new_owned_entry.rs").write_text("// candidate native owner change\n")
        after = self.snapshot()
        self.assertNotEqual(object_digest(before), object_digest(after))
        self.assertIn("new_owned_entry.rs", after["runtime_repository"]["dirty_files"])
        (self.owner / "codex-rs/hepta-native-agent/src/events.rs").write_text("// another event implementation\n")
        self.assertNotEqual(object_digest(after), object_digest(self.snapshot()))

    def test_old_context_policy_source_is_rejected(self):
        (self.owner / "codex-rs/hepta-native-agent/src/context_policy.rs").write_text("// previous policy\n")
        with self.assertRaisesRegex(ValueError, "current native streaming/context policy"):
            self.snapshot()

    def test_generated_caches_do_not_reclassify_unchanged_source(self):
        before = self.snapshot()
        for root in (self.owner, self.runtime):
            (root / "__pycache__").mkdir()
            (root / "__pycache__/module.pyc").write_bytes(b"generated Python cache")
        self.assertEqual(before, self.snapshot())

    def test_patch_cannot_change_an_unrelated_repository_or_escape_tree(self):
        self.config.write_text('[patch."https://example.invalid/unrelated"]\nthing={path="/tmp/unrelated"}\n')
        with self.assertRaisesRegex(ValueError, "unrelated"):
            patch_configuration(self.config, self.runtime)
        self.config.write_text('[patch."https://github.com/TrillionniumFoundation/hepta-runtime.git"]\n'
            'hepta-runtime={path="/tmp/outside-declared-tree"}\n')
        with self.assertRaisesRegex(ValueError, "escaped"):
            patch_configuration(self.config, self.runtime)

    def test_both_dependency_graphs_and_full_commit_are_required(self):
        with self.assertRaisesRegex(ValueError, "exact base commit"):
            metadata_contract(self.metadata, self.owner, "main", self.runtime)
        del self.metadata["graphs"]["owner"]
        with self.assertRaisesRegex(ValueError, "owner resolved dependency graphs"):
            self.contract()


class BuildProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "provenance/native-current/build_native.py"
        if not path.exists():
            path = Path(os.environ["HEPTA_NATIVE_BUILDER_TEST_PATH"])
        spec = importlib.util.spec_from_file_location("native_builder_test", path)
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)

    def exercise(self, cancel):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_code = (
                "import json, os, pathlib, signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "raw=pathlib.Path('/proc/self/stat').read_text(); "
                "fields=raw.rsplit(')',1)[1].split(); "
                "print(json.dumps({'pid':int(raw.split(' ',1)[0]),'namespace_pid':os.getpid(),'start_ticks':fields[19]}),flush=True); "
                "time.sleep(30)"
            )
            code = (
                "import os, signal, subprocess, sys, time\n"
                f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}], stdout=subprocess.PIPE, text=True)\n"
                "print(child.stdout.readline().strip(), flush=True)\n"
                + ("time.sleep(.2); os.kill(os.getppid(), signal.SIGTERM)\n" if cancel else "")
                + "time.sleep(30)\n"
            )
            result = self.builder.bounded_command([sys.executable, "-c", code], root,
                os.environ.copy(), root / "original.log", 2)
            self.assertTrue(result["cleanup"]["leader_reaped"])
            self.assertEqual(result["cleanup"]["SIGKILL"], "sent")
            if cancel:
                self.assertEqual(result["cancelled_signal"], 15)
            else:
                self.assertTrue(result["timed_out"])
            original = json.loads((root / "original.log").read_text().strip())
            # The /proc-visible identity can differ from getpid() inside a
            # nested PID namespace; capture it in the original child itself.
            state = Path(f"/proc/{original['pid']}/stat")
            deadline = time.monotonic() + 3
            last = None
            while time.monotonic() < deadline:
                try:
                    last = state.read_text().rsplit(")", 1)[1].split()
                except FileNotFoundError:
                    return
                if last[19] != original["start_ticks"] or last[0] == "Z":
                    return
                # Signal delivery and scheduler exit are not synchronous. We
                # only observe the captured original identity; never send a
                # later signal to a possibly reused PID after leader reap.
                time.sleep(.02)
            self.fail(f"original descendant did not exit within the observation bound: {original}, state={last[0] if last else None}")

    @unittest.skipUnless(sys.platform.startswith("linux"), "uses Linux waitid/proc process observations")
    def test_timeout_kills_original_descendant_even_after_leader_term(self):
        self.exercise(False)

    @unittest.skipUnless(sys.platform.startswith("linux"), "uses Linux waitid/proc process observations")
    def test_signal_cancellation_closes_original_cargo_group(self):
        self.exercise(True)


if __name__ == "__main__":
    unittest.main()
