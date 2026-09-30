"""Executable adversarial tests; fixture bytes are NOT runnable product builds."""
from __future__ import annotations

import copy
import hashlib
import json
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

TOOLS = Path(__file__).resolve().parents[1]
# Match direct CLI imports without permanently changing another test's search path.
sys.path.insert(0, str(TOOLS))
try:
    import archive_safety as safety
    import package_unsigned as package
finally:
    sys.path.pop(0)


class PackageSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="native-package-security-")
        cls.root = Path(cls.temp.name).resolve()
        cls.receipts, cls.archives = {}, {}
        for platform in sorted(package.PLATFORMS):
            release = cls.root / platform / "release"
            release.mkdir(parents=True)
            for name in package.BINARIES:
                suffix = ".exe" if platform == "windows" else ""
                (release / (name + suffix)).write_bytes(f"fixture:{platform}:{name}".encode())
            output = cls.root / platform / "dist"
            receipt = package.build_package(platform, "test-arch", release, output)
            cls.receipts[platform] = receipt
            cls.archives[platform] = output / receipt["archive"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.work.cleanup)
        self.workdir = Path(self.work.name)

    def rewrite(self, transform, platform="linux"):
        with zipfile.ZipFile(self.archives[platform]) as original:
            entries = [(copy.copy(info), original.read(info)) for info in original.infolist()]
        entries = transform(entries)
        target = self.workdir / f"mutated-{len(list(self.workdir.iterdir()))}.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(target, "w") as out:
                for info, body in entries:
                    out.writestr(info, body)
        return target

    def manifest_change(self, change, platform="linux"):
        def transform(entries):
            for index, (info, body) in enumerate(entries):
                if info.filename.endswith("/" + safety.MANIFEST):
                    manifest = json.loads(body)
                    change(manifest)
                    entries[index] = info, json.dumps(manifest).encode()
            return entries
        return self.rewrite(transform, platform)

    def test_all_platforms_have_closed_population_and_product_version(self):
        expected_files = {
            "linux": {
                "usr/bin/hepta-native", "usr/bin/hepta-native-updater",
                "usr/bin/hepta-native-credential",
                "usr/share/applications/hepta-native.desktop", "PACKAGING.md",
            },
            "macos": {
                "Contents/MacOS/hepta-native", "Contents/Helpers/hepta-native-updater",
                "Contents/Helpers/hepta-native-credential", "Contents/Info.plist",
                "PACKAGING.md",
            },
            "windows": {
                "hepta-native.exe", "hepta-native-updater.exe",
                "hepta-native-credential.exe", "app.manifest",
                "Register-HeptaNativeIdentity.ps1", "PACKAGING.md",
            },
        }
        for platform, archive in self.archives.items():
            with self.subTest(platform=platform):
                manifest = safety.validate_archive(archive)
                self.assertEqual(manifest["schema"], safety.SCHEMA)
                self.assertEqual(set(manifest["fileSha256"]), expected_files[platform])
                self.assertEqual(manifest["version"], package.tomllib.loads(
                    (package.APP / "Cargo.toml").read_text())["package"]["version"])
                self.assertFalse(manifest["releaseAuthorized"])

    def test_reproducible_three_platform_packages(self):
        package.self_test()

    def test_extra_unlisted_member_is_rejected(self):
        archive = self.rewrite(lambda entries: entries + [("HeptaNative.AppDir/extra", b"x")])
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_self_listed_extra_member_cannot_expand_platform_contract(self):
        archive = self.manifest_change(lambda manifest: manifest["fileSha256"].update(
            {"extra": hashlib.sha256(b"x").hexdigest()}))
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_metadata_tampering_is_rejected(self):
        archive = self.rewrite(lambda entries: [(info, b"tampered" if info.filename.endswith(".desktop") else body)
                                                for info, body in entries])
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            safety.validate_archive(archive)

    def test_binary_tampering_is_rejected(self):
        archive = self.rewrite(lambda entries: [(info, b"tampered" if info.filename.endswith("/hepta-native") else body)
                                                for info, body in entries])
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            safety.validate_archive(archive)

    def test_missing_binary_is_rejected(self):
        archive = self.rewrite(lambda entries: [(info, body) for info, body in entries
                                               if not info.filename.endswith("/hepta-native")])
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_nonportable_paths_are_rejected(self):
        names = ["/absolute", "../escape", "HeptaNative.AppDir/../escape",
                 "HeptaNative.AppDir//alias", "HeptaNative.AppDir/./alias",
                 "HeptaNative.AppDir/file:stream", "HeptaNative.AppDir/CON.txt",
                 "HeptaNative.AppDir/aux", "HeptaNative.AppDir/LPT9.log",
                 "HeptaNative.AppDir/trailing.", "HeptaNative.AppDir/trailing ",
                 "HeptaNative.AppDir/a\\b", "HeptaNative.AppDir/line\nbreak",
                 "HeptaNative.AppDir/unicodé", "HeptaNative.AppDir/C:/escape",
                 "HeptaNative.AppDir/a?b", "HeptaNative.AppDir/" + "x" * 129]
        for name in names:
            with self.subTest(name=name):
                archive = self.rewrite(lambda entries: entries + [(name, b"x")])
                with self.assertRaises(ValueError):
                    safety.validate_archive(archive)

    def test_case_aliased_member_is_rejected(self):
        archive = self.rewrite(lambda entries: entries + [("HeptaNative.AppDir/packaging.md", b"x")])
        with self.assertRaisesRegex(ValueError, "case-aliased"):
            safety.validate_archive(archive)

    def test_exact_duplicate_member_is_rejected(self):
        archive = self.rewrite(lambda entries: entries + [entries[0]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            safety.validate_archive(archive)

    def test_multiple_roots_are_rejected(self):
        archive = self.rewrite(lambda entries: entries + [("Other/extra", b"x")])
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_file_directory_prefix_collision_is_rejected(self):
        archive = self.rewrite(lambda entries: entries + [("HeptaNative.AppDir/usr", b"x")])
        with self.assertRaisesRegex(ValueError, "prefix collision"):
            safety.validate_archive(archive)

    def test_special_member_types_and_privileged_modes_are_rejected(self):
        for mode in [stat.S_IFLNK | 0o777, stat.S_IFDIR | 0o755,
                     stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4755, stat.S_IFREG | 0o2755]:
            def transform(entries):
                entries[0][0].external_attr = mode << 16
                return entries
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                safety.validate_archive(self.rewrite(transform))

    def test_member_count_bound(self):
        with mock.patch.object(safety, "MAX_MEMBERS", 5), self.assertRaises(ValueError):
            safety.validate_archive(self.archives["linux"])

    def test_member_size_bound(self):
        with mock.patch.object(safety, "MAX_MEMBER_BYTES", 1), self.assertRaises(ValueError):
            safety.validate_archive(self.archives["linux"])

    def test_total_expansion_bound(self):
        with mock.patch.object(safety, "MAX_TOTAL_BYTES", 1), self.assertRaises(ValueError):
            safety.validate_archive(self.archives["linux"])

    def test_manifest_size_bound(self):
        with mock.patch.object(safety, "MAX_MANIFEST_BYTES", 1), self.assertRaises(ValueError):
            safety.validate_archive(self.archives["linux"])

    def test_mismatched_platform_root_is_rejected(self):
        archive = self.manifest_change(lambda manifest: manifest.update(platform="windows"))
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_unknown_schema_is_rejected(self):
        archive = self.manifest_change(lambda manifest: manifest.update(schema="legacy"))
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_placeholder_and_malformed_versions_are_rejected(self):
        for value in ["0.0.0", "", "1", "01.0.0", 1, None]:
            archive = self.manifest_change(lambda manifest: manifest.update(version=value))
            with self.subTest(version=value), self.assertRaises(ValueError):
                safety.validate_archive(archive)

    def test_unsigned_manifest_cannot_promote_authority(self):
        for field, value in [("releaseAuthorized", True), ("notarizationObserved", True),
                             ("productionSigningObserved", True), ("unsignedDevelopmentArtifact", False),
                             ("releaseAuthorized", 0), ("unsignedDevelopmentArtifact", 1)]:
            archive = self.manifest_change(lambda manifest: manifest.update({field: value}))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                safety.validate_archive(archive)

    def test_binary_inventory_cannot_drop_updater(self):
        archive = self.manifest_change(lambda manifest: manifest["binarySha256"].pop("usr/bin/hepta-native-updater"))
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_file_inventory_cannot_drop_metadata(self):
        archive = self.manifest_change(lambda manifest: manifest["fileSha256"].pop("PACKAGING.md"))
        with self.assertRaises(ValueError):
            safety.validate_archive(archive)

    def test_digest_must_be_canonical_sha256(self):
        for value in ["f" * 63, "F" * 64, "0" * 65, 1, None]:
            archive = self.manifest_change(lambda manifest: manifest["fileSha256"].update({"PACKAGING.md": value}))
            with self.subTest(value=value), self.assertRaises(ValueError):
                safety.validate_archive(archive)

    def test_binary_and_file_inventory_must_agree(self):
        archive = self.manifest_change(lambda manifest: manifest["binarySha256"].update({"usr/bin/hepta-native": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "disagree"):
            safety.validate_archive(archive)

    def test_duplicate_manifest_fields_are_rejected(self):
        def transform(entries):
            for i, (info, body) in enumerate(entries):
                if info.filename.endswith("/" + safety.MANIFEST):
                    entries[i] = info, body.replace(b'{', b'{"platform":"linux",', 1)
            return entries
        with self.assertRaisesRegex(ValueError, "duplicate manifest"):
            safety.validate_archive(self.rewrite(transform))

    def test_existing_destination_is_not_deleted(self):
        destination = self.workdir / "existing"
        destination.mkdir()
        sentinel = destination / "preserve"
        sentinel.write_bytes(b"operator-data")
        with self.assertRaises(ValueError):
            safety.extract_verified_archive(self.archives["linux"], destination)
        self.assertEqual(sentinel.read_bytes(), b"operator-data")

    @unittest.skipUnless(hasattr(__import__('os'), 'symlink') and sys.platform != 'win32', 'requires unprivileged symlinks')
    def test_archive_symlink_is_rejected(self):
        link = self.workdir / "link.zip"
        link.symlink_to(self.archives["linux"])
        with self.assertRaises(ValueError):
            safety.validate_archive(link)

    @unittest.skipUnless(hasattr(__import__('os'), 'symlink') and sys.platform != 'win32', 'requires unprivileged symlinks')
    def test_destination_parent_symlink_is_rejected(self):
        real = self.workdir / "real"
        real.mkdir()
        link = self.workdir / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            safety.extract_verified_archive(self.archives["linux"], link / "extracted")
        self.assertEqual(list(real.iterdir()), [])

    def test_invalid_archive_never_creates_destination(self):
        archive = self.rewrite(lambda entries: entries + [("../outside", b"x")])
        destination = self.workdir / "extracted"
        with self.assertRaises(ValueError):
            safety.extract_verified_archive(archive, destination)
        self.assertFalse(destination.exists())

    def test_extraction_reuses_the_validated_archive_handle(self):
        original = zipfile.ZipFile
        with mock.patch.object(safety.zipfile, "ZipFile", wraps=original) as opened:
            root = safety.extract_verified_archive(self.archives["linux"], self.workdir / "extracted")
            self.assertEqual(opened.call_count, 1)
            self.assertTrue((root / "PACKAGING.md").is_file())

    def test_mutated_bytes_after_validation_are_rejected_during_extraction(self):
        validated = False
        original_validate = safety.validate_open_archive
        original_open = zipfile.ZipFile.open

        def validate(source):
            nonlocal validated
            result = original_validate(source)
            validated = True
            return result

        def open_member(source, member, *args, **kwargs):
            if validated and isinstance(member, zipfile.ZipInfo) and member.filename.endswith("/PACKAGING.md"):
                return io.BytesIO(b"x" * member.file_size)
            return original_open(source, member, *args, **kwargs)

        with mock.patch.object(safety, "validate_open_archive", side_effect=validate), \
             mock.patch.object(zipfile.ZipFile, "open", open_member):
            with self.assertRaisesRegex(ValueError, "digest changed"):
                safety.extract_verified_archive(self.archives["linux"], self.workdir / "extracted")

    def test_package_builder_never_deletes_existing_output(self):
        output = self.workdir / "output"
        output.mkdir()
        sentinel = output / "operator-data"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            package.build_package("linux", "test-arch", self.root / "linux/release", output)
        self.assertEqual(sentinel.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
