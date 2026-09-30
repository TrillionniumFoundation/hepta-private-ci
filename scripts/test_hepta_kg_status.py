from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta_kg_status.py")
SPEC = importlib.util.spec_from_file_location("hepta_kg_status", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load hepta_kg_status.py")
status_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status_module)


def fixture() -> dict:
    return {
        "module": "knowledge.graph",
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productCallerState": "candidate_product_composition",
        "observedAtHead": {"commit": "a" * 40, "tree": "b" * 40},
        "claimBoundary": {
            "nativeSourceMappingComplete": True,
            "implementedOperationMappingComplete": True,
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }


class KnowledgeGraphStatusTests(unittest.TestCase):
    def test_split_status_never_invents_completion_percentage(self) -> None:
        with mock.patch.object(status_module, "git", return_value="c" * 40):
            result = status_module.build_status(fixture())
        self.assertIsNone(result["singleCompletionPercentage"])
        self.assertEqual(
            result["states"]["implementation"]["state"],
            "candidate_source_implemented",
        )
        self.assertEqual(result["states"]["testing"]["qualified"], False)
        self.assertEqual(result["states"]["operatorAcceptance"]["accepted"], False)
        self.assertEqual(result["states"]["activation"]["enabled"], False)
        self.assertEqual(result["states"]["release"]["eligible"], False)

    def test_activation_without_independent_acceptance_fails_closed(self) -> None:
        row = fixture()
        row["claimBoundary"]["activation"] = True
        with mock.patch.object(status_module, "git", return_value="c" * 40):
            with self.assertRaisesRegex(
                status_module.StatusError,
                "activation cannot precede independent acceptance",
            ):
                status_module.build_status(row)

    def test_markdown_exposes_every_delivery_dimension(self) -> None:
        with mock.patch.object(status_module, "git", return_value="c" * 40):
            rendered = status_module.render_markdown(status_module.build_status(fixture()))
        for label in (
            "Implementation",
            "Testing",
            "Integration",
            "Evidence",
            "Operator acceptance",
            "Activation",
            "Release",
        ):
            self.assertIn(label, rendered)


if __name__ == "__main__":
    unittest.main()
