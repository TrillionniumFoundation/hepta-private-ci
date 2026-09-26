//! Canonical consumer migration registry and shadow-comparison receipts.
//!
//! The registry makes ownership, legacy surfaces, canonical schemas, mismatch
//! metrics, cutover gates and rollback paths reviewable in code. It grants no
//! runtime authority and does not by itself claim that a consumer has cut over.

use codex_hepta_types::Digest32;

use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;

const SHADOW_COMPARISON_DOMAIN: &[u8] = b"hepta.cognitive.consumer-shadow.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConsumerConvergenceStateV1 {
    CanonicalAuthoritative,
    CanonicalShadow,
    RegisteredPendingCutover,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalConsumerRegistrationV1 {
    pub consumer: &'static str,
    pub owner: &'static str,
    pub legacy_surface: &'static str,
    pub canonical_schema: &'static str,
    pub shadow_mismatch_metric: &'static str,
    pub cutover_gate: &'static str,
    pub rollback_path: &'static str,
    pub state: ConsumerConvergenceStateV1,
}

pub const COGNITIVE_READ_CONSUMER_V1: CanonicalConsumerRegistrationV1 =
    CanonicalConsumerRegistrationV1 {
        consumer: "cognitive.read",
        owner: "cognitive-platform",
        legacy_surface: "MemoryRecord/CognitiveSnapshot compatibility read",
        canonical_schema: "hepta.hnmf.memory-event.v1",
        shadow_mismatch_metric: "cognitive_read_canonical_shadow_mismatch_total",
        cutover_gate: "exact-record bridge parity plus strict-wire qualification",
        rollback_path: "disable canonical projection and retain owner snapshot read",
        state: ConsumerConvergenceStateV1::CanonicalShadow,
    };

pub const COGNITIVE_STORE_CONSUMER_V1: CanonicalConsumerRegistrationV1 =
    CanonicalConsumerRegistrationV1 {
        consumer: "cognitive.store",
        owner: "cognitive-platform",
        legacy_surface: "MemoryAdmissionCandidateV1/MemoryRecord compatibility writer",
        canonical_schema: "hepta.hnmf.memory-event.v1",
        shadow_mismatch_metric: "cognitive_store_canonical_shadow_mismatch_total",
        cutover_gate: "canonical envelope authentication plus durable receipt parity",
        rollback_path: "disable canonical admission endpoint; retain append-only ledger image",
        state: ConsumerConvergenceStateV1::CanonicalShadow,
    };

pub const MEMORY_RETRIEVAL_CONSUMER_V1: CanonicalConsumerRegistrationV1 =
    CanonicalConsumerRegistrationV1 {
        consumer: "memory.retrieval",
        owner: "memory-retrieval",
        legacy_surface: "generation-bound RecallPacketV1 compatibility projection",
        canonical_schema: "hepta.hnmf.recall-packet.v1",
        shadow_mismatch_metric: "memory_retrieval_canonical_shadow_mismatch_total",
        cutover_gate: "candidate/order/abstention parity on exact generation vectors",
        rollback_path: "disable canonical result projection; retain generation-bound reader",
        state: ConsumerConvergenceStateV1::RegisteredPendingCutover,
    };

pub const COMPACT_ENGINE_CONSUMER_V1: CanonicalConsumerRegistrationV1 =
    CanonicalConsumerRegistrationV1 {
        consumer: "compact.engine",
        owner: "memory-platform",
        legacy_surface: "MemoryRecord and Lane C compaction compatibility surface",
        canonical_schema: "hepta.hnmf.forget-propagation-receipt.v1",
        shadow_mismatch_metric: "compact_engine_canonical_shadow_mismatch_total",
        cutover_gate: "tombstone/forget/rebuild parity on one immutable source cut",
        rollback_path: "disable canonical forget projection; retain qualified checkpoint path",
        state: ConsumerConvergenceStateV1::RegisteredPendingCutover,
    };

