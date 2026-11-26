//! Authority-free DecisionCell adapter for calibrated intuition receipts.
//!
//! `hepta-intuition` owns the calibrated decision kernel and (when used by the
//! host) the authenticated profile/evidence admission.  This module binds the
//! resulting receipt to the shared `CellRoleStepV1` contract.  It deliberately
//! does not load a policy, mutate a route, persist state, or dispatch an action.
//! A target-host owner must supply the policy/evidence binding and the committed
//! successor state digest.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::AbstentionReasonV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::SlowPathReasonV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CellAdapterContextV1;
use crate::CellRoleAdapterErrorV1;
use crate::CellRoleStepV1;
use crate::digest_bytes;
use crate::step_receipt;

/// Versioned schema for the typed Decision result and its receipt binding.
pub const DECISION_SCHEMA_V1: &str = "hepta.cell-role.decision.v1";
/// The calibrated policy kernel remains the execution owner.  This adapter is
/// only the role projection and receipt binder.
pub const DECISION_OWNER_MODULE: &str = "hepta-intuition::decide_calibrated_v3";

/// Policy and candidate-set facts supplied by the owner that authenticated the
/// intuition request.  The calibrated receipt intentionally does not duplicate
/// every request field, so these facts are carried as an explicit binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionPolicyBindingV1 {
    pub policy_digest: Digest32,
    pub policy_profile_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub candidate_order_digest: Digest32,
    pub policy_generation: u64,
    pub sequence: u64,
}

impl DecisionPolicyBindingV1 {
    pub fn validate(&self) -> Result<(), DecisionAdapterErrorV1> {
        for (label, digest) in [
            ("policy", self.policy_digest),
            ("policy profile", self.policy_profile_digest),
            ("candidate set", self.candidate_set_digest),
            ("candidate order", self.candidate_order_digest),
        ] {
            if digest.is_zero() {
                return Err(DecisionAdapterErrorV1::EmptyDigest(label));
            }
        }
        Ok(())
    }
}

/// Authentication evidence produced by the host/evaluator boundary.  The
/// adapter binds these digests but never verifies signatures itself; signature
/// verification remains owned by `hepta-intelligence` and the host trust
/// snapshot.  `runtime_payload_digest` is optional so both authenticated V1
/// (profile qualification) and V2 (per-decision observer) evidence can be
/// represented without weakening the binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionAuthenticationBindingV1 {
    pub trust_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub qualification_payload_digest: Digest32,
    pub runtime_payload_digest: Option<Digest32>,
    pub authentication_digest: Digest32,
}

impl DecisionAuthenticationBindingV1 {
    pub fn validate(&self) -> Result<(), DecisionAdapterErrorV1> {
        for (label, digest) in [
            ("trust", self.trust_digest),
            ("completeness payload", self.completeness_payload_digest),
            ("qualification payload", self.qualification_payload_digest),
            ("authentication", self.authentication_digest),
        ] {
            if digest.is_zero() {
                return Err(DecisionAdapterErrorV1::EmptyDigest(label));
            }
        }
        if let Some(digest) = self.runtime_payload_digest
            && digest.is_zero()
        {
            return Err(DecisionAdapterErrorV1::EmptyDigest("runtime payload"));
        }
        Ok(())
    }
}

/// Facts supplied by the real Decision owner for one invocation.  In
/// particular, the successor state must be a committed/checkpointed state
/// digest from that owner; the adapter never invents it from the predecessor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionExecutionBindingV1 {
    pub policy: DecisionPolicyBindingV1,
    pub authentication: Option<DecisionAuthenticationBindingV1>,
    pub completeness_receipt_digest: Digest32,
    pub state_successor_digest: Digest32,
    pub uncertainty_ppm: u32,
    pub ood_ppm: u32,
}

