#!/usr/bin/env python3
"""Executable regressions for source-only status projection; no native pass claims."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "control_runtime_state", Path(__file__).with_name("hepta-control-runtime-state.py")
)
assert SPEC is not None and SPEC.loader is not None
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


def row():
    return {
        "module": "control.runtime",
        "sourceBase": {"commit": "1" * 40, "tree": "2" * 40},
        "observedAtHead": {"commit": "3" * 40, "tree": "4" * 40},
        "sourceObjects": [{"path": "codex-rs/hepta-control-plane/src/lib.rs", "object": "5" * 40}],
        "componentMaturity": {
            name: {"sourceState": "source_implemented_candidate", "productState": "not_composed", "qualificationState": "not_executed"}
            for name in ("planner", "organHost", "runtimeRegistry", "embodimentReference", "readOnlyAgentd", "plannerStore")
        },
        "productCallerState": "source_composed_candidate",
        "globalPlannerProductCallerState": "not_composed",
        "productionWriterState": "not_composed",
        "qualificationState": {"exactHead": "not_executed", "syntheticMerge": "not_executed"},
        "repositoryControlledGaps": ["Exact native qualification remains required."],
        "externalEvidenceGates": ["Independent acceptance is not issued by the source author."],
        "claimBoundary": {name: False for name in STATE.CLAIMS},
    }


class ProjectionTests(unittest.TestCase):
    def test_historical_provenance_and_partial_product_composition_are_preserved(self):
        source = row()
        result = STATE.project(source)
        self.assertEqual(result["sourceBase"], source["sourceBase"])
        self.assertEqual(result["readOnlyProductCallerState"], "source_composed_candidate")
        self.assertEqual(result["globalPlannerProductCallerState"], "not_composed")
        self.assertFalse(any(result["claimBoundary"].values()))

    def test_wrong_module_and_missing_component_are_rejected(self):
        for change in ("module", "component"):
            source = row()
            if change == "module":
                source["module"] = "another.module"
            else:
                del source["componentMaturity"]["plannerStore"]
            with self.assertRaises(ValueError):
                STATE.project(source)

    def test_execution_claims_cannot_be_issued_by_projection(self):
        for name in STATE.CLAIMS:
            for location in ("top", "boundary"):
                source = row()
                target = source if location == "top" else source["claimBoundary"]
                target[name] = True
                with self.subTest(name=name, location=location), self.assertRaises(ValueError):
                    STATE.project(source)

    def test_strings_are_not_boolean_evidence(self):
        source = row()
        source["claimBoundary"]["activation"] = "false"
        with self.assertRaises(ValueError):
            STATE.project(source)

    def test_component_pass_cannot_be_manufactured(self):
        source = row()
        source["componentMaturity"]["planner"]["qualificationState"] = "passed"
        with self.assertRaises(ValueError):
            STATE.project(source)

    def test_duplicate_and_self_referential_observations_are_rejected(self):
        source = row()
        source["sourceObjects"] *= 2
        with self.assertRaises(ValueError):
            STATE.project(source)
        for path in (STATE.MAP, STATE.STATE, STATE.PRODUCT):
            source = row()
            source["sourceObjects"][0]["path"] = path
            with self.assertRaises(ValueError):
                STATE.project(source)

    def test_path_escape_and_invalid_object_are_rejected(self):
        for field, value in (("path", "../secret"), ("path", "/absolute"), ("path", "a//b"), ("object", "main")):
            source = row()
            source["sourceObjects"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                STATE.project(source)

    def test_observation_order_does_not_change_digest(self):
        source = row()
        source["sourceObjects"].append({"path": "another.rs", "object": "6" * 40})
        reverse = copy.deepcopy(source)
        reverse["sourceObjects"].reverse()
        self.assertEqual(STATE.project(source)["sourceObjectSetSha256"], STATE.project(reverse)["sourceObjectSetSha256"])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"module":"control.runtime","module":"other"}', object_pairs_hook=STATE.unique_keys)

    def test_check_does_not_repair_a_changed_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / STATE.MAP).parent.mkdir(parents=True)
            (root / STATE.MAP).write_text(STATE.encode(row()))
            self.assertEqual(STATE.main(["--root", str(root), "--write"]), 0)
            self.assertEqual(STATE.main(["--root", str(root), "--check"]), 0)
            target = root / STATE.STATE
            target.write_text("deliberate drift\n")
            with self.assertRaises(ValueError):
                STATE.main(["--root", str(root), "--check"])
            self.assertEqual(target.read_text(), "deliberate drift\n")

    def test_source_verification_rejects_dirty_and_hidden_index_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("config", "user.name", "Control runtime test")
            git("config", "user.email", "control-runtime-test@example.invalid")
            source = row()
            path = source["sourceObjects"][0]["path"]
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text("pub fn marker() {}\n")
            git("add", ".")
            git("commit", "-qm", "fixture")
            identity = {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}
            source["sourceBase"] = identity
            source["observedAtHead"] = identity
            source["sourceObjects"][0]["object"] = git("rev-parse", f"HEAD:{path}")
            STATE.verify_source(root, source)
            target.write_text("pub fn changed() {}\n")
            with self.assertRaises(ValueError):
                STATE.verify_source(root, source)
            git("checkout", "--", path)
            git("update-index", "--assume-unchanged", path)
            with self.assertRaises(ValueError):
                STATE.verify_source(root, source)


if __name__ == "__main__":
    unittest.main()
