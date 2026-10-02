"""Federation's qualification companions must describe its registered source roots."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class FederationSourceRootFidelityTests(unittest.TestCase):
    def test_companions_match_canonical_roots(self):
        bindings = json.loads((ROOT / "docs/modules/SOURCE_BINDINGS.json").read_text())
        expected = next(
            row["declaredRoots"]
            for row in bindings["bindings"]
            if row["module"] == "memory.federation"
        )
        for filename, collection in [
            ("DETAILS.json", "rows"),
            ("IMPLEMENTATION_PROFILES.json", "modules"),
        ]:
            with self.subTest(companion=filename):
                document = json.loads(
                    (ROOT / "qualification/module-execution-dossiers" / filename).read_text()
                )
                actual = next(
                    row["declaredRoots"]
                    for row in document[collection]
                    if row["module"] == "memory.federation"
                )
                self.assertEqual(actual, expected)
                for source_root in actual:
                    self.assertTrue((ROOT / source_root).is_dir(), source_root)


if __name__ == "__main__":
    unittest.main()
