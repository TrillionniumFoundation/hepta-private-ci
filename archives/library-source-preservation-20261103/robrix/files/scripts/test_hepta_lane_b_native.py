"""Real-Git Lane-B regressions using the existing strict native fixture."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_hepta_ui_native_map_adapter as fixtures


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_script("hepta-lane-b-path-guard")
truth_guard = load_script("hepta-lane-b-truth")


class LaneBNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeMapAdapterTests(
            "test_strict_checker_is_reused_and_v3_maps_stay_separate"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.alpha = copy.deepcopy(self.fixture.alpha)
        self.alpha.update(
            repositoryControlledGaps=[],
            externalEvidenceGates=["unobserved execution"],
            stateOwnerDisposition="alpha owns fixture state",
            terminalObserverDisposition="No executed evidence",
        )
        self.alpha["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = (
            False
        )
        self.alpha["operations"][0].update(
            tests=[{"path": "src/alpha/tests.rs", "command": "fixture test command"}],
            sourceSemantics="fixture source only",
        )
        self.fixture.write("src/alpha/tests.rs", "// fixture test source\n")
        self.fixture.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", self.alpha)
        for module in ("alpha", "ui.native"):
            for path in (
                f"docs/modules/{module}/TECHNICAL.md",
                f"qualification/module-execution-dossiers/detail/{module}.md",
            ):
                self.fixture.write(path, module + " source navigation\n")
        self.truth = json.loads(truth_guard.TRUTH.read_text())
        self.truth["sourceBase"] = self.fixture.source
        self.truth["modules"] = [
            {
                "module": row["module"],
                "mapPath": f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json",
                "operationIds": [item["operation"] for item in row["operations"]],
            }
            for row in (self.fixture.row, self.alpha)
        ]
        self.truth["moduleOrder"] = ["ui.native", "alpha"]
        self.truth["operationCount"] = 7
        self.fixture.write(
            "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json", self.truth
        )
        self.base = self.fixture.commit("Lane-B fixture navigation")
        for name, value in (
            ("ROOT", self.root),
            ("MODULES", self.truth["moduleOrder"]),
            ("OPERATION_COUNT", 7),
            (
                "OPS",
                {
                    entry["module"]: entry["operationIds"]
                    for entry in self.truth["modules"]
                },
            ),
        ):
            binding = patch.object(truth_guard, name, value)
            binding.start()
            self.addCleanup(binding.stop)

    def maps(self):
        return [
            truth_guard.load(self.root / entry["mapPath"])
            for entry in self.truth["modules"]
        ]

    def verify_both(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            guard.verify(self.root)
        maps = truth_guard.module_maps(self.truth)
        self.assertEqual(truth_guard.verify_truth(self.truth, maps), (7, 1))
        return json.loads(output.getvalue()), maps

    def reject_both(self, message):
        with self.assertRaisesRegex(guard.Invalid, message):
            guard.verify(self.root)
        with self.assertRaisesRegex(truth_guard.Invalid, message):
            truth_guard.verify_truth(self.truth, self.maps())

    def save(self, row):
        self.fixture.write(f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json", row)
        self.fixture.commit("mutated fixture map")

    def restore(self):
        self.fixture.git("reset", "--hard", self.base["commit"])

    def test_actual_v6_adapter_preserves_v3_checks_without_mutating_maps(self):
        original = self.maps()
        with patch.object(
            fixtures.adapter.native,
            "check_repository",
            wraps=fixtures.adapter.native.check_repository,
        ) as strict:
            result, maps = self.verify_both()
        self.assertEqual(strict.call_count, 3)
        self.assertEqual(maps, original)
        self.assertEqual(result["operations"], 7)
        self.assertEqual(result["testBindings"], 1)
        self.assertEqual(
            result["nativeSchemaAdapters"][0]["ownedRoots"], ["apps/hepta-native"]
        )
        self.assertFalse(result["nativeSchemaAdapters"][0]["qualificationEstablished"])
        projection = truth_guard.trace_projection(self.truth, maps)
        self.assertFalse(projection["claimBoundary"]["testPathCoverageComplete"])
        for entry in projection["entries"][:6]:
            self.assertEqual(entry["testBindingScope"], "module")
            self.assertNotIn("tests", entry)
            self.assertFalse(entry["qualificationEstablished"])
        self.assertEqual(
            projection["entries"][-1]["tests"], self.alpha["operations"][0]["tests"]
        )

    def test_native_schema_and_foreign_v6_are_never_fallbacks(self):
        for schema, version in (
            ("hepta.module-implementation-map.v6", True),
            ("hepta.module-implementation-map.v6", "6"),
            ("hepta.module-implementation-map.v3", 3),
            ("hepta.module-implementation-map.v7", 7),
        ):
            with self.subTest(schema=schema, version=version):
                row = copy.deepcopy(self.fixture.row)
                row.update(schema=schema, schemaVersion=version)
                self.save(row)
                self.reject_both("requires map schema v6")
                self.restore()
        row = copy.deepcopy(self.alpha)
        row.update(schema="hepta.module-implementation-map.v6", schemaVersion=6)
        self.save(row)
        self.reject_both("requires map schema v3")

    def test_native_entrypoints_claims_and_references_stay_strict(self):
        for mutation, message in (
            (lambda row: row["operations"].pop(), "operation inventory"),
            (
                lambda row: row["operations"][0].update(
                    entrypoint="src/alpha/lib.rs::calculate"
                ),
                "entrypoint identity",
            ),
            (lambda row: row.update(releaseAuthorized=True), "claim promoted"),
            (
                lambda row: row.update(testSurfaces=["apps/hepta-native/missing.rs"]),
                "missing native test reference",
            ),
        ):
            row = copy.deepcopy(self.fixture.row)
            mutation(row)
            self.save(row)
            self.reject_both(message)
            self.restore()

    def test_native_owner_cannot_expand_to_dependency(self):
        modules = copy.deepcopy(self.fixture.modules)
        modules[0]["rootBindings"] = [{"path": "codex-rs/hepta-native-gateway"}]
        self.fixture.write("docs/modules/MODULES.json", {"modules": modules})
        self.fixture.commit("changed registered owner")
        self.reject_both("canonical owned roots changed")

    def test_frozen_native_source_drift_and_nonancestor_still_reject(self):
        path = self.root / "apps/hepta-native/src/runtime.rs"
        path.write_text(path.read_text() + "\n// committed drift\n")
        self.fixture.commit("changed frozen source")
        self.reject_both("after the frozen source")
        self.restore()
        self.fixture.reanchor(self.fixture.sibling_anchor())
        self.fixture.commit("foreign native provenance")
        self.reject_both("merge-base")

    def test_v3_anchor_and_test_bindings_still_reject(self):
        for field, value, message in (
            ("nativeSymbol", "nonexistent", "missing symbol"),
            ("sourcePath", "apps/hepta-native/src/runtime.rs", "owner-root escape"),
            ("tests", [], "tests"),
        ):
            row = copy.deepcopy(self.alpha)
            row["operations"][0][field] = value
            self.save(row)
            self.reject_both(message)
            self.restore()

    def test_registered_cross_lane_delegate_still_requires_actual_owner(self):
        modules = copy.deepcopy(self.fixture.modules)
        modules.append({"id": "beta", "rootBindings": [{"path": "src/beta"}]})
        self.fixture.write("docs/modules/MODULES.json", {"modules": modules})
        self.fixture.write("src/beta/lib.rs", "pub fn observe() {}\n")
        row = copy.deepcopy(self.alpha)
        delegate = {
            "role": "delegate",
            "path": "src/beta/lib.rs",
            "symbol": "observe",
            "buildTarget": "beta",
            "ownerModule": "beta",
        }
        row["operations"][0]["delegatedCallees"] = [delegate]
        self.save(row)
        self.verify_both()
        for owner, message in (
            ("unknown", "unregistered delegated owner"),
            ("ui.native", "delegate-root escape"),
        ):
            delegate["ownerModule"] = owner
            self.save(row)
            self.reject_both(message)


if __name__ == "__main__":
    unittest.main()
