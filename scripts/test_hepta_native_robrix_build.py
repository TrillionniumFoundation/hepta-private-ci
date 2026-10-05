import importlib.util
import fnmatch
import io
import os
from pathlib import Path
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_builder", ROOT / "apps/hepta-native/tools/build-robrix-native.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class BuildInputsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def metadata(self):
        return {
            "packages": [
                {
                    "name": "hepta-native",
                    "source": None,
                    "manifest_path": str(self.root / module.NATIVE / "Cargo.toml"),
                },
                {
                    "name": "hepta-robrix-ui",
                    "source": None,
                    "manifest_path": str(self.root / module.ROBRIX / "Cargo.toml"),
                },
                {
                    "name": "makepad-widgets",
                    "version": "2.0.0",
                    "source": module.SOURCE,
                    "manifest_path": str(self.root / "sdk/widgets/Cargo.toml"),
                },
            ]
        }

    def test_unique_pinned_metadata_keeps_generated_resource_identity(self):
        sdk, robrix = module.selected_inputs(self.metadata(), self.root)
        self.assertEqual((sdk, robrix), (self.root / "sdk", self.root / module.ROBRIX))
        generated = self.root / "generated"
        metadata = self.metadata()
        for package in metadata["packages"][:2]:
            package["manifest_path"] = package["manifest_path"].replace(
                str(self.root), str(generated)
            )
        self.assertEqual(
            module.selected_inputs(metadata, generated)[1], generated / module.ROBRIX
        )
        with self.assertRaisesRegex(ValueError, "native package source"):
            module.selected_inputs(metadata, self.root)

    def test_ambiguous_or_wrong_revision_packages_are_rejected(self):
        metadata = self.metadata()
        metadata["packages"].append(dict(metadata["packages"][-1]))
        with self.assertRaisesRegex(ValueError, "Require one"):
            module.selected_inputs(metadata, self.root)
        for replacement in [
            "registry+https://github.com/rust-lang/crates.io-index",
            module.SOURCE[:-1] + "1",
            "git+https://other.invalid/sdk#" + module.PIN,
        ]:
            metadata = self.metadata()
            metadata["packages"][-1]["source"] = replacement
            with self.assertRaisesRegex(ValueError, "exact revision"):
                module.selected_inputs(metadata, self.root)

    def test_foreign_robrix_or_native_manifest_is_rejected(self):
        for index in (0, 1):
            metadata = self.metadata()
            metadata["packages"][index]["manifest_path"] = str(
                self.root / "other/Cargo.toml"
            )
            with self.assertRaises(ValueError):
                module.selected_inputs(metadata, self.root)

    def test_lock_transform_changes_only_one_exact_source_line(self):
        canonical = (
            'version = 4\n\n[[package]]\nname = "makepad-platform"\nversion = "2.0.0"\nsource = "'
            + module.SOURCE
            + '"\ndependencies = ["makepad-script"]\n\n[[package]]\nname = "makepad-script"\nversion = "2.0.0"\nsource = "'
            + module.SOURCE
            + '"\n'
        )
        expected = canonical.replace('source = "' + module.SOURCE + '"\n', "", 1)
        self.assertEqual(module.overlay_lock(canonical), expected)
        for value in (
            canonical.replace(module.PIN, "0" * 40),
            canonical.replace('version = "2.0.0"', 'version = "3.0.0"', 1),
            canonical + canonical.split("version = 4\n\n")[1],
        ):
            with self.assertRaises(ValueError):
                module.overlay_lock(value)

    def test_native_workflow_covers_shared_and_asset_build_inputs(self):
        workflow = (
            ROOT / ".github/workflows/ui-native-lifecycle-source.yml"
        ).read_text()
        paths = [
            line.strip()[2:]
            for line in workflow.splitlines()
            if line.startswith("      - ")
        ]
        for changed in [
            "apps/hepta-control-ui/rust/robrix-ui/src/app.rs",
            "apps/hepta-control-ui/rust/robrix-ui/resources/lunar-titanium.png",
            "apps/hepta-control-ui/rust/core/src/chat.rs",
            "apps/hepta-control-ui/rust/Cargo.toml",
            "apps/hepta-native/tools/build-robrix-native.py",
            "apps/hepta-native/tools/generate-native-assets.py",
            "apps/hepta-native/resources/NATIVE-ASSETS.json",
            "apps/hepta-native/patches/makepad-native-memory-only.patch",
            "scripts/test_hepta_native_robrix_build.py",
        ]:
            with self.subTest(changed=changed):
                self.assertTrue(
                    any(fnmatch.fnmatchcase(changed, pattern) for pattern in paths)
                )
        self.assertIn("branches: [work/ui-rust-scifi-audit-20261002]", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)

    def test_current_preview_caller_binds_same_repository_head_and_merge(self):
        workflow = (ROOT / ".github/workflows/ui-native-robrix-preview.yml").read_text()
        self.assertIn("branches: [work/ui-rust-scifi-audit-20261002, dot/ui-ime-routing-20261005]", workflow)
        self.assertEqual(
            [line.strip() for line in workflow.splitlines() if line.startswith("    if: ")],
            ["if: github.event.pull_request.head.repo.full_name == github.repository"],
        )
        self.assertIn("pr-number: ${{ github.event.pull_request.number }}", workflow)
        self.assertNotIn("1338", workflow)
        self.assertIn("lane: [source-head, base-merge]", workflow)
        self.assertIn("SOURCE_SHA: ${{ github.event.pull_request.head.sha }}", workflow)
        self.assertIn("BASE_SHA: ${{ github.event.pull_request.base.sha }}", workflow)
        self.assertIn('git checkout --detach "$SOURCE_SHA"', workflow)
        self.assertIn("base-sha: ${{ env.BASE_SHA }}", workflow)
        self.assertIn("source-sha: ${{ env.SOURCE_SHA }}", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        for forbidden in ("self-hosted", "secrets.", "contents: write", "write-all", "id-token: write"):
            self.assertNotIn(forbidden, workflow)
        paths = [line.strip()[2:] for line in workflow.splitlines() if line.startswith("      - ")]
        for changed in (
            "apps/hepta-control-ui/rust/Cargo.lock",
            "apps/hepta-control-ui/rust/robrix-ui/build.rs",
            "apps/hepta-control-ui/rust/robrix-ui/resources/fonts/MANIFEST.json",
            "apps/hepta-control-ui/tools/prepare-fonts.py",
            "apps/hepta-control-ui/tools/run-desktop.py",
            "scripts/test_hepta_native_robrix_build.py",
        ):
            self.assertTrue(any(fnmatch.fnmatchcase(changed, pattern) for pattern in paths), changed)

    def test_toml_platform_path_roundtrips_unicode_and_controls(self):
        for value in [
            "/tmp/中文 😀/platform",
            '/tmp/quote"/back\\slash',
            "/tmp/tab\tline\nbell\x07delete\x7f/platform",
        ]:
            with self.subTest(value=value):
                encoded = module.toml_path(Path(value))
                self.assertEqual(tomllib.loads("path = " + encoded)["path"], value)
                self.assertNotIn("\\ud83d", encoded)
        with self.assertRaises(UnicodeEncodeError):
            module.toml_path(Path("/tmp/invalid\ud800"))

    def test_platform_siblings_remain_exact_git_types(self):
        manifest = '[package]\nname="makepad-platform"\nversion="2.0.0"\n[dependencies]\nmakepad-script = { path = "../script", version = "2.0.0" }\n[target.\'cfg(unix)\'.dependencies]\nmakepad-network = {path="../network", optional=true}\n'
        rendered = module.platform_manifest(manifest)
        self.assertNotIn("path=", rendered)
        self.assertNotIn("path =", rendered)
        self.assertEqual(rendered.count(module.PIN), 2)
        self.assertIn("[workspace]", rendered)
        with self.assertRaisesRegex(ValueError, "standalone"):
            module.platform_manifest(manifest + "\n[workspace]\n")
        with self.assertRaisesRegex(ValueError, "No pinned"):
            module.platform_manifest(
                '[package]\nname="makepad-platform"\nversion="2.0.0"\n'
            )

    def test_cross_build_environment_is_not_inherited(self):
        with patch.dict(
            os.environ,
            {
                "CARGO_BUILD_TARGET": "foreign",
                "CARGO_ENCODED_RUSTFLAGS": "foreign",
                "RUSTFLAGS": "foreign",
            },
        ):
            env = module.build_env(
                self.root / "target", self.root / "assets/native-assets.rs"
            )
        for key in ("CARGO_BUILD_TARGET", "CARGO_ENCODED_RUSTFLAGS", "RUSTFLAGS"):
            self.assertNotIn(key, env)
        self.assertEqual(env["CARGO_TARGET_DIR"], str(self.root / "target"))
        self.assertEqual(env["CARGO_BUILD_JOBS"], "1")
        self.assertEqual(
            env["HEPTA_NATIVE_ASSET_INPUT"], str(self.root / "assets/native-assets.rs")
        )

    def test_source_archive_requires_exact_bytes_and_explicit_fetch(self):
        wrong = self.root / "source.tar.gz"
        wrong.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            module.checked_font_source(wrong, self.root, False)
        with self.assertRaisesRegex(ValueError, "explicitly permit"):
            module.checked_font_source(None, self.root, False)

    def test_regeneration_rejects_changed_rust_or_json_and_never_qualifies_renderer(
        self,
    ):
        source = self.root / "repo"
        for path in (
            module.NATIVE / "Cargo.toml",
            module.NATIVE / "Cargo.lock",
            module.NATIVE / "resources/NATIVE-ASSETS.json",
            module.NATIVE / "tools/generate-native-assets.py",
            Path("apps/hepta-control-ui/tools/prepare-fonts.py"),
            module.ROBRIX / "resources/fonts/MANIFEST.json",
            module.ROBRIX / "resources/fonts/OFL.txt",
        ):
            file = source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("source fixture")
        output = self.root / "assets"
        output.mkdir()
        font = self.root / "source.tar.gz"
        font.write_bytes(b"source fixture")
        rust, data = b"const INPUT: u8 = 1;", b'{"fixed":"input"}'
        (output / "native-assets.rs").write_bytes(rust)
        (output / "native-assets-input.json").write_bytes(data)

        def regenerate(root, out, target, font_source, offline):
            self.assertEqual(root, source)
            self.assertEqual(font_source, font)
            out.mkdir(exist_ok=True)
            (out / "native-assets.rs").write_bytes(rust)
            (out / "native-assets-input.json").write_bytes(data)
            return self.root / "sdk", out / "native-assets.rs"

        receipt = self.root / "receipt.json"
        with patch.object(module, "prepare_assets", side_effect=regenerate):
            result = module.verify_assets(
                source, output, self.root / "target", font, True, receipt
            )
            self.assertTrue(result["regeneratedBytesMatch"])
            self.assertFalse(result["rendererQualified"])
            self.assertEqual(result["assetRustSha256"], module.sha(rust))
            with self.assertRaisesRegex(ValueError, "existing asset verification"):
                module.verify_assets(
                    source, output, self.root / "target", font, True, receipt
                )
            for name, original in (
                ("native-assets.rs", rust),
                ("native-assets-input.json", data),
            ):
                receipt.unlink(missing_ok=True)
                (output / name).write_bytes(original + b"drift")
                with self.assertRaisesRegex(
                    ValueError, "Regenerated asset input differs"
                ):
                    module.verify_assets(
                        source, output, self.root / "target", font, True, receipt
                    )
                self.assertFalse(receipt.exists())
                (output / name).write_bytes(original)

    def test_verify_cli_rejects_dangling_receipt_without_following_it(self):
        receipt = self.root / "receipt.json"
        target = self.root / "absent.json"
        receipt.symlink_to(target)
        argv = [
            "builder",
            "verify-assets",
            "--source-root",
            str(self.root),
            "--out",
            str(self.root / "out"),
            "--receipt",
            str(receipt),
        ]
        with (
            patch.object(module.sys, "argv", argv),
            patch.object(
                module, "checked_font_source", return_value=self.root / "font"
            ),
            patch.object(module, "prepare_assets") as prepare,
        ):
            with self.assertRaisesRegex(ValueError, "existing asset verification"):
                module.main()
            prepare.assert_not_called()
        self.assertTrue(receipt.is_symlink())
        self.assertFalse(target.exists())

    def archive(self, entries):
        path = self.root / "source.tar"
        with tarfile.open(path, "w") as archive:
            for name, kind, value in entries:
                item = tarfile.TarInfo(name)
                if kind == "file":
                    item.size = len(value)
                    item.mode = 0o644
                    archive.addfile(item, io.BytesIO(value))
                elif kind == "link":
                    item.type = tarfile.SYMTYPE
                    item.linkname = value
                    archive.addfile(item)
                else:
                    item.type = tarfile.LNKTYPE
                    item.linkname = value
                    archive.addfile(item)
        return path

    def test_canonical_archive_relative_notice_link_is_preserved(self):
        target = self.root / "source"
        target.mkdir()
        archive = self.archive(
            [
                ("vendor/COPYING", "file", b"notice"),
                ("vendor/LICENSE", "link", "COPYING"),
            ]
        )
        module.extract_source(archive, target)
        self.assertTrue((target / "vendor/LICENSE").is_symlink())
        self.assertEqual((target / "vendor/LICENSE").read_bytes(), b"notice")

    def test_archive_escape_and_link_traversal_are_rejected(self):
        bad = [
            [("../escape", "file", b"bad")],
            [("/escape", "file", b"bad")],
            [("link", "link", "../escape")],
            [("link", "link", "/tmp/escape")],
            [("hard", "hard", "source")],
        ]
        for number, entries in enumerate(bad):
            target = self.root / f"source{number}"
            target.mkdir()
            with self.assertRaises(ValueError):
                module.extract_source(self.archive(entries), target)


if __name__ == "__main__":
    unittest.main()
