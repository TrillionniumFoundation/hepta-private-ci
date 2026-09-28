import json
import tempfile
import unittest
from pathlib import Path

from scripts.hepta_ci_risk import classify
from scripts.hepta_ci_scope import GROUPS
from scripts.hepta_ci_scope import generated_package_groups


class CiRiskTests(unittest.TestCase):
    def scope(self, **values):
        scope = {group: False for group in GROUPS}
        scope.update(native=False, derived=False, full_repo=False)
        scope.update(values)
        return scope

    def test_risk_order_matches_execution_boundary(self):
        self.assertEqual(classify(self.scope()), "ordinary")
        self.assertEqual(classify(self.scope(inference=True, native=True)), "ordinary")
        self.assertEqual(classify(self.scope(lifecycle=True, native=True)), "stateful")
        self.assertEqual(classify(self.scope(effects=True, native=True)), "effect")
        self.assertEqual(classify(self.scope(full_repo=True)), "release")

    def test_package_groups_are_loaded_only_from_generated_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "docs/modules/CI_MATRIX.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "schema": "hepta.module-ci-matrix.v1",
                        "groups": sorted(GROUPS),
                        "packages": [
                            {
                                "packagePath": "codex-rs/hepta-sample",
                                "packageName": "codex-hepta-sample",
                                "module": "sample.module",
                                "ciGroups": ["lifecycle"],
                                "compileLayer": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                generated_package_groups(root), {"hepta-sample": {"lifecycle"}}
            )


if __name__ == "__main__":
    unittest.main()
