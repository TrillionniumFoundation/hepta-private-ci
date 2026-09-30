import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReadinessManifestTest(unittest.TestCase):
    def test_source_green_without_product_caller_is_fail_closed(self):
        root = Path(__file__).resolve().parents[3]
        script = Path(__file__).with_name(
            "build_readiness_manifest.py"
        )
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            subprocess.run(
                [
                    "python3",
                    str(script),
                    "--candidate-role",
                    "source-head",
                    "--source-head-sha",
                    head,
                    "--qualified",
                    "--output",
                    str(output),
                ],
                cwd=root,
                check=True,
            )
            receipt = json.loads(
                output.read_text(encoding="utf-8")
            )
            self.assertTrue(receipt["identityClosed"])
            self.assertTrue(
                receipt["readinessDimensions"]["sourceQualified"]
            )
            self.assertFalse(
                receipt["readinessDimensions"]["productComposed"]
            )
            self.assertFalse(receipt["productionQualified"])
            self.assertFalse(receipt["mergeReady"])
            self.assertEqual(
                receipt["candidateSha"],
                receipt["qualificationSha"],
            )


if __name__ == "__main__":
    unittest.main()
