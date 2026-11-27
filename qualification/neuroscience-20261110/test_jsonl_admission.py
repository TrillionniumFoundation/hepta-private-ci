"""Read-only JSONL ingress limits; synthetic tests only, not model evidence."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from study import ARMS, ContractError, main
from test_study import row


class JsonlAdmissionTests(unittest.TestCase):
    def invoke(self, content):
        with tempfile.TemporaryDirectory(prefix="hpca-jsonl-bound-") as td:
            filepath = Path(td) / "trials.jsonl"
            filepath.write_text(content, encoding="utf-8")
            out = io.StringIO()
            with patch.object(sys, "argv", ["study.py", "--trials", str(filepath)]):
                with contextlib.redirect_stdout(out):
                    main()
            return out.getvalue()

    def test_empty_line_flood_cannot_skip_input_budget(self):
        with self.assertRaisesRegex(ContractError, "raw trial JSONL input exceeds size limit"):
            self.invoke("\n" * 400_001)

    def test_one_oversized_line_rejected_before_parse(self):
        with self.assertRaisesRegex(ContractError, "trial JSONL line exceeds character limit"):
            self.invoke("{" + (" " * 65_537) + "}\n")

    def test_non_object_row_returns_contract_error(self):
        with self.assertRaisesRegex(ContractError, "invalid trial JSONL row"):
            self.invoke("[]\n")

    def test_small_valid_four_arm_file_keeps_existing_report(self):
        payload = "".join(json.dumps(asdict(row(arm))) + "\n" for arm in ARMS)
        report = json.loads(self.invoke(payload))
        self.assertEqual(report["blocks"], 1)
        self.assertEqual(report["seed_clusters"], 1)
        self.assertEqual(report["research_posture"], "HOLD_NO_PRODUCTION_AUTHORITY")
        self.assertEqual(report["qualification"], "RECEIPTS_NOT_EXTERNALLY_ATTESTED")


if __name__ == "__main__":
    unittest.main()
