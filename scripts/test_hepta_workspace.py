"""Manifest preflight reads only the actual local Cargo dependency graph."""

import tempfile
import unittest
from pathlib import Path

from hepta_workspace import verify_workspace


class WorkspacePreflightTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write(
            "Cargo.toml",
            '[workspace]\nmembers = ["app"]\n[workspace.package]\nversion = "1.0.0"\n',
        )
        self.write(
            "app/Cargo.toml", '[package]\nname = "app"\nversion.workspace = true\n'
        )

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_valid_graph_ignores_unreferenced_broken_fixture_workspaces(self):
        self.write("app/tests/fixtures/broken/Cargo.toml", "not TOML")
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_missing_workspace_inheritance_is_reported_before_build(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write("[dependencies]\nmissing.workspace = true\n")
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 1)
        self.assertTrue(
            any("workspace.dependencies.missing" in error for error in errors)
        )

    def test_workspace_paths_are_relative_to_workspace_not_member(self):
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\nalias = { path = "helper", package = "real" }\n'
            )
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write(
                "[target.'cfg(unix)'.build-dependencies]\nalias.workspace = true\n"
            )
        self.write("helper/Cargo.toml", '[package]\nname = "real"\n')
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_local_transitive_dev_dependencies_are_checked(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dev-dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dependencies]\nmissing.workspace = true\n',
        )
        self.assertTrue(
            any(
                "workspace.dependencies.missing" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_wrong_package_name_and_missing_local_path_are_errors(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write(
                '[dependencies]\nhelper = { path = "../helper" }\nabsent = { path = "../absent" }\n'
            )
        self.write("helper/Cargo.toml", '[package]\nname = "wrong"\n')
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("expects helper" in error for error in errors))
        self.assertTrue(any("absent/Cargo.toml" in error for error in errors))

    def test_path_cycle_is_bounded(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dev-dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dev-dependencies]\napp = { path = "../app" }\n',
        )
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_unmatched_member_and_missing_inherited_package_field_fail(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "missing"]\n')
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("member not found" in error for error in errors))
        self.assertTrue(any("workspace.package.version" in error for error in errors))

    def test_execution_core_rejects_direct_product_dependency(self):
        for name in ("codex-core", "codex-extension-api"):
            for kind in (
                "dependencies",
                "build-dependencies",
                "target.'cfg(unix)'.dependencies",
            ):
                with self.subTest(name=name, kind=kind):
                    self.write(
                        "app/Cargo.toml",
                        f'[package]\nname = "{name}"\n[{kind}]\ncodex-hepta-memory = "0.0.0"\n',
                    )
                    errors = verify_workspace(self.root)[1]
                    self.assertTrue(
                        any("execution boundary" in error for error in errors)
                    )

    def test_execution_core_rejects_inherited_renamed_product_dependency(self):
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\ninnocent = { package = "codex-hepta-memory", path = "memory" }\n'
            )
        self.write("memory/Cargo.toml", '[package]\nname = "codex-hepta-memory"\n')
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\ninnocent.workspace = true\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertTrue(any("execution boundary" in error for error in errors))

    def test_test_only_fixture_dependency_does_not_widen_product_graph(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dev-dependencies]\ncodex-hepta-memory = "0.0.0"\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_host_composition_can_depend_on_product_implementations(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-hepta-agentd"\n[dependencies]\ncodex-hepta-memory = "0.0.0"\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_invalid_dependency_package_name_fails_without_execution(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\nwrong = { package = 3, version = "0.0.0" }\n',
        )
        self.assertTrue(
            any(
                "invalid package name" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def helper_chain(self, root_kind="dependencies", helper_kind="dependencies"):
        self.write(
            "app/Cargo.toml",
            f'[package]\nname = "codex-core"\n[{root_kind}]\nhelper = {{ path = "../helper" }}\n',
        )
        self.write(
            "helper/Cargo.toml",
            f'[package]\nname = "helper"\n[{helper_kind}]\n'
            'renamed = { package = "codex-hepta-memory", path = "../memory", optional = true }\n',
        )
        self.write("memory/Cargo.toml", '[package]\nname = "codex-hepta-memory"\n')

    def test_transitive_product_dependency_reports_the_route(self):
        self.helper_chain()
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "codex-core --dependencies--> helper --dependencies--> codex-hepta-memory",
            errors[0],
        )

    def test_transitive_build_and_target_optional_edges_are_not_loopholes(self):
        for root_kind in (
            "dependencies",
            "build-dependencies",
            "target.'cfg(windows)'.dependencies",
        ):
            for helper_kind in (
                "dependencies",
                "build-dependencies",
                "target.'cfg(unix)'.build-dependencies",
            ):
                with self.subTest(root_kind=root_kind, helper_kind=helper_kind):
                    self.helper_chain(root_kind, helper_kind)
                    self.assertTrue(
                        any(
                            "execution boundary" in e
                            for e in verify_workspace(self.root)[1]
                        )
                    )

    def test_transitive_test_only_edges_do_not_contaminate_shipped_graph(self):
        for root_kind, helper_kind in (
            ("dev-dependencies", "dependencies"),
            ("dependencies", "dev-dependencies"),
        ):
            with self.subTest(root_kind=root_kind, helper_kind=helper_kind):
                self.helper_chain(root_kind, helper_kind)
                self.assertEqual(verify_workspace(self.root), (3, []))

    def test_inherited_transitive_alias_resolves_from_workspace(self):
        self.helper_chain()
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\nalias = { package = "codex-hepta-memory", path = "memory" }\n'
            )
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dependencies]\nalias.workspace = true\n',
        )
        self.assertTrue(
            any("execution boundary" in e for e in verify_workspace(self.root)[1])
        )

    def test_local_patch_cannot_hide_a_transitive_product_edge(self):
        self.helper_chain()
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\nhelper = "1.0"\n',
        )
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[patch.crates-io]\nhelper = { path = "helper" }\n')
        self.assertTrue(
            any(
                "helper --dependencies--> codex-hepta-memory" in e
                for e in verify_workspace(self.root)[1]
            )
        )

    def test_patch_rename_and_wrong_package_identity_are_checked(self):
        self.helper_chain()
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-extension-api"\n[dependencies]\nhelper = "1.0"\n',
        )
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[patch.crates-io]\ninnocent = { package = "helper", path = "helper" }\n'
            )
        self.assertTrue(
            any("execution boundary" in e for e in verify_workspace(self.root)[1])
        )
        self.write("helper/Cargo.toml", '[package]\nname = "different"\n')
        self.assertTrue(
            any("must name helper" in e for e in verify_workspace(self.root)[1])
        )

    def test_patch_used_only_in_tests_does_not_widen_boundary(self):
        self.helper_chain()
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dev-dependencies]\nhelper = "1.0"\n',
        )
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[patch.crates-io]\nhelper = { path = "helper" }\n')
        self.assertEqual(verify_workspace(self.root), (3, []))

    def test_runtime_cycle_has_a_finite_deterministic_diagnostic(self):
        self.helper_chain()
        with (self.root / "helper/Cargo.toml").open("a") as stream:
            stream.write('codex-core = { path = "../app" }\n')
        result = verify_workspace(self.root)
        self.assertEqual(len(result[1]), 1)
        self.assertEqual(result, verify_workspace(self.root))

    def test_transitive_secret_product_name_is_also_blocked(self):
        self.helper_chain()
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dependencies]\ncodex-heptabao = "1.0"\n',
        )
        self.assertTrue(
            any("codex-heptabao" in e for e in verify_workspace(self.root)[1])
        )

    def test_shared_helper_is_checked_for_each_execution_boundary(self):
        self.helper_chain()
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "extension"]\n')
        self.write(
            "extension/Cargo.toml",
            '[package]\nname = "codex-extension-api"\n[dependencies]\nhelper = { path = "../helper" }\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("codex-core --" in e for e in errors))
        self.assertTrue(any("codex-extension-api --" in e for e in errors))

    def test_shared_kernel_contracts_are_not_product_implementations(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "codex-core"\n[dependencies]\ncodex-hepta-contracts = { path = "../contracts" }\n',
        )
        self.write(
            "contracts/Cargo.toml", '[package]\nname = "codex-hepta-contracts"\n'
        )
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_shared_contracts_cannot_hide_product_implementation(self):
        self.test_shared_kernel_contracts_are_not_product_implementations()
        with (self.root / "contracts/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\ncodex-hepta-memory = "1.0"\n')
        self.assertTrue(
            any(
                "codex-hepta-contracts --dependencies--> codex-hepta-memory" in e
                for e in verify_workspace(self.root)[1]
            )
        )

    def sqlx_package(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\n[dependencies]\nsqlx = "0.9"\n',
        )

    def test_duplicate_up_migration_is_rejected_before_compilation(self):
        self.sqlx_package()
        self.write(
            "app/migrations/0004_effect.sql", "CREATE TABLE effects (id INTEGER);\n"
        )
        self.write(
            "app/migrations/0004_calendar.sql", "CREATE TABLE calendars (id INTEGER);\n"
        )
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("migration version 4 (up) collides", errors[0])
        self.assertIn("0004_calendar.sql and 0004_effect.sql", errors[0])

    def test_numeric_aliases_and_inherited_sqlx_name_do_not_hide_collision(self):
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write(
                '[workspace.dependencies]\nrenamed = { package = "sqlx", version = "0.9" }\n'
            )
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write("[dependencies]\nrenamed.workspace = true\n")
        self.write("app/migrations/4_alpha.sql", "SELECT 1;\n")
        self.write("app/migrations/+0004_beta.sql", "SELECT 2;\n")
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 1)
        self.assertIn("migration version 4 (up) collides", errors[0])

    def test_reversible_pair_is_not_a_duplicate(self):
        self.sqlx_package()
        self.write(
            "app/migrations/0004_owner.up.sql", "CREATE TABLE owner (id INTEGER);\n"
        )
        self.write("app/migrations/0004_owner.down.sql", "DROP TABLE owner;\n")
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_plain_plus_up_and_duplicate_down_are_collisions(self):
        self.sqlx_package()
        for names, direction in [
            (("0004_a.sql", "4_b.up.sql"), "up"),
            (("0004_a.down.sql", "4_b.down.sql"), "down"),
        ]:
            with self.subTest(names=names):
                for migration in (self.root / "app/migrations").glob("*.sql"):
                    migration.unlink()
                for name in names:
                    self.write(f"app/migrations/{name}", "SELECT 1;\n")
                errors = verify_workspace(self.root)[1]
                self.assertEqual(len(errors), 1)
                self.assertIn(f"migration version 4 ({direction}) collides", errors[0])

    def test_migration_versions_are_scoped_to_their_package(self):
        self.sqlx_package()
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('helper = { path = "../helper" }\n')
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\n[dependencies]\nsqlx = "0.9"\n',
        )
        self.write("app/migrations/0004_owner.sql", "SELECT 1;\n")
        self.write("helper/migrations/0004_owner.sql", "SELECT 1;\n")
        self.assertEqual(verify_workspace(self.root), (2, []))

    def test_unreferenced_fixture_migrations_are_not_global_gates(self):
        self.sqlx_package()
        self.write("app/tests/fixtures/migrations/0004_a.sql", "SELECT 1;\n")
        self.write("app/tests/fixtures/migrations/0004_b.sql", "SELECT 2;\n")
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_other_migration_frameworks_are_not_interpreted_as_sqlx(self):
        self.write("app/migrations/0004_a.sql", "SELECT 1;\n")
        self.write("app/migrations/0004_b.sql", "SELECT 2;\n")
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_invalid_sqlx_version_range_is_reported(self):
        self.sqlx_package()
        for prefix in ("0", "-1", str(2**63)):
            with self.subTest(prefix=prefix):
                name = f"app/migrations/{prefix}_invalid.sql"
                self.write(name, "SELECT 1;\n")
                errors = verify_workspace(self.root)[1]
                self.assertEqual(len(errors), 1)
                self.assertIn(
                    "SQLx migration version must be a positive i64", errors[0]
                )
                (self.root / name).unlink()

    def test_malformed_manifest_is_reported_without_execution(self):
        self.write("app/Cargo.toml", "this is not valid = TOML")
        self.assertTrue(verify_workspace(self.root)[1])

    def test_inherited_lints_require_an_owner_definition(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write("[lints]\nworkspace = true\n")
        self.assertTrue(
            any(
                "workspace.lints is missing" in error
                for error in verify_workspace(self.root)[1]
            )
        )
        with (self.root / "Cargo.toml").open("a") as stream:
            stream.write('[workspace.lints.rust]\nunsafe_code = "forbid"\n')
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_nested_workspace_uses_its_own_inheritance(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../nested/helper" }\n')
        self.write(
            "nested/Cargo.toml",
            '[workspace]\nmembers = ["helper"]\n[workspace.package]\nversion = "2.0.0"\n[workspace.dependencies]\nleaf = { path = "leaf" }\n',
        )
        self.write(
            "nested/helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n[dependencies]\nleaf.workspace = true\n',
        )
        self.write(
            "nested/leaf/Cargo.toml",
            '[package]\nname = "leaf"\nversion.workspace = true\n',
        )
        self.assertEqual(verify_workspace(self.root), (3, []))

    def test_nested_workspace_cannot_borrow_parent_package_fields(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../nested/helper" }\n')
        self.write("nested/Cargo.toml", '[workspace]\nmembers = ["helper"]\n')
        self.write(
            "nested/helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertTrue(
            any("workspace.package.version is missing" in error for error in errors)
        )

    def test_explicit_workspace_path_is_relative_to_package(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\nworkspace = ".."\nversion.workspace = true\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_explicit_missing_workspace_fails(self):
        self.write(
            "app/Cargo.toml",
            '[package]\nname = "app"\nworkspace = "../absent"\nversion.workspace = true\n',
        )
        self.assertTrue(
            any(
                "package.workspace has no" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_excluded_dependency_cannot_inherit_parent_workspace(self):
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nhelper = { path = "../helper" }\n')
        self.write(
            "Cargo.toml",
            '[workspace]\nmembers = ["app"]\nexclude = ["helper"]\n[workspace.package]\nversion = "1.0.0"\n',
        )
        self.write(
            "helper/Cargo.toml",
            '[package]\nname = "helper"\nversion.workspace = true\n',
        )
        self.assertTrue(
            any(
                "workspace.package.version is missing" in error
                for error in verify_workspace(self.root)[1]
            )
        )

    def test_preflight_never_mutates_manifests(self):
        before = {path: path.read_bytes() for path in self.root.rglob("Cargo.toml")}
        self.assertEqual(verify_workspace(self.root), (1, []))
        self.assertEqual(
            before, {path: path.read_bytes() for path in self.root.rglob("Cargo.toml")}
        )

    def duplicate_boundary_workspaces(self, name="codex-core", kind="dependencies"):
        # Different package versions and explicit workspaces are legitimate
        # distinct Cargo identities; a name-only index must not drop either.
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "host"]\n')
        self.write("app/Cargo.toml", f'[package]\nname = "{name}"\nversion = "1.0.0"\n')
        self.write(
            "host/Cargo.toml",
            '[package]\nname = "codex-hepta-agentd"\nversion = "1.0.0"\n'
            '[dependencies]\nolder = { package = "' + name + '", path = "../app" }\n'
            'newer = { package = "' + name + '", path = "../foreign" }\n',
        )
        self.write(
            "foreign/Cargo.toml",
            '[workspace]\n[package]\nname = "' + name + '"\nversion = "2.0.0"\n'
            f'[{kind}]\nrenamed = {{ package = "codex-hepta-memory", version = "1.0", optional = true }}\n',
        )

    def test_each_same_named_boundary_in_independent_workspaces_is_checked(self):
        for name in ("codex-core", "codex-extension-api"):
            for kind in (
                "dependencies",
                "build-dependencies",
                "target.'cfg(unix)'.dependencies",
            ):
                with self.subTest(name=name, kind=kind):
                    self.duplicate_boundary_workspaces(name, kind)
                    count, errors = verify_workspace(self.root)
                    self.assertEqual(count, 3)
                    self.assertEqual(len(errors), 1)
                    self.assertIn(str(self.root / "foreign/Cargo.toml"), errors[0])
                    self.assertIn("execution boundary", errors[0])
                    self.assertIn("codex-hepta-memory", errors[0])

    def test_two_offending_same_named_boundaries_both_report(self):
        self.duplicate_boundary_workspaces()
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\ncodex-hepta-memory = "1.0"\n')
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 2)
        for path in ("app/Cargo.toml", "foreign/Cargo.toml"):
            self.assertTrue(
                any(error.startswith(str(self.root / path) + ":") for error in errors)
            )

    def test_same_named_foreign_boundary_transitive_dependencies_are_checked(self):
        self.duplicate_boundary_workspaces()
        self.write(
            "foreign/Cargo.toml",
            '[workspace]\n[package]\nname = "codex-core"\nversion = "2.0.0"\n'
            '[dependencies]\nhelper = { path = "helper" }\n',
        )
        self.write(
            "foreign/helper/Cargo.toml",
            '[package]\nname = "helper"\nversion = "1.0.0"\n'
            '[build-dependencies]\ncodex-hepta-memory = "1.0"\n',
        )
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 4)
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "codex-core --dependencies--> helper --build-dependencies--> codex-hepta-memory",
            errors[0],
        )

    def test_same_named_foreign_boundary_inherits_its_own_alias(self):
        self.duplicate_boundary_workspaces()
        self.write(
            "foreign/Cargo.toml",
            "[workspace]\n[workspace.dependencies]\n"
            'alias = { package = "codex-hepta-memory", version = "1.0" }\n'
            '[package]\nname = "codex-core"\nversion = "2.0.0"\n'
            "[dependencies]\nalias.workspace = true\n",
        )
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 1)
        self.assertIn("execution boundary", errors[0])
        self.assertNotIn("workspace.dependencies.alias is missing", errors[0])

    def test_dependency_enumeration_order_cannot_hide_a_boundary(self):
        self.duplicate_boundary_workspaces()
        first = verify_workspace(self.root)
        self.write("Cargo.toml", '[workspace]\nmembers = ["host", "app"]\n')
        self.assertEqual(first, verify_workspace(self.root))
        self.assertEqual(len(first[1]), 1)

    def test_same_named_safe_independent_workspaces_are_not_duplicate_errors(self):
        self.duplicate_boundary_workspaces(kind="dev-dependencies")
        self.assertEqual(verify_workspace(self.root), (3, []))

    def test_duplicate_names_inside_one_workspace_still_fail(self):
        self.write("Cargo.toml", '[workspace]\nmembers = ["app", "other"]\n')
        self.write(
            "app/Cargo.toml", '[package]\nname = "codex-core"\nversion = "1.0.0"\n'
        )
        self.write(
            "other/Cargo.toml", '[package]\nname = "codex-core"\nversion = "2.0.0"\n'
        )
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 2)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate local package codex-core", errors[0])

    def test_multiple_aliases_to_one_boundary_are_one_vertex(self):
        self.duplicate_boundary_workspaces()
        with (self.root / "host/Cargo.toml").open("a") as stream:
            stream.write(
                'again = { package = "codex-core", path = "../foreign/../foreign" }\n'
            )
        count, errors = verify_workspace(self.root)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 1)
        self.assertIn("execution boundary", errors[0])

    def test_unreferenced_same_named_fixture_is_not_an_execution_boundary(self):
        self.write(
            "app/tests/fixtures/core/Cargo.toml",
            '[workspace]\n[package]\nname = "codex-core"\nversion = "2.0.0"\n'
            '[dependencies]\ncodex-hepta-memory = "1.0"\n',
        )
        self.assertEqual(verify_workspace(self.root), (1, []))

    def test_shared_contract_exemption_still_traverses_each_boundary(self):
        self.duplicate_boundary_workspaces()
        self.write(
            "foreign/Cargo.toml",
            '[workspace]\n[package]\nname = "codex-core"\nversion = "2.0.0"\n'
            '[dependencies]\ncodex-hepta-contracts = { path = "contracts" }\n',
        )
        self.write(
            "foreign/contracts/Cargo.toml",
            '[package]\nname = "codex-hepta-contracts"\nversion = "1.0.0"\n'
            '[dependencies]\ncodex-hepta-memory = "1.0"\n',
        )
        errors = verify_workspace(self.root)[1]
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "codex-core --dependencies--> codex-hepta-contracts --dependencies--> codex-hepta-memory",
            errors[0],
        )

    def test_same_named_boundary_cycle_remains_finite_and_deterministic(self):
        self.duplicate_boundary_workspaces()
        with (self.root / "foreign/Cargo.toml").open("a") as stream:
            stream.write('previous = { package = "codex-core", path = "../app" }\n')
        with (self.root / "app/Cargo.toml").open("a") as stream:
            stream.write(
                '[dependencies]\nnext = { package = "codex-core", path = "../foreign" }\n'
            )
        result = verify_workspace(self.root)
        self.assertEqual(result, verify_workspace(self.root))
        self.assertEqual(result[0], 3)
        self.assertEqual(len(result[1]), 2)


if __name__ == "__main__":
    unittest.main()
