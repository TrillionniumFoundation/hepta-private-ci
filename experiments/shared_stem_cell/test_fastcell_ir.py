"""Contract tests for the research-only FastCell ActionIR boundary."""

import unittest

from fastcell_ir import ActionIR, FastCellRejected, propose_action, validate_action


class FastCellContractTests(unittest.TestCase):
    def test_valid_proposal_is_typed_and_denied(self):
        receipt = propose_action(
            "ui.focus",
            {"app_id": "demo"},
            ("ui.demo",),
            "ui.focus.result.v1",
            "stem-e1-shadow-g1",
        )
        self.assertEqual(receipt["schema"], "hepta.fastcell.validation-receipt.v1")
        self.assertFalse(receipt["compilation_permitted"])
        self.assertFalse(receipt["external_effect_permitted"])
        self.assertEqual(receipt["authority"], "DENY_ALL")

    def test_digest_is_canonical(self):
        a = ActionIR(
            "ui.click", {"x": 1, "y": 2}, ("ui.demo",), "ui.click.result.v1", "g1"
        )
        b = ActionIR(
            "ui.click", {"y": 2, "x": 1}, ("ui.demo",), "ui.click.result.v1", "g1"
        )
        self.assertEqual(a.digest(), b.digest())

    def test_native_material_is_rejected(self):
        with self.assertRaisesRegex(FastCellRejected, "raw execution"):
            validate_action(
                ActionIR(
                    "ui.click",
                    {"native_bytes": "AA=="},
                    ("ui.demo",),
                    "ui.click.result.v1",
                    "g1",
                )
            )

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(FastCellRejected):
            propose_action(
                "process.exec",
                {"argv": ["rm", "-rf", "/"]},
                ("host",),
                "result.v1",
                "g1",
            )

    def test_authority_cannot_be_promoted_by_the_cell(self):
        with self.assertRaises(FastCellRejected):
            validate_action(
                ActionIR(
                    "fs.read_bounded",
                    {"path": "fixture.txt"},
                    ("research.fixture",),
                    "fs.result.v1",
                    "g1",
                    authority="ALLOW",
                )
            )


if __name__ == "__main__":
    unittest.main()
