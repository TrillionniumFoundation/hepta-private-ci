from pathlib import Path
import unittest


class LegacyProductPathTests(unittest.TestCase):
    def test_v2_product_package_does_not_import_legacy_module(self):
        root = Path(__file__).resolve().parent / "control_engineering_v2"
        offenders = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "hepta_engineering_control" in text:
                offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            "v2 product code must not depend on hepta_engineering_control legacy primitives",
        )


if __name__ == "__main__":
    unittest.main()