impl DecisionExecutionBindingV1 {
    pub fn validate(&self) -> Result<(), DecisionAdapterErrorV1> {
        self.policy.validate()?;
        if self.completeness_receipt_digest.is_zero() {
            return Err(DecisionAdapterErrorV1::EmptyDigest("completeness receipt"));
        }
        if self.state_successor_digest.is_zero() {
            return Err(DecisionAdapterErrorV1::EmptyDigest("state successor"));
        }
        if self.uncertainty_ppm > 1_000_000 || self.ood_ppm > 1_000_000 {
            return Err(DecisionAdapterErrorV1::InvalidPpm);
        }
        if let Some(authentication) = &self.authentication {
            authentication.validate()?;
        }
        Ok(())
    }
}

/// Typed output of DecisionCell.  It contains no action capability.  A
/// selected candidate can be converted into an `ActionProposalV1`, but effect
/// execution remains owned by the downstream effect boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionResultV1 {
    pub decision_id: StableId,
    /// Exact calibrated-intuition receipt that was projected.  Keeping this
    /// separate from the derived output digest prevents a caller from
    /// replacing the receipt digest while leaving the visible disposition
    /// fields unchanged.
    pub intuition_receipt_digest: Digest32,
    pub disposition_digest: Digest32,
    pub selected_candidate: Option<StableId>,
    pub selected_propensity_raw_q32: u64,
    pub policy_digest: Digest32,
    pub policy_profile_digest: Digest32,
    pub completeness_receipt_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub candidate_order_digest: Digest32,
    pub propensity_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub policy_generation: u64,
    pub sequence: u64,
    pub candidate_count: u32,
    pub abstain_probability_raw_q32: u64,
    pub slow_path_probability_raw_q32: u64,
    pub authentication_digest: Option<Digest32>,
    pub authority: AuthorityPosture,
}

