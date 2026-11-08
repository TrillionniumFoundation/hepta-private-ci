"""Serial acquisition handoffs retain successful and failed material spending."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .material_budget import INCREMENT, SCHEMA, advance_material_budget


class MaterialBudgetContracts(unittest.TestCase):
    def test_increment_chain_preserves_failed_spending_and_rejects_resets(self):
        anchor = {"cumulative_body_bytes": 17669796, "shared_cap_bytes": 26214400}
        anchor_pin = hashlib.sha256(b"explicit image transfer fixture").hexdigest()
        body_sha = hashlib.sha256(b"x" * 23181).hexdigest()
        body = {"bytes": 23181, "sha256": body_sha}
        attempt = {
            "status": "completed",
            "bytes_read": 23181,
            "sha256": body_sha,
            "body": body,
        }

        def index(receipts):
            previous, spent, entries = anchor_pin, anchor["cumulative_body_bytes"], []
            for row in receipts:
                receipt = {
                    "schema": INCREMENT,
                    "status": "completed",
                    "prior_receipt_sha256": previous,
                    "prior_body_bytes": spent,
                    "new_body_bytes": 23181,
                    "cumulative_body_bytes": spent + 23181,
                    "shared_cap_bytes": anchor["shared_cap_bytes"],
                    "reservation_bytes": 262144,
                    "attempts": [attempt],
                }
                receipt.update(row)
                raw = json.dumps(receipt, sort_keys=True) + "\n"
                previous = hashlib.sha256(raw.encode()).hexdigest()
                entries.append(
                    {
                        "receipt_utf8": raw,
                        "sha256": previous,
                        "bytes": len(raw.encode()),
                    }
                )
                spent = receipt["cumulative_body_bytes"]
            return {
                "schema": SCHEMA,
                "anchor_sha256": anchor_pin,
                "receipts": entries,
                "head_receipt_sha256": previous,
                "cumulative_body_bytes": spent,
            }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"

            def check(value, expected_pin=None):
                data = (json.dumps(value, sort_keys=True) + "\n").encode()
                path.write_bytes(data)
                return advance_material_budget(
                    anchor,
                    anchor_pin,
                    path,
                    expected_pin or hashlib.sha256(data).hexdigest(),
                )

            good = index([{}, {"status": "failed"}])
            spent, head, raw = check(good)
            self.assertEqual(
                (spent, head, raw),
                (
                    17716158,
                    good["head_receipt_sha256"],
                    path.read_bytes(),
                ),
            )
            self.assertEqual(check(index([]))[:2], (17669796, anchor_pin))
            variants = [
                {"status": "in_progress"},
                {"prior_receipt_sha256": "0" * 64},
                {"prior_body_bytes": 11064483},
                {"new_body_bytes": True},
                {"new_body_bytes": 0},
                {"shared_cap_bytes": 26214401},
                {"reservation_bytes": 26214400},
                {"attempts": [{"status": "started", "bytes_read": 23181}]},
                {"attempts": [{"status": "failed", "bytes_read": 7}]},
                {"attempts": [dict(attempt, body=None)]},
                {"attempts": [dict(attempt, body=dict(body, bytes=0))]},
                {"attempts": [dict(attempt, body=dict(body, bytes=True))]},
                {"attempts": [dict(attempt, sha256="0" * 64)]},
                {"attempts": [dict(attempt, body=dict(body, sha256="not-a-hash"))]},
                {
                    "new_body_bytes": 0,
                    "cumulative_body_bytes": 17669796,
                    "attempts": [dict(attempt, bytes_read=0)],
                },
            ]
            for change in variants:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    check(index([change]))
            for field, value in (
                ("anchor_sha256", "0" * 64),
                ("head_receipt_sha256", "0" * 64),
                ("cumulative_body_bytes", 17669796),
            ):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    check(dict(good, **{field: value}))
            corrupt = copy.deepcopy(good)
            corrupt["receipts"][0]["receipt_utf8"] += " "
            with self.assertRaises(ValueError):
                check(corrupt)
            with self.assertRaisesRegex(ValueError, "index hash"):
                check(good, "0" * 64)


if __name__ == "__main__":
    unittest.main()
