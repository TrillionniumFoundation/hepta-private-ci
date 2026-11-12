"""Guard actual V2 custody/admission separation without weakening legacy V1.

These are source mutation controls, not native cold recovery or learning proof.
Descriptions remain data; actual Root custody and the live lane construct the
factory, and a restored V2 reservation keeps its original witness generation.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
REG = A + "authority_host_q24_model_registration.rs"
V2 = A + "authority_host_q24_model_registration_v2.rs"
DATA = A + "authority_host_q24_model_profile_v2.rs"
VAR = A + "authority_host_q24_model_profile_variants.rs"
LEGACY = A + "authority_host_q24_model_profile.rs"
CLIENT = A + "root_q24_model_factory.rs"
WIRE = A + "authority_host_q24_model_transport.rs"
INPUTS = A + "root_production_q24_model_inputs.rs"
POST = A + "authority_host_post_a_learning.rs"
CALLERS = {
    "root_q24_factory_v2_reserve_same_service": (POST,),
    "root_q24_factory_v2_open_existing": (POST,),
    "root_q24_factory_v2_reservation_description": (V2,),
    "root_q24_factory_v2_live_admission": (V2,),
    "root_q24_factory_v2_original_reservation": (V2,),
    "root_q24_factory_v2_live_context": (VAR,),
    "root_q24_factory_versioned_live_context": (REG, WIRE, INPUTS, CLIENT),
    "root_q24_factory_original_witness_generation": (CLIENT,),
    "root_q24_factory_original_witness_binding": (CLIENT,),
}


def require_structure(path, source):
    if path == V2:
        for name, marker in (
            ("reserve_q24_model_factory_v2_for_profile", "|initial, _proof| {"),
            ("open_q24_model_factory_v2", "|initial, proof| {"),
        ):
            body, _ = route.function(source, "fn " + name + "(")
            if len(re.findall(r"self\s*\.\s*with_learning_profile\s*\(", body)) != 1:
                raise PROOF.VerificationFailure("one original live writer context required")
            begin, end = route.original.span(body, marker)
            if not re.match(r"^\s*,\s*\)\?\s*;\s*require_factory_end\(end\)", body[end:]):
                raise PROOF.VerificationFailure("whole writer postchecks must return before the last end check")
            if "open_q24" in name:
                for forbidden in ("::initialize(", "::create(", "new_file(", "FileAnchorWitnessStore::open(", ".or_else("):
                    if forbidden in body:
                        raise PROOF.VerificationFailure("V2 reopen is existing-only")
                for physical in ("factory.current(config)?", "observe_original_file_anchor_v1("):
                    positions = [m.start() for m in re.finditer(re.escape(physical), body)]
                    if len(positions) != 2 or not begin < positions[0] < end < positions[1]:
                        raise PROOF.VerificationFailure("physical before/after must enclose actual Root postchecks")
            else:
                for mutation in ("std::fs::DirBuilder::new()", "HostAuthorityFrontierStore::initialize("):
                    if body.count(mutation) != 1 or not begin < body.index(mutation) < end:
                        raise PROOF.VerificationFailure("reservation mutation escaped actual Root context")
    if path == DATA:
        body, _ = route.function(source, "fn canonical_reservation_binding(")
        for live in ("process_identity", "writer_proof", "spawn_generation", "admission_binding"):
            if live in body:
                raise PROOF.VerificationFailure("durable reservation must not impersonate a later live session")
    if path == VAR:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name, variants in (
            ("ReservedFactoryProfile", "LegacyV1(HostAuthorityQ24ModelFactoryProfileV1), DurableV2(DurableQ24ModelFactoryProfileV2),"),
            ("LiveFactoryProfile", "LegacyV1(HostAuthorityQ24ModelFactoryProfileV1), SessionV2(LiveQ24ModelFactoryProfileV2),"),
        ):
            start = code.index("enum " + name + " {")
            end = PROOF._rust_item_end(code, start)
            actual = code[code.index("{", start) + 1:end]
            if re.sub(r"\s+", "", actual) != re.sub(r"\s+", "", variants):
                raise PROOF.VerificationFailure("only explicit exact V1/V2 descriptions are accepted")


class Q24FactoryV2SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[k].definition_path for k in CALLERS}
        paths.update(p for values in CALLERS.values() for p in values)
        cls.sources = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
                       for p in paths}

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

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_versioned_boundaries_have_actual_closed_callers(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                bypass = (f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                          if row.receiver_type else f"fn bypass() {{ {row.symbol}(); }}")
                extra = dict(self.sources, **{A + "unregistered_factory.rs": bypass})
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_legacy_stays_exact_live_bound_and_original_root_custody(self):
        self.check(LEGACY, "require_context", (
            "Self::new(", "identity,", "proof,", "self.journal,", "self.witness,", "if self != &expected",
        ))
        self.check(LEGACY, "canonical_binding", ("&self.process_identity_digest", "&self.writer_proof_digest"))
        self.check(LEGACY, "capture", ("metadata.uid() != 0", "metadata.mode() & 0o777 != 0o600", "metadata.nlink() != 1"))
        self.check(LEGACY, "require_writable", ("flags < 0", "flags & libc::O_ACCMODE != libc::O_RDWR", "flags & libc::O_APPEND != 0"))
        self.reject(REG, "open_q24_model_factory", "retained.profile != ReservedFactoryProfile::LegacyV1(profile.clone())")

    def test_durable_context_keeps_every_original_file_scope_and_generation(self):
        self.check(DATA, "reserve_description", (
            "scope.validate_snapshot(initial)", "journal == witness || witness_domain.is_zero() || local_policy.is_zero()",
            "&generation.get().to_be_bytes()", "witness_generation: generation.get()",
            "profile.canonical_reservation_binding()?",
        ))
        self.check(DATA, "require_reserved_context", (
            "initial,", "scope,", "journal,", "witness,", "witness_domain,", "local_policy,",
            "self.original_generation()?", "if self != &expected",
        ))
        self.reject(DATA, "original_generation", "Generation::new(self.witness_generation)")
        self.check(DATA, "canonical_reservation_binding", (
            "&self.initial_head", "&self.scope_binding", "&self.journal_slot_binding",
            "&self.witness_enrollment_binding", "&self.local_policy_digest", "self.witness_generation.to_be_bytes()",
        ))

    def test_current_admission_cannot_reuse_old_process_or_proof(self):
        self.check(DATA, "admit_current_session", (
            "reservation.require_reserved_context(", "neuron_generation_process_identity_digest_v1(identity)",
            "writer_proof_digest: canonical_digest(proof)?", "profile.canonical_admission_binding()?",
        ))
        self.check(DATA, "canonical_admission_binding", (
            "canonical_digest(self.reservation.durable_binding())?", "canonical_digest(&self.process_identity_digest)?",
            "canonical_digest(&self.writer_proof_digest)?",
        ))
        self.reject(DATA, "require_live_context", "if self != &expected")
        self.check(VAR, "witness_generation", ("Self::LegacyV1(_)", "profile.reservation.original_generation()"))
        self.check(VAR, "witness_binding", ("Self::LegacyV1(profile) => profile.binding()", "profile.reservation.durable_binding()"))
        for enum in ("ReservedFactoryProfile", "LiveFactoryProfile"):
            self.mutate(VAR, lambda source: source.replace("enum " + enum + " {", "enum " + enum + " { Auto,", 1))

    def test_reserve_alone_mutates_under_actual_root_and_original_end(self):
        self.check(V2, "reserve_q24_model_factory_v2_for_profile", (
            "self.with_learning_profile(", "learning.require_cell_scope(&initial)?", "Generation::new(self.identity.spawn_generation)",
            "std::fs::DirBuilder::new().mode(0o700).create(&directory)?", "File::open(&config.state_dir)?.sync_all()?",
            "FilePin::capture(&journal)?", "FilePin::capture(&witness)?", "FileAnchorWitnessStore::open(",
            "enrolled.current().map_err(io::Error::other)?.is_some()", "drop(enrolled)",
            "HostAuthorityFrontierStore::initialize(", "profile: ReservedFactoryProfile::DurableV2(profile)",
        ))
        for occurrence in range(5):
            self.reject(V2, "reserve_q24_model_factory_v2_for_profile", "require_factory_end(end)", occurrence)
        for occurrence in range(2):
            self.reject(V2, "reserve_q24_model_factory_v2_for_profile", ">= initial.request.envelope.expiry_unix_seconds", occurrence)

    def test_reopen_never_upgrades_initializes_or_repairs(self):
        self.check(V2, "open_q24_model_factory_v2", (
            "read_root_json(reservation_file)?", "learning.require_cell_scope(&initial)?", "HostAuthorityFrontierStore::open(",
            "store.load(OWNER_V2)", "retained.validate()?", "let ReservedFactoryProfile::DurableV2(original) = &retained.profile else",
            "DurableQ24ModelFactoryProfileV2::require_reserved_context(", "original.require_files(&journal, &witness)?",
            "let generation = original.original_generation()?", "observe_file(&witness_path)?",
            "LiveQ24ModelFactoryProfileV2::admit_current_session(", "&self.identity,", "&proof,",
        ))
        for forbidden in ("HostAuthorityFrontierStore::initialize(root)", "new_file(path)", "FileAnchorWitnessStore::open(file)", "result.or_else(fresh)"):
            self.mutate(V2, lambda source: source.replace("        let reservation: HostAuthorityQ24ModelFactoryReservationV1", "        " + forbidden + ";\n        let reservation: HostAuthorityQ24ModelFactoryReservationV1", 1))

    def test_reopen_physical_checks_enclose_all_root_postchecks(self):
        for occurrence in range(5):
            self.reject(V2, "open_q24_model_factory_v2", "require_factory_end(end)", occurrence)
        for occurrence in range(2):
            self.reject(V2, "open_q24_model_factory_v2", "factory.current(config)? != retained", occurrence)
            self.reject(V2, "open_q24_model_factory_v2", "observe_original_file_anchor_v1(", occurrence)
        self.mutate(V2, lambda source: source.replace("            )?;\n        // The original", "            );\n        // The original", 1))

    def test_actual_client_uses_original_witness_and_current_live_reply(self):
        self.check(CLIENT, "from_original_handoff", (
            "profile.require_files(&journal, &witness)?", "LiveFactoryProfile::witness_generation(&profile, spawn_generation)",
            "factory.exchange(Command::Observe).await?",
        ))
        self.check(CLIENT, "operate<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>", (
            "LiveFactoryProfile::witness_binding(&self.profile)", "self.generation,",
        ))
        self.reject(CLIENT, "exchange", "response.schema != self.profile.wire_schema()")
        self.reject(CLIENT, "exchange", "response.operation != self.profile.purpose()")
        self.reject(CLIENT, "require_successor_session", "original.require_current_successor_session()?")
        self.check(REG, "current", (
            "self.profile.directory()", "self.profile.witness_filename()", ".load(self.profile.store_owner())",
            "current.profile != self.profile.reserved()",
        ))


if __name__ == "__main__":
    unittest.main()
