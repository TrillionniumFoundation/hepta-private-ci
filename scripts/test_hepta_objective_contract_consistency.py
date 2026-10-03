from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-objective-contract-consistency.py")
SPEC = importlib.util.spec_from_file_location("objective_contract_consistency", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class ObjectiveContractConsistencyTests(unittest.TestCase):
    def test_extract_product_path_requires_one_ordered_pair(self) -> None:
        value = f"before{subject.BEGIN}canonical{subject.END}after"
        self.assertEqual(subject.extract_product_path(value), "canonical")
        for malformed in (
            subject.BEGIN,
            subject.END,
            subject.END + subject.BEGIN,
            subject.BEGIN + subject.BEGIN + subject.END,
        ):
            with self.assertRaises(subject.ConsistencyError):
                subject.extract_product_path(malformed)

    def test_load_json_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with mock.patch.object(subject, "ROOT", Path(directory)):
                with self.assertRaisesRegex(
                    subject.ConsistencyError, "duplicate JSON key"
                ):
                    subject.load_json(path)

    def test_registry_requires_exact_ordered_error_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "errors.json"
            rows = [{"code": f"OBJ-E00{index}"} for index in range(1, 10)]
            path.write_text(
                json.dumps(
                    {
                        "schema": "hepta.objective-error-registry.v1",
                        "owner": "objective.compiler",
                        "errors": rows,
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(subject, "ROOT", root),
                mock.patch.object(subject, "ERRORS", path),
            ):
                subject.verify_registry()
                rows[-1]["code"] = "OBJ-E008"
                path.write_text(
                    json.dumps(
                        {
                            "schema": "hepta.objective-error-registry.v1",
                            "owner": "objective.compiler",
                            "errors": rows,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    subject.ConsistencyError, "inventory drifted"
                ):
                    subject.verify_registry()

    def test_identity_requires_both_exact_values_and_clean_checkout(self) -> None:
        with mock.patch.object(
            subject,
            "git",
            side_effect=("a" * 40, "b" * 40, ""),
        ):
            subject.verify_identity("a" * 40, "b" * 40)
        with self.assertRaisesRegex(subject.ConsistencyError, "full lowercase commit"):
            subject.verify_identity("short", "b" * 40)

    def test_embedded_self_test(self) -> None:
        subject.self_test()


if __name__ == "__main__":
    unittest.main()