impl DecisionResultV1 {
    pub fn validate(&self) -> Result<(), DecisionAdapterErrorV1> {
        if self.decision_id.as_str().is_empty() {
            return Err(DecisionAdapterErrorV1::EmptyId("decision"));
        }
        for (label, digest) in [
            ("intuition receipt", self.intuition_receipt_digest),
            ("disposition", self.disposition_digest),
            ("policy", self.policy_digest),
            ("policy profile", self.policy_profile_digest),
            ("completeness receipt", self.completeness_receipt_digest),
            ("candidate set", self.candidate_set_digest),
            ("candidate order", self.candidate_order_digest),
            ("propensity", self.propensity_digest),
            ("calibration artifact", self.calibration_artifact_digest),
            ("OOD artifact", self.ood_artifact_digest),
        ] {
            if digest.is_zero() {
                return Err(DecisionAdapterErrorV1::EmptyDigest(label));
            }
        }
        if self.candidate_count == 0 {
            return Err(DecisionAdapterErrorV1::InvalidCandidateSet);
        }
        if let Some(digest) = self.authentication_digest
            && digest.is_zero()
        {
            return Err(DecisionAdapterErrorV1::EmptyDigest("authentication"));
        }
        if self.authority.grants_any() {
            return Err(DecisionAdapterErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, DecisionAdapterErrorV1> {
        self.validate()?;
        let selected = self
            .selected_candidate
            .as_ref()
            .map_or(&[][..], |candidate| candidate.as_str().as_bytes());
        let authentication = self.authentication_digest.unwrap_or(Digest32::ZERO);
        Ok(digest_bytes(
            DECISION_SCHEMA_V1.as_bytes(),
            &[
                self.decision_id.as_str().as_bytes(),
                self.intuition_receipt_digest.as_array(),
                self.disposition_digest.as_array(),
                selected,
                &self.selected_propensity_raw_q32.to_be_bytes(),
                self.policy_digest.as_array(),
                self.policy_profile_digest.as_array(),
                self.completeness_receipt_digest.as_array(),
                self.candidate_set_digest.as_array(),
                self.candidate_order_digest.as_array(),
                self.propensity_digest.as_array(),
                self.calibration_artifact_digest.as_array(),
                self.ood_artifact_digest.as_array(),
                &self.policy_generation.to_be_bytes(),
                &self.sequence.to_be_bytes(),
                &self.candidate_count.to_be_bytes(),
                &self.abstain_probability_raw_q32.to_be_bytes(),
                &self.slow_path_probability_raw_q32.to_be_bytes(),
                authentication.as_array(),
                &[u8::from(self.authority.grants_any())],
            ],
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecisionAdapterErrorV1 {
    Adapter(CellRoleAdapterErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    InvalidPpm,
    InvalidCandidateSet,
    DuplicateCandidate,
    InvalidPropensityDistribution,
    SelectedCandidateMissing,
    AuthorityGrant,
    BindingMismatch(&'static str),
    ReplayMismatch,
}

impl fmt::Display for DecisionAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DecisionAdapterErrorV1 {}

impl From<CellRoleAdapterErrorV1> for DecisionAdapterErrorV1 {
    fn from(error: CellRoleAdapterErrorV1) -> Self {
        Self::Adapter(error)
    }
}

/// Projection adapter from the calibrated intuition owner to the shared
/// DecisionCell role receipt.
pub struct DecisionAdapterV1;

impl DecisionAdapterV1 {
    pub const OWNER_MODULE: &'static str = DECISION_OWNER_MODULE;

    pub fn adapt(
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
    ) -> Result<CellRoleStepV1<DecisionResultV1>, DecisionAdapterErrorV1> {
        context.validate(CellRoleV1::Decision)?;
        binding.validate()?;
        validate_intuition_receipt(intuition, binding)?;

        let propensity_digest = digest_propensities(intuition);
        let disposition_digest = digest_disposition(intuition);
        let selected = selected_propensity(intuition)?;
        let result = DecisionResultV1 {
            decision_id: intuition.decision_id.clone(),
            intuition_receipt_digest: intuition.receipt_digest,
            disposition_digest,
            selected_candidate: selected.as_ref().map(|(id, _)| id.clone()),
            selected_propensity_raw_q32: selected.map_or(0, |(_, probability)| probability.raw()),
            policy_digest: binding.policy.policy_digest,
            policy_profile_digest: binding.policy.policy_profile_digest,
            completeness_receipt_digest: intuition.completeness_receipt_digest,
            candidate_set_digest: binding.policy.candidate_set_digest,
            candidate_order_digest: binding.policy.candidate_order_digest,
            propensity_digest,
            calibration_artifact_digest: intuition.calibration_artifact_digest,
            ood_artifact_digest: intuition.ood_artifact_digest,
            policy_generation: binding.policy.policy_generation,
            sequence: binding.policy.sequence,
            candidate_count: u32::try_from(intuition.propensities.len()).unwrap_or(u32::MAX),
            abstain_probability_raw_q32: intuition.abstain_probability.raw(),
            slow_path_probability_raw_q32: intuition.slow_path_probability.raw(),
            authentication_digest: binding
                .authentication
                .as_ref()
                .map(|evidence| evidence.authentication_digest),
            authority: intuition.authority,
        };
        let output_digest = result.content_digest()?;
        let status = match intuition.disposition {
            CalibratedDispositionV1::Selected(_) => CellStepStatusV1::Accepted,
            CalibratedDispositionV1::Abstained(_) => CellStepStatusV1::Abstained,
            CalibratedDispositionV1::SlowPath(_) => CellStepStatusV1::SlowPath,
        };
        let receipt = step_receipt(
            context,
            CellRoleV1::Decision,
            binding.state_successor_digest,
            output_digest,
            binding.uncertainty_ppm,
            binding.ood_ppm,
            status,
        )?;
        Ok(CellRoleStepV1 { result, receipt })
    }

    /// Explicit authenticated path.  This makes it difficult for a caller to
    /// accidentally omit the trust/evaluator binding when a production host
    /// has one available.
    pub fn adapt_authenticated(
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        mut binding: DecisionExecutionBindingV1,
        authentication: DecisionAuthenticationBindingV1,
    ) -> Result<CellRoleStepV1<DecisionResultV1>, DecisionAdapterErrorV1> {
        authentication.validate()?;
        binding.authentication = Some(authentication);
        Self::adapt(context, intuition, &binding)
    }

    pub fn replay(
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
        expected: &CellRoleStepV1<DecisionResultV1>,
    ) -> Result<(), DecisionAdapterErrorV1> {
        let replayed = Self::adapt(context, intuition, binding)?;
        if replayed != *expected {
            return Err(DecisionAdapterErrorV1::ReplayMismatch);
        }
        Ok(())
    }
}

/// A narrow execution-owner contract for the Decision role.  Real owners
/// implement this by loading a committed policy, invoking calibrated intuition,
/// committing a successor checkpoint, and then calling `DecisionAdapterV1`.
/// The projection implementation below is intentionally useful in repository
/// qualification and tests, but does not claim durable production ownership.
pub trait DecisionExecutionOwnerV1 {
    fn execute_calibrated(
        &mut self,
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
    ) -> Result<CellRoleStepV1<DecisionResultV1>, DecisionAdapterErrorV1>;

    fn replay_calibrated(
        &mut self,
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
        expected: &CellRoleStepV1<DecisionResultV1>,
    ) -> Result<(), DecisionAdapterErrorV1>;
}

/// Repository qualification owner.  This is an adapter fixture/seam, not a
/// registry, CAS, route, or target-host owner.
#[derive(Default)]
pub struct DecisionProjectionOwnerV1;

impl DecisionExecutionOwnerV1 for DecisionProjectionOwnerV1 {
    fn execute_calibrated(
        &mut self,
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
    ) -> Result<CellRoleStepV1<DecisionResultV1>, DecisionAdapterErrorV1> {
        DecisionAdapterV1::adapt(context, intuition, binding)
    }

    fn replay_calibrated(
        &mut self,
        context: &CellAdapterContextV1,
        intuition: &CalibratedIntuitionReceiptV1,
        binding: &DecisionExecutionBindingV1,
        expected: &CellRoleStepV1<DecisionResultV1>,
    ) -> Result<(), DecisionAdapterErrorV1> {
        DecisionAdapterV1::replay(context, intuition, binding, expected)
    }
}

fn validate_intuition_receipt(
    intuition: &CalibratedIntuitionReceiptV1,
    binding: &DecisionExecutionBindingV1,
) -> Result<(), DecisionAdapterErrorV1> {
    if intuition.decision_id.as_str().is_empty() {
        return Err(DecisionAdapterErrorV1::EmptyId("decision"));
    }
    for (label, digest) in [
        (
            "completeness receipt",
            intuition.completeness_receipt_digest,
        ),
        (
            "calibration artifact",
            intuition.calibration_artifact_digest,
        ),
        ("OOD artifact", intuition.ood_artifact_digest),
        ("decision receipt", intuition.receipt_digest),
    ] {
        if digest.is_zero() {
            return Err(DecisionAdapterErrorV1::EmptyDigest(label));
        }
    }
    if intuition.authority != AuthorityPosture::DENY_ALL {
        return Err(DecisionAdapterErrorV1::AuthorityGrant);
    }
    if intuition.completeness_receipt_digest != binding.completeness_receipt_digest {
        return Err(DecisionAdapterErrorV1::BindingMismatch(
            "completeness receipt",
        ));
    }
    if intuition.propensities.is_empty() {
        return Err(DecisionAdapterErrorV1::InvalidCandidateSet);
    }
    let mut ids = BTreeSet::new();
    let mut total = u128::from(intuition.abstain_probability.raw())
        .checked_add(u128::from(intuition.slow_path_probability.raw()))
        .ok_or(DecisionAdapterErrorV1::InvalidPropensityDistribution)?;
    for propensity in &intuition.propensities {
        if propensity.candidate_id.as_str().is_empty()
            || !ids.insert(propensity.candidate_id.clone())
        {
            return Err(DecisionAdapterErrorV1::DuplicateCandidate);
        }
        total = total
            .checked_add(u128::from(propensity.probability.raw()))
            .ok_or(DecisionAdapterErrorV1::InvalidPropensityDistribution)?;
    }
    if total != u128::from(ProbabilityQ32::ONE.raw()) {
        return Err(DecisionAdapterErrorV1::InvalidPropensityDistribution);
    }
    if let CalibratedDispositionV1::Selected(candidate) = &intuition.disposition
        && !intuition.propensities.iter().any(|propensity| {
            &propensity.candidate_id == candidate && propensity.probability != ProbabilityQ32::ZERO
        })
    {
        return Err(DecisionAdapterErrorV1::SelectedCandidateMissing);
    }
    Ok(())
}

fn selected_propensity(
    intuition: &CalibratedIntuitionReceiptV1,
) -> Result<Option<(StableId, ProbabilityQ32)>, DecisionAdapterErrorV1> {
    let CalibratedDispositionV1::Selected(selected) = &intuition.disposition else {
        return Ok(None);
    };
    let propensity = intuition
        .propensities
        .iter()
        .find(|candidate| &candidate.candidate_id == selected)
        .map(|candidate| candidate.probability)
        .ok_or(DecisionAdapterErrorV1::SelectedCandidateMissing)?;
    Ok(Some((selected.clone(), propensity)))
}

fn digest_propensities(intuition: &CalibratedIntuitionReceiptV1) -> Digest32 {
    let mut fields = Vec::with_capacity(intuition.propensities.len() * 48 + 16);
    for propensity in &intuition.propensities {
        fields.extend_from_slice(&(propensity.candidate_id.as_str().len() as u64).to_be_bytes());
        fields.extend_from_slice(propensity.candidate_id.as_str().as_bytes());
        fields.extend_from_slice(&propensity.probability.raw().to_be_bytes());
    }
    fields.extend_from_slice(&intuition.abstain_probability.raw().to_be_bytes());
    fields.extend_from_slice(&intuition.slow_path_probability.raw().to_be_bytes());
    Digest32::of_bytes(
        &[
            b"hepta.cell-role.decision-propensities.v1".as_slice(),
            fields.as_slice(),
        ]
        .concat(),
    )
}

fn digest_disposition(intuition: &CalibratedIntuitionReceiptV1) -> Digest32 {
    let mut fields = Vec::from(b"hepta.cell-role.decision-disposition.v1".as_slice());
    match &intuition.disposition {
        CalibratedDispositionV1::Selected(candidate) => {
            fields.push(0);
            fields.extend_from_slice(candidate.as_str().as_bytes());
        }
        CalibratedDispositionV1::SlowPath(reason) => {
            fields.push(1);
            fields.push(slow_path_tag(*reason));
        }
        CalibratedDispositionV1::Abstained(reason) => {
            fields.push(2);
            fields.push(abstention_tag(*reason));
        }
    }
    Digest32::of_bytes(&fields)
}

const fn slow_path_tag(reason: SlowPathReasonV1) -> u8 {
    match reason {
        SlowPathReasonV1::HighRisk => 0,
        SlowPathReasonV1::OutOfDistribution => 1,
        SlowPathReasonV1::LowConfidence => 2,
        SlowPathReasonV1::Unsupported => 3,
    }
}

const fn abstention_tag(reason: AbstentionReasonV1) -> u8 {
    match reason {
        AbstentionReasonV1::NoLegalCandidate => 0,
        AbstentionReasonV1::RandomizedAbstain => 1,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intuition::AssignmentModeV1;
    use codex_hepta_intuition::CalibratedActionCandidateV1;
    use codex_hepta_intuition::CalibratedDecisionRequestV1;
    use codex_hepta_intuition::CalibrationArtifactV1;
    use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
    use codex_hepta_intuition::OodArtifactV1;
    use codex_hepta_intuition::RiskClass;
    use codex_hepta_intuition::canonical_candidate_order_digest_v1;
    use codex_hepta_intuition::canonical_candidate_set_digest_v1;
    use codex_hepta_intuition::decide_calibrated_v2;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn context() -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("cell.decision.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(1),
            role: CellRoleV1::Decision,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            resource_receipt_digest: digest(5),
            evidence_digest: digest(6),
        }
    }

    fn fixture() -> (CalibratedIntuitionReceiptV1, DecisionExecutionBindingV1) {
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("candidate:a"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(10),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ONE,
            support_digest: digest(11),
        }];
        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision:adapter"),
            objective_digest: digest(12),
            objective_class_digest: digest(13),
            state_digest: digest(14),
            policy_digest: digest(15),
            policy_generation: 7,
            sequence: 10,
            minimum_confidence: ProbabilityQ32::from_raw(1_u64 << 31).expect("probability"),
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: digest(16),
                generator_digest: digest(17),
                grammar_digest: digest(18),
                hard_filter_digest: digest(19),
                truncation_digest: digest(20),
                candidate_set_digest: canonical_candidate_set_digest_v1(&candidates)
                    .expect("candidate set"),
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                    .expect("candidate order"),
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: digest(21),
                policy_digest: digest(15),
                objective_class_digest: digest(13),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                measured_ece_ppm: 10_000,
                subgroup_audit_digest: digest(22),
            },
            ood: OodArtifactV1 {
                artifact_digest: digest(23),
                policy_digest: digest(15),
                detector_digest: digest(24),
                support_digest: digest(25),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                maximum_in_domain_score: ProbabilityQ32::from_raw(1_u64 << 30)
                    .expect("probability"),
                measured_false_acceptance_ppm: 1_000,
            },
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        let intuition = decide_calibrated_v2(request).expect("calibrated decision");
        let binding = DecisionExecutionBindingV1 {
            policy: DecisionPolicyBindingV1 {
                policy_digest: digest(15),
                policy_profile_digest: digest(26),
                candidate_set_digest: digest(27),
                candidate_order_digest: digest(28),
                policy_generation: 7,
                sequence: 10,
            },
            authentication: None,
            completeness_receipt_digest: intuition.completeness_receipt_digest,
            state_successor_digest: digest(29),
            uncertainty_ppm: 2_000,
            ood_ppm: 3_000,
        };
        (intuition, binding)
    }

    #[test]
    fn decision_adapter_binds_policy_propensity_and_successor_state() {
        let (intuition, binding) = fixture();
        let mut owner = DecisionProjectionOwnerV1;
        let step = owner
            .execute_calibrated(&context(), &intuition, &binding)
            .expect("decision step");
        assert_eq!(step.receipt.role, CellRoleV1::Decision);
        assert_eq!(step.receipt.state_successor_digest, digest(29));
        assert_eq!(step.result.policy_digest, digest(15));
        assert_eq!(step.result.selected_candidate, Some(id("candidate:a")));
        assert_eq!(
            step.result.selected_propensity_raw_q32,
            ProbabilityQ32::ONE.raw()
        );
        assert_eq!(step.receipt.status, CellStepStatusV1::Accepted);
        assert_eq!(step.receipt.authority, AuthorityPosture::DENY_ALL);
        owner
            .replay_calibrated(&context(), &intuition, &binding, &step)
            .expect("replay");
    }

    #[test]
    fn authenticated_path_requires_nonzero_evidence_and_binds_it() {
        let (intuition, mut binding) = fixture();
        let authentication = DecisionAuthenticationBindingV1 {
            trust_digest: digest(30),
            completeness_payload_digest: digest(31),
            qualification_payload_digest: digest(32),
            runtime_payload_digest: Some(digest(33)),
            authentication_digest: digest(34),
        };
        let step = DecisionAdapterV1::adapt_authenticated(
            &context(),
            &intuition,
            binding.clone(),
            authentication.clone(),
        )
        .expect("authenticated decision");
        assert_eq!(step.result.authentication_digest, Some(digest(34)));
        binding.authentication = Some(authentication);
        DecisionAdapterV1::replay(&context(), &intuition, &binding, &step).expect("replay");
    }

    #[test]
    fn stale_completeness_or_state_is_rejected() {
        let (intuition, mut binding) = fixture();
        binding.completeness_receipt_digest = digest(99);
        assert!(matches!(
            DecisionAdapterV1::adapt(&context(), &intuition, &binding),
            Err(DecisionAdapterErrorV1::BindingMismatch(
                "completeness receipt"
            ))
        ));
        binding.completeness_receipt_digest = intuition.completeness_receipt_digest;
        binding.state_successor_digest = Digest32::ZERO;
        assert!(matches!(
            DecisionAdapterV1::adapt(&context(), &intuition, &binding),
            Err(DecisionAdapterErrorV1::EmptyDigest("state successor"))
        ));
    }
}
