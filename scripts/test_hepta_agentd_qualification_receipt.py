from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import hepta_agentd_qualification_receipt as receipt


class AgentdQualificationReceiptTests(unittest.TestCase):
    def test_parse_artifacts_requires_unique_absolute_paths(self) -> None:
        parsed = receipt.parse_artifacts(["agentd=/tmp/agentd", "app-server=/tmp/app"])
        self.assertEqual([name for name, _path in parsed], ["agentd", "app-server"])
        with self.assertRaisesRegex(receipt.ReceiptError, "duplicate artifact"):
            receipt.parse_artifacts(["agentd=/tmp/a", "agentd=/tmp/b"])
        with self.assertRaisesRegex(receipt.ReceiptError, "absolute"):
            receipt.parse_artifacts(["agentd=relative/path"])

    def test_freeze_artifact_copies_exact_bytes_and_owner_execute_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-agentd"
            payload = b"agentd-qualified-binary\x00fixture"
            source.write_bytes(payload)
            source.chmod(0o755)
            output = root / "receipt"

            frozen = receipt.freeze_artifact("codex-hepta-agentd", source, output)

            destination = output / frozen["relative_path"]
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(frozen["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(frozen["size_bytes"], len(payload))
            self.assertEqual(frozen["frozen_mode_octal"], "0o500")

    def test_freeze_artifact_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"binary")
            link = root / "link"
            try:
                link.symlink_to(source)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(receipt.ReceiptError, "non-symlink"):
                receipt.freeze_artifact("agentd", link, root / "receipt")

    def test_checkout_output_is_rejected(self) -> None:
        with self.assertRaisesRegex(receipt.ReceiptError, "outside"):
            receipt.require_outside_checkout(receipt.ROOT / "qualification-output")


if __name__ == "__main__":
    unittest.main()
