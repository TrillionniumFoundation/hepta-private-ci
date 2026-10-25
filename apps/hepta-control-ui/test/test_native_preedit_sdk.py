"""Exercise the explicit preedit profile through the original source verifier.

Temporary source/metadata fixtures are not evidence of XIM or UI execution.
The actual candidate still needs the real IBus window qualification.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_native_clipboard_sdk as fixture


class PreeditSdkGraphTests(fixture.OriginalSdkGraphTests):
    def setUp(self):
        super().setUp()
        patch_root = self.hepta / "third_party/makepad-patches"
        candidate_root = patch_root / "preedit-callbacks"
        candidate_root.mkdir()
        manifest = json.loads((patch_root / "MANIFEST.json").read_text())
        manifest.update(profile="preedit-callbacks", upstream_tree=self.git("rev-parse", "HEAD^{tree}"))
        (candidate_root / "MANIFEST.json").write_text(json.dumps(manifest))
        for metadata in (self.original, self.candidate):
            self.node(metadata, "original-ui")["features"] = ["ui", "native-presentation"]
        _, config = fixture.VERIFY.PREPARE.cargo_override(self.original, self.prepared, "preedit-callbacks")
        self.config = config.encode()

    def verify(self, candidate=None):
        return fixture.VERIFY.verify(
            self.hepta, self.prepared, json.dumps(self.original).encode(),
            json.dumps(self.candidate if candidate is None else candidate).encode(),
            self.config, "preedit-callbacks")

    def test_clipboard_api_cannot_be_advertised_by_the_preedit_only_sdk(self):
        self.node(self.candidate, "original-ui")["features"].append("native-clipboard-sdk")
        with self.assertRaisesRegex(ValueError, "does not provide the separate clipboard SDK API"):
            self.verify()

    def test_original_tree_mismatch_is_rejected_before_graph_validation(self):
        path = self.hepta / "third_party/makepad-patches/preedit-callbacks/MANIFEST.json"
        manifest = json.loads(path.read_text())
        manifest["upstream_tree"] = "0" * 40
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "original full tree differs"):
            self.verify()

    def test_tracked_flags_cannot_hide_changed_source_from_the_profile(self):
        relative = "platform/Cargo.toml"
        path = self.prepared / relative
        original = path.read_bytes()
        for flag, clear in (("--assume-unchanged", "--no-assume-unchanged"),
                            ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                self.git("update-index", flag, relative)
                path.write_bytes(original + b"# hidden changed source\n")
                with self.assertRaisesRegex(ValueError, "hidden tracked source flags"):
                    self.verify()
                self.git("update-index", clear, relative)
                path.write_bytes(original)

    def test_source_identity_alone_does_not_accept_different_sdk_features(self):
        self.node(self.candidate, self.ids["makepad-platform"][1])["features"] = ["different-feature"]
        with self.assertRaisesRegex(ValueError, "resolved different features: makepad-platform"):
            self.verify()

    def test_sdk_dependency_target_and_kind_are_part_of_the_bound_graph(self):
        edge = self.node(self.candidate, self.ids["makepad-half"][1])["deps"][0]
        edge["dep_kinds"] = [{"kind": "build", "target": 'cfg(target_os = "linux")'}]
        with self.assertRaisesRegex(ValueError, "SDK dependency edge points to a different source: makepad-half"):
            self.verify()


class PreeditWidgetPreparationTests(unittest.TestCase):
    """Run real source preparation; synthetic files are not a UI qualification."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="preedit-widget-preparation-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.hepta = self.root / "hepta"
        self.license = b"Synthetic preparation fixture, not the actual SDK license.\n"
        (self.upstream / "LICENSE").write_bytes(self.license)
        for name in ("window.rs", "text_input.rs", "unrelated.rs"):
            path = self.upstream / "widgets/src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original fixture\n")
        self.git("init", "--quiet")
        self.git("add", "--all")
        self.git("-c", "user.name=Preedit preparation fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "Synthetic upstream fixture")
        self.base = self.git("rev-parse", "HEAD").decode().strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()
        base_patch = patch.object(fixture.VERIFY.PREPARE, "BASE", self.base)
        base_patch.start()
        self.addCleanup(base_patch.stop)
        self.sequence = 0

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.upstream), *args])

    def manifest(self, relative, profile):
        path = self.upstream / relative
        previous = path.read_bytes() if path.exists() else None
        replacement = b"changed synthetic widget fixture\n"
        path.write_bytes(replacement)
        self.git("add", "--all")
        patch_bytes = self.git("diff", "--cached", "--full-index", self.base)
        patched_tree = self.git("write-tree").decode().strip()
        self.git("reset", "--hard", self.base)
        directory = self.hepta / "third_party/makepad-patches"
        if profile == "preedit-callbacks":
            directory /= profile
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fixture.patch").write_bytes(patch_bytes)
        digest = lambda data: hashlib.sha256(data).hexdigest()
        manifest = {
            "schema_version": 1, "profile": profile,
            "upstream_repository": fixture.VERIFY.PREPARE.SOURCE,
            "upstream_commit": self.base, "upstream_tree": self.tree,
            "patched_tree": patched_tree,
            "package": {"name": "makepad-platform", "version": "2.0.0"},
            "patches": [{"file": "fixture.patch", "bytes": len(patch_bytes), "sha256": digest(patch_bytes)}],
            "changed_files": [{"path": relative,
                               "upstream_sha256": digest(previous) if previous is not None else None,
                               "patched_sha256": digest(replacement), "bytes": len(replacement)}],
            "license": {"path": "LICENSE", "bytes": len(self.license), "sha256": digest(self.license)},
            "effects_authority": False, "automatic_update": False,
        }
        path = directory / "MANIFEST.json"
        path.write_text(json.dumps(manifest))
        self.sequence += 1
        return path, manifest, self.root / f"prepared-{self.sequence}"

    def test_exact_preedit_widget_files_prepare_and_bind_the_complete_tree(self):
        for relative in ("widgets/src/window.rs", "widgets/src/window_focus_tests.rs",
                         "widgets/src/text_input.rs", "widgets/src/text_input_composition_undo_tests.rs"):
            with self.subTest(relative=relative):
                _, manifest, destination = self.manifest(relative, "preedit-callbacks")
                result = fixture.VERIFY.PREPARE.prepare(
                    self.upstream, destination, self.hepta, "preedit-callbacks")
                self.assertEqual(result["patched_tree"], manifest["patched_tree"])
                self.assertEqual((destination / relative).read_bytes(), b"changed synthetic widget fixture\n")
                self.assertFalse(result["runtime_qualified"])

    def test_unreviewed_widget_path_is_refused_even_when_its_tree_and_hashes_match(self):
        _, _, destination = self.manifest("widgets/src/unrelated.rs", "preedit-callbacks")
        with self.assertRaisesRegex(ValueError, "Invalid or duplicate SDK source path"):
            fixture.VERIFY.PREPARE.prepare(self.upstream, destination, self.hepta, "preedit-callbacks")

    def test_clipboard_profile_cannot_adopt_preedit_widget_changes(self):
        for relative in ("widgets/src/window.rs", "widgets/src/window_focus_tests.rs",
                         "widgets/src/text_input.rs", "widgets/src/text_input_composition_undo_tests.rs"):
            with self.subTest(relative=relative):
                _, _, destination = self.manifest(relative, "clipboard")
                with self.assertRaisesRegex(ValueError, "Invalid or duplicate SDK source path"):
                    fixture.VERIFY.PREPARE.prepare(self.upstream, destination, self.hepta, "clipboard")

    def test_allowed_widget_paths_still_require_the_exact_declared_patched_tree(self):
        path, manifest, destination = self.manifest("widgets/src/window.rs", "preedit-callbacks")
        manifest["patched_tree"] = "0" * 40
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Prepared SDK tree differs from the exact reviewed tree"):
            fixture.VERIFY.PREPARE.prepare(self.upstream, destination, self.hepta, "preedit-callbacks")
