"""Keep post-freeze registration on the real retained Root service.

No helper definition is a product late caller or native registration proof.
The final provider must hold the original historical refusal context around
these calls, and explicitly choose register versus open-only recovery.
"""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT = route.ROOT
PROOF = route.PROOF
A = route.A
DERIVED = A + "authority_host_derived_learning_registration.rs"
LEARNING = A + "authority_host_learning_registration.rs"
MODEL = A + "authority_host_q24_model_registration.rs"
SERVICE = A + "authority_host_service.rs"
CALLERS = {
    "root_learning_derived_checkpoint": (),
    "root_learning_original_store_core": (DERIVED,),
    "root_q24_factory_reserve_same_service": (),
}


def require_structure(path, source):
    if path == SERVICE:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("enum OriginalDerivedLearningMode {")
        end = PROOF._rust_item_end(code, start)
        variants = code[code.index("{", start) + 1:end]
        if not re.fullmatch(r"\s*Register\s*,\s*Reopen\s*,?\s*", variants):
            raise PROOF.VerificationFailure("registration and recovery require an explicit fixed choice")
        return
    if path not in (DERIVED, MODEL):
        return
    name, marker, deadline = (
        ("prepare_original_derived_learning_checkpoint", "|initial, _| {", "require_original_end")
        if path == DERIVED else
        ("reserve_q24_model_factory_for_profile", "|initial, proof| {", "require_factory_end")
    )
    body, _ = route.function(source, "fn " + name + "(")
    if body.count("self.with_learning_profile(") != 1:
        raise PROOF.VerificationFailure("one original writer context required")
    begin, end = route.original.span(body, marker)
    for forbidden in ("open_registered_writer", "read_root_json", "Instant::now() +",
                      "checked_add(", "SigningKey", "or_else(", "unwrap_or", "NoUpdate"):
        pattern = r"(?<!\w)" + re.escape(forbidden)
        if re.search(pattern, body):
            raise PROOF.VerificationFailure("same-service core cannot substitute custody or renew its end")
    call = "learning_store(" if path == DERIVED else "HostAuthorityFrontierStore::initialize("
    if body.count(call) != 1 or not begin < body.index(call) < end:
        raise PROOF.VerificationFailure("store mutation must stay in the actual Root context")
    tail = body[end:]
    if not re.match(r"^\s*,\s*\)\?\s*;\s*" + deadline + r"\(end\)\?\s*;", tail):
        raise PROOF.VerificationFailure("full original context postchecks and deadline must finish")
    if path == DERIVED and ("Some(scope)" not in body or "profile.require_cell_scope(&initial)?" not in body):
        raise PROOF.VerificationFailure("derived checkpoint must retain its exact Cell scope")


class DerivedLearningSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in (DERIVED, LEARNING, MODEL, SERVICE)
        }

    def mutate(self, path, change):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)

            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, name, marker, occurrence=0):
        def change(source):
            key = "fn " + name + "("
            body, _ = route.function(source, key)
            matches = list(re.finditer(route.token_pattern(marker), body))
            self.assertGreater(len(matches), occurrence, marker)
            match = matches[occurrence]
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index(key)
            lo, hi = start + match.start(), start + match.end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def check(self, path, name, markers):
        for marker in markers:
            with self.subTest(function=name, marker=marker):
                self.reject(path, name, marker)

    def test_same_service_helpers_and_original_store_have_exact_callers(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                sources = dict(self.sources)
                sources[A + "unregistered_late_owner.rs"] = (
                    f"fn bypass(service: &HostAuthorityService) {{ service.{method}(); }}"
                    if row.receiver_type else f"fn bypass() {{ {method}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_derived_checkpoint_is_cell_scoped_on_the_original_registration(self):
        self.check(DERIVED, "prepare_original_derived_learning_checkpoint", (
            "profile.schema_version != 2", "profile.update_scope.is_none()", "self.with_learning_profile(",
            "profile.require_cell_scope(&initial)?", "let binding = scope.binding()",
            "validate_runtime_lanes(config)?", "paths.push(&socket_path)",
            "validate_lane_paths(&paths, config.peer_gid)?",
            "learning_store(&config.state_dir, &initial, mode, Some(scope))?",
            "backend.frozen_scope_binding() != Some(binding)", "q24_model: None",
        ))

    def test_register_and_reopen_cannot_be_inferred_or_fall_back(self):
        self.check(DERIVED, "prepare_original_derived_learning_checkpoint", (
            "OriginalDerivedLearningMode::Register => StoreMode::Register",
            "OriginalDerivedLearningMode::Reopen => StoreMode::Reopen",
        ))
        self.mutate(SERVICE, lambda source: source.replace(
            "enum OriginalDerivedLearningMode {", "enum OriginalDerivedLearningMode { Auto,", 1))
        self.mutate(DERIVED, lambda source: source.replace(
            "let backend = learning_store(", "let backend = fallback.or_else(|| learning_store(", 1))

    def test_every_stage_keeps_the_original_absolute_end(self):
        for path, name, guard in (
            (DERIVED, "prepare_original_derived_learning_checkpoint", "require_original_end(end)?"),
            (MODEL, "reserve_q24_model_factory_for_profile", "require_factory_end(end)?"),
        ):
            for occurrence in range(5):
                with self.subTest(path=path, occurrence=occurrence):
                    self.reject(path, name, guard, occurrence)
        self.reject(DERIVED, "require_original_end", "Instant::now() >= end")
        self.reject(MODEL, "require_factory_end", "Instant::now() >= end")

    def test_mutation_and_postchecks_cannot_escape_or_be_swallowed(self):
        for path, marker in ((DERIVED, "require_original_end(end)?;"),
                             (MODEL, "require_factory_end(end)?;")):
            self.mutate(path, lambda source: source.replace(
                "        )?;\n        " + ("// Includes the actual writer/pidfd/lease/revocation postchecks above.\n        " if path == DERIVED else "") + marker,
                "        );\n        " + marker, 1))
        self.mutate(DERIVED, lambda source: source.replace(
            "        let (backend, socket_path) = self.with_learning_profile(",
            "        learning_store(&config.state_dir, &initial, mode, Some(scope))?;\n"
            "        let (backend, socket_path) = self.with_learning_profile(", 1))

    def test_factory_reservation_retains_original_physical_and_clock_checks(self):
        self.check(MODEL, "reserve_q24_model_factory_for_profile", (
            "self.with_learning_profile(", "learning.require_cell_scope(&initial)?",
            "now >= initial.request.envelope.expiry_unix_seconds", "witness_domain(config, reservation)?",
            "std::fs::DirBuilder::new().mode(0o700).create(&directory)?",
            "File::open(&config.state_dir)?.sync_all()?", "FilePin::capture(&journal)?",
            "FilePin::capture(&witness)?", "policy_digest(reservation)?", "FileAnchorWitnessStore::open(",
            "scope_digest: profile.binding().parse()", "objective_digest: initial.request.envelope.objective_digest",
            "Generation::new(self.identity.spawn_generation)", "WITNESS_RECORDS",
            "enrolled.current().map_err(io::Error::other)?.is_some()", "drop(enrolled)",
            "HostAuthorityFrontierStore::initialize(", "epoch: 1", "material: None",
            "config.required_bind.verify()?", ">= initial.request.envelope.expiry_unix_seconds",
        ))
        for occurrence in (0, 1):
            self.reject(MODEL, "reserve_q24_model_factory_for_profile", "self.clock.refresh_projection()", occurrence)
            self.reject(MODEL, "reserve_q24_model_factory_for_profile", "witness_domain(config, reservation)?", occurrence)

    def test_file_cli_preserves_metadata_and_existing_learning_predecessor(self):
        self.check(MODEL, "register_host_q24_model_factory", (
            "read_root_json(config_file)?", "read_root_json(registration_file)?",
            "read_root_json(reservation_file)?", "open_registered_writer(&config, &registration, owner_pidfd)?",
            "service.open_registered_learning_checkpoint(", "learning_profile_file,",
            ".checked_add(Duration::from_millis(config.timeout_ms))",
            "service.reserve_q24_model_factory_for_profile(", "&learning.profile,", "&reservation,", "end,",
        ))

    def test_core_cannot_reopen_a_writer_or_create_a_relative_timeout(self):
        for path, name in ((DERIVED, "prepare_original_derived_learning_checkpoint"),
                           (MODEL, "reserve_q24_model_factory_for_profile")):
            for forbidden in ("open_registered_writer()", "read_root_json(path)",
                              "Instant::now() + extra", "SigningKey::from_bytes(bytes)",
                              "result.or_else(fallback)"):
                with self.subTest(path=path, forbidden=forbidden):
                    def insert(source):
                        body, _ = route.function(source, "fn " + name + "(")
                        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
                        start = code.index("fn " + name + "(") + body.index("{") + 1
                        return source[:start] + "\n" + forbidden + ";\n" + source[start:]
                    self.mutate(path, insert)


if __name__ == "__main__":
    unittest.main()