pub const INTELLIGENCE_CONTROL_CONSUMER_V1: CanonicalConsumerRegistrationV1 =
    CanonicalConsumerRegistrationV1 {
        consumer: "intelligence.control",
        owner: "intelligence-control",
        legacy_surface: "CognitiveSnapshot compatibility context input",
        canonical_schema: "hepta.hnmf.memory-event.v1",
        shadow_mismatch_metric: "intelligence_control_canonical_shadow_mismatch_total",
        cutover_gate: "context fragment parity and exact generation-vector binding",
        rollback_path: "disable canonical event fragments; retain immutable snapshot input",
        state: ConsumerConvergenceStateV1::RegisteredPendingCutover,
    };

pub const REGISTERED_CONSUMERS_V1: [CanonicalConsumerRegistrationV1; 5] = [
    COGNITIVE_READ_CONSUMER_V1,
    COGNITIVE_STORE_CONSUMER_V1,
    MEMORY_RETRIEVAL_CONSUMER_V1,
    COMPACT_ENGINE_CONSUMER_V1,
    INTELLIGENCE_CONTROL_CONSUMER_V1,
];

#[must_use]
pub fn registered_consumer_v1(name: &str) -> Option<&'static CanonicalConsumerRegistrationV1> {
    REGISTERED_CONSUMERS_V1
        .iter()
        .find(|registration| registration.consumer == name)
}

/// Digest-bound result of running legacy and canonical adapters side by side.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalShadowComparisonV1 {
    consumer: &'static str,
    legacy_digest: Digest32,
    canonical_digest: Digest32,
    matched: bool,
    comparison_digest: Digest32,
}

impl CanonicalShadowComparisonV1 {
    pub fn new(
        registration: &'static CanonicalConsumerRegistrationV1,
        legacy_digest: Digest32,
        canonical_digest: Digest32,
    ) -> Result<Self, ContractViolationV1> {
        if legacy_digest.is_zero() {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::EmptyDigest,
                "legacyDigest",
                "legacy shadow digest must be non-zero",
            ));
        }
        if canonical_digest.is_zero() {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::EmptyDigest,
                "canonicalDigest",
                "canonical shadow digest must be non-zero",
            ));
        }
        let matched = legacy_digest == canonical_digest;
        let comparison_digest = compute_comparison_digest(
            registration.consumer,
            legacy_digest,
            canonical_digest,
            matched,
        );
        Ok(Self {
            consumer: registration.consumer,
            legacy_digest,
            canonical_digest,
            matched,
            comparison_digest,
        })
    }

    #[must_use]
    pub const fn consumer(&self) -> &'static str {
        self.consumer
    }

    #[must_use]
    pub const fn legacy_digest(&self) -> Digest32 {
        self.legacy_digest
    }

    #[must_use]
    pub const fn canonical_digest(&self) -> Digest32 {
        self.canonical_digest
    }

    #[must_use]
    pub const fn matched(&self) -> bool {
        self.matched
    }

    #[must_use]
    pub const fn comparison_digest(&self) -> Digest32 {
        self.comparison_digest
    }

    pub fn validate(&self) -> Result<(), ContractViolationV1> {
        let registration = registered_consumer_v1(self.consumer).ok_or_else(|| {
            ContractViolationV1::new(
                ContractErrorCodeV1::ContractMismatch,
                "consumer",
                "consumer is not registered for canonical migration",
            )
        })?;
        if self.legacy_digest.is_zero() || self.canonical_digest.is_zero() {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::EmptyDigest,
                "comparison",
                "shadow comparison contains a zero digest",
            ));
        }
        if self.matched != (self.legacy_digest == self.canonical_digest)
            || self.comparison_digest
                != compute_comparison_digest(
                    registration.consumer,
                    self.legacy_digest,
                    self.canonical_digest,
                    self.matched,
                )
        {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::DigestMismatch,
                "comparisonDigest",
                "shadow comparison binding does not match its payload",
            ));
        }
        Ok(())
    }
}

fn compute_comparison_digest(
    consumer: &str,
    legacy_digest: Digest32,
    canonical_digest: Digest32,
    matched: bool,
) -> Digest32 {
    let mut bytes = SHADOW_COMPARISON_DOMAIN.to_vec();
    let consumer_bytes = consumer.as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(consumer_bytes.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(consumer_bytes);
    bytes.extend_from_slice(legacy_digest.as_array());
    bytes.extend_from_slice(canonical_digest.as_array());
    bytes.push(u8::from(matched));
    Digest32::of_bytes(&bytes)
}
