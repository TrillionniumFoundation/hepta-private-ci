#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "hepta-implementation-maps.py"
spec = importlib.util.spec_from_file_location("hepta_impl_maps_under_test", SCRIPT)
assert spec and spec.loader
MOD = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MOD
spec.loader.exec_module(MOD)


class SourceBaseSelectionTests(unittest.TestCase):
    def test_maps_only_wrapper_binds_parent(self):
        calls = {
            ("rev-parse", "HEAD"): "wrapper",
            ("show", "-s", "--format=%P", "wrapper"): "source",
            ("diff", "--name-only", "source", "wrapper"):
                "docs/modules/a/IMPLEMENTATION_MAP.json\n"
                "scripts/hepta-implementation-maps.py\n"
                "scripts/test_hepta_implementation_maps.py",
            ("rev-parse", "source"): "source",
            ("rev-parse", "source^{tree}"): "source-tree",
        }
        with mock.patch.object(MOD, "git", side_effect=lambda *args: calls[args]):
            self.assertEqual(
                MOD.current_source_base(),
                {"commit": "source", "tree": "source-tree"},
            )

    def test_code_change_cannot_hide_behind_wrapper(self):
        calls = {
            ("rev-parse", "HEAD"): "head",
            ("show", "-s", "--format=%P", "head"): "parent",
            ("diff", "--name-only", "parent", "head"):
                "codex-rs/hepta-bao-adapter/src/lib.rs",
            ("rev-parse", "head"): "head",
            ("rev-parse", "head^{tree}"): "head-tree",
        }
        with mock.patch.object(MOD, "git", side_effect=lambda *args: calls[args]):
            self.assertEqual(
                MOD.current_source_base(),
                {"commit": "head", "tree": "head-tree"},
            )

    def test_synthetic_merge_uses_ordered_source_wrapper_parent(self):
        calls = {
            ("rev-parse", "HEAD"): "merge",
            ("show", "-s", "--format=%P", "merge"): "base wrapper",
            ("show", "-s", "--format=%P", "wrapper"): "source",
            ("diff", "--name-only", "source", "wrapper"):
                "docs/modules/a/IMPLEMENTATION_MAP.json",
            ("rev-parse", "source"): "source",
            ("rev-parse", "source^{tree}"): "source-tree",
        }
        with mock.patch.object(MOD, "git", side_effect=lambda *args: calls[args]):
            self.assertEqual(
                MOD.current_source_base(),
                {"commit": "source", "tree": "source-tree"},
            )


class VerifyEqualityTests(unittest.TestCase):
    def test_verify_rejects_uniformly_stale_maps(self):
        expected = {"commit": "b" * 40, "tree": "c" * 40}
        stale = {"commit": "a" * 40, "tree": "d" * 40}
        module = {
            "id": "a",
            "owner": "owner",
            "deputy": "deputy",
            "technicalDocument": "docs/modules/a/TECHNICAL.md",
            "rootBindings": [{"path": "root"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "root").mkdir()
            path = root / "docs/modules/a/IMPLEMENTATION_MAP.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema": "hepta.module-implementation-map.v3",
                "schemaVersion": 3,
                "sourceBase": stale,
                "laneId": "LANE",
                "module": "a",
                "owner": "owner",
                "deputy": "deputy",
                "technicalGuide": "docs/modules/a/TECHNICAL.md",
                "declaredRoots": ["root"],
                "resolvedRoots": ["root"],
                "sourceRootPresent": True,
                "productionImplementation": False,
                "operations": [{
                    "operation": "op",
                    "nativeSymbol": "symbol",
                    "sourcePath": None,
                }],
                "claimBoundary": {},
            }), encoding="utf-8")

            def load(rel):
                if rel == "docs/modules/MODULES.json":
                    return {"modules": [module]}
                if rel == "docs/readiness/READINESS.json":
                    return {"implementationLanes": [{"id": "LANE", "modules": ["a"]}]}
                raise AssertionError(rel)

            with (
                mock.patch.object(MOD, "ROOT", root),
                mock.patch.object(MOD, "load", side_effect=load),
                mock.patch.object(MOD, "current_source_base", return_value=expected),
                mock.patch.object(MOD, "resolve_source_roots", return_value=["root"]),
            ):
                with self.assertRaisesRegex(SystemExit, "current source"):
                    MOD.verify()


if __name__ == "__main__":
    unittest.main()
