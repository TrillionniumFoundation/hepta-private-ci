#!/usr/bin/env python3
"""Development-only source edit. This script never issues qualification evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path, old, new, count=1):
    p = ROOT / path
    text = p.read_text()
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f'{path}: expected {count} occurrences, found {actual}: {old[:100]!r}')
    p.write_text(text.replace(old, new))


p = 'codex-rs/hepta-objective/src/objective_admission.rs'
replace(p, '''    envelope.validate_structure()?;
    let profile_digest = profile.digest()?;
    if context.selected_profile_digest != profile_digest {''', '''    envelope.validate_structure()?;
    let profile_digest = profile.digest()?;
    admit_profile_bound_objective_v1(envelope, profile, context, profile_digest)
}

/// Internal typed boundary: only a frozen, owner-validated profile supplies the
/// cached digest. Authentication, source freshness and deadlines are never cached.
pub(crate) fn admit_frozen_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &crate::ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    admit_profile_bound_objective_v1(envelope, profile.profile(), context, profile.profile_digest())
}

fn admit_profile_bound_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    profile_digest: Digest32,
) -> Result<AdmittedObjectiveV1, ObjectiveAdmissionError> {
    if context.selected_profile_digest != profile_digest {''')

p = 'codex-rs/hepta-objective/src/validated_admission.rs'
replace(p, 'use crate::admit_objective_v1;', 'use crate::objective_admission::admit_frozen_objective_v1;')
replace(p, 'let admitted = admit_objective_v1(envelope, profile.profile(), context)?;', 'let admitted = admit_frozen_objective_v1(envelope, profile, context)?;')
replace(p, '''    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub fn constraint(
''', '''    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    /// Static reuse identity only; this never stands in for a current grant.
    #[must_use]
    pub fn reuse_key(&self) -> (Digest32, u64, Digest32) {
        (
            self.profile_digest,
            self.profile.profile_revision.get(),
            Digest32::of_bytes(COMPILER_CONTRACT_V1),
        )
    }

    #[must_use]
    pub fn constraint(
''')
needle = '''    pub fn into_parts(self) -> (ObjectiveAdmissionOutcomeV1, ObjectiveAdmissionProofV1) {
        (self.outcome, self.proof)
    }
'''
replace(p, needle, needle + '''
    /// Rebind projection inputs without reconstructing a caller-controlled
    /// receipt or recompiling. Only this module can construct the outcome/proof
    /// pair, and the complete source-envelope identity is checked again.
    pub(crate) fn validate_projection_inputs(
        &self,
        envelope: &ObjectiveSourceEnvelopeV1,
        profile: &ValidatedAdmissionProfileV1,
    ) -> Result<(), crate::ObjectiveFunctionV1Error> {
        let source_digest = source_envelope_digest(envelope).map_err(|_| {
            crate::ObjectiveFunctionV1Error::ProjectionMismatch("proof source envelope")
        })?;
        if source_digest != self.proof.source_envelope_digest
            || envelope.intent_digest != self.outcome.receipt.intent_digest
            || profile.profile_digest() != self.proof.profile_digest
            || Digest32::of_bytes(COMPILER_CONTRACT_V1) != self.proof.compiler_contract_digest
            || self.outcome.receipt.profile_digest != self.proof.profile_digest
            || self.outcome.receipt.admitted_source_digest != self.proof.admitted_source_digest
        {
            return Err(crate::ObjectiveFunctionV1Error::ProjectionMismatch(
                "proof-bearing projection binding",
            ));
        }
        Ok(())
    }
''')

p = 'codex-rs/hepta-objective/src/objective_function_v1.rs'
marker = 'fn validate_projection_binding(\n'
replace(p, marker, '''/// Encode an opaque authoritative compile outcome without a second admission
/// or feasibility solve. Static source/profile identities are rebound; current
/// authentication and effect authority remain the product owner's obligation.
pub fn encode_proof_bearing_objective_function_v1(
    proof_bearing: &crate::ProofBearingObjectiveCompileV1,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &crate::ValidatedAdmissionProfileV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    proof_bearing.validate_projection_inputs(source, profile)?;
    let outcome = proof_bearing.outcome();
    let compiled = outcome.compile_result.as_ref().map_err(|_| {
        ObjectiveFunctionV1Error::ProjectionMismatch("compiled/conflict disposition")
    })?;
    encode_validated(compiled, source, profile.profile(), &outcome.receipt)
}

''' + marker)

p = 'codex-rs/hepta-objective/src/lib.rs'
replace(p, 'pub use objective_function_v1::encode_authenticated_objective_function_v1;', 'pub use objective_function_v1::encode_authenticated_objective_function_v1;\npub use objective_function_v1::encode_proof_bearing_objective_function_v1;')

p = 'codex-rs/hepta-intelligence/src/objective_run.rs'
replace(p, 'use codex_hepta_objective::encode_authenticated_objective_function_v1;', 'use codex_hepta_objective::encode_proof_bearing_objective_function_v1;')
replace(p, '''    let validated_profile = ValidatedAdmissionProfileV1::from_profile(profile)?;
    let proof_bearing =
        compile_authoritative_objective_v1(envelope, &validated_profile, context)?;
    let (outcome, admission_proof) = proof_bearing.into_parts();''', '''    let validated_profile = ValidatedAdmissionProfileV1::from_profile(profile)?;
    compile_and_publish_validated_objective_run_v1(
        envelope, &validated_profile, context, bindings, journal,
    )
}

/// Product entrypoint with a process-generation-frozen semantic profile. Each
/// invocation still checks admission using the supplied current authenticated
/// context. The destination owner remains the only durable run-start writer.
pub fn compile_and_publish_validated_objective_run_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunBindingsV1,
    journal: &mut dyn RunStartJournal,
) -> Result<PublishedObjectiveRunV1, ObjectiveRunError> {
    let proof_bearing = compile_authoritative_objective_v1(envelope, profile, context)?;
    let protocol = if proof_bearing.outcome().compile_result.is_ok() {
        Some(encode_proof_bearing_objective_function_v1(&proof_bearing, envelope, profile)?)
    } else {
        None
    };
    let (outcome, admission_proof) = proof_bearing.into_parts();''')
replace(p, '''    let objective_function_v1 = encode_authenticated_objective_function_v1(
        &objective, envelope, profile, context, &receipt,
    )?;''', '''    let objective_function_v1 = protocol.ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
        "compiled objective requires a proof-bound protocol artifact",
    ))?;''')

p = 'codex-rs/hepta-intelligence/src/lib.rs'
replace(p, 'pub use objective_run::compile_and_publish_objective_run_v1;', 'pub use objective_run::compile_and_publish_objective_run_v1;\npub use objective_run::compile_and_publish_validated_objective_run_v1;')

p = 'codex-rs/hepta-agentd/src/objective_runtime.rs'
replace(p, 'use codex_hepta_intelligence::compile_and_publish_objective_run_v1;', 'use codex_hepta_intelligence::compile_and_publish_validated_objective_run_v1;')
replace(p, 'use codex_hepta_objective::ObjectiveAdmissionProfileV1;', 'use codex_hepta_objective::ValidatedAdmissionProfileV1;')
replace(p, '    profile: ObjectiveAdmissionProfileV1,', '    profile: ValidatedAdmissionProfileV1,')
replace(p, '''        let profile_digest = profile
            .digest()
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;''', '''        let profile = ValidatedAdmissionProfileV1::new(profile)
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;
        let profile_digest = profile.profile_digest();''')
replace(p, 'match compile_and_publish_objective_run_v1(', 'match compile_and_publish_validated_objective_run_v1(')

p = ROOT / 'codex-rs/hepta-objective/src/validated_admission_tests.rs'
p.write_text(p.read_text() + r'''

#[test]
fn cached_profile_never_caches_current_source_authentication_or_time() {
    let raw = profile();
    let source = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen profile");
    let current = context(&raw, &source);
    let key = frozen.reuse_key();
    let first = compile_authoritative_objective_v1(&source, &frozen, &current)
        .expect("current admission");
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
    stale.now_unix_micros += raw.maximum_source_age_micros + 1;
    assert!(compile_authoritative_objective_v1(&source, &frozen, &stale).is_err());
    let mut drifted_profile = current.clone();
    drifted_profile.selected_profile_digest = digest("another-profile");
    assert!(compile_authoritative_objective_v1(&source, &frozen, &drifted_profile).is_err());
    let mut next = current;
    next.now_unix_micros += 1;
    let second = compile_authoritative_objective_v1(&source, &frozen, &next)
        .expect("new current admission, same static profile");
    assert_ne!(first.proof().proof_digest(), second.proof().proof_digest());
    assert_eq!(first.outcome().compile_result, second.outcome().compile_result);
    assert_eq!(frozen.reuse_key(), key);
}

#[test]
fn proof_bound_encoder_matches_authenticated_encoder_and_rejects_substitution() {
    let raw = profile();
    let original = source();
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen profile");
    let current = context(&raw, &original);
    let compiled = compile_authoritative_objective_v1(&original, &frozen, &current)
        .expect("authoritative compilation");
    let outcome = compiled.outcome();
    let expected = crate::encode_authenticated_objective_function_v1(
        outcome.compile_result.as_ref().expect("feasible"), &original, &raw,
        &current, &outcome.receipt,
    ).expect("independently replayed encoding");
    let actual = crate::encode_proof_bearing_objective_function_v1(&compiled, &original, &frozen)
        .expect("opaque proof-bound encoding");
    assert_eq!(actual, expected);
    assert!(!outcome.receipt.authority.grants_any());
    let mut changed = original.clone();
    changed.request_id = "request.substituted".to_owned();
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &changed, &frozen).is_err());
    changed = original.clone();
    changed.intent_digest = digest("supplied-intent-drift");
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &changed, &frozen).is_err());
    changed = original.clone();
    changed.deadline = Some("2026-09-08T10:06:00Z".to_owned());
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &changed, &frozen).is_err());
    changed = original.clone();
    changed.structured_intent.resources.token_count += 1;
    changed.intent_digest = canonical_objective_intent_digest_v1(&changed).expect("new intent");
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &changed, &frozen).is_err());
    let mut revised = raw;
    revised.profile_revision = Revision::new(2).expect("new revision");
    let revised = ValidatedAdmissionProfileV1::new(revised).expect("new frozen profile");
    assert_ne!(frozen.reuse_key(), revised.reuse_key());
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &original, &revised).is_err());
}

#[test]
fn proof_bound_encoder_never_projects_a_hard_conflict_as_a_run() {
    let raw = profile();
    let mut source = source();
    source.structured_intent.forbidden_action_classes.push("read".to_owned());
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("intent");
    let frozen = ValidatedAdmissionProfileV1::from_profile(&raw).expect("frozen");
    let current = context(&raw, &source);
    let compiled = compile_authoritative_objective_v1(&source, &frozen, &current)
        .expect("authenticated conflict outcome");
    assert!(compiled.outcome().compile_result.is_err());
    assert!(crate::encode_proof_bearing_objective_function_v1(&compiled, &source, &frozen).is_err());
}
''')
print('Applied source edits to the existing Agentd/intelligence/objective path. No qualification was executed.')
