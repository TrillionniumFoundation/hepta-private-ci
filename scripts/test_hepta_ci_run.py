from pathlib import Path
import tempfile
import unittest

from hepta_ci_run import ScopeError, commands, validate_plan, check_cargo_graph
from test_hepta_ci_scope import FixtureBase


def plan(packages=(), **flags):
    return {"schema": "hepta.ci-test-plan.v1", "tested_commit": "a" * 40,
            "tested_tree": "b" * 40, "rust_packages": sorted(packages),
            **dict.fromkeys(("full_workspace", "engineering", "os_evidence", "ui_browser", "ui_native", "source_owner"), False),
            **flags}


class RunnerTests(unittest.TestCase):
    def test_empty_selection_never_invokes_cargo(self):
        for stage in ("format", "native", "source-owner", "engineering", "os", "ui"):
            self.assertEqual(commands(Path("/tmp"), plan(), stage), [])

    def test_package_names_cannot_inject_shell(self):
        for name in ("--workspace", "a;echo_pwn", "a b", "a\nENV=true", "$(id)"):
            with self.subTest(name=name), self.assertRaises(ScopeError):
                validate_plan(plan([name]))

    def test_boolean_string_is_not_accepted(self):
        with self.assertRaises(ScopeError):
            validate_plan(plan(engineering="false"))

    def test_duplicates_rejected(self):
        with self.assertRaises(ScopeError):
            validate_plan(plan(["a", "a"]))

    def test_full_without_packages_rejected(self):
        with self.assertRaises(ScopeError):
            validate_plan(plan(full_workspace=True))

    def test_selected_owner_test_uses_exact_packages(self):
        result = commands(Path("/repo"), plan(["test-a", "test-b"]), "native")
        self.assertEqual(result[0][2], ["just", "test", "--locked", "-p", "test-a", "-p", "test-b"])
        self.assertNotIn("--all-features", result[1][2])

    def test_full_workspace_ignores_default_members(self):
        result = commands(Path("/repo"), plan(["test-a"], full_workspace=True), "native")
        self.assertEqual(result[0][2], ["just", "test", "--locked", "--workspace"])

    def test_default_supervisor_checked_separately(self):
        result = commands(Path("/repo"), plan(["codex-hepta-supervisor"]), "native")
        self.assertEqual(result[0][0], "supervisor-default-library")
        self.assertIn("--no-default-features", result[0][2])

    def test_selected_ui_cannot_have_empty_glob(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ScopeError):
            commands(Path(tmp), plan(ui_browser=True), "ui")

    def test_ui_file_with_spaces_is_one_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "apps/hepta-browser/test/file with spaces.js"
            target.parent.mkdir(parents=True)
            target.write_text("", encoding="utf-8")
            result = commands(root, plan(ui_browser=True), "ui")
            self.assertEqual(result[0][2], ["node", "--test", str(target)])


class MetadataTests(FixtureBase, unittest.TestCase):
    def metadata(self):
        graph = self.graph()
        rows = []
        for manifest, package in graph.packages.items():
            deps = [{"path": str((self.root / target).parent)} for target, consumers in graph.consumers.items() if manifest in consumers]
            rows.append({"id": manifest, "name": package.name,
                         "manifest_path": str(self.root / manifest), "dependencies": deps})
        return {"packages": rows, "workspace_members": sorted(graph.members)}

    def test_metadata_agreement(self):
        check_cargo_graph(self.root, self.metadata())

    def test_missing_member_detected(self):
        data = self.metadata()
        data["workspace_members"].pop()
        with self.assertRaises(ScopeError):
            check_cargo_graph(self.root, data)

    def test_missing_edge_detected(self):
        data = self.metadata()
        data["packages"][0]["dependencies"].append({"path": str(self.root / "codex-rs/unrelated")})
        with self.assertRaises(ScopeError):
            check_cargo_graph(self.root, data)


if __name__ == "__main__":
    unittest.main()
