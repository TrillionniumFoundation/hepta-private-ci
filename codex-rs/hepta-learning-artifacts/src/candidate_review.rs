//! Scientific admission for a parameter candidate, before immutable publication.
//!
//! The host installs the frozen comparison policy and reviewer key. The reviewer
//! attests measurements, not caller-supplied pass flags. Publication still uses
//! the existing owner, withdrawal frontier, writer fence and signed CURRENT head.
//! This path cannot select a candidate or mutate a running model.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::TrustedArtifactSignerV1;
use crate::validate_artifact_publication_v3;

/// A digest names the frozen endpoint, comparator, analysis and cost scope.
/// Task improvement requires a strictly smaller upper bound; retention and
/// total-cost limits are inclusive. These operators are fixed by this version.
#[derive(Clone, Debug, PartialEq)]
pub struct ScientificComparisonPolicyV1 {
    pub comparison_digest: Digest32,
    pub maximum_upper_bound: f64,
    pub minimum_observations: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ScientificCandidatePolicyV1 {
    pub protocol_digest: Digest32,
    pub candidate_definition_digest: Digest32,
    pub task: ScientificComparisonPolicyV1,
    pub retention: ScientificComparisonPolicyV1,
    pub total_cost: ScientificComparisonPolicyV1,
}

impl ScientificCandidatePolicyV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning-artifacts.scientific-policy.v1".to_vec();
        bytes.extend_from_slice(self.protocol_digest.as_array());
        bytes.extend_from_slice(self.candidate_definition_digest.as_array());
        for comparison in [&self.task, &self.retention, &self.total_cost] {
            bytes.extend_from_slice(comparison.comparison_digest.as_array());
            bytes.extend_from_slice(&comparison.maximum_upper_bound.to_bits().to_be_bytes());
            bytes.extend_from_slice(&comparison.minimum_observations.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Values and their analysis are independently attested. The native gate does
/// not infer statistical independence or cost completeness from a sample count.
#[derive(Clone, Debug, PartialEq)]
pub struct ScientificMeasurementV1 {
    pub comparison_digest: Digest32,
    pub evidence_digest: Digest32,
    pub observations: u64,
    pub lower_bound: f64,
    pub estimate: f64,
    pub upper_bound: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub enum ScientificMeasurementStatusV1 {
    Unavailable,
    Measured(ScientificMeasurementV1),
}

#[derive(Clone, Debug, PartialEq)]
pub struct SignedScientificCandidateReviewV1 {
    pub reviewer_id: StableId,
    pub operation_id: StableId,
    pub authority_epoch: u64,
    pub policy_digest: Digest32,
    pub admission_digest: Digest32,
    pub expected_registry_predecessor_head: Digest32,
    pub report_digest: Digest32,
    pub task: ScientificMeasurementStatusV1,
    pub retention: ScientificMeasurementStatusV1,
    pub total_cost: ScientificMeasurementStatusV1,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl SignedScientificCandidateReviewV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.scientific-review.v1".to_vec();
        for identity in [&self.reviewer_id, &self.operation_id] {
            let identity = identity.as_str().as_bytes();
            bytes.extend_from_slice(&(identity.len() as u64).to_be_bytes());
            bytes.extend_from_slice(identity);
        }
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for digest in [
            self.policy_digest,
            self.admission_digest,
            self.expected_registry_predecessor_head,
            self.report_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for status in [&self.task, &self.retention, &self.total_cost] {
            match status {
                ScientificMeasurementStatusV1::Unavailable => bytes.push(0),
                ScientificMeasurementStatusV1::Measured(measurement) => {
                    bytes.push(1);
                    bytes.extend_from_slice(measurement.comparison_digest.as_array());
                    bytes.extend_from_slice(measurement.evidence_digest.as_array());
                    bytes.extend_from_slice(&measurement.observations.to_be_bytes());
                    for value in [
                        measurement.lower_bound,
                        measurement.estimate,
                        measurement.upper_bound,
                    ] {
                        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
                    }
                }
            }
        }
        bytes.extend_from_slice(&self.issued_at.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at.to_be_bytes());
        bytes
    }
}

pub enum ScientificReviewEvidenceV1 {
    Missing,
    Signed(Box<SignedScientificCandidateReviewV1>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScientificCandidatePublicationReceiptV1 {
    pub review_digest: Digest32,
    pub policy_digest: Digest32,
    pub publication: ArtifactPublicationReceiptV1,
}

/// Owns the existing publication service; callers cannot swap reviewer trust or
/// acceptance thresholds for an individual candidate. Trust freshness remains a
/// host obligation, as for the existing artifact writer and CURRENT signers.
/// The host also supplies the trusted clock in `request.now`; this typed API is
/// not an untrusted network request boundary.
pub struct ScientificCandidatePublisherV1 {
    service: LearningArtifactOwnerService,
    policy: ScientificCandidatePolicyV1,
    reviewer: TrustedArtifactSignerV1,
}

impl ScientificCandidatePublisherV1 {
    pub fn new(
        service: LearningArtifactOwnerService,
        policy: ScientificCandidatePolicyV1,
        reviewer: TrustedArtifactSignerV1,
    ) -> Result<Self, ScientificCandidateReviewError> {
        if policy.protocol_digest.is_zero()
            || policy.candidate_definition_digest.is_zero()
            || [&policy.task, &policy.retention, &policy.total_cost]
                .iter()
                .any(|gate| {
                    gate.comparison_digest.is_zero()
                        || !gate.maximum_upper_bound.is_finite()
                        || gate.minimum_observations == 0
                })
            || policy.task.maximum_upper_bound >= 0.0
            || policy.task.comparison_digest == policy.retention.comparison_digest
            || policy.task.comparison_digest == policy.total_cost.comparison_digest
            || policy.retention.comparison_digest == policy.total_cost.comparison_digest
            || policy.retention.maximum_upper_bound < 0.0
            || policy.total_cost.maximum_upper_bound <= 0.0
            || reviewer.minimum_authority_epoch == 0
            || reviewer.maximum_authority_epoch < reviewer.minimum_authority_epoch
            || reviewer.valid_from > reviewer.expires_at
            || VerifyingKey::from_bytes(&reviewer.verifying_key).is_err()
        {
            return Err(ScientificCandidateReviewError::InvalidHostPolicy);
        }
        Ok(Self {
            service,
            policy,
            reviewer,
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        self.service.registry()
    }

    /// Keep the same monotonic authenticated withdrawal feed as the owned
    /// publication service. Supplying its current frontier is a host duty.
    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), ScientificCandidateReviewError> {
        self.service
            .install_withdrawal_frontier(next)
            .map_err(ScientificCandidateReviewError::Owner)
    }

    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
        evidence: ScientificReviewEvidenceV1,
    ) -> Result<ScientificCandidatePublicationReceiptV1, ScientificCandidateReviewError> {
        let ScientificReviewEvidenceV1::Signed(review) = evidence else {
            return Err(ScientificCandidateReviewError::MissingReview);
        };
        let manifest = &request.admission.validated_manifest.manifest;
        let now = request.now;
        if review.reviewer_id != self.reviewer.signer_id
            || review.reviewer_id == manifest.producer_id
            || review.authority_epoch < self.reviewer.minimum_authority_epoch
            || review.authority_epoch > self.reviewer.maximum_authority_epoch
            || now < self.reviewer.valid_from
            || now > self.reviewer.expires_at
            || self
                .reviewer
                .revoked_at
                .is_some_and(|revoked| now >= revoked)
            || review.issued_at < self.reviewer.valid_from
            || review.issued_at > now
            || review.issued_at < request.admission.admitted_at
            || review.expires_at < now
            || review.expires_at > self.reviewer.expires_at
        {
            return Err(ScientificCandidateReviewError::ReviewerAuthority);
        }
        VerifyingKey::from_bytes(&self.reviewer.verifying_key)
            .map_err(|_| ScientificCandidateReviewError::ReviewerAuthority)?
            .verify_strict(
                &review.signing_bytes(),
                &Signature::from_bytes(&review.signature),
            )
            .map_err(|_| ScientificCandidateReviewError::Signature)?;
        if review.operation_id != request.operation_id
            || review.policy_digest != self.policy.digest()
            || review.admission_digest != request.admission.admission_digest
            || review.expected_registry_predecessor_head
                != request.expected_registry_predecessor_head
            || review.report_digest.is_zero()
            || !manifest.lineage_digests.contains(&review.report_digest)
        {
            return Err(ScientificCandidateReviewError::ReviewBinding);
        }
        for (name, status, gate) in [
            ("task", &review.task, &self.policy.task),
            ("retention", &review.retention, &self.policy.retention),
            ("total_cost", &review.total_cost, &self.policy.total_cost),
        ] {
            let ScientificMeasurementStatusV1::Measured(value) = status else {
                return Err(ScientificCandidateReviewError::GateUnavailable(name));
            };
            if value.comparison_digest != gate.comparison_digest
                || value.evidence_digest.is_zero()
                || value.observations < gate.minimum_observations
                || ![value.lower_bound, value.estimate, value.upper_bound]
                    .iter()
                    .all(|x| x.is_finite())
                || value.lower_bound > value.estimate
                || value.estimate > value.upper_bound
                || (name == "total_cost" && value.lower_bound < 0.0)
                || value.upper_bound > gate.maximum_upper_bound
                || (name == "task" && value.upper_bound == gate.maximum_upper_bound)
            {
                return Err(ScientificCandidateReviewError::GateFailed(name));
            }
        }
        validate_artifact_publication_v3(
            &request.admission,
            self.service.withdrawal_registry(),
            now,
        )
        .map_err(|_| ScientificCandidateReviewError::Admission)?;
        if manifest.kind != ArtifactKind::Parameters
            || manifest.predecessor_ids.len() != 1
            || manifest.rollback_predecessor.as_ref() != manifest.predecessor_ids.first()
            || manifest.encoded_size_bytes != request.payload.len() as u64
            || manifest.bytes_digest != Digest32::of_bytes(&request.payload)
        {
            return Err(ScientificCandidateReviewError::CandidateBinding);
        }
        let predecessor_id = &manifest.predecessor_ids[0];
        let predecessor = self
            .service
            .registry()
            .manifest(predecessor_id)
            .ok_or(ScientificCandidateReviewError::Predecessor)?;
        if !self.service.registry().is_eligible(predecessor_id)
            || predecessor.kind != ArtifactKind::Parameters
            || predecessor.generation.get().checked_add(1) != Some(manifest.generation.get())
            || predecessor.compatibility_digest != manifest.compatibility_digest
            || predecessor.objective_digest != manifest.objective_class_digest
        {
            return Err(ScientificCandidateReviewError::Predecessor);
        }
        self.validate_registry_predecessor(&request)?;
        let mut reviewed_bytes = review.signing_bytes();
        reviewed_bytes.extend_from_slice(&review.signature);
        let review_digest = Digest32::of_bytes(&reviewed_bytes);
        let publication = self
            .service
            .publish(request)
            .map_err(ScientificCandidateReviewError::Owner)?;
        Ok(ScientificCandidatePublicationReceiptV1 {
            review_digest,
            policy_digest: self.policy.digest(),
            publication,
        })
    }

    fn validate_registry_predecessor(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<(), ScientificCandidateReviewError> {
        let registry = self.service.registry();
        let artifact_id = &request.admission.validated_manifest.manifest.artifact_id;
        if registry.manifest(artifact_id).is_none() {
            return if registry.snapshot().head_digest == request.expected_registry_predecessor_head
            {
                Ok(())
            } else {
                Err(ScientificCandidateReviewError::Predecessor)
            };
        }
        // An existing artifact permits only the original publication intent.
        // Reconstruct its bounded registry prefix without opening a new durable
        // operation: a different, even re-signed operation must not write first.
        let mut prefix = ArtifactRegistry::new();
        for record in registry.records() {
            if let ArtifactEvent::Register { event_id, manifest } = &record.event
                && &manifest.artifact_id == artifact_id
            {
                let transaction = ArtifactPublicationTransactionV1::begin(
                    request.operation_id.clone(),
                    request.admission.clone(),
                    self.service.withdrawal_registry(),
                    &prefix,
                    request.expected_registry_predecessor_head,
                    request.now,
                )
                .map_err(|_| ScientificCandidateReviewError::Predecessor)?;
                return if event_id.as_str()
                    == format!(
                        "artifact-publication:{}",
                        transaction.intent().intent_digest
                    ) {
                    Ok(())
                } else {
                    Err(ScientificCandidateReviewError::Predecessor)
                };
            }
            prefix
                .append(record.event.clone())
                .map_err(|_| ScientificCandidateReviewError::Predecessor)?;
        }
        Err(ScientificCandidateReviewError::Predecessor)
    }
}

#[derive(Debug)]
pub enum ScientificCandidateReviewError {
    InvalidHostPolicy,
    MissingReview,
    ReviewerAuthority,
    Signature,
    ReviewBinding,
    GateUnavailable(&'static str),
    GateFailed(&'static str),
    Admission,
    CandidateBinding,
    Predecessor,
    Owner(LearningArtifactOwnerServiceError),
}

impl std::fmt::Display for ScientificCandidateReviewError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ScientificCandidateReviewError {}

#[cfg(test)]
#[path = "candidate_review_tests.rs"]
mod tests;
