//! Indexed, proof-bearing admission for authoritative objective publication.
//!
//! The legacy V1 entrypoints remain available for compatibility fixtures. New
//! product composition must first freeze and validate a profile through
//! [`ValidatedAdmissionProfileV1`], then use
//! [`compile_authoritative_objective_v1`]. This closes target collisions before
//! source adaptation, rejects deadlines that cannot be represented exactly by
//! `ObjectiveFunctionV1`, and carries a non-forgeable provenance proof beside
//! the native compile outcome.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmittedObjectiveV1;
use crate::ObjectiveActionProfileV1;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveConstraintProfileV1;
use crate::ObjectiveEvidenceProfileV1;
use crate::ObjectivePredicateProfileV1;
use crate::ObjectiveSoftDimensionProfileV1;
use crate::ObjectiveSourceAuthenticationV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourceTrustV1;
use crate::admit_objective_v1;
use crate::canonical_objective_intent_digest_v1;
use crate::compile_admitted_objective_v1;

const COMPILER_CONTRACT_V1: &[u8] = b"hepta.objective.compiler.contract.v1:indexed-profile:exact-ms-deadline:proof-bearing-admission";

/// Frozen profile plus indexes and collision proofs used by authoritative
/// product composition.
///
/// Construction reuses the complete V1 profile validation and then strengthens
/// it with target uniqueness and a single semantic-identity namespace for all
/// native constraints and predicates produced by admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedAdmissionProfileV1 {
    profile: ObjectiveAdmissionProfileV1,
    profile_digest: Digest32,
    constraint_sources: BTreeMap<String, usize>,
    predicate_sources: BTreeMap<String, usize>,
    action_sources: BTreeMap<String, usize>,
    soft_sources: BTreeMap<String, usize>,
    evidence_sources: BTreeMap<String, usize>,
    semantic_ids: BTreeSet<StableId>,
}

impl ValidatedAdmissionProfileV1 {
    pub fn new(profile: ObjectiveAdmissionProfileV1) -> Result<Self, ObjectiveAdmissionError> {
        let profile_digest = profile.digest()?;
        let constraint_sources = source_index(
            profile
                .constraints
                .iter()
                .map(|mapping| mapping.source_constraint_id.as_str()),
            "constraint source index",
        )?;
        let predicate_sources = source_index(
            profile
                .predicates
                .iter()
                .map(|mapping| mapping.source_predicate_id.as_str()),
            "predicate source index",
        )?;
        let action_sources = source_index(
            profile
                .actions
                .iter()
                .map(|mapping| mapping.source_action_class.as_str()),
            "action source index",
        )?;
        let soft_sources = source_index(
            profile
                .soft_dimensions
                .iter()
                .map(|mapping| mapping.source_dimension_id.as_str()),
            "soft source index",
        )?;
        let evidence_sources = source_index(
            profile
                .evidence_requirements
                .iter()
                .map(|mapping| mapping.source_requirement_id.as_str()),
            "evidence source index",
        )?;

        unique_targets(
            profile.actions.iter().map(|mapping| &mapping.action_id),
            "duplicate action target",
        )?;
        if profile
            .actions
            .iter()
            .any(|mapping| mapping.action_id.as_str() == "abstain")
        {
            return Err(ObjectiveAdmissionError::InvalidProfile(
                "reserved abstain action target",
            ));
        }
        unique_targets(
            profile
                .soft_dimensions
                .iter()
                .map(|mapping| &mapping.dimension),
            "duplicate soft target",
        )?;

        let mut semantic_ids = BTreeSet::new();
        for source_id in profile
            .constraints
            .iter()
            .map(|mapping| mapping.source_constraint_id.as_str())
            .chain(
                profile
                    .predicates
                    .iter()
                    .map(|mapping| mapping.source_predicate_id.as_str()),
            )
            .chain(
                profile
                    .evidence_requirements
                    .iter()
                    .map(|mapping| mapping.source_requirement_id.as_str()),
            )
        {
            insert_semantic_id(
                &mut semantic_ids,
                StableId::new(source_id.to_owned()).map_err(|_| {
                    ObjectiveAdmissionError::InvalidProfile("semantic source identity")
                })?,
            )?;
        }
        for id in generated_constraint_ids(&profile) {
            insert_semantic_id(&mut semantic_ids, id)?;
        }

        Ok(Self {
            profile,
            profile_digest,
            constraint_sources,
            predicate_sources,
            action_sources,
            soft_sources,
            evidence_sources,
            semantic_ids,
        })
    }

    pub fn from_profile(
        profile: &ObjectiveAdmissionProfileV1,
    ) -> Result<Self, ObjectiveAdmissionError> {
        Self::new(profile.clone())
    }

