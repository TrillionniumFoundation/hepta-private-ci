"""Exercise the explicit preedit profile through the original source verifier.

Temporary source/metadata fixtures are not evidence of XIM or UI execution.
The actual candidate still needs the real IBus window qualification.
"""
import json

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
