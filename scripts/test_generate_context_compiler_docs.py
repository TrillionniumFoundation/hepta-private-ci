#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

GENERATOR = Path(__file__).with_name("generate-context-compiler-docs.py")
SPEC = importlib.util.spec_from_file_location("context_compiler_docs", GENERATOR)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ContextCompilerDocsGeneratorTests(unittest.TestCase):
    def test_generated_block_is_idempotent(self) -> None:
        manifest = {
            "schema": "hepta.context-compiler-current-state.v1",
            "module": "context.compiler",
            "provenance": {
                "generatedFrom": "state.json",
                "generator": "generator.py",
                "sourceBaseMode": "strict",
                "sourceBase": {"commit": "a" * 40, "tree": "b" * 40},
                "qualificationIdentityRule": "receipt only.",
            },
            "status": {
                "coreImplementation": "complete",
                "productComposition": "partial",
                "v2ProviderClosure": "incomplete",
                "currentHeadQualification": "absent",
            },
            "statusMeaning": {
                "coreImplementation": "core",
                "productComposition": "partial",
                "v2ProviderClosure": "open",
                "currentHeadQualification": "none",
            },
            "byteIdentities": [],
            "sequence": [
                {"id": 1, "actor": "A", "action": "start"},
                {"id": 2, "actor": "B", "action": "finish"},
            ],
            "requiredTokenizerBinding": [],
            "serializerCoverage": {"allowedSegmentKinds": [], "requirements": []},
            "repositoryControlledGaps": [],
        }
        block = module.render_technical(manifest)
        once = module.replace_block("# Guide\n\nbody\n", block, heading="guide")
        twice = module.replace_block(once, block, heading="guide")
        self.assertEqual(once, twice)
        self.assertEqual(once.count(module.BEGIN), 1)
        self.assertEqual(once.count(module.END), 1)

    def test_map_states_are_fail_closed(self) -> None:
        manifest = json.loads((module.REPO_ROOT / "docs/modules/context.compiler/CURRENT_STATE.json").read_text())
        rendered = json.loads(module.render_map(json.dumps({"claimBoundary": {}}), manifest))
        self.assertTrue(rendered["productionImplementation"])
        self.assertFalse(rendered["claimBoundary"]["productExecutionProved"])
        self.assertFalse(rendered["claimBoundary"]["activation"])
        self.assertEqual(rendered["generatedState"]["v2ProviderClosure"], "incomplete")


if __name__ == "__main__":
    unittest.main()