    #[must_use]
    pub const fn profile(&self) -> &ObjectiveAdmissionProfileV1 {
        &self.profile
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub fn constraint(
        &self,
        source_id: &str,
    ) -> Option<&ObjectiveConstraintProfileV1> {
        self.constraint_sources
            .get(source_id)
            .and_then(|index| self.profile.constraints.get(*index))
    }

    #[must_use]
    pub fn predicate(
        &self,
        source_id: &str,
    ) -> Option<&ObjectivePredicateProfileV1> {
        self.predicate_sources
            .get(source_id)
            .and_then(|index| self.profile.predicates.get(*index))
    }

    #[must_use]
    pub fn action(&self, source_id: &str) -> Option<&ObjectiveActionProfileV1> {
        self.action_sources
            .get(source_id)
            .and_then(|index| self.profile.actions.get(*index))
    }

    #[must_use]
    pub fn soft_dimension(
        &self,
        source_id: &str,
    ) -> Option<&ObjectiveSoftDimensionProfileV1> {
        self.soft_sources
            .get(source_id)
            .and_then(|index| self.profile.soft_dimensions.get(*index))
    }

    #[must_use]
    pub fn evidence_requirement(
        &self,
        source_id: &str,
    ) -> Option<&ObjectiveEvidenceProfileV1> {
        self.evidence_sources
            .get(source_id)
            .and_then(|index| self.profile.evidence_requirements.get(*index))
    }

    #[must_use]
    pub fn owns_semantic_id(&self, id: &StableId) -> bool {
        self.semantic_ids.contains(id)
    }
}

/// Provenance bound to one authenticated admission and native compile.
///
/// Fields are private so downstream code cannot construct a proof from a set of
/// mutually consistent but independently forged receipts.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionProofV1 {
    source_envelope_digest: Digest32,
    profile_digest: Digest32,
    authentication_context_digest: Digest32,
    compiler_contract_digest: Digest32,
    admitted_source_digest: Digest32,
    proof_digest: Digest32,
}

impl ObjectiveAdmissionProofV1 {
    #[must_use]
    pub const fn source_envelope_digest(&self) -> Digest32 {
        self.source_envelope_digest
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub const fn authentication_context_digest(&self) -> Digest32 {
        self.authentication_context_digest
    }

    #[must_use]
    pub const fn compiler_contract_digest(&self) -> Digest32 {
        self.compiler_contract_digest
    }

    #[must_use]
    pub const fn admitted_source_digest(&self) -> Digest32 {
        self.admitted_source_digest
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }
}

/// Opaque admission capability consumed exactly once by native compilation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedObjectiveAdmissionV1 {
    admitted: AdmittedObjectiveV1,
    proof: ObjectiveAdmissionProofV1,
}

impl ValidatedObjectiveAdmissionV1 {
    #[must_use]
    pub fn receipt(&self) -> &crate::ObjectiveAdmissionReceiptV1 {
        self.admitted.receipt()
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }
}

/// Native compile outcome that remains inseparable from its admission proof.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProofBearingObjectiveCompileV1 {
    outcome: ObjectiveAdmissionOutcomeV1,
    proof: ObjectiveAdmissionProofV1,
}

impl ProofBearingObjectiveCompileV1 {
    #[must_use]
    pub const fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }

    #[must_use]
    pub fn into_parts(self) -> (ObjectiveAdmissionOutcomeV1, ObjectiveAdmissionProofV1) {
        (self.outcome, self.proof)
    }
}

/// Authoritative admission boundary used by durable publication paths.
pub fn admit_validated_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ValidatedObjectiveAdmissionV1, ObjectiveAdmissionError> {
    let admitted = admit_objective_v1(envelope, profile.profile(), context)?;
    if admitted
        .receipt()
        .deadline_unix_micros
        .is_some_and(|deadline| deadline % 1_000 != 0)
    {
        return Err(ObjectiveAdmissionError::InvalidTimestamp(
            "deadline millisecond precision",
        ));
    }
    let proof = admission_proof(envelope, profile, context, &admitted)?;
    Ok(ValidatedObjectiveAdmissionV1 { admitted, proof })
}

/// Consume a proof-bearing admission and compile it once.
pub fn compile_validated_objective_v1(
    admitted: ValidatedObjectiveAdmissionV1,
) -> Result<ProofBearingObjectiveCompileV1, ObjectiveAdmissionError> {
    let ValidatedObjectiveAdmissionV1 { admitted, proof } = admitted;
    let outcome = compile_admitted_objective_v1(admitted)?;
    Ok(ProofBearingObjectiveCompileV1 { outcome, proof })
}

/// Canonical authoritative source-to-native boundary. Durable publication code
/// should call this function and persist the returned proof digest beside the
/// protocol and run-start identities.
pub fn compile_authoritative_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ProofBearingObjectiveCompileV1, ObjectiveAdmissionError> {
    compile_validated_objective_v1(admit_validated_objective_v1(
        envelope, profile, context,
    )?)
}

/// Compatibility preflight with an explicit non-publication name. It performs
/// the same strict validation and proof construction, but grants no durable
/// publication or effect authority.
pub fn preflight_validate_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ProofBearingObjectiveCompileV1, ObjectiveAdmissionError> {
    let validated = ValidatedAdmissionProfileV1::from_profile(profile)?;
    compile_authoritative_objective_v1(envelope, &validated, context)
}

