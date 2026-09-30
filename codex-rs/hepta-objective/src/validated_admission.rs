//! Indexed admission for authoritative objective publication.
//!
//! Static profile validation remains here. Product admission uses the frozen
//! lookup indexes in `indexed_admission`; proof encoding/verification lives in
//! `admission_proof`, while authority-bearing and diagnostic result types live
//! in `admission_results`. Product composition must freeze a profile through
//! [`ValidatedAdmissionProfileV1`] and call
//! [`compile_authoritative_objective_v1`].

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ObjectiveAbstentionRuleProfileV1;
use crate::ObjectiveActionProfileV1;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveConstraintProfileV1;
use crate::ObjectiveEvidenceProfileV1;
use crate::ObjectivePredicateProfileV1;
use crate::ObjectiveSoftDimensionProfileV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::admission_proof::build_admission_proof_v1;
use crate::admission_proof::compiler_contract_digest_v1;
use crate::admission_proof::source_envelope_proof_digest_v1;
use crate::admission_results::ObjectivePreflightReportV1;
use crate::admission_results::ProofBearingObjectiveCompileV1;
use crate::admission_results::ValidatedObjectiveAdmissionV1;
use crate::compile_admitted_objective_v1;
use crate::indexed_admission::admit_indexed_objective_v1;
use crate::objective_admission::admit_frozen_objective_v1;

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

/// Frozen profile plus lookup indexes and collision proofs used by authoritative
/// product composition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedAdmissionProfileV1 {
    profile: ObjectiveAdmissionProfileV1,
    profile_digest: Digest32,
    allowed_locales: BTreeSet<String>,
    trusted_source_identities: BTreeSet<StableId>,
    constraint_sources: BTreeMap<String, usize>,
    predicate_sources: BTreeMap<String, usize>,
    action_sources: BTreeMap<String, usize>,
    soft_sources: BTreeMap<String, usize>,
    evidence_sources: BTreeMap<String, usize>,
    abstention_sources: BTreeMap<String, usize>,
    semantic_ids: BTreeSet<StableId>,
}

impl ValidatedAdmissionProfileV1 {
    pub fn new(profile: ObjectiveAdmissionProfileV1) -> Result<Self, ObjectiveAdmissionError> {
        let profile_digest = profile.digest()?;
        let allowed_locales = profile.allowed_locales.iter().cloned().collect();
        let trusted_source_identities = profile
            .allowed_trusted_source_identities
            .iter()
            .cloned()
            .collect();
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
        let abstention_sources = source_index(
            profile
                .risk
                .abstention_rules
                .iter()
                .map(|mapping| mapping.source_rule.as_str()),
            "abstention rule source index",
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
            allowed_locales,
            trusted_source_identities,
            constraint_sources,
            predicate_sources,
            action_sources,
            soft_sources,
            evidence_sources,
            abstention_sources,
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
    pub fn reuse_key(&self) -> ValidatedAdmissionProfileReuseKeyV1 {
        ValidatedAdmissionProfileReuseKeyV1 {
            profile_digest: self.profile_digest,
            profile_revision: self.profile.profile_revision.get(),
            compiler_contract_digest: compiler_contract_digest_v1(),
        }
    }

    #[must_use]
    pub fn locale_allowed(&self, locale: &str) -> bool {
        self.allowed_locales.contains(locale)
    }

    #[must_use]
    pub fn trusted_source_identity_allowed(&self, identity: &StableId) -> bool {
        self.trusted_source_identities.contains(identity)
    }

    #[must_use]
    pub fn constraint(&self, source_id: &str) -> Option<&ObjectiveConstraintProfileV1> {
        self.constraint_sources
            .get(source_id)
            .and_then(|index| self.profile.constraints.get(*index))
    }

    #[must_use]
    pub fn predicate(&self, source_id: &str) -> Option<&ObjectivePredicateProfileV1> {
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
    pub fn soft_dimension(&self, source_id: &str) -> Option<&ObjectiveSoftDimensionProfileV1> {
        self.soft_sources
            .get(source_id)
            .and_then(|index| self.profile.soft_dimensions.get(*index))
    }

    #[must_use]
    pub fn evidence_requirement(&self, source_id: &str) -> Option<&ObjectiveEvidenceProfileV1> {
        self.evidence_sources
            .get(source_id)
            .and_then(|index| self.profile.evidence_requirements.get(*index))
    }

    #[must_use]
    pub fn abstention_rule(&self, source_rule: &str) -> Option<&ObjectiveAbstentionRuleProfileV1> {
        self.abstention_sources
            .get(source_rule)
            .and_then(|index| self.profile.risk.abstention_rules.get(*index))
    }

    #[must_use]
    pub fn owns_semantic_id(&self, id: &StableId) -> bool {
        self.semantic_ids.contains(id)
    }
}

/// Authoritative indexed admission boundary used by durable publication paths.
pub fn admit_validated_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ValidatedObjectiveAdmissionV1, ObjectiveAdmissionError> {
    let (source, receipt) = admit_indexed_objective_v1(envelope, profile, context)?;
    let proof = build_admission_proof_v1(
        envelope,
        profile,
        context,
        receipt.admitted_source_digest,
    )?;
    Ok(ValidatedObjectiveAdmissionV1::new(source, receipt, proof))
}

/// Consume a proof-bearing indexed admission and compile it once.
pub fn compile_validated_objective_v1(
    admitted: ValidatedObjectiveAdmissionV1,
) -> Result<ProofBearingObjectiveCompileV1, ObjectiveAdmissionError> {
    let (source, receipt, proof) = admitted.into_parts();
    let compile_result = crate::compiler::compile(source)?;
    Ok(ProofBearingObjectiveCompileV1::new(
        ObjectiveAdmissionOutcomeV1 {
            receipt,
            compile_result,
        },
        proof,
    ))
}

/// Canonical authoritative source-to-native boundary. Durable publication code
/// should call this function and bind its private publication token to the exact
/// destination/run/predecessor/generation/fence before projection.
pub fn compile_authoritative_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ProofBearingObjectiveCompileV1, ObjectiveAdmissionError> {
    compile_validated_objective_v1(admit_validated_objective_v1(envelope, profile, context)?)
}

/// Strict diagnostics-only compatibility boundary. It performs full raw-profile
/// admission and native compilation but constructs neither an admission proof nor
/// publication token.
pub fn preflight_validate_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ObjectivePreflightReportV1, ObjectiveAdmissionError> {
    let validated = ValidatedAdmissionProfileV1::from_profile(profile)?;
    let admitted = admit_frozen_objective_v1(envelope, &validated, context)?;
    let outcome = compile_admitted_objective_v1(admitted)?;
    Ok(ObjectivePreflightReportV1::new(
        outcome,
        source_envelope_proof_digest_v1(envelope)?,
        validated.profile_digest(),
        compiler_contract_digest_v1(),
    ))
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
        profile
            .resources
            .external_effect_count
            .constraint_id
            .clone(),
        profile.risk.risk_constraint_id.clone(),
        profile.risk.rollback_constraint_id.clone(),
        profile.risk.compensation_constraint_id.clone(),
        profile.risk.abstention_constraint_id.clone(),
    ]
}

#[cfg(test)]
#[path = "validated_admission_tests.rs"]
mod tests;
