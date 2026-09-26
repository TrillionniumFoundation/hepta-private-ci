#!/usr/bin/env python3
"""Real Git regressions for Lane D scope without weakening owner contracts."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-lane-d-semantic-conformance.py")
SPEC = importlib.util.spec_from_file_location("lane_d_scope", SCRIPT)
assert SPEC and SPEC.loader
LANE_D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LANE_D)


class LaneDChangeScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        self.root.mkdir()
        self.event_path = Path(directory.name) / "event.json"
        self.git("init", "-q")
        self.git("config", "user.name", "Lane D regression")
        self.git("config", "user.email", "lane-d-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        for module, crate in zip(
            LANE_D.MODULES, ("hepta-objective", "hepta-ndu", "hepta-control-plane")
        ):
            root = f"codex-rs/{crate}"
            self.write(f"{root}/src/component.rs", "pub fn run() {}\n")
            self.write(f"{root}/src/component_tests.rs", "fn run_regression() {}\n")
            self.write(
                LANE_D.MAPS[module],
                json.dumps(
                    {
                        "module": module,
                        "authorityDelta": "none",
                        "sourceRoot": root,
                        "operations": [
                            {
                                "sourcePath": f"{root}/src/component.rs",
                                "nativeSymbol": "crate::run",
                                "tests": [
                                    {
                                        "path": f"{root}/src/component_tests.rs",
                                        "symbol": "run_regression",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            )
        initial = self.commit("owner contracts")
        self.git("switch", "-q", "-c", "old-side")
        self.write("other-lane/old.txt", "historical")
        self.commit("old unrelated lane")
        self.git("switch", "-q", "-c", "target", initial)
        self.write("target.txt", "target")
        self.commit("old target change")
        self.git("merge", "--no-ff", "--no-edit", "old-side")
        self.base = self.git("rev-parse", "HEAD")
        self.git("switch", "-q", "-c", "candidate")
        self.write("codex-rs/hepta-ndu/src/new_policy.rs", "pub fn new_policy() {}")
        self.write("other-lane/current.txt", "parallel lane")
        self.head = self.commit("current multi-lane source")
        self.event = {
            "pull_request": {"base": {"sha": self.base}, "head": {"sha": self.head}}
        }

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=True
        ).stdout.strip()

    def write(self, path: str, contents: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def check(self, base: str | None = None) -> dict:
        self.event_path.write_text(json.dumps(self.event), encoding="utf-8")
        stdout = io.StringIO()
        with (
            mock.patch.object(LANE_D, "ROOT", self.root),
            mock.patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_PATH": str(self.event_path),
                    "GITHUB_EVENT_NAME": "pull_request",
                },
                clear=True,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(
                LANE_D.verify_changes(self.base if base is None else base), 0
            )
        return json.loads(stdout.getvalue())

    def test_current_multi_lane_delta_keeps_owner_scope_and_exact_identity(
        self,
    ) -> None:
        result = self.check()
        self.assertEqual(
            result["laneDChangedPaths"], ["codex-rs/hepta-ndu/src/new_policy.rs"]
        )
        self.assertEqual(result["otherLaneChangedPaths"], 1)
        self.assertEqual(result["sourceHead"], self.head)
        self.assertEqual(result["baseHead"], self.base)
        self.assertEqual(result["ownerMapsVerified"], list(LANE_D.MODULES))
        self.assertFalse(result["authorityGranted"])

    def test_target_only_updates_after_divergence_do_not_enter_source_delta(
        self,
    ) -> None:
        self.git("switch", "-q", "target")
        self.write("codex-rs/hepta-objective/src/target_only.rs", "target-only")
        advanced = self.commit("target advances independently")
        self.git("switch", "-q", "candidate")
        self.event["pull_request"]["base"]["sha"] = advanced
        self.assertEqual(
            self.check(advanced)["laneDChangedPaths"],
            ["codex-rs/hepta-ndu/src/new_policy.rs"],
        )

    def test_other_lane_only_pr_still_checks_all_d_owner_maps(self) -> None:
        self.git("checkout", "--detach", self.base)
        self.write("other-lane/only.txt", "foreign change")
        self.event["pull_request"]["head"]["sha"] = self.commit("other lane only")
        self.assertEqual(self.check()["changedPaths"], 0)
        source = self.root / "codex-rs/hepta-objective/src/component.rs"
        source.unlink()
        self.event["pull_request"]["head"]["sha"] = self.commit(
            "registered owner removed"
        )
        with self.assertRaisesRegex(SystemExit, "missing source"):
            self.check()

    def test_stale_base_or_head_and_dirty_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "base differs"):
            self.check(self.head)
        self.event["pull_request"]["head"]["sha"] = self.base
        with self.assertRaisesRegex(SystemExit, "checkout is not"):
            self.check()
        self.event["pull_request"]["head"]["sha"] = self.head
        self.write("codex-rs/hepta-objective/src/component.rs", "uncommitted")
        with self.assertRaises(subprocess.CalledProcessError):
            self.check()

    def test_d_native_symbol_failure_is_not_hidden_by_scope_filter(self) -> None:
        self.write("codex-rs/hepta-ndu/src/component.rs", "pub fn renamed() {}")
        self.event["pull_request"]["head"]["sha"] = self.commit("break owner contract")
        with self.assertRaisesRegex(SystemExit, "missing native symbol"):
            self.check()

    def test_map_cannot_reassign_source_outside_declared_owner(self) -> None:
        path = LANE_D.MAPS["objective.compiler"]
        mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
        self.write("other-lane/impostor.rs", "pub fn run() {}")
        mapping["operations"][0]["sourcePath"] = "other-lane/impostor.rs"
        self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("escape owner")
        with self.assertRaisesRegex(SystemExit, "source escapes owner root"):
            self.check()
        mapping["sourceRoot"] = "../outside"
        self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("escape root")
        with self.assertRaisesRegex(SystemExit, "invalid owner root"):
            self.check()

    def test_canonical_root_arrays_preserve_exact_owner_scope(self) -> None:
        for module in LANE_D.MODULES:
            path = LANE_D.MAPS[module]
            mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
            roots = [mapping["sourceRoot"]]
            mapping.update(sourceRoot=roots, declaredRoots=roots, resolvedRoots=roots)
            self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("canonical root arrays")
        result = self.check()
        self.assertEqual(result["ownerMapsVerified"], list(LANE_D.MODULES))
        self.assertIn(
            "codex-rs/hepta-ndu/src/new_policy.rs", result["laneDChangedPaths"]
        )
        self.assertFalse(result["authorityGranted"])

    def test_root_arrays_reject_empty_duplicate_invalid_and_inconsistent_roots(
        self,
    ) -> None:
        path = LANE_D.MAPS["objective.compiler"]
        mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
        root = mapping["sourceRoot"]
        for roots in (
            [],
            [root, root],
            [""],
            [None],
            ["."],
            ["../outside"],
            [str(self.root)],
        ):
            with (
                self.subTest(roots=roots),
                mock.patch.object(LANE_D, "ROOT", self.root),
            ):
                self.write(path, json.dumps({**mapping, "sourceRoot": roots}))
                with self.assertRaisesRegex(SystemExit, "invalid owner root"):
                    LANE_D.verify_map("objective.compiler")
        for key in ("declaredRoots", "resolvedRoots"):
            with self.subTest(key=key), mock.patch.object(LANE_D, "ROOT", self.root):
                self.write(
                    path,
                    json.dumps({**mapping, "sourceRoot": [root], key: ["other-lane"]}),
                )
                with self.assertRaisesRegex(SystemExit, "owner root aliases differ"):
                    LANE_D.verify_map("objective.compiler")

    def test_root_arrays_still_reject_source_escape_and_missing_symbols(self) -> None:
        path = LANE_D.MAPS["objective.compiler"]
        mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
        mapping["sourceRoot"] = [mapping["sourceRoot"]]
        self.write(path, json.dumps(mapping))
        with mock.patch.object(LANE_D, "ROOT", self.root):
            self.write(
                "codex-rs/hepta-objective/src/component.rs", "pub fn renamed() {}"
            )
            with self.assertRaisesRegex(SystemExit, "missing native symbol"):
                LANE_D.verify_map("objective.compiler")
            mapping["operations"][0]["sourcePath"] = "other-lane/impostor.rs"
            self.write("other-lane/impostor.rs", "pub fn run() {}")
            self.write(path, json.dumps(mapping))
            with self.assertRaisesRegex(SystemExit, "source escapes owner root"):
                LANE_D.verify_map("objective.compiler")

    def test_v3_multi_root_delta_uses_every_declared_owner(self) -> None:
        path = LANE_D.MAPS["utility.ndu"]
        mapping = json.loads((self.root / path).read_text(encoding="utf-8"))
        extra = "components/alternate-ndu"
        roots = [mapping["sourceRoot"], extra]
        mapping["schema"] = "hepta.module-implementation-map.v3"
        mapping["sourceRoot"] = roots
        mapping["declaredRoots"] = roots
        self.write(f"{extra}/component.rs", "pub fn run() {}\n")
        mapping["operations"].append(
            {
                "sourcePath": f"{extra}/component.rs",
                "nativeSymbol": "crate::run",
                "tests": [],
            }
        )
        self.write(path, json.dumps(mapping))
        self.event["pull_request"]["head"]["sha"] = self.commit("v3 owner roots")
        result = self.check()
        self.assertEqual(
            result["laneDChangedPaths"],
            sorted(
                [
                    "codex-rs/hepta-ndu/src/new_policy.rs",
                    f"{extra}/component.rs",
                    path,
                ]
            ),
        )
        self.assertEqual(result["otherLaneChangedPaths"], 1)


class LaneDOwnerMapTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        self.root.mkdir()
        self.module = "objective.compiler"
        self.map_path = self.root / LANE_D.MAPS[self.module]
        self.map_path.parent.mkdir(parents=True)
        self.roots = ["components/first", "components/second"]
        self.operations = []
        for owner in self.roots:
            directory = self.root / owner
            directory.mkdir(parents=True)
            (directory / "component.rs").write_text("pub fn run() {}\n")
            (directory / "tests.rs").write_text("fn regression() {}\n")
            self.operations.append(
                {
                    "sourcePath": f"{owner}/component.rs",
                    "nativeSymbol": "crate::run",
                    "tests": [{"path": f"{owner}/tests.rs", "symbol": "regression"}],
                }
            )
        self.mapping = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "module": self.module,
            "authorityDelta": "none",
            "sourceRoot": self.roots.copy(),
            "declaredRoots": self.roots.copy(),
            "operations": self.operations,
        }
        self.patch = mock.patch.object(LANE_D, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def verify(self) -> tuple[str, ...]:
        self.map_path.write_text(json.dumps(self.mapping), encoding="utf-8")
        return LANE_D.verify_map(self.module)

    def test_canonical_v3_roots_admit_sources_in_each_declared_owner(self) -> None:
        self.assertEqual(self.verify(), tuple(self.roots))

    def test_declared_roots_work_without_legacy_alias(self) -> None:
        del self.mapping["sourceRoot"]
        self.assertEqual(self.verify(), tuple(self.roots))

    def test_legacy_scalar_root_preserves_owner_validation(self) -> None:
        del self.mapping["declaredRoots"]
        self.mapping["sourceRoot"] = self.roots[0]
        self.mapping["operations"] = self.operations[:1]
        self.assertEqual(self.verify(), (self.roots[0],))

    def test_root_alias_drift_is_not_silently_accepted(self) -> None:
        self.mapping["sourceRoot"] = [self.roots[1]]
        with self.assertRaisesRegex(SystemExit, "owner root aliases differ"):
            self.verify()

    def test_invalid_root_lists_and_paths_are_rejected(self) -> None:
        del self.mapping["declaredRoots"]
        for roots in (
            [],
            None,
            True,
            [False],
            [""],
            ["."],
            ["../outside"],
            [str(self.root)],
            ["C:\\outside"],
            ["missing"],
            [self.roots[0], self.roots[0]],
            [self.roots[0], self.roots[0] + "/"],
            [self.roots[0] + "/component.rs"],
        ):
            with self.subTest(roots=roots):
                self.mapping["sourceRoot"] = roots
                with self.assertRaises(SystemExit):
                    self.verify()

    def test_owner_symlink_escape_is_rejected(self) -> None:
        outside = self.root.parent / "outside"
        outside.mkdir()
        (self.root / "redirect").symlink_to(outside, target_is_directory=True)
        del self.mapping["declaredRoots"]
        self.mapping["sourceRoot"] = ["redirect"]
        with self.assertRaisesRegex(SystemExit, "owner-root escape"):
            self.verify()

    def test_sources_and_tests_cannot_escape_through_symlinks(self) -> None:
        outside = self.root.parent / "outside.rs"
        outside.write_text("pub fn run() {}\nfn regression() {}\n")
        for field in ("sourcePath", "test"):
            with self.subTest(field=field):
                entry = self.operations[0]
                path = (
                    entry["sourcePath"]
                    if field == "sourcePath"
                    else entry["tests"][0]["path"]
                )
                target = self.root / path
                original = target.read_text()
                target.unlink()
                target.symlink_to(outside)
                try:
                    with self.assertRaisesRegex(SystemExit, "escape"):
                        self.verify()
                finally:
                    target.unlink()
                    target.write_text(original)

    def test_real_json_loader_rejects_ambiguous_or_nonobject_maps(self) -> None:
        relative = LANE_D.MAPS[self.module]
        for content in (
            '{"module":"first","module":"second"}',
            '{"nested":{"sourceRoot":"a","sourceRoot":"b"}}',
            "[]",
            "null",
            "{",
        ):
            with self.subTest(content=content):
                self.map_path.write_text(content, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    LANE_D.load(relative)


class ObjectiveProductOperationTests(unittest.TestCase):
    def mapping(self) -> dict:
        canonical = [
            "decode_source_envelope_json_v1",
            "validate_structure",
            "admit_objective_v1",
            "compile_admitted_objective_v1",
            "encode_authenticated_objective_function_v1",
            "decode_objective_function_v1",
        ]
        return {
            "canonicalProductOperations": canonical,
            "operations": [
                {"operation": name}
                for name in canonical
                + [
                    "canonical_objective_intent_digest_v1",
                    "check_feasibility_v1",
                ]
            ]
            + [
                {
                    "operation": "admit_and_compile_objective_v1",
                    "productRole": "compatibility_not_canonical_product_path",
                }
            ],
        }

    def test_authenticated_projection_is_the_required_product_operation(self) -> None:
        LANE_D.verify_objective_product_operations(self.mapping())

    def test_raw_projection_cannot_replace_authenticated_projection(self) -> None:
        mapping = self.mapping()
        mapping["canonicalProductOperations"][4] = "encode_objective_function_v1"
        for operation in mapping["operations"]:
            if operation["operation"] == "encode_authenticated_objective_function_v1":
                operation["operation"] = "encode_objective_function_v1"
        with self.assertRaisesRegex(
            SystemExit, "canonical operation mapping incomplete"
        ):
            LANE_D.verify_objective_product_operations(mapping)

    def test_product_order_and_compatibility_role_cannot_drift(self) -> None:
        mapping = self.mapping()
        mapping["canonicalProductOperations"][2:4] = reversed(
            mapping["canonicalProductOperations"][2:4]
        )
        with self.assertRaisesRegex(SystemExit, "canonical product operation order"):
            LANE_D.verify_objective_product_operations(mapping)
        mapping = self.mapping()
        mapping["operations"][-1]["productRole"] = "canonical"
        with self.assertRaisesRegex(
            SystemExit, "convenience wrapper product-role drift"
        ):
            LANE_D.verify_objective_product_operations(mapping)


if __name__ == "__main__":
    unittest.main()