fn admission_proof(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    admitted: &AdmittedObjectiveV1,
) -> Result<ObjectiveAdmissionProofV1, ObjectiveAdmissionError> {
    let source_envelope_digest = source_envelope_digest(envelope)?;
    let authentication_context_digest = authentication_context_digest(context);
    let compiler_contract_digest = Digest32::of_bytes(COMPILER_CONTRACT_V1);
    let admitted_source_digest = admitted.receipt().admitted_source_digest;
    let mut bytes = b"hepta.objective.admission-proof.v1".to_vec();
    for digest in [
        source_envelope_digest,
        profile.profile_digest(),
        authentication_context_digest,
        compiler_contract_digest,
        admitted_source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let proof_digest = Digest32::of_bytes(&bytes);
    Ok(ObjectiveAdmissionProofV1 {
        source_envelope_digest,
        profile_digest: profile.profile_digest(),
        authentication_context_digest,
        compiler_contract_digest,
        admitted_source_digest,
        proof_digest,
    })
}

fn source_envelope_digest(
    envelope: &ObjectiveSourceEnvelopeV1,
) -> Result<Digest32, ObjectiveAdmissionError> {
    let intent_digest = canonical_objective_intent_digest_v1(envelope)?;
    let mut bytes = b"hepta.objective.source-envelope-proof.v1".to_vec();
    push_text(&mut bytes, &envelope.request_id);
    push_digest(&mut bytes, envelope.principal_scope_digest);
    push_digest(&mut bytes, intent_digest);
    push_digest(&mut bytes, envelope.input_schema_digest);
    push_text(&mut bytes, &envelope.locale);
    push_text(&mut bytes, &envelope.observed_at);
    match &envelope.deadline {
        Some(deadline) => {
            bytes.push(1);
            push_text(&mut bytes, deadline);
        }
        None => bytes.push(0),
    }
    bytes.push(match envelope.source_trust_class {
        ObjectiveSourceTrustV1::Principal => 1,
        ObjectiveSourceTrustV1::TrustedSystem => 2,
        ObjectiveSourceTrustV1::AuthorizedAdapter => 3,
        ObjectiveSourceTrustV1::UntrustedEvidence => 4,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn authentication_context_digest(context: &ObjectiveAdmissionContextV1) -> Digest32 {
    let mut bytes = b"hepta.objective.authentication-context.v1".to_vec();
    bytes.extend_from_slice(&context.revision.get().to_be_bytes());
    bytes.extend_from_slice(&context.now_unix_micros.to_be_bytes());
    push_digest(&mut bytes, context.selected_profile_digest);
    match &context.source_authentication {
        ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest,
            source_digest,
        } => {
            bytes.push(1);
            push_digest(&mut bytes, *principal_scope_digest);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::TrustedSystem {
            source_identity,
            source_digest,
        } => {
            bytes.push(2);
            push_id(&mut bytes, source_identity);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity,
            source_digest,
        } => {
            bytes.push(3);
            push_id(&mut bytes, source_identity);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::UntrustedEvidence { source_digest } => {
            bytes.push(4);
            push_digest(&mut bytes, *source_digest);
        }
    }
    Digest32::of_bytes(&bytes)
}

fn source_index<'a>(
    values: impl Iterator<Item = &'a str>,
    field: &'static str,
) -> Result<BTreeMap<String, usize>, ObjectiveAdmissionError> {
    let mut index = BTreeMap::new();
    for (position, value) in values.enumerate() {
        if index.insert(value.to_owned(), position).is_some() {
            return Err(ObjectiveAdmissionError::InvalidProfile(field));
        }
    }
    Ok(index)
}

fn unique_targets<'a>(
    values: impl Iterator<Item = &'a StableId>,
    field: &'static str,
) -> Result<(), ObjectiveAdmissionError> {
    let mut targets = BTreeSet::new();
    for value in values {
        if !targets.insert(value.clone()) {
            return Err(ObjectiveAdmissionError::InvalidProfile(field));
        }
    }
    Ok(())
}

fn insert_semantic_id(
    values: &mut BTreeSet<StableId>,
    value: StableId,
) -> Result<(), ObjectiveAdmissionError> {
    if !values.insert(value) {
        return Err(ObjectiveAdmissionError::InvalidProfile(
            "global semantic identity collision",
        ));
    }
    Ok(())
}

fn generated_constraint_ids(profile: &ObjectiveAdmissionProfileV1) -> Vec<StableId> {
    vec![
        profile.resources.time_micros.constraint_id.clone(),
        profile.resources.token_count.constraint_id.clone(),
        profile.resources.compute_micros.constraint_id.clone(),
        profile.resources.memory_bytes.constraint_id.clone(),
        profile.resources.network_bytes.constraint_id.clone(),
        profile.resources.external_effect_count.constraint_id.clone(),
        profile.risk.risk_constraint_id.clone(),
        profile.risk.rollback_constraint_id.clone(),
        profile.risk.compensation_constraint_id.clone(),
        profile.risk.abstention_constraint_id.clone(),
    ]
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let len = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

#[cfg(test)]
#[path = "validated_admission_tests.rs"]
mod tests;
