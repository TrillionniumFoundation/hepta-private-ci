from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
            path.write_text(LOCK, encoding="utf-8")
        receipt = root / "package-receipt.json"
        receipt.write_text(json.dumps({
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
        }), encoding="utf-8")
        return receipt

    def test_emits_bound_non_promoting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = self.prepare(root)
            manifest = MODULE.generate(
                root=root, candidate=SHA, base=SHA, implementation=SHA,
                source_sha=SHA, source_tree=TREE, kind="head", platform="linux",
                package_receipt_path=receipt, out_dir=root / "out",
                timestamp="2026-09-30T00:00:00Z",
            )
            self.assertFalse(manifest["productionQualified"])
            self.assertFalse(manifest["releaseAuthorized"])
            sbom = json.loads((root / "out/sbom.cdx.json").read_text())
            provenance = json.loads((root / "out/provenance.intoto.json").read_text())
            self.assertEqual(sbom["bomFormat"], "CycloneDX")
            self.assertEqual(provenance["predicateType"], "https://slsa.dev/provenance/v1")
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
                    root=root, candidate=SHA, base=SHA, implementation=SHA,
                    source_sha=SHA, source_tree=TREE, kind="head", platform="linux",
                    package_receipt_path=receipt, out_dir=root / "out",
                    timestamp="2026-09-30T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
