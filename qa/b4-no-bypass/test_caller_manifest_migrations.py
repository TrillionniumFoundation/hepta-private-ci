"""Exercise migrated caller proofs against the actual source and verifier."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

from test_verify_hepta_callers import MODULE, ROOT


class CallerManifestMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in MODULE._boundary_rows(cls.manifest)
        }

    def check_boundary(self, boundary, extra=()):
        paths = set(boundary.product_callers) | set(extra)
        index = {
            path: MODULE._strip_cfg_test_items(
                MODULE._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        return MODULE._verify_boundary(
            ROOT, boundary, index, tuple(self.manifest["ignored_path_fragments"])
        )

    def check_protected(self, path, *, rows=None, mutation=None):
        if rows is None:
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        source = (ROOT / path).read_text()
        if mutation is not None:
            old, new = mutation
            self.assertIn(old, source)
            source = source.replace(old, new, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            return MODULE._verify_protected_files(root, {"protected_file": rows})

    def test_dispatch_move_is_a_closed_caller_migration(self):
        boundary = self.boundaries["final_use_dispatch_raw"]
        current = "codex-rs/hepta-operations/src/durable_dispatch.rs"
        previous = "codex-rs/hepta-operations/src/durable_store.rs"
        self.check_boundary(boundary, (current, previous))
        for callers in ((), (previous,)):
            with self.subTest(callers=callers), self.assertRaisesRegex(
                MODULE.VerificationFailure, "unexpected.*durable_dispatch"
            ):
                self.check_boundary(replace(boundary, product_callers=callers), (current, previous))
        index = {
            current: MODULE._strip_rust_non_code((ROOT / current).read_text()),
            "codex-rs/unregistered/src/lib.rs": "fn enter() { authority.with_dispatch_boundary(token, binding, effect); }",
        }
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected.*unregistered"):
            MODULE._verify_boundary(ROOT, boundary, index, ())

    def test_delivery_rejects_the_former_dispatch_location(self):
        boundary = self.boundaries["final_use_delivery_raw"]
        previous = "codex-rs/hepta-operations/src/durable_store.rs"
        self.check_boundary(boundary, (previous,))
        stale = replace(boundary, product_callers=(*boundary.product_callers, previous))
        with self.assertRaisesRegex(MODULE.VerificationFailure, "missing.*durable_store"):
            self.check_boundary(stale)

    def test_human_cas_and_retained_lookup_keep_distinct_callers(self):
        for name in ("root_human_text_same_issuer_cas", "root_retained_human_text_lookup"):
            with self.subTest(boundary=name):
                boundary = self.boundaries[name]
                self.check_boundary(boundary)
        lookup = self.boundaries["root_retained_human_text_lookup"]
        stale = replace(
            lookup,
            call_pattern=lookup.call_pattern.replace("verify_retained_human_text", "text_until_checked"),
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "caller set mismatch"):
            self.check_boundary(stale, ("codex-rs/hepta-agentd/src/deployment_text.rs",))

    def test_pinned_and_boxed_marker_migrations_are_enforced(self):
        cases = (
            ("root_original_issuer_writer_rotation", ".with_retired_predecessor_for_pinned_issuer_boundary(", ".with_retired_predecessor_boundary("),
            ("root_physical_current_retired_adoption", "AdoptMaterial::Physical(Box::new(profile))", "AdoptMaterial::Physical(profile)"),
            ("root_physical_current_backend_genesis", "FreshMaterial::Physical(Box::new(profile))", "FreshMaterial::Physical(profile)"),
        )
        for name, current, previous in cases:
            with self.subTest(boundary=name):
                boundary = self.boundaries[name]
                self.check_boundary(boundary)
                stale = replace(
                    boundary,
                    definition_markers=tuple(marker.replace(current, previous) for marker in boundary.definition_markers),
                )
                with self.assertRaisesRegex(MODULE.VerificationFailure, "missing definition marker"):
                    self.check_boundary(stale)
                path = boundary.definition_path
                self.check_protected(path)
                rows = deepcopy([row for row in self.manifest["protected_file"] if row["path"] == path])
                for row in rows:
                    row["required"] = [marker.replace(current, previous) for marker in row["required"]]
                with self.assertRaisesRegex(MODULE.VerificationFailure, "required marker missing"):
                    self.check_protected(path, rows=rows)
        rotation = self.boundaries["root_original_issuer_writer_rotation"].definition_path
        rows = deepcopy([row for row in self.manifest["protected_file"] if row["path"] == rotation])
        for row in rows:
            if "required_order" in row:
                row["required_order"] = [[marker.replace(cases[0][1], cases[0][2]) for marker in sequence] for sequence in row["required_order"]]
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.check_protected(rotation, rows=rows)

    def test_moved_writer_and_retirement_guards_remain_required(self):
        cases = (
            ("codex-rs/hepta-agentd/src/deployment_notes.rs", "issuer.with_live_issuer_writer_effect(", "issuer.unchecked_effect("),
            ("codex-rs/hepta-agentd/src/deployment_calculator.rs", "issuer.with_live_issuer_writer_effect(", "issuer.unchecked_effect("),
            ("codex-rs/hepta-agentd/src/deployment_issuer_dependencies.rs", "actual_writer != writer || actual_effect != effect", "false"),
            ("codex-rs/hepta-memory/src/local_retirement_ack.rs", "self.store.begin_write_transaction()", "self.store.begin_checkpoint_barrier()"),
            ("codex-rs/hepta-memory/src/cognitive_store_barrier.rs", 'begin_with("BEGIN IMMEDIATE")', 'begin_with("BEGIN")'),
            ("codex-rs/hepta-memory/src/cognitive_store_barrier.rs", "publication.begin_writes().await.map_err(unavailable)?;", "/* publication.begin_writes().await.map_err(unavailable)?; */"),
        )
        for path, original, bypass in cases:
            with self.subTest(path=path, mutation=original):
                self.check_protected(path)
                with self.assertRaises(MODULE.VerificationFailure):
                    self.check_protected(path, mutation=(original, bypass))


if __name__ == "__main__":
    unittest.main()
