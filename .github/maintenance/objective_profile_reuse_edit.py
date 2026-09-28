#!/usr/bin/env python3
"""Apply the remaining objective.compiler source changes.

Development-only edit. This script creates ordinary source changes and never
asserts qualification, target-host acceptance, activation, or release.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences, found {actual}: {old[:120]!r}"
        )
    write(path, text.replace(old, new))


def replace_after(
    path: str, marker: str, old: str, new: str, count: int = 1
) -> None:
    text = read(path)
    offset = text.find(marker)
    if offset < 0:
        raise RuntimeError(f"{path}: marker not found: {marker!r}")
    prefix, suffix = text[:offset], text[offset:]
    actual = suffix.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences after marker, found {actual}: {old[:120]!r}"
        )
    write(path, prefix + suffix.replace(old, new))


def append(path: str, content: str, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        raise RuntimeError(f"{path}: sentinel already present: {sentinel}")
    write(path, text.rstrip() + "\n\n" + content.strip() + "\n")


# ---------------------------------------------------------------------------
# 1. Reuse the process-generation-frozen profile without caching request state.
# ---------------------------------------------------------------------------

p = "codex-rs/hepta-objective/src/objective_admission.rs"
replace(
    p,
    '''pub fn admit_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    let profile_digest = profile.digest()?;
    if context.selected_profile_digest != profile_digest {''',
    '''pub fn admit_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    let profile_digest = profile.digest()?;
    admit_profile_bound_objective_v1(envelope, profile, context, profile_digest)
}

/// Internal typed boundary for a process-generation-frozen profile.
///
/// Only static validation, indexes and the exact profile digest are reused.
/// Authentication, source identity, freshness, deadline and every final-use
/// check remain request-local and execute below on every call.
pub(crate) fn admit_frozen_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &crate::validated_admission::ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    admit_profile_bound_objective_v1(
        envelope,
        profile.profile(),
        context,
        profile.profile_digest(),
    )
}

fn admit_profile_bound_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    profile_digest: Digest32,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    if context.selected_profile_digest != profile_digest {''',
)

p = "codex-rs/hepta-objective/src/validated_admission.rs"
replace(
    p,
    "use crate::admit_objective_v1;",
    "use crate::objective_admission::admit_frozen_objective_v1;",
)
replace(
    p,
    '''const COMPILER_CONTRACT_V1: &[u8] = b"hepta.objective.compiler.contract.v1:indexed-profile:exact-ms-deadline:proof-bearing-admission";

/// Frozen profile plus indexes and collision proofs used by authoritative''',
    '''const COMPILER_CONTRACT_V1: &[u8] = b"hepta.objective.compiler.contract.v1:indexed-profile:exact-ms-deadline:proof-bearing-admission";

/// Exact identity of reusable static profile validation.
///
/// This key deliberately excludes authentication, time, revocation, generation,
/// fence and effect authority. Those facts are request- or final-use-local and
/// are never cached by the compiler.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedAdmissionProfileReuseKeyV1 {
    pub profile_digest: Digest32,
    pub profile_revision: u64,
    pub compiler_contract_digest: Digest32,
}

/// Frozen profile plus indexes and collision proofs used by authoritative''',
)
replace(
    p,
    '''    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub fn constraint(''',
    '''    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    /// Static semantic reuse identity. This is never an authorization result.
    #[must_use]
    pub fn reuse_key(&self) -> ValidatedAdmissionProfileReuseKeyV1 {
        ValidatedAdmissionProfileReuseKeyV1 {
            profile_digest: self.profile_digest,
            profile_revision: self.profile.profile_revision.get(),
            compiler_contract_digest: Digest32::of_bytes(COMPILER_CONTRACT_V1),
        }
    }

    #[must_use]
    pub fn constraint(''',
)
replace(
    p,
    "    let admitted = admit_objective_v1(envelope, profile.profile(), context)?;",
    "    let admitted = admit_frozen_objective_v1(envelope, profile, context)?;",
)

p = "codex-rs/hepta-objective/src/lib.rs"
replace(
    p,
    "pub use validated_admission::ValidatedAdmissionProfileV1;\n",
    "pub use validated_admission::ValidatedAdmissionProfileReuseKeyV1;\n"
    "pub use validated_admission::ValidatedAdmissionProfileV1;\n",
)

# Strict protocol projection consumes the non-forgeable validated profile and
# cached digest, while still rechecking every source/receipt/canonical invariant.
p = "codex-rs/hepta-objective/src/objective_function_v1.rs"
replace(
    p,
    '''pub(crate) fn encode_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    validate_projection_binding(compiled, source, profile, admission)?;
    encode_validated(compiled, source, profile, admission)
}
''',
    '''pub(crate) fn encode_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    validate_projection_binding(compiled, source, profile, admission)?;
    encode_validated(compiled, source, profile, admission)
}

/// Strict projection for a profile whose static validation is already frozen.
///
/// The cached digest is accepted only from the opaque validated profile type.
/// Source structure, intent, timestamps, receipt binding, native semantics and
/// canonical decode remain mandatory.
pub(crate) fn encode_validated_profile_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &crate::ValidatedAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    validate_projection_binding_with_digest(
        compiled,
        source,
        profile.profile(),
        profile.profile_digest(),
        admission,
    )?;
    encode_validated(compiled, source, profile.profile(), admission)
}
''',
)
replace(
    p,
    '''fn validate_projection_binding(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<(), ObjectiveFunctionV1Error> {
    source
        .validate_structure()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source structure"))?;
    let intent_digest = canonical_objective_intent_digest_v1(source)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source intent"))?;
    let profile_digest = profile
        .digest()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("profile"))?;
    let observed_at_unix_micros = parse_utc_micros(&source.observed_at).ok_or(''',
    '''fn validate_projection_binding(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<(), ObjectiveFunctionV1Error> {
    let profile_digest = profile
        .digest()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("profile"))?;
    validate_projection_binding_with_digest(
        compiled,
        source,
        profile,
        profile_digest,
        admission,
    )
}

fn validate_projection_binding_with_digest(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    profile_digest: Digest32,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<(), ObjectiveFunctionV1Error> {
    source
        .validate_structure()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source structure"))?;
    let intent_digest = canonical_objective_intent_digest_v1(source)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source intent"))?;
    let observed_at_unix_micros = parse_utc_micros(&source.observed_at).ok_or(''',
)

p = "codex-rs/hepta-objective/src/proof_projection.rs"
replace(
    p,
    '''    crate::objective_function_v1::encode_objective_function_v1(
        compiled,
        source,
        profile.profile(),
        &outcome.receipt,
    )''',
    '''    crate::objective_function_v1::encode_validated_profile_objective_function_v1(
        compiled,
        source,
        profile,
        &outcome.receipt,
    )''',
)
replace(
    p,
    '''    // Deliberately retain all native/source/profile/receipt and canonical-wire
    // validation. The removed work is duplicate admission and feasibility, not
    // authorization or validation of arbitrary caller-created receipts.''',
    '''    // Deliberately retain all native/source/receipt and canonical-wire
    // validation. Static profile validation and its exact digest come only from
    // the opaque validated profile; no caller-controlled skip flag exists.''',
)

p = "codex-rs/hepta-intelligence/src/objective_run.rs"
replace(
    p,
    '''    let validated_profile = ValidatedAdmissionProfileV1::from_profile(profile)?;
    let proof_bearing =
        compile_authoritative_objective_v1(envelope, &validated_profile, context)?;
    let protocol = if proof_bearing.outcome().compile_result.is_ok() {
        Some(encode_proof_bearing_objective_function_v1(
            &proof_bearing,
            envelope,
            &validated_profile,
        )?)
    } else {
        None
    };''',
    '''    let validated_profile = ValidatedAdmissionProfileV1::from_profile(profile)?;
    compile_and_publish_validated_objective_run_v1(
        envelope,
        &validated_profile,
        context,
        bindings,
        journal,
    )
}

/// Product entrypoint for a process-generation-frozen validated profile.
///
/// Static profile validation and indexes are reused. The supplied admission
/// context is still authenticated and checked for source identity, freshness,
/// deadline and exact profile binding on every invocation. The destination
/// journal remains the only durable run-start owner.
pub fn compile_and_publish_validated_objective_run_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunBindingsV1,
    journal: &mut dyn RunStartJournal,
) -> Result<PublishedObjectiveRunV1, ObjectiveRunError> {
    let proof_bearing = compile_authoritative_objective_v1(envelope, profile, context)?;
    let protocol = if proof_bearing.outcome().compile_result.is_ok() {
        Some(encode_proof_bearing_objective_function_v1(
            &proof_bearing,
            envelope,
            profile,
        )?)
    } else {
        None
    };''',
)

p = "codex-rs/hepta-intelligence/src/lib.rs"
replace(
    p,
    "pub use objective_run::compile_and_publish_objective_run_v1;\n",
    "pub use objective_run::compile_and_publish_objective_run_v1;\n"
    "pub use objective_run::compile_and_publish_validated_objective_run_v1;\n",
)

p = "codex-rs/hepta-agentd/src/objective_runtime.rs"
replace(
    p,
    "use codex_hepta_intelligence::compile_and_publish_objective_run_v1;",
    "use codex_hepta_intelligence::compile_and_publish_validated_objective_run_v1;",
)
replace(
    p,
    "use codex_hepta_objective::ObjectiveAdmissionProfileV1;",
    "use codex_hepta_objective::ValidatedAdmissionProfileV1;",
)
replace(
    p,
    "    profile: ObjectiveAdmissionProfileV1,",
    "    profile: ValidatedAdmissionProfileV1,",
)
replace(
    p,
    '''        let profile_digest = profile
            .digest()
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;
        let journal = open_run_start_store(identity, profile_digest, checkpoint_file)?;''',
    '''        let profile = ValidatedAdmissionProfileV1::new(profile)
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;
        let profile_digest = profile.profile_digest();
        let journal = open_run_start_store(identity, profile_digest, checkpoint_file)?;''',
)
replace(
    p,
    "                    let published = match compile_and_publish_objective_run_v1(",
    "                    let published = match compile_and_publish_validated_objective_run_v1(",
)

append(
    "codex-rs/hepta-objective/src/validated_admission_tests.rs",
    r'''
#[test]
fn frozen_profile_reuse_never_caches_authentication_time_or_profile_selection() {
    let raw = profile();
    let source = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen profile");
    let key = frozen.reuse_key();
    let current = context(&raw, &source);

    let first = compile_authoritative_objective_v1(&source, &frozen, &current)
        .expect("current authenticated admission");

    let mut wrong_source = current.clone();
    wrong_source.source_authentication = ObjectiveSourceAuthenticationV1::Principal {
        principal_scope_digest: source.principal_scope_digest,
        source_digest: digest("not-the-authenticated-source"),
    };
    assert!(compile_authoritative_objective_v1(&source, &frozen, &wrong_source).is_err());

    let mut wrong_scope = current.clone();
    wrong_scope.source_authentication = ObjectiveSourceAuthenticationV1::Principal {
        principal_scope_digest: digest("another-principal"),
        source_digest: source.structured_intent.provenance.source_digest,
    };
    assert!(compile_authoritative_objective_v1(&source, &frozen, &wrong_scope).is_err());

    let mut stale = current.clone();
    stale.now_unix_micros = stale
        .now_unix_micros
        .checked_add(raw.maximum_source_age_micros + 1)
        .expect("test timestamp");
    assert_eq!(
        compile_authoritative_objective_v1(&source, &frozen, &stale),
        Err(ObjectiveAdmissionError::SourceStale)
    );

    let mut wrong_profile = current.clone();
    wrong_profile.selected_profile_digest = digest("another-profile");
    assert_eq!(
        compile_authoritative_objective_v1(&source, &frozen, &wrong_profile),
        Err(ObjectiveAdmissionError::ProfileDigestMismatch)
    );

    let mut next = current;
    next.now_unix_micros += 1;
    let second = compile_authoritative_objective_v1(&source, &frozen, &next)
        .expect("new request-local admission");
    assert_ne!(first.proof().proof_digest(), second.proof().proof_digest());
    assert_eq!(first.outcome().compile_result, second.outcome().compile_result);
    assert_eq!(frozen.reuse_key(), key);
    assert_eq!(key.profile_digest, frozen.profile_digest());
    assert_eq!(key.profile_revision, raw.profile_revision.get());
    assert!(!key.compiler_contract_digest.is_zero());
}
''',
    "frozen_profile_reuse_never_caches_authentication_time_or_profile_selection",
)


print("objective_profile_reuse_edit.py: applied")
