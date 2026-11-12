"""Actual CURRENT registration and frame verification stay in durable arms.

Source mutations complement, and do not replace, actual UID0 process tests.
The independent refusal history itself is outside the primary-rollback claim.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
REFUSAL = A + "authority_host_publication_refusal.rs"
REGISTRATION = A + "authority_host_publication_registration.rs"
ENROLLMENT = A + "authority_host_generation_publication_enrollment.rs"
OWNER = A + "authority_host_generation_publication.rs"
TRANSPORT = A + "authority_host_generation_publication_transport.rs"
RUNTIME = A + "authority_host_generation_publication_runtime.rs"
SESSION = A + "authority_host_generation_publication_session.rs"
PROFILE = A + "authority_host_learning_profile.rs"
CALLERS = {
    "root_generation_publication_original_registration": (RUNTIME,),
    "root_publication_armed_registration": (REGISTRATION,),
    "root_publication_original_initial_data": (REGISTRATION,),
    "root_publication_refusal_binding": (REGISTRATION,),
    "root_publication_refusal_enroll": (REGISTRATION,),
    "root_publication_refusal_inspect": (TRANSPORT,),
    "root_publication_refusal_persist": (OWNER,),
    "root_publication_refusal_uncertain_ack": (RUNTIME,),
    "root_publication_original_frame_deadline": ('codex-rs/hepta-agentd/src/authority_host_generation_publication_transport.rs', 'codex-rs/hepta-agentd/src/authority_host_q24_model_transport.rs',),
}


def at_depth(body, marker, depth):
    matches = list(re.finditer(route.token_pattern(marker), body))
    if not matches:
        raise PROOF.VerificationFailure("required physical operation absent")
    for match in matches:
        prefix = body[:match.start()]
        if prefix.count("{") - prefix.count("}") != depth:
            raise PROOF.VerificationFailure("actual operation hidden in another branch")


def require_structure(path, source):
    if path == REFUSAL:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name in ("PublicationRefusalBinding", "RefusalRecord", "PublicationRefusal"):
            start = code.index("struct " + name + " {")
            begin, end = code.index("{", start), PROOF._rust_item_end(code, start)
            if end is None or re.search(r"\bpub\b", code[begin + 1:end]):
                raise PROOF.VerificationFailure("refusal fields are private original data")
        body, _ = route.function(source, "fn owner(")
        if re.search(r"self\.(?:target|previous|scope|publication_purpose)\b", body):
            raise PROOF.VerificationFailure("changing a cut cannot allocate another operation slot")
        body, _ = route.function(source, "fn enroll<T>(")
        start, stop = route.original.span(body, "RootGenerationPublicationModeV1::Recover => {")
        if "initialize" in body[start:stop] or "None =>" in body[start:stop]:
            raise PROOF.VerificationFailure("recover cannot retrofit a missing marker")
        at_depth(body, "retained.complete_armed(", 1)
        for name in ("inspect<T>", "refuse"):
            body, _ = route.function(source, "fn " + name + "(")
            at_depth(body, "try_lock()", 1)
        body, _ = route.function(source, "fn arm_ready(")
        at_depth(body, "armed.attempt = attempt", 1)
        at_depth(body, "armed.phase = Phase::Armed", 1)
        at_depth(body, "self.store.compare_and_set(&self.owner, &before, &armed)", 1)
        body, _ = route.function(source, "fn complete_armed<T>(")
        start, stop = route.original.span(body, "let result = (|| {")
        enclosed = body[start:stop]
        for marker in ("action()?", "self.binding.require_profile(&original)?",
                       "ready.phase = Phase::Ready", "require_end(end)?",
                       "compare_and_set(&self.owner, armed, &ready)"):
            at_depth(enclosed, marker, 1)
        if not re.match(r"^\s*\)\(\);\s*if result.is_err\(\)", body[stop:]):
            raise PROOF.VerificationFailure("action failure must poison, never finalize")
    if path == REGISTRATION:
        body, _ = route.function(source, "fn enroll_generation_publication(")
        start, stop = route.original.span(body, "|refusal| {")
        if not body.index("PublicationRefusal::enroll(") < start:
            raise PROOF.VerificationFailure("the complete context must enter the durable arm")
        for marker in ("self.enroll_armed_generation_publication(",
                       "verify_pinned_process(", "let original = enrolled.reserved.clone()"):
            if not start < body.index(marker) < stop:
                raise PROOF.VerificationFailure("whole original context or final read escaped arm")
            at_depth(body[start:stop], marker, 1)
        # The added C registration uses a second, sequential actual context.
        # Both contexts and all of their postchecks remain inside this arm.
        for match in re.finditer(r"with_learning_profile\s*\(", body):
            if not start < match.start() < stop:
                raise PROOF.VerificationFailure("actual Root proof before durable arm")
        inner = body[start:stop]
        context, done = route.original.span(inner, "|initial, proof| {")
        if not re.match(r"^\s*,\s*\)\?;", inner[done:]):
            raise PROOF.VerificationFailure("successor context postcheck must propagate")
        if "enrolled.require_profile()?" not in inner[context:done]:
            raise PROOF.VerificationFailure("actual C registration lacks its profile check")
        at_depth(inner[done:], "enrolled.require_profile()?", -1)
    if path == TRANSPORT:
        body, _ = route.function(source, "fn serve_generation_publication_with_end(")
        start, stop = route.original.span(body, "PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {")
        inner = body[start:stop]
        context, done = route.original.span(inner, "|initial, proof| {")
        if not re.match(r"^\s*,\s*\)\?;", inner[done:]):
            raise PROOF.VerificationFailure("actual Root context postchecks must return first")
        for marker in ("let (raw, expected) = self.with_learning_profile(",
                       "refusal::require_end(end)?", "Ok(raw)"):
            at_depth(inner, marker, 1)
        final = inner[done:]
        for marker in ("slot.require_profile()?", "slot.require_previous()?", "slot.require_selection(",
                       "original_broker_head()", "verify_pinned_process(", "refusal::require_end(end)?"):
            if marker not in final:
                raise PROOF.VerificationFailure("physical or actual peer postcheck missing after Root context")
    if path == OWNER:
        body, _ = route.function(source, "fn refuse(")
        at_depth(body, "PublicationRefusal::refuse(&self.refusal)?", 1)
        at_depth(body, "fence_record(&self.profile_store, &self.profile_owner)", 1)


class PublicationRefusalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[name].definition_path for name in CALLERS}
        paths.update(path for callers in CALLERS.values() for path in callers)
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def mutate(self, path, change):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(value):
                target.write_text(value)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, value)
            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_only_actual_registration_and_frame_callers_can_enter_arms(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                extra = dict(self.sources, **{A + "unregistered_publication_refusal.rs":
                    f"fn bypass() {{ {row.symbol}(); }}"})
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_operation_slot_and_complete_fixed_bindings_cannot_split(self):
        self.reject(REFUSAL, "owner", "Digest32::of_bytes(self.learning_operation.as_bytes())")
        self.mutate(REFUSAL, lambda s: s.replace("Digest32::of_bytes(self.learning_operation.as_bytes())", "Digest32::of_bytes(self.target.digest()?.as_ref())", 1))
        self.check(REFUSAL, "require_profile", ("original.learning_operation != self.learning_operation",
            "original.initial != self.initial", "original.scope != self.scope",
            "original.intent.previous != self.previous", "original.intent.target != self.target"))
        self.mutate(REFUSAL, lambda s: s.replace("    attempt: u64,", "    pub(crate) attempt: u64,", 1))

    def test_reserve_arms_first_and_recover_never_initializes(self):
        self.check(REFUSAL, "enroll<T>", ("RootGenerationPublicationModeV1::Reserve => HostAuthorityFrontierStore::initialize(",
            "phase: Phase::Armed", "original: None", "observed.attempt != 1",
            "observed.original.is_some()", "RootGenerationPublicationModeV1::Recover => retained.arm_ready(observed)?"))
        self.mutate(REFUSAL, lambda s: s.replace("RootGenerationPublicationModeV1::Recover => {", "RootGenerationPublicationModeV1::Recover => { HostAuthorityFrontierStore::initialize(root);", 1))

    def test_monotonic_exact_cas_and_locks_cannot_clear_another_attempt(self):
        self.check(REFUSAL, "arm_ready", ("before.phase != Phase::Ready || before.original.is_none()",
            "before.attempt.checked_add(1)", "armed.attempt = attempt", "armed.phase = Phase::Armed",
            "self.store.compare_and_set(&self.owner, &before, &armed)"))
        for name in ("inspect<T>", "refuse"):
            self.reject(REFUSAL, name, "try_lock()")
        self.check(REFUSAL, "inspect<T>", ("self.poisoned.load(Ordering::Acquire)",
            "observed.original.as_ref() != Some(original)", "self.arm_ready(observed)?"))

    def test_complete_callback_profile_and_deadline_precede_ready(self):
        self.check(REFUSAL, "complete_armed<T>", ("action()?", "self.binding.require_profile(&original)?",
            "is_some_and(|before| before != &original)", "ready.original = Some(original)",
            "compare_and_set(&self.owner, armed, &ready)", "self.refuse_locked()?", "self.poisoned.store(true, Ordering::Release)"))
        for occurrence in (0, 1):
            self.reject(REFUSAL, "complete_armed<T>", "require_end(end)?", occurrence)
        self.mutate(REFUSAL, lambda s: s.replace("let (value, original) = action()?;", "let (value, original) = if false { action()? } else { fabricated() };", 1))

    def test_first_live_root_proof_and_primary_io_are_inside_arm(self):
        self.check(REGISTRATION, "enroll_generation_publication", ("learning.profile.original_initial_data()?",
            "PublicationRefusalBinding::from_original(&initial, &scope, &inputs, version)?", "PublicationRefusal::enroll(",
            "self.enroll_armed_generation_publication(", "enrolled.require_profile()?", "verify_pinned_process(", "require_end(end)?"))
        self.mutate(REGISTRATION, lambda s: s.replace("let binding =", "self.with_learning_profile(config); let binding =", 1))
        self.reject(PROFILE, "original_initial_data", "decode_initial(&self.initial_snapshot)")
        self.check(ENROLLMENT, "enroll_armed_generation_publication", ("self.with_learning_profile(", "HostAuthorityFrontierStore::<PublicationRecord>::open(", "store.load(&profile_owner)"))

    def test_frame_arm_covers_root_postchecks_and_exact_current_readback(self):
        self.check(TRANSPORT, "serve_generation_publication_with_end", ("exchange_with_original_deadline(|bytes, end| {",
            "PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {", "Ok((raw, after))",
            "!= expected", "refusal::require_end(end)?"))
        for occurrence in (0, 1, 2):
            self.reject(TRANSPORT, "serve_generation_publication_with_end", "slot.require_profile()?", occurrence)
        self.mutate(TRANSPORT, lambda s: s.replace("refusal::require_end(end)?;", "if false { refusal::require_end(end)?; }", 1))

    def test_registration_delivery_uses_original_end_and_independent_refusal(self):
        self.check(RUNTIME, "serve_optional_with_end", ("let operation_end = end.min(submission.end)",
            "owner_alive(owner, operation_end)?", "RegisteredGenerationPublication::refuse(&slot)?"))
        self.check(OWNER, "refuse", ("PublicationRefusal::refuse(&self.refusal)?", "fence_record(&self.profile_store, &self.profile_owner)"))
        self.mutate(OWNER, lambda s: s.replace("PublicationRefusal::refuse(&self.refusal)?;", "if false { PublicationRefusal::refuse(&self.refusal)?; }", 1))


if __name__ == "__main__":
    unittest.main()
