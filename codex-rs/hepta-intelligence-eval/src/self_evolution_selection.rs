//! Independent self-evolution selection and rollback admission.
//!
//! Evaluation, selection and behavior consumption remain separate identities.
//! Canonical preparation requires the original product runner's sealed,
//! durably published longitudinal qualification and authoritative ledger
//! membership. Compatibility preparation verifies a caller's signed bundle
//! without granting product qualification. Both require an independently
//! trusted selector signature before returning an opaque runtime token. Rollback
//! requires a fresh independent evaluator signature over the exact selected
//! candidate and regression evidence. None of these values grants merge,
//! promotion, release, tool, model or external-effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricRoleContractV2;
use crate::ProductQualificationReceiptV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::future_window_signing_payload_v1;
use crate::longitudinal_evaluation_signing_payload_v3;

const MAX_DATASET_RECORDS: u32 = 1_000_000;

#[path = "self_evolution_product_selection.rs"]
mod product_selection;
pub use product_selection::prepare_self_evolution_product_selection_v1;
pub use product_selection::product_candidate_binding_payload_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductSelfEvolutionSelectionBindingV1 {
    pub qualification_evidence_digest: Digest32,
    pub qualification_publication_digest: Digest32,
    pub temporal_execution_digest: Digest32,
    pub candidate_binding_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionPolicyV1 {
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub minimum_dataset_records: u32,
    pub minimum_future_window_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionRequestV1 {
    pub selection_id: StableId,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionReceiptV1 {
    pub product_qualification_binding: Option<ProductSelfEvolutionSelectionBindingV1>,
    pub selection_id: StableId,
    pub objective_digest: Digest32,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub dataset_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub evaluation_authentication_digest: Digest32,
    pub evaluation_trust_digest: Digest32,
    pub frozen_plan_digest: Digest32,
    pub minimum_dataset_records: u32,
    pub minimum_future_window_micros: u64,
    pub authority: AuthorityPosture,
}

/// Prepared selection with the independently verified generator, evaluator and
/// observer identities retained in memory until a separate selector signs the
/// exact selection payload. Fields are private so callers cannot fabricate the
/// role-verification state.
#[derive(Clone, Debug)]
pub struct PreparedSelfEvolutionSelectionV1 {
    product_qualification: Option<Box<ProductQualificationReceiptV1>>,
    candidate_binding: Option<VerifiedLearningEvidenceV1>,
    receipt: SelfEvolutionSelectionReceiptV1,
    generator: VerifiedLearningEvidenceV1,
    evaluator: VerifiedLearningEvidenceV1,
    observer: VerifiedLearningEvidenceV1,
}

impl PreparedSelfEvolutionSelectionV1 {
    #[must_use]
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV1 {
        &self.receipt
    }
}

/// Opaque token returned only after selector signature and role-separation
/// verification. Runtime consumers may inspect the receipt but cannot construct
/// a token from receipt bytes alone.
#[derive(Clone, Debug)]
pub struct VerifiedSelfEvolutionSelectionV1 {
    product_qualification: Option<Box<ProductQualificationReceiptV1>>,
    candidate_binding: Option<VerifiedLearningEvidenceV1>,
    receipt: SelfEvolutionSelectionReceiptV1,
    generator: VerifiedLearningEvidenceV1,
    evaluator: VerifiedLearningEvidenceV1,
    observer: VerifiedLearningEvidenceV1,
    selector: VerifiedLearningEvidenceV1,
    selector_evidence_digest: Digest32,
    selection_digest: Digest32,
}

impl VerifiedSelfEvolutionSelectionV1 {
    /// Recheck the admitted role lifetimes at each bounded consumption. This
    /// uses the original immutable trust snapshot; the host still owns fresh
    /// trust/revocation distribution and must reload after a trust change.
    pub fn validate_at(&self, now: u64) -> Result<(), SelfEvolutionSelectionError> {
        validate_retained_product_at(
            &self.receipt,
            self.product_qualification.as_deref(),
            self.candidate_binding.as_ref(),
            &self.generator,
            now,
        )?;
        for role in [&self.generator, &self.evaluator, &self.observer] {
            verify_verified_role_separation(&self.selector, role, now)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV1 {
        &self.receipt
    }

    /// Require the original canonical product runner's sealed, durably
    /// published qualification. A compatibility signed bundle is insufficient.
    pub fn require_product_qualification(&self) -> Result<(), SelfEvolutionSelectionError> {
        let qualification = self
            .product_qualification
            .as_ref()
            .ok_or(SelfEvolutionSelectionError::CanonicalQualificationRequired)?;
        if self.candidate_binding.is_none() {
            return Err(SelfEvolutionSelectionError::CanonicalQualificationRequired);
        }
        product_selection::validate_product_binding(&self.receipt, qualification)
    }

    #[must_use]
    pub fn selector_id(&self) -> &StableId {
        &self.selector.principal().principal_id
    }

    #[must_use]
    pub fn selector_evidence_digest(&self) -> Digest32 {
        self.selector_evidence_digest
    }

    #[must_use]
    pub fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
}

/// Opaque rollback admission. Restoring predecessor bytes advances the runtime
/// generation rather than resurrecting the predecessor generation.
#[derive(Clone, Debug)]
pub struct VerifiedSelfEvolutionRollbackV1 {
    selection: VerifiedSelfEvolutionSelectionV1,
    evaluator: VerifiedLearningEvidenceV1,
    regression_evidence_digest: Digest32,
    rollback_generation: Generation,
}

impl VerifiedSelfEvolutionRollbackV1 {
    /// Recheck the rollback evaluator and selector in the admitted trust
    /// snapshot. Current owner trust distribution remains a host obligation.
    pub fn validate_at(&self, now: u64) -> Result<(), SelfEvolutionSelectionError> {
        verify_verified_role_separation(&self.selection.selector, &self.evaluator, now)?;
        Ok(())
    }

    #[must_use]
    pub fn selection(&self) -> &VerifiedSelfEvolutionSelectionV1 {
        &self.selection
    }

    #[must_use]
    pub fn evaluator_id(&self) -> &StableId {
        &self.evaluator.principal().principal_id
    }

    #[must_use]
    pub fn regression_evidence_digest(&self) -> Digest32 {
        self.regression_evidence_digest
    }

    #[must_use]
    pub fn rollback_generation(&self) -> Generation {
        self.rollback_generation
    }
}

#[allow(clippy::too_many_arguments)]
/// Compatibility admission for independently signed caller-supplied bundles.
/// This does not establish ProductEvaluationRunner production qualification.
pub fn prepare_self_evolution_selection_v1(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: SelfEvolutionSelectionRequestV1,
    evaluation_bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evaluation_evidence: &SignedEvaluationEvidenceV1,
    longitudinal_time: &LongitudinalTimeEvidenceV1,
    dataset_receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<PreparedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    validate_policy(policy)?;
    validate_request(policy, &request)?;
    verify_dataset_snapshot_receipt_against_ledger_v3(dataset_receipt, ledger_snapshot, now)?;
    if dataset_receipt.snapshot.source_record_digests.len()
        < policy.minimum_dataset_records as usize
    {
        return Err(SelfEvolutionSelectionError::DatasetTooSmall);
    }
    if evaluation_bundle.dataset_digest != dataset_receipt.snapshot.dataset_digest
        || evaluation_bundle.objective_digest != dataset_receipt.snapshot.objective_digest
        || evaluation_bundle.candidate_id != request.candidate_id
        || evaluation_bundle.baseline_id != policy.no_change_baseline_id
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }

    let evaluation = decide_with_signed_longitudinal_evidence_v3(
        evaluation_bundle.clone(),
        metric_roles.clone(),
        evaluation_evidence,
        longitudinal_time,
        policy.minimum_future_window_micros,
        verifier,
        now,
    )?;
    if evaluation.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(SelfEvolutionSelectionError::EvaluationRejected);
    }
    if evaluation.decision.candidate_id != request.candidate_id
        || evaluation.decision.baseline_id != policy.no_change_baseline_id
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evaluation_evidence.generator_plan,
        evaluation_bundle.frozen_plan.plan_digest.as_array(),
        now,
    )?;
    let evaluator_payload = longitudinal_evaluation_signing_payload_v3(
        &evaluation_bundle,
        &metric_roles,
        longitudinal_time,
        policy.minimum_future_window_micros,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evaluation_evidence.evaluator_bundle,
        &evaluator_payload,
        now,
    )?;
    let observer_payload = future_window_signing_payload_v1(
        &evaluation_bundle,
        longitudinal_time,
        policy.minimum_future_window_micros,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &longitudinal_time.observer,
        &observer_payload,
        now,
    )?;
    verify_verified_role_separation(&generator, &evaluator, now)?;
    verify_verified_role_separation(&generator, &observer, now)?;
    verify_verified_role_separation(&evaluator, &observer, now)?;

    let receipt = SelfEvolutionSelectionReceiptV1 {
        product_qualification_binding: None,
        selection_id: request.selection_id,
        objective_digest: evaluation_bundle.objective_digest,
        predecessor_id: request.predecessor_id,
        predecessor_generation: request.predecessor_generation,
        predecessor_artifact_digest: request.predecessor_artifact_digest,
        candidate_id: request.candidate_id,
        candidate_generation: request.candidate_generation,
        candidate_artifact_digest: request.candidate_artifact_digest,
        no_change_baseline_id: policy.no_change_baseline_id.clone(),
        no_change_baseline_digest: policy.no_change_baseline_digest,
        dataset_digest: dataset_receipt.snapshot.dataset_digest,
        ledger_head_digest: dataset_receipt.snapshot.ledger_head_digest,
        evaluation_evidence_digest: evaluation.decision.evidence_digest,
        evaluation_authentication_digest: evaluation.authentication_digest,
        evaluation_trust_digest: evaluation.trust_digest,
        frozen_plan_digest: evaluation_bundle.frozen_plan.plan_digest,
        minimum_dataset_records: policy.minimum_dataset_records,
        minimum_future_window_micros: policy.minimum_future_window_micros,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(PreparedSelfEvolutionSelectionV1 {
        product_qualification: None,
        candidate_binding: None,
        receipt,
        generator,
        evaluator,
        observer,
    })
}

pub fn selection_signing_payload_v1(
    receipt: &SelfEvolutionSelectionReceiptV1,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    validate_receipt(receipt)?;
    let mut bytes = if receipt.product_qualification_binding.is_some() {
        b"hepta.intelligence-eval.self-evolution-selection.v2\0".to_vec()
    } else {
        b"hepta.intelligence-eval.self-evolution-selection.v1\0".to_vec()
    };
    for id in [
        &receipt.selection_id,
        &receipt.predecessor_id,
        &receipt.candidate_id,
        &receipt.no_change_baseline_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(&receipt.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    for digest in [
        receipt.objective_digest,
        receipt.predecessor_artifact_digest,
        receipt.candidate_artifact_digest,
        receipt.no_change_baseline_digest,
        receipt.dataset_digest,
        receipt.ledger_head_digest,
        receipt.evaluation_evidence_digest,
        receipt.evaluation_authentication_digest,
        receipt.evaluation_trust_digest,
        receipt.frozen_plan_digest,
    ] {
        require_digest(digest)?;
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.minimum_dataset_records.to_be_bytes());
    bytes.extend_from_slice(&receipt.minimum_future_window_micros.to_be_bytes());
    if let Some(binding) = &receipt.product_qualification_binding {
        for digest in [
            binding.qualification_evidence_digest,
            binding.qualification_publication_digest,
            binding.temporal_execution_digest,
            binding.candidate_binding_evidence_digest,
        ] {
            require_digest(digest)?;
            bytes.extend_from_slice(digest.as_array());
        }
    }
    Ok(bytes)
}

pub fn admit_self_evolution_selection_v1(
    prepared: PreparedSelfEvolutionSelectionV1,
    selector_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    if verifier.trust_digest() != prepared.receipt.evaluation_trust_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    validate_retained_product_at(
        &prepared.receipt,
        prepared.product_qualification.as_deref(),
        prepared.candidate_binding.as_ref(),
        &prepared.generator,
        now,
    )?;
    let payload = selection_signing_payload_v1(&prepared.receipt)?;
    let selector = verifier.verify(
        LearningEvidenceRoleV1::Selector,
        selector_evidence,
        &payload,
        now,
    )?;
    for role in [&prepared.generator, &prepared.evaluator, &prepared.observer] {
        verify_verified_role_separation(&selector, role, now)?;
    }
    let selector_evidence_digest = Digest32::of_bytes(&selector_evidence.signing_bytes());
    let mut digest_bytes =
        b"hepta.intelligence-eval.self-evolution-selection-receipt.v1\0".to_vec();
    digest_bytes.extend_from_slice(&payload);
    digest_bytes.extend_from_slice(selector_evidence_digest.as_array());
    digest_bytes.extend_from_slice(&selector_evidence.signature);
    Ok(VerifiedSelfEvolutionSelectionV1 {
        product_qualification: prepared.product_qualification,
        candidate_binding: prepared.candidate_binding,
        receipt: prepared.receipt,
        generator: prepared.generator,
        evaluator: prepared.evaluator,
        observer: prepared.observer,
        selector,
        selector_evidence_digest,
        selection_digest: Digest32::of_bytes(&digest_bytes),
    })
}

fn validate_retained_product_at(
    receipt: &SelfEvolutionSelectionReceiptV1,
    qualification: Option<&ProductQualificationReceiptV1>,
    candidate_binding: Option<&VerifiedLearningEvidenceV1>,
    generator: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), SelfEvolutionSelectionError> {
    match (
        qualification,
        candidate_binding,
        &receipt.product_qualification_binding,
    ) {
        (None, None, None) => Ok(()),
        (Some(qualification), Some(binding), Some(_)) => {
            product_selection::validate_product_binding(receipt, qualification)?;
            if binding.principal() != &qualification.evaluator {
                return Err(SelfEvolutionSelectionError::BindingMismatch);
            }
            verify_verified_role_separation(generator, binding, now)?;
            Ok(())
        }
        _ => Err(SelfEvolutionSelectionError::CanonicalQualificationRequired),
    }
}

pub fn rollback_signing_payload_v1(
    selection: &VerifiedSelfEvolutionSelectionV1,
    regression_evidence_digest: Digest32,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    require_digest(regression_evidence_digest)?;
    let receipt = selection.receipt();
    let mut bytes = b"hepta.intelligence-eval.self-evolution-rollback.v1\0".to_vec();
    bytes.extend_from_slice(selection.selection_digest().as_array());
    bytes.extend_from_slice(receipt.candidate_artifact_digest.as_array());
    bytes.extend_from_slice(receipt.predecessor_artifact_digest.as_array());
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(regression_evidence_digest.as_array());
    Ok(bytes)
}

pub fn admit_self_evolution_rollback_v1(
    selection: &VerifiedSelfEvolutionSelectionV1,
    regression_evidence_digest: Digest32,
    evaluator_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedSelfEvolutionRollbackV1, SelfEvolutionSelectionError> {
    if verifier.trust_digest() != selection.receipt.evaluation_trust_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let payload = rollback_signing_payload_v1(selection, regression_evidence_digest)?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evaluator_evidence,
        &payload,
        now,
    )?;
    verify_verified_role_separation(&selection.selector, &evaluator, now)?;
    let rollback_generation = selection
        .receipt
        .candidate_generation
        .next()
        .map_err(|_| SelfEvolutionSelectionError::GenerationMismatch)?;
    Ok(VerifiedSelfEvolutionRollbackV1 {
        selection: selection.clone(),
        evaluator,
        regression_evidence_digest,
        rollback_generation,
    })
}

fn validate_policy(
    policy: &SelfEvolutionSelectionPolicyV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if policy.minimum_dataset_records == 0
        || policy.minimum_dataset_records > MAX_DATASET_RECORDS
        || policy.minimum_future_window_micros == 0
    {
        return Err(SelfEvolutionSelectionError::InvalidPolicy);
    }
    require_digest(policy.no_change_baseline_digest)
}

fn validate_request(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: &SelfEvolutionSelectionRequestV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if request.predecessor_generation.next().ok() != Some(request.candidate_generation) {
        return Err(SelfEvolutionSelectionError::GenerationMismatch);
    }
    if request.predecessor_id == request.candidate_id
        || request.predecessor_id != policy.no_change_baseline_id
        || request.predecessor_artifact_digest != policy.no_change_baseline_digest
        || request.predecessor_artifact_digest == request.candidate_artifact_digest
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    require_digest(request.predecessor_artifact_digest)?;
    require_digest(request.candidate_artifact_digest)
}

fn validate_receipt(
    receipt: &SelfEvolutionSelectionReceiptV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.predecessor_generation.next().ok() != Some(receipt.candidate_generation)
        || receipt.predecessor_id != receipt.no_change_baseline_id
        || receipt.predecessor_artifact_digest != receipt.no_change_baseline_digest
        || receipt.predecessor_id == receipt.candidate_id
        || receipt.predecessor_artifact_digest == receipt.candidate_artifact_digest
        || receipt.minimum_dataset_records == 0
        || receipt.minimum_dataset_records > MAX_DATASET_RECORDS
        || receipt.minimum_future_window_micros == 0
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    Ok(())
}

fn require_digest(digest: Digest32) -> Result<(), SelfEvolutionSelectionError> {
    if digest.is_zero() {
        return Err(SelfEvolutionSelectionError::EmptyDigest);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), SelfEvolutionSelectionError> {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| SelfEvolutionSelectionError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SelfEvolutionSelectionError {
    CanonicalQualificationRequired,
    Dataset(DatasetReceiptError),
    Evaluation(SignedEvaluationError),
    Evidence(SignedEvidenceError),
    InvalidPolicy,
    DatasetTooSmall,
    BindingMismatch,
    GenerationMismatch,
    EvaluationRejected,
    EmptyDigest,
    Arithmetic,
}

impl fmt::Display for SelfEvolutionSelectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SelfEvolutionSelectionError {}

impl From<DatasetReceiptError> for SelfEvolutionSelectionError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}

impl From<SignedEvaluationError> for SelfEvolutionSelectionError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}

impl From<SignedEvidenceError> for SelfEvolutionSelectionError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn receipt() -> SelfEvolutionSelectionReceiptV1 {
        SelfEvolutionSelectionReceiptV1 {
            product_qualification_binding: None,
            selection_id: id("selection"),
            objective_digest: digest("objective"),
            predecessor_id: id("baseline"),
            predecessor_generation: generation(/*value*/ 7),
            predecessor_artifact_digest: digest("baseline-bytes"),
            candidate_id: id("candidate"),
            candidate_generation: generation(/*value*/ 8),
            candidate_artifact_digest: digest("candidate-bytes"),
            no_change_baseline_id: id("baseline"),
            no_change_baseline_digest: digest("baseline-bytes"),
            dataset_digest: digest("dataset"),
            ledger_head_digest: digest("ledger"),
            evaluation_evidence_digest: digest("evaluation"),
            evaluation_authentication_digest: digest("authentication"),
            evaluation_trust_digest: digest("trust"),
            frozen_plan_digest: digest("plan"),
            minimum_dataset_records: 10,
            minimum_future_window_micros: 1_000,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn signing_payload_binds_predecessor_candidate_and_longitudinal_policy() {
        let first = selection_signing_payload_v1(&receipt()).expect("payload");
        let mut changed = receipt();
        changed.predecessor_artifact_digest = digest("other-baseline");
        changed.no_change_baseline_digest = changed.predecessor_artifact_digest;
        let second = selection_signing_payload_v1(&changed).expect("payload");
        assert_ne!(first, second);
    }

    fn principal(
        name: &str,
        scope: Digest32,
        key: &ed25519_dalek::SigningKey,
    ) -> codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
        codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        }
    }

    fn signed(
        verifier: &LearningEvidenceVerifierV1,
        key: &ed25519_dalek::SigningKey,
        name: &str,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        use ed25519_dalek::Signer;
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("{name}-evidence")),
            principal_id: id(name),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: digest("selection-scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }

    enum SelectorRevocation {
        NotRevoked,
        At(u64),
    }

    fn selected_fixture(
        revocation: SelectorRevocation,
    ) -> (
        VerifiedSelfEvolutionSelectionV1,
        LearningEvidenceVerifierV1,
        [ed25519_dalek::SigningKey; 4],
    ) {
        use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
        use codex_hepta_learning_ledger::TrustedLearningSignerV1;
        use ed25519_dalek::SigningKey;

        let scope = digest("selection-scope");
        let roles = [
            (
                "generator",
                "controller-generator",
                LearningEvidenceRoleV1::Generator,
                11_u8,
            ),
            (
                "evaluator",
                "controller-evaluator",
                LearningEvidenceRoleV1::Evaluator,
                22_u8,
            ),
            (
                "observer",
                "controller-observer",
                LearningEvidenceRoleV1::Observer,
                33_u8,
            ),
            (
                "selector",
                "controller-selector",
                LearningEvidenceRoleV1::Selector,
                44_u8,
            ),
        ];
        let keys = roles.map(|(_, _, _, seed)| SigningKey::from_bytes(&[seed; 32]));
        let signers = roles
            .iter()
            .zip(keys.iter())
            .map(
                |((name, controller, role, _), key)| TrustedLearningSignerV1 {
                    principal: principal(name, scope, key),
                    controller_id: id(controller),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![*role],
                    revoked_at: if *role == LearningEvidenceRoleV1::Selector {
                        match revocation {
                            SelectorRevocation::NotRevoked => None,
                            SelectorRevocation::At(at) => Some(at),
                        }
                    } else {
                        None
                    },
                },
            )
            .collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers,
        })
        .expect("trust");

        let generator = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &signed(
                    &verifier,
                    &keys[0],
                    "generator",
                    LearningEvidenceRoleV1::Generator,
                    b"generator",
                ),
                b"generator",
                /*now*/ 50,
            )
            .expect("generator");
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed(
                    &verifier,
                    &keys[1],
                    "evaluator",
                    LearningEvidenceRoleV1::Evaluator,
                    b"evaluator",
                ),
                b"evaluator",
                /*now*/ 50,
            )
            .expect("evaluator");
        let observer = verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &signed(
                    &verifier,
                    &keys[2],
                    "observer",
                    LearningEvidenceRoleV1::Observer,
                    b"observer",
                ),
                b"observer",
                /*now*/ 50,
            )
            .expect("observer");

        let mut admitted_receipt = receipt();
        admitted_receipt.evaluation_trust_digest = verifier.trust_digest();
        let prepared = PreparedSelfEvolutionSelectionV1 {
            product_qualification: None,
            candidate_binding: None,
            receipt: admitted_receipt,
            generator,
            evaluator,
            observer,
        };
        let selector_payload =
            selection_signing_payload_v1(prepared.receipt()).expect("selection payload");
        let selector_evidence = signed(
            &verifier,
            &keys[3],
            "selector",
            LearningEvidenceRoleV1::Selector,
            &selector_payload,
        );
        let selected = admit_self_evolution_selection_v1(
            prepared,
            &selector_evidence,
            &verifier,
            /*now*/ 50,
        )
        .expect("independent selection");
        (selected, verifier, keys)
    }

    #[test]
    fn retained_selection_rechecks_signed_role_lifetimes_before_late_consumption() {
        let (selected, _, _) = selected_fixture(SelectorRevocation::NotRevoked);
        assert!(selected.validate_at(/*now*/ 50).is_ok());
        assert!(selected.validate_at(/*now*/ 90).is_ok());
        assert!(selected.validate_at(/*now*/ 19).is_err());
        assert!(selected.validate_at(/*now*/ 91).is_err());
        // Cloning the opaque admission retains its original validity bound.
        assert!(selected.validate_at(/*now*/ 91).is_err());
    }

    #[test]
    fn retained_selection_checks_revocation_already_present_in_admitted_trust() {
        let (selected, _, _) = selected_fixture(SelectorRevocation::At(80));
        assert!(selected.validate_at(/*now*/ 79).is_ok());
        assert!(selected.validate_at(/*now*/ 80).is_err());
        assert!(selected.validate_at(/*now*/ 81).is_err());
    }

    #[test]
    fn selector_and_rollback_are_opaque_independent_admissions() {
        let (selected, verifier, keys) = selected_fixture(SelectorRevocation::NotRevoked);
        assert_eq!(selected.selector_id(), &id("selector"));

        let regression = digest("observed-regression");
        let rollback_payload =
            rollback_signing_payload_v1(&selected, regression).expect("rollback payload");
        let rollback_evidence = signed(
            &verifier,
            &keys[1],
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &rollback_payload,
        );
        let rollback = admit_self_evolution_rollback_v1(
            &selected,
            regression,
            &rollback_evidence,
            &verifier,
            /*now*/ 50,
        )
        .expect("independent rollback");
        assert_eq!(rollback.rollback_generation(), generation(/*value*/ 9));
        assert_eq!(rollback.evaluator_id(), &id("evaluator"));
        assert!(rollback.validate_at(/*now*/ 90).is_ok());
        assert!(rollback.validate_at(/*now*/ 91).is_err());
    }

    #[test]
    fn receipt_rejects_generation_rewind_and_baseline_drift() {
        let mut changed = receipt();
        changed.candidate_generation = generation(/*value*/ 9);
        assert_eq!(
            selection_signing_payload_v1(&changed),
            Err(SelfEvolutionSelectionError::BindingMismatch)
        );
        let mut changed = receipt();
        changed.no_change_baseline_id = id("other-baseline");
        assert_eq!(
            selection_signing_payload_v1(&changed),
            Err(SelfEvolutionSelectionError::BindingMismatch)
        );
    }
}
