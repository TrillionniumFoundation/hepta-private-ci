import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "proposal", Path(__file__).parents[1] / "prepare_verify_dependency_candidate.py"
)
proposal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proposal)


class PreparationTests(unittest.TestCase):
    def archive(self, name="sqlx-sqlite-0.9.0/src/lib.rs", kind=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            item = tarfile.TarInfo(name)
            if kind:
                item.type = kind
                item.linkname = "../outside"
                archive.addfile(item)
            else:
                raw = b"official code\n"
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
        return stream.getvalue()

    def test_checksum_refuses_before_writing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "vendor"
            with self.assertRaises(ValueError):
                proposal.unpack(self.archive(), path)
            self.assertFalse(path.exists())

    def test_regular_source_is_exact_and_existing_destination_is_refused(self):
        raw = self.archive()
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(proposal, "ARCHIVE_SHA", hashlib.sha256(raw).hexdigest()),
        ):
            path = Path(root) / "vendor"
            records = proposal.unpack(raw, path)
            self.assertEqual(
                records["src/lib.rs"],
                hashlib.sha256((path / "src/lib.rs").read_bytes()).hexdigest(),
            )
            with self.assertRaises(ValueError):
                proposal.unpack(raw, path)

    def test_unsafe_archive_members_are_refused(self):
        for name, kind in [
            ("../escape", None),
            ("sqlx-sqlite-0.9.0/../escape", None),
            ("sqlx-sqlite-0.9.0/link", tarfile.SYMTYPE),
            ("sqlx-sqlite-0.9.0/link", tarfile.LNKTYPE),
        ]:
            raw = self.archive(name, kind)
            with (
                tempfile.TemporaryDirectory() as root,
                patch.object(proposal, "ARCHIVE_SHA", hashlib.sha256(raw).hexdigest()),
            ):
                with self.assertRaises(ValueError):
                    proposal.unpack(raw, Path(root) / "vendor")

    def test_manifest_patch_requires_unique_exact_preimage(self):
        self.assertEqual(proposal.replace_once("a old b", "old", "new"), "a new b")
        for text in ("absent", "old old"):
            with self.assertRaises(ValueError):
                proposal.replace_once(text, "old", "new")

    def test_disposable_source_patch_retains_official_implementation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, output = Path(temporary) / "source", Path(temporary) / "evidence"
            root.mkdir()
            inputs = {
                "codex-rs/Cargo.toml": 'libsqlite3-sys = { version = "0.37", default-features = false }\nrmcp = { version = "=3.1.3", default-features = false }\n[patch.crates-io]\nmatrix-sdk-sqlite = { path = "third_party/matrix-sdk-sqlite-0.19.1" }\n',
                "codex-rs/Cargo.lock": "fixture original lock\n",
                "MODULE.bazel.lock": "fixture original bazel lock\n",
                "codex-rs/deny.toml": "[advisories]\nignore = []\n",
                "codex-rs/.cargo/audit.toml": "[advisories]\nignore = []\n",
                "scripts/check_hepta_rustsec_advisories.py": "# fixture guard\n",
                "scripts/tests/test_hepta_rustsec_guard.py": "# fixture tests\n",
                ".github/workflows/cargo-deny.yml": "name: fixture guard workflow\n",
                proposal.MATRIX + "/Cargo.toml": 'version = "=0.39.0"\n',
                proposal.MATRIX
                + "/Cargo.toml.orig": 'rusqlite = { version = "=0.39.0" }\n',
            }
            for name, text in inputs.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            for args in (
                ["init", "-q"],
                ["add", "."],
                [
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@localhost",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "Fixture source",
                ],
            ):
                subprocess.run(["git", *args], cwd=root, check=True)
            base = proposal.git(root, "rev-parse", "HEAD")
            pins = {name: proposal.git(root, "hash-object", name) for name in inputs}
            for name in (
                "scripts/align_verify_bindgen_syn.py",
                "qualification/verify3-syn-alignment-20261110/README.md",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("reviewed qualification addition\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            commit = [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@localhost",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Qualification paths",
            ]
            subprocess.run(commit, cwd=root, check=True)
            (root / "unreviewed.txt").write_text("not a proposal input\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(commit, cwd=root, check=True)
            with patch.object(proposal, "BASE", base):
                with self.assertRaisesRegex(
                    ValueError, "outside the reviewed proposal"
                ):
                    proposal.prepare(root, output)
            self.assertFalse(output.exists())
            self.assertFalse((root / proposal.VENDOR).exists())
            subprocess.run(["git", "rm", "-q", "unreviewed.txt"], cwd=root, check=True)
            subprocess.run(commit, cwd=root, check=True)
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                for name, raw in {
                    "Cargo.toml": b'">=0.30.1, <0.38.0"',
                    "Cargo.toml.orig": b'">=0.30.1, <0.38.0"',
                    "src/lib.rs": b"original official bytes\n",
                }.items():
                    item = tarfile.TarInfo("sqlx-sqlite-0.9.0/" + name)
                    item.size = len(raw)
                    archive.addfile(item, io.BytesIO(raw))
            raw = stream.getvalue()
            with (
                patch.object(proposal, "BASE", base),
                patch.object(proposal, "PINNED", pins),
                patch.object(proposal, "ARCHIVE_SHA", hashlib.sha256(raw).hexdigest()),
                patch.object(
                    proposal.urllib.request, "urlopen", return_value=io.BytesIO(raw)
                ),
            ):
                proposal.prepare(root, output)
            self.assertEqual(
                (root / proposal.VENDOR / "src/lib.rs").read_bytes(),
                b"original official bytes\n",
            )
            self.assertEqual(
                (root / "codex-rs/Cargo.lock").read_text(),
                inputs["codex-rs/Cargo.lock"],
            )
            self.assertIn(
                'version = "=3.9.0"', (root / "codex-rs/Cargo.toml").read_text()
            )
            self.assertFalse(
                json.loads((output / "preparation.json").read_text())[
                    "production_adoption"
                ]
            )


if __name__ == "__main__":
    unittest.main()
