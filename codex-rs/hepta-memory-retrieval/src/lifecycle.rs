//! Strongly typed retrieval lifecycle and durable decision-port contract.
//!
//! This module deliberately owns no storage implementation. Product code must provide a
//! durable port with fencing, compare-and-swap frontier advancement, atomic append,
//! idempotent replay, quarantine, and retention semantics.

use std::error::Error as StdError;
use std::fmt;

const MAX_IDENTITY_PART_BYTES: usize = 256;
const MAX_REASON_BYTES: usize = 1024;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct RetrievalExecutionIdentityV1 {
    tenant: String,
    principal: String,
    request: String,
    query_digest: String,
    policy_generation: String,
    encoder_identity: String,
    snapshot_identity: String,
    decision_identity: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalExecutionIdentityPartsV1 {
    pub tenant: String,
    pub principal: String,
    pub request: String,
    pub query_digest: String,
    pub policy_generation: String,
    pub encoder_identity: String,
    pub snapshot_identity: String,
    pub decision_identity: String,
}

impl RetrievalExecutionIdentityV1 {
    pub fn new(parts: RetrievalExecutionIdentityPartsV1) -> Result<Self, LifecycleErrorV1> {
        validate_identity_part("tenant", &parts.tenant)?;
        validate_identity_part("principal", &parts.principal)?;
        validate_identity_part("request", &parts.request)?;
        validate_identity_part("query_digest", &parts.query_digest)?;
        validate_identity_part("policy_generation", &parts.policy_generation)?;
        validate_identity_part("encoder_identity", &parts.encoder_identity)?;
        validate_identity_part("snapshot_identity", &parts.snapshot_identity)?;
        validate_identity_part("decision_identity", &parts.decision_identity)?;
        Ok(Self {
            tenant: parts.tenant,
            principal: parts.principal,
            request: parts.request,
            query_digest: parts.query_digest,
            policy_generation: parts.policy_generation,
            encoder_identity: parts.encoder_identity,
            snapshot_identity: parts.snapshot_identity,
            decision_identity: parts.decision_identity,
        })
    }

    pub fn tenant(&self) -> &str {
        &self.tenant
    }

    pub fn principal(&self) -> &str {
        &self.principal
    }

    pub fn request(&self) -> &str {
        &self.request
    }

    pub fn query_digest(&self) -> &str {
        &self.query_digest
    }

    pub fn policy_generation(&self) -> &str {
        &self.policy_generation
    }

    pub fn encoder_identity(&self) -> &str {
        &self.encoder_identity
    }

    pub fn snapshot_identity(&self) -> &str {
        &self.snapshot_identity
    }

    pub fn decision_identity(&self) -> &str {
        &self.decision_identity
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedRequestV1 {
    identity: RetrievalExecutionIdentityV1,
}

impl ValidatedRequestV1 {
    pub fn new(identity: RetrievalExecutionIdentityV1) -> Self {
        Self { identity }
    }

    pub fn bind_tenant(self) -> TenantBoundExecutionV1 {
        TenantBoundExecutionV1 {
            identity: self.identity,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TenantBoundExecutionV1 {
    identity: RetrievalExecutionIdentityV1,
}

impl TenantBoundExecutionV1 {
    pub fn seal_snapshot(
        self,
        observed_snapshot_identity: &str,
    ) -> Result<SealedSnapshotV1, LifecycleErrorV1> {
        if self.identity.snapshot_identity() != observed_snapshot_identity {
            return Err(LifecycleErrorV1::IdentityMismatch("snapshot_identity"));
        }
        Ok(SealedSnapshotV1 {
            identity: self.identity,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SealedSnapshotV1 {
    identity: RetrievalExecutionIdentityV1,
}

impl SealedSnapshotV1 {
    pub fn qualify_decision(
        self,
        observed_decision_identity: &str,
    ) -> Result<QualifiedDecisionV1, LifecycleErrorV1> {
        if self.identity.decision_identity() != observed_decision_identity {
            return Err(LifecycleErrorV1::IdentityMismatch("decision_identity"));
        }
        Ok(QualifiedDecisionV1 {
            identity: self.identity,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedDecisionV1 {
    identity: RetrievalExecutionIdentityV1,
}

impl QualifiedDecisionV1 {
    pub fn publish(
        self,
        publication_digest: String,
    ) -> Result<PublishedRetrievalV1, LifecycleErrorV1> {
        validate_identity_part("publication_digest", &publication_digest)?;
        Ok(PublishedRetrievalV1 {
            identity: self.identity,
            publication_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedRetrievalV1 {
    identity: RetrievalExecutionIdentityV1,
    publication_digest: String,
}

impl PublishedRetrievalV1 {
    pub fn consume(
        self,
        observed_publication_digest: &str,
        downstream_effect_digest: String,
    ) -> Result<ConsumedRetrievalV1, LifecycleErrorV1> {
        if self.publication_digest != observed_publication_digest {
            return Err(LifecycleErrorV1::IdentityMismatch("publication_digest"));
        }
        validate_identity_part("downstream_effect_digest", &downstream_effect_digest)?;
        Ok(ConsumedRetrievalV1 {
            identity: self.identity,
            publication_digest: self.publication_digest,
            downstream_effect_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConsumedRetrievalV1 {
    identity: RetrievalExecutionIdentityV1,
    publication_digest: String,
    downstream_effect_digest: String,
}

impl ConsumedRetrievalV1 {
    pub fn acknowledge(
        self,
        observed_effect_digest: &str,
        acknowledgement_digest: String,
    ) -> Result<AcknowledgedRetrievalV1, LifecycleErrorV1> {
        if self.downstream_effect_digest != observed_effect_digest {
            return Err(LifecycleErrorV1::IdentityMismatch(
                "downstream_effect_digest",
            ));
        }
        validate_identity_part("acknowledgement_digest", &acknowledgement_digest)?;
        Ok(AcknowledgedRetrievalV1 {
            identity: self.identity,
            publication_digest: self.publication_digest,
            downstream_effect_digest: self.downstream_effect_digest,
            acknowledgement_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AcknowledgedRetrievalV1 {
    identity: RetrievalExecutionIdentityV1,
    publication_digest: String,
    downstream_effect_digest: String,
    acknowledgement_digest: String,
}

impl AcknowledgedRetrievalV1 {
    pub fn identity(&self) -> &RetrievalExecutionIdentityV1 {
        &self.identity
    }

    pub fn publication_digest(&self) -> &str {
        &self.publication_digest
    }

    pub fn downstream_effect_digest(&self) -> &str {
        &self.downstream_effect_digest
    }

    pub fn acknowledgement_digest(&self) -> &str {
        &self.acknowledgement_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuarantinedUnknownOutcomeV1 {
    identity: RetrievalExecutionIdentityV1,
    reason: String,
}

impl QuarantinedUnknownOutcomeV1 {
    pub fn new(
        identity: RetrievalExecutionIdentityV1,
        reason: String,
    ) -> Result<Self, LifecycleErrorV1> {
        if reason.is_empty() || reason.len() > MAX_REASON_BYTES {
            return Err(LifecycleErrorV1::InvalidQuarantineReason);
        }
        Ok(Self { identity, reason })
    }

    pub fn identity(&self) -> &RetrievalExecutionIdentityV1 {
        &self.identity
    }

    pub fn reason(&self) -> &str {
        &self.reason
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalLifecyclePhaseV1 {
    ValidatedRequest,
    TenantBoundExecution,
    SealedSnapshot,
    QualifiedDecision,
    PublishedRetrieval,
    ConsumedRetrieval,
    AcknowledgedRetrieval,
    QuarantinedUnknownOutcome,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableDecisionRecordV1 {
    pub identity: RetrievalExecutionIdentityV1,
    pub phase: RetrievalLifecyclePhaseV1,
    pub writer_fence: u64,
    pub frontier: u64,
    pub payload_digest: String,
}

impl DurableDecisionRecordV1 {
    pub fn validate(&self) -> Result<(), LifecycleErrorV1> {
        if self.writer_fence == 0 {
            return Err(LifecycleErrorV1::InvalidWriterFence);
        }
        validate_identity_part("payload_digest", &self.payload_digest)
    }
}

pub trait DurableDecisionPortV1 {
    type Error: StdError + Send + Sync + 'static;

    fn acquire_writer_fence(&mut self, writer_identity: &str) -> Result<u64, Self::Error>;

    fn compare_and_append(
        &mut self,
        expected_frontier: u64,
        record: &DurableDecisionRecordV1,
    ) -> Result<u64, Self::Error>;

    fn load_latest(
        &self,
        identity: &RetrievalExecutionIdentityV1,
    ) -> Result<Option<DurableDecisionRecordV1>, Self::Error>;

    fn quarantine_unknown_outcome(
        &mut self,
        expected_frontier: u64,
        outcome: &QuarantinedUnknownOutcomeV1,
        writer_fence: u64,
        payload_digest: &str,
    ) -> Result<u64, Self::Error>;

    fn verify_replay_integrity(&self) -> Result<(), Self::Error>;

    fn retire_before_frontier(&mut self, exclusive_frontier: u64) -> Result<u64, Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LifecycleErrorV1 {
    EmptyIdentityPart(&'static str),
    OversizedIdentityPart(&'static str),
    IdentityMismatch(&'static str),
    InvalidWriterFence,
    InvalidQuarantineReason,
}

impl fmt::Display for LifecycleErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LifecycleErrorV1 {}

fn validate_identity_part(name: &'static str, value: &str) -> Result<(), LifecycleErrorV1> {
    if value.is_empty() {
        return Err(LifecycleErrorV1::EmptyIdentityPart(name));
    }
    if value.len() > MAX_IDENTITY_PART_BYTES {
        return Err(LifecycleErrorV1::OversizedIdentityPart(name));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> RetrievalExecutionIdentityV1 {
        RetrievalExecutionIdentityV1::new(RetrievalExecutionIdentityPartsV1 {
            tenant: "tenant-a".to_string(),
            principal: "principal-a".to_string(),
            request: "request-a".to_string(),
            query_digest: "query-digest-a".to_string(),
            policy_generation: "policy-7".to_string(),
            encoder_identity: "encoder-a".to_string(),
            snapshot_identity: "snapshot-a".to_string(),
            decision_identity: "decision-a".to_string(),
        })
        .expect("valid identity")
    }

    #[test]
    fn full_lifecycle_preserves_exact_identity() {
        let acknowledged = ValidatedRequestV1::new(identity())
            .bind_tenant()
            .seal_snapshot("snapshot-a")
            .expect("snapshot identity")
            .qualify_decision("decision-a")
            .expect("decision identity")
            .publish("publication-a".to_string())
            .expect("publication")
            .consume("publication-a", "effect-a".to_string())
            .expect("consumption")
            .acknowledge("effect-a", "ack-a".to_string())
            .expect("acknowledgement");

        assert_eq!(acknowledged.identity(), &identity());
        assert_eq!(acknowledged.publication_digest(), "publication-a");
        assert_eq!(acknowledged.downstream_effect_digest(), "effect-a");
        assert_eq!(acknowledged.acknowledgement_digest(), "ack-a");
    }

    #[test]
    fn lifecycle_rejects_cross_identity_transition() {
        let error = ValidatedRequestV1::new(identity())
            .bind_tenant()
            .seal_snapshot("snapshot-b")
            .expect_err("mismatched snapshot must fail");

        assert_eq!(
            error,
            LifecycleErrorV1::IdentityMismatch("snapshot_identity")
        );
    }

    #[test]
    fn unknown_outcome_requires_bounded_reason() {
        let error = QuarantinedUnknownOutcomeV1::new(identity(), String::new())
            .expect_err("empty quarantine reason must fail");
        assert_eq!(error, LifecycleErrorV1::InvalidQuarantineReason);
    }
}
