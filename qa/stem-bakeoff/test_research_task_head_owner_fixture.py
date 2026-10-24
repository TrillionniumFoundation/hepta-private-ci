"""No model or real dataset is needed for fixture-boundary negative tests."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import prepare_research_task_head_owner as fixture


def binding(index=0, case="paired"):
    value = {key: fixture.sha(key.encode()) for key in fixture.DIGEST_FIELDS}
    value.update(case_id=case, row_index=index, row_id=fixture.sha(str(index).encode()),
                 image_id=11, caption_id=23, source_caption_image_id=29, present_mask=3,
                 features_sha256=fixture.sha(bytes(fixture.ROW_BYTES)))
    return value


def inventory(rows):
    return fixture.canonical({"schema": "hepta.research-task-head-row-inventory.v1", "rows": rows})


def package(root, rows):
    raw = inventory(rows)
    (root / "inventory.json").write_bytes(raw)
    (root / "features.f32le").write_bytes(bytes(fixture.ROW_BYTES * len(rows)))
    header = fixture.canonical({"feature_identity": {"purpose": "research"},
                                "inventory_sha256": fixture.sha(raw), "inventory_rows": len(rows)})
    (root / "gated-owner.json").write_bytes(header)
    return fixture.sha(header)


class FixtureContractTests(unittest.TestCase):
    def test_producer_identity_binds_helper_bytes_and_retained_plan_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / "sample.py"
            helper.write_bytes(b"# immutable helper\n")
            pin = fixture.sha(helper.read_bytes())
            report = {"plan": {"code_file_sha256": {"sample.py": pin}}}
            with patch.dict(fixture.SOURCE_PINS, {"sample.py": pin}, clear=True), patch.object(fixture, "_helper_source_path", return_value=helper):
                first = fixture._producer_identity(report)
                self.assertEqual(first, fixture._producer_identity(report))
                self.assertEqual(first[0], fixture.sha(fixture.PRODUCER_SCHEME.encode() + b"\0" + fixture.canonical(first[1])))
                report["plan"]["code_file_sha256"]["sample.py"] = "b" * 64
                with self.assertRaisesRegex(ValueError, "retained plan code pin differs"):
                    fixture._producer_identity(report)
                helper.write_bytes(b"# drift\n")
                with self.assertRaisesRegex(ValueError, "fixture helper source drift"):
                    fixture._producer_identity(report)

    def test_duplicate_keys_nonfinite_and_byte_overflow_are_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{}' * 20):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                fixture.strict_json(raw, 30)

    def test_separate_inventory_larger_than_header_limit_is_valid(self):
        rows = [binding(index) for index in range(1280)]
        raw = inventory(rows)
        self.assertGreater(len(raw), fixture.HEADER_BYTES)
        self.assertLess(len(raw), fixture.INVENTORY_BYTES)
        self.assertEqual(fixture.validate_inventory(raw)["rows"], rows)

    def test_inventory_byte_and_row_caps_never_truncate(self):
        for raw in (b" " * (fixture.INVENTORY_BYTES + 1),
                    inventory([binding(index % fixture.MAX_ROWS) for index in range(fixture.MAX_ROWS + 1)])):
            with self.assertRaises(ValueError):
                fixture.validate_inventory(raw)

    def test_masks_and_endpoint_indices_require_exact_integers(self):
        for key, value in (("present_mask", True), ("present_mask", 32),
                           ("row_index", False), ("image_id", True),
                           ("caption_id", 2**64), ("source_caption_image_id", 0)):
            changed = binding()
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                fixture.validate_inventory(inventory([changed]))

    def test_labels_unknown_fields_duplicate_rows_and_bad_digests_are_rejected(self):
        rows = [binding()]
        for change in (lambda row: row.update(label=0), lambda row: row.update(extra="ignored"),
                       lambda row: row.update(features_sha256="0" * 64),
                       lambda row: row.update(row_id="BAD")):
            changed = copy.deepcopy(rows)
            change(changed[0])
            with self.assertRaises(ValueError):
                fixture.validate_inventory(inventory(changed))
        with self.assertRaises(ValueError):
            fixture.validate_inventory(inventory(rows + rows))

    def test_crossed_negative_and_declared_shuffle_are_not_filtered(self):
        rows = [binding(), binding(0, "shuffled_image")]
        self.assertNotEqual(rows[0]["image_id"], rows[0]["source_caption_image_id"])
        self.assertEqual(fixture.validate_inventory(inventory(rows))["rows"], rows)

    def test_reordered_bindings_are_not_silently_sorted(self):
        with self.assertRaisesRegex(ValueError, "inventory row order"):
            fixture.validate_inventory(inventory([binding(1), binding(0)]))

    def test_repeated_source_row_under_another_index_is_rejected(self):
        rows = [binding(0), binding(1)]
        rows[1]["row_id"] = rows[0]["row_id"]
        with self.assertRaisesRegex(ValueError, "duplicate case source row"):
            fixture.validate_inventory(inventory(rows))

    def test_zero_features_with_declared_presence_remain_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding()])
            result = json.loads(fixture.request_for_case(root, "gated", "paired", pin))
            self.assertEqual(result["rows"][0]["binding"], binding())
            self.assertEqual(result["rows"][0]["features"], [0.0] * fixture.WIDTH)
            self.assertNotIn("label", result["rows"][0]["binding"])

    def test_owner_and_inventory_pins_are_external_and_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding()])
            with self.assertRaisesRegex(ValueError, "owner pin mismatch"):
                fixture.request_for_case(root, "gated", "paired", "a" * 64)
            (root / "inventory.json").write_bytes(inventory([binding(1)]))
            with self.assertRaisesRegex(ValueError, "inventory pin mismatch"):
                fixture.request_for_case(root, "gated", "paired", pin)

    def test_drift_in_unselected_case_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding(), binding(0, "missing_text")])
            raw = bytearray((root / "features.f32le").read_bytes())
            raw[-1] = 1
            (root / "features.f32le").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "feature row drift"):
                fixture.request_for_case(root, "gated", "paired", pin)

    def test_nan_features_fail_even_with_recomputed_inventory_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vector = np.zeros(fixture.WIDTH, dtype="<f4")
            vector[0] = np.nan
            row = binding()
            row["features_sha256"] = fixture.sha(vector.tobytes())
            pin = package(root, [row])
            (root / "features.f32le").write_bytes(vector.tobytes())
            with self.assertRaisesRegex(ValueError, "nonfinite feature row"):
                fixture.request_for_case(root, "gated", "paired", pin)

    def test_trailing_payload_and_symbolic_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding()])
            with (root / "features.f32le").open("ab") as stream:
                stream.write(b"x")
            with self.assertRaisesRegex(ValueError, "exact length"):
                fixture.request_for_case(root, "gated", "paired", pin)
            link = root / "link"
            link.symlink_to(root / "inventory.json")
            with self.assertRaisesRegex(ValueError, "regular input file"):
                fixture._bounded_file(link, fixture.INVENTORY_BYTES)

    def test_request_row_and_byte_budgets_reject_without_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding(i) for i in range(513)])
            with self.assertRaisesRegex(ValueError, "request row bound"):
                fixture.request_for_case(root, "gated", "paired", pin)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding()])
            with patch.object(fixture, "REQUEST_BYTES", 100), self.assertRaisesRegex(ValueError, "request byte bound"):
                fixture.request_for_case(root, "gated", "paired", pin)

    def test_missing_case_and_bad_selection_are_not_empty_successes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = package(root, [binding()])
            for mode, case in (("gated", "missing_image"), ("other", "paired"), ("gated", "other")):
                with self.subTest(mode=mode, case=case), self.assertRaises(ValueError):
                    fixture.request_for_case(root, mode, case, pin)


if __name__ == "__main__":
    unittest.main()
