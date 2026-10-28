"""Static source controls only; no Cargo, Rust, Bazel or crypto is executed."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import hepta_pon_aws_crypto_source as source


def archive_fixture(names, link=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name in names:
            item = tarfile.TarInfo(name)
            if link:
                item.type = tarfile.SYMTYPE
                item.linkname = "outside"
                archive.addfile(item)
            else:
                item.size = 1
                archive.addfile(item, io.BytesIO(b"x"))
    return output.getvalue()


class SourceControls(unittest.TestCase):
    def test_retention_cannot_follow_an_ancestor_link_or_overwrite_bytes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            alias = root / "alias"
            alias.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                source.retain_files(alias, {"nested/data": b"candidate"})
            self.assertEqual(list(outside.iterdir()), [])
            destination = root / "retained"
            source.retain_files(destination, {"data": b"original"})
            with self.assertRaises(ValueError):
                source.retain_files(destination, {"data": b"replacement"})
            self.assertEqual((destination / "data").read_bytes(), b"original")

    def test_real_source_capsule_preserves_every_original_fixture(self):
        _, original, proposed = source.source_proposal()
        trees = json.loads(
            (source.EVIDENCE / "upstream/aws-config-git-trees.json").read_text()
        )
        verified = 0
        for directory, tree in trees["trees"].items():
            self.assertFalse(tree["truncated"])
            for item in tree["tree"]:
                if item["type"] != "blob":
                    continue
                name = directory + "/" + item["path"]
                raw = original[name]
                blob = hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest()
                self.assertEqual(
                    (blob, len(raw), item["mode"]),
                    (item["sha"], item["size"], "100644"),
                )
                if directory != "src":
                    self.assertEqual(proposed[name], raw)
                verified += 1
        self.assertEqual(verified, 310)
        self.assertEqual(proposed["LICENSE"], original["LICENSE"])
        self.assertEqual(
            source.static_review()["existing_files_changed"],
            ["Cargo.toml", "src/login/dpop.rs"],
        )

    def test_archive_parser_rejects_paths_links_and_duplicate_members(self):
        valid = "aws-config-1.8.12/file"
        self.assertEqual(
            source.archive_members(archive_fixture([valid]), "aws-config-1.8.12"),
            {"file": b"x"},
        )
        for name in [
            "/absolute/file",
            "aws-config-1.8.12/../outside",
            "aws-config-1.8.12/a//b",
            "aws-config-1.8.12/a\\b",
            "aws-config-1.8.12/a:b",
            "other/file",
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                source.archive_members(archive_fixture([name]), "aws-config-1.8.12")
        for raw in [
            archive_fixture([valid, valid]),
            archive_fixture([valid], link=True),
        ]:
            with self.assertRaises(ValueError):
                source.archive_members(raw, "aws-config-1.8.12")

    def test_workspace_mutation_is_exact_and_cannot_reapply(self):
        original = (source.ROOT / source.INPUTS[0]).read_bytes()
        proposed = source.change_workspace(original)
        with self.assertRaises(ValueError):
            source.change_workspace(proposed)
        for invalid in [
            original.replace(b'aws-config = "1"', b'aws-config = "1.13"'),
            original.replace(b'aws-sigv4 = "1"', b'aws-sigv4 = "1.6"'),
        ]:
            with self.assertRaises(ValueError):
                source.change_workspace(invalid)

    def test_modified_archive_fails_before_source_materialization(self):
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            shutil.copytree(source.EVIDENCE, evidence)
            archive = evidence / "upstream/aws-config-1.8.12.crate"
            archive.write_bytes(archive.read_bytes() + b"x")
            with (
                patch.object(source, "EVIDENCE", evidence),
                self.assertRaisesRegex(ValueError, "archive identity"),
            ):
                source.source_proposal()

    def test_feature_trimming_and_original_test_removal_remain_rejected_even_with_new_hashes(
        self,
    ):
        for relative, before, after in [
            ("Cargo.toml", b'    "dep:rand",\n', b""),
            ("BUILD.bazel", b'        "credentials-login",\n', b""),
            (
                "src/login/dpop.rs",
                b"fn test_calculate_valid_key()",
                b"fn omitted_original_test()",
            ),
        ]:
            with self.subTest(path=relative), TemporaryDirectory() as temporary:
                evidence = Path(temporary) / "evidence"
                shutil.copytree(source.EVIDENCE, evidence)
                target = evidence / "overrides" / relative
                raw = target.read_bytes().replace(before, after, 1)
                target.write_bytes(raw)
                spec_path = evidence / "source-spec.json"
                spec = json.loads(spec_path.read_text())
                spec["overrides"][relative] = source.identity(raw)
                spec_path.write_text(json.dumps(spec))
                with (
                    patch.object(source, "EVIDENCE", evidence),
                    self.assertRaises(ValueError),
                ):
                    source.source_proposal()


if __name__ == "__main__":
    unittest.main()
