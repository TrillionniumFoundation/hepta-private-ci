from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("hepta_ui_native_supply_chain.py")
SPEC = importlib.util.spec_from_file_location("hepta_ui_native_supply_chain", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA = "1" * 40
TREE = "2" * 40
DIGEST = "a" * 64
LOCK = """version = 3

[[package]]
name = "demo"
version = "1.2.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"""


class UiNativeSupplyChainTests(unittest.TestCase):
    def prepare(self, root: Path) -> Path:
        for relative in ("apps/hepta-native/Cargo.lock", "codex-rs/Cargo.lock"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(LOCK, encoding="utf-8", newline="\n")
        receipt = root / "package-receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema": "hepta.ui-native-package-receipt.v1",
                    "platform": "linux",
                    "archive": "hepta-native-linux-x86_64-unsigned.zip",
                    "archiveSha256": DIGEST,
                    "manifest": {
                        "version": "0.1.0",
                        "productionSigningObserved": False,
                        "notarizationObserved": False,
                        "releaseAuthorized": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return receipt

    def test_emits_bound_non_promoting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = self.prepare(root)
            manifest = MODULE.generate(
                root=root,
                candidate=SHA,
                base=SHA,
                implementation=SHA,
                source_sha=SHA,
                source_tree=TREE,
                kind="head",
                platform="linux",
                package_receipt_path=receipt,
                out_dir=root / "out",
                timestamp="2026-09-30T00:00:00Z",
            )
            self.assertFalse(manifest["productionQualified"])
            self.assertFalse(manifest["releaseAuthorized"])
            sbom = json.loads((root / "out/sbom.cdx.json").read_text())
            provenance = json.loads((root / "out/provenance.intoto.json").read_text())
            self.assertEqual(sbom["bomFormat"], "CycloneDX")
            self.assertEqual(
                provenance["predicateType"], "https://slsa.dev/provenance/v1"
            )
            self.assertEqual(provenance["subject"][0]["digest"]["sha256"], DIGEST)

    def test_rejects_promoted_unsigned_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = self.prepare(root)
            value = json.loads(receipt.read_text())
            value["manifest"]["releaseAuthorized"] = True
            receipt.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                MODULE.generate(
                    root=root,
                    candidate=SHA,
                    base=SHA,
                    implementation=SHA,
                    source_sha=SHA,
                    source_tree=TREE,
                    kind="head",
                    platform="linux",
                    package_receipt_path=receipt,
                    out_dir=root / "out",
                    timestamp="2026-09-30T00:00:00Z",
                )

    def test_autocrlf_checkout_matches_git_inventory_only_with_lf_attributes(
        self,
    ) -> None:
        import hepta_ui_native_aggregate as aggregate
        import hepta_ui_native_evidence as evidence

        # The CLI wrapper patches shared modules; preserve unittest isolation.
        original = aggregate.aggregate, evidence.WORKFLOW, evidence.REQUIRED
        try:
            qualified = importlib.import_module(
                "hepta_ui_native_qualification_aggregate"
            )
        finally:
            aggregate.aggregate, evidence.WORKFLOW, evidence.REQUIRED = original

        repository = Path(__file__).resolve().parents[1]
        root_attributes = (repository / ".gitattributes").read_text(encoding="utf-8")
        app_attributes = (repository / "apps/hepta-native/.gitattributes").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as raw:
            for protected in (False, True):
                with self.subTest(lf_attributes=protected):
                    root = Path(raw).resolve() / (
                        "protected" if protected else "unprotected"
                    )
                    receipt = self.prepare(root)
                    package = json.loads(receipt.read_text(encoding="utf-8"))
                    package.update(
                        {
                            "platform": "windows",
                            "archive": "hepta-native-windows-x86_64-unsigned.zip",
                        }
                    )
                    receipt.write_text(
                        json.dumps(package), encoding="utf-8", newline="\n"
                    )
                    (root / ".gitattributes").write_text(
                        root_attributes if protected else "",
                        encoding="utf-8",
                        newline="\n",
                    )
                    (root / "apps/hepta-native/.gitattributes").write_text(
                        app_attributes, encoding="utf-8", newline="\n"
                    )
                    commands = (
                        ("init", "--quiet"),
                        ("config", "user.email", "fixture@example.invalid"),
                        ("config", "user.name", "fixture"),
                        ("config", "core.autocrlf", "true"),
                        (
                            "add",
                            ".gitattributes",
                            "apps/hepta-native/.gitattributes",
                            "apps/hepta-native/Cargo.lock",
                            "codex-rs/Cargo.lock",
                        ),
                        ("commit", "--quiet", "-m", "exact source locks"),
                    )
                    for command in commands:
                        subprocess.run(
                            ["git", *command], cwd=root, check=True, capture_output=True
                        )
                    lock_paths = ("apps/hepta-native/Cargo.lock", "codex-rs/Cargo.lock")
                    for path in lock_paths:
                        (root / path).unlink()
                    subprocess.run(
                        ["git", "checkout", "--", *lock_paths],
                        cwd=root,
                        check=True,
                        capture_output=True,
                    )
                    self.assertEqual(
                        subprocess.check_output(
                            ["git", "status", "--porcelain", "--untracked-files=no"],
                            cwd=root,
                        ),
                        b"",
                    )
                    source = {
                        "sourceSha": subprocess.check_output(
                            ["git", "rev-parse", "HEAD"], cwd=root, text=True
                        ).strip(),
                        "sourceTreeSha": subprocess.check_output(
                            ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True
                        ).strip(),
                    }
                    expected_locks, expected_components = (
                        qualified.source_dependency_inventory(root, source)
                    )
                    manifest = MODULE.generate(
                        root=root,
                        candidate=source["sourceSha"],
                        base=source["sourceSha"],
                        implementation=source["sourceSha"],
                        source_sha=source["sourceSha"],
                        source_tree=source["sourceTreeSha"],
                        kind="head",
                        platform="windows",
                        package_receipt_path=receipt,
                        out_dir=root / "out",
                        timestamp="2026-09-30T00:00:00Z",
                    )
                    observed_locks = {
                        lock_paths[0]: manifest["applicationCargoLockSha256"],
                        lock_paths[1]: manifest["ownerCargoLockSha256"],
                    }
                    sbom = json.loads(
                        (root / "out/sbom.cdx.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(sbom["components"], expected_components)
                    self.assertNotIn(b"\r\n", (root / lock_paths[0]).read_bytes())
                    self.assertEqual(
                        observed_locks[lock_paths[0]], expected_locks[lock_paths[0]]
                    )
                    if protected:
                        self.assertNotIn(b"\r\n", (root / lock_paths[1]).read_bytes())
                        self.assertEqual(observed_locks, expected_locks)
                        self.assertEqual(
                            sbom["metadata"]["properties"],
                            [
                                {
                                    "name": "hepta:application-lock-sha256",
                                    "value": expected_locks[lock_paths[0]],
                                },
                                {
                                    "name": "hepta:owner-lock-sha256",
                                    "value": expected_locks[lock_paths[1]],
                                },
                            ],
                        )
                    else:
                        self.assertIn(b"\r\n", (root / lock_paths[1]).read_bytes())
                        self.assertNotEqual(
                            observed_locks[lock_paths[1]], expected_locks[lock_paths[1]]
                        )


if __name__ == "__main__":
    unittest.main()
