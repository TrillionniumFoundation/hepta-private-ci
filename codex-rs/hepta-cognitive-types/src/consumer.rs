//! Closed consumer-convergence registry and canonical shadow accounting.
//!
//! This registry is executable data rather than prose. A consumer is eligible
//! for cutover only when its exact canonical schema bindings, mismatch metric,
//! cutover gate and rollback owner are present here and its shadow receipts
//! prove equality on the cut being promoted.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::contract::Validated;
use crate::registry::decode_registered_wire_v1;
use crate::wire::CognitiveContractV1;

pub const CONSUMER_PROFILE_REVISION_V1: &str =
    "cognitive-consumer-convergence/2026-09-27/v1";
pub const REGISTERED_CONSUMER_COUNT_V1: usize = 5;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CognitiveConsumerV1 {
    CognitiveRead,
    CognitiveStore,
    MemoryRetrieval,
    CompactEngine,
    IntelligenceControl,
}

impl CognitiveConsumerV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CognitiveRead => "cognitive.read",
            Self::CognitiveStore => "cognitive.store",
            Self::MemoryRetrieval => "memory.retrieval",
            Self::CompactEngine => "compact.engine",
            Self::IntelligenceControl => "intelligence.control",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SchemaFlowV1 {
    Input,
    Output,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ConsumerSchemaBindingV1 {
    pub flow: SchemaFlowV1,
    pub schema_id: &'static str,
    pub contract_id: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ConsumerConvergenceProfileV1 {
    pub consumer: CognitiveConsumerV1,
    pub owner: &'static str,
    pub legacy_surfaces: &'static [&'static str],
    pub canonical_bindings: &'static [ConsumerSchemaBindingV1],
    pub shadow_mismatch_metric: &'static str,
    pub cutover_gate: &'static str,
    pub rollback_strategy: &'static str,
}

const COGNITIVE_READ_LEGACY: &[&str] = &["MemoryRecord", "CognitiveSnapshot"];
const COGNITIVE_READ_BINDINGS: &[ConsumerSchemaBindingV1] = &[
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.memory-event.v1",
        contract_id: "MemoryEventV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.cross-modal-binding.v1",
        contract_id: "CrossModalBindingV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.forget-propagation-receipt.v1",
        contract_id: "ForgetPropagationReceiptV1",
    },
];

const COGNITIVE_STORE_LEGACY: &[&str] = &[
    "MemoryRecord",
    "lane_c::MemoryAdmissionCandidateV1",
    "lane_c::MemoryWriteIntentV1",
    "lane_c::MemoryWriteReceiptV1",
];
const COGNITIVE_STORE_BINDINGS: &[ConsumerSchemaBindingV1] = &[
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.memory-event.v1",
        contract_id: "MemoryEventV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Output,
        schema_id: "hepta.cognitive.memory-write-receipt.v1",
        contract_id: "MemoryWriteReceiptV1",
    },
];

const MEMORY_RETRIEVAL_LEGACY: &[&str] = &["generation_bound::RecallPacketV1"];
const MEMORY_RETRIEVAL_BINDINGS: &[ConsumerSchemaBindingV1] = &[
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.memory-cue.v1",
        contract_id: "MemoryCueV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Output,
        schema_id: "hepta.hnmf.recall-packet.v1",
        contract_id: "RecallPacketV1",
    },
];

const COMPACT_ENGINE_LEGACY: &[&str] =
    &["MemoryRecord", "lane_c::CompactCheckpointV1"];
const COMPACT_ENGINE_BINDINGS: &[ConsumerSchemaBindingV1] = &[
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.memory-event.v1",
        contract_id: "MemoryEventV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.forget-propagation-receipt.v1",
        contract_id: "ForgetPropagationReceiptV1",
    },
];

const INTELLIGENCE_CONTROL_LEGACY: &[&str] = &["CognitiveSnapshot"];
const INTELLIGENCE_CONTROL_BINDINGS: &[ConsumerSchemaBindingV1] = &[
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.recall-packet.v1",
        contract_id: "RecallPacketV1",
    },
    ConsumerSchemaBindingV1 {
        flow: SchemaFlowV1::Input,
        schema_id: "hepta.hnmf.outcome-signal.v1",
        contract_id: "OutcomeSignalV1",
    },
];

pub const CONSUMER_CONVERGENCE_PROFILES_V1: &[ConsumerConvergenceProfileV1] = &[
    ConsumerConvergenceProfileV1 {
        consumer: CognitiveConsumerV1::CognitiveRead,
        owner: "cognitive-platform/read",
        legacy_surfaces: COGNITIVE_READ_LEGACY,
        canonical_bindings: COGNITIVE_READ_BINDINGS,
        shadow_mismatch_metric: "hepta_cognitive_read_canonical_shadow_mismatch_total",
        cutover_gate: "cognitive-read-canonical-v1-zero-mismatch-exact-head",
        rollback_strategy: "disable canonical read projection and resume legacy snapshot read",
    },
    ConsumerConvergenceProfileV1 {
        consumer: CognitiveConsumerV1::CognitiveStore,
        owner: "cognitive-platform/store",
        legacy_surfaces: COGNITIVE_STORE_LEGACY,
        canonical_bindings: COGNITIVE_STORE_BINDINGS,
        shadow_mismatch_metric: "hepta_cognitive_store_canonical_shadow_mismatch_total",
        cutover_gate: "cognitive-store-authenticated-canonical-v1-writer",
        rollback_strategy: "stop canonical admission before commit and retain legacy journal replay",
    },
    ConsumerConvergenceProfileV1 {
        consumer: CognitiveConsumerV1::MemoryRetrieval,
        owner: "memory-platform/retrieval",
        legacy_surfaces: MEMORY_RETRIEVAL_LEGACY,
        canonical_bindings: MEMORY_RETRIEVAL_BINDINGS,
        shadow_mismatch_metric: "hepta_memory_retrieval_canonical_shadow_mismatch_total",
        cutover_gate: "memory-retrieval-canonical-v1-recall-equivalence",
        rollback_strategy: "route reads to generation-bound compatibility packet",
    },
    ConsumerConvergenceProfileV1 {
        consumer: CognitiveConsumerV1::CompactEngine,
        owner: "memory-platform/compact",
        legacy_surfaces: COMPACT_ENGINE_LEGACY,
        canonical_bindings: COMPACT_ENGINE_BINDINGS,
        shadow_mismatch_metric: "hepta_compact_engine_canonical_shadow_mismatch_total",
        cutover_gate: "compact-engine-canonical-v1-reconstruction-proof",
        rollback_strategy: "retain predecessor checkpoint and disable canonical compaction publication",
    },
    ConsumerConvergenceProfileV1 {
        consumer: CognitiveConsumerV1::IntelligenceControl,
        owner: "intelligence-platform/control",
        legacy_surfaces: INTELLIGENCE_CONTROL_LEGACY,
        canonical_bindings: INTELLIGENCE_CONTROL_BINDINGS,
        shadow_mismatch_metric: "hepta_intelligence_control_canonical_shadow_mismatch_total",
        cutover_gate: "intelligence-control-canonical-v1-policy-equivalence",
        rollback_strategy: "restore legacy snapshot adapter without changing authority epoch",
    },
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowComparisonStateV1 {
    Matched,
    Mismatched,
    LegacyOnly,
    CanonicalOnly,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowComparisonReceiptV1 {
    pub comparison_id: StableId,
    pub consumer: CognitiveConsumerV1,
    pub legacy_digest: Option<Digest32>,
    pub canonical_digest: Option<Digest32>,
    pub state: ShadowComparisonStateV1,
    pub observed_at_unix_ms: u64,
    pub profile_revision_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConsumerConvergenceErrorV1 {
    MissingConsumer,
    DuplicateConsumer,
    EmptyOwner,
    EmptyLegacySurface,
    EmptyCanonicalBinding,
    DuplicateCanonicalBinding,
    DuplicateMetric,
    DuplicateGate,
    UnknownSchemaBinding,
    RequestedFlowMismatch,
    InvalidShadowState,
    EmptyDigest(&'static str),
    ZeroObservedAt,
    DigestMismatch,
    AuthorityGranted,
    Registry(String),
    Wire(String),
}

impl fmt::Display for ConsumerConvergenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ConsumerConvergenceErrorV1 {}

impl ShadowComparisonReceiptV1 {
    pub fn new(
        comparison_id: StableId,
        consumer: CognitiveConsumerV1,
        legacy_digest: Option<Digest32>,
        canonical_digest: Option<Digest32>,
        observed_at_unix_ms: u64,
    ) -> Result<Self, ConsumerConvergenceErrorV1> {
        let state = match (legacy_digest, canonical_digest) {
            (Some(legacy), Some(canonical)) if legacy == canonical => {
                ShadowComparisonStateV1::Matched
            }
            (Some(_), Some(_)) => ShadowComparisonStateV1::Mismatched,
            (Some(_), None) => ShadowComparisonStateV1::LegacyOnly,
            (None, Some(_)) => ShadowComparisonStateV1::CanonicalOnly,
            (None, None) => return Err(ConsumerConvergenceErrorV1::InvalidShadowState),
        };
        let mut receipt = Self {
            comparison_id,
            consumer,
            legacy_digest,
            canonical_digest,
            state,
            observed_at_unix_ms,
            profile_revision_digest: Digest32::of_bytes(
                CONSUMER_PROFILE_REVISION_V1.as_bytes(),
            ),
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_receipt_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), ConsumerConvergenceErrorV1> {
        if self.observed_at_unix_ms == 0 {
            return Err(ConsumerConvergenceErrorV1::ZeroObservedAt);
        }
        for (field, digest) in [
            ("profile_revision", self.profile_revision_digest),
            ("shadow_receipt", self.receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(ConsumerConvergenceErrorV1::EmptyDigest(field));
            }
        }
        if self.legacy_digest.is_some_and(Digest32::is_zero) {
            return Err(ConsumerConvergenceErrorV1::EmptyDigest("legacy"));
        }
        if self.canonical_digest.is_some_and(Digest32::is_zero) {
            return Err(ConsumerConvergenceErrorV1::EmptyDigest("canonical"));
        }
        let expected_state = match (self.legacy_digest, self.canonical_digest) {
            (Some(legacy), Some(canonical)) if legacy == canonical => {
                ShadowComparisonStateV1::Matched
            }
            (Some(_), Some(_)) => ShadowComparisonStateV1::Mismatched,
            (Some(_), None) => ShadowComparisonStateV1::LegacyOnly,
            (None, Some(_)) => ShadowComparisonStateV1::CanonicalOnly,
            (None, None) => return Err(ConsumerConvergenceErrorV1::InvalidShadowState),
        };
        if expected_state != self.state {
            return Err(ConsumerConvergenceErrorV1::InvalidShadowState);
        }
        if self.authority.grants_any() {
            return Err(ConsumerConvergenceErrorV1::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ConsumerConvergenceErrorV1::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn cutover_eligible(&self) -> bool {
        self.validate().is_ok() && self.state == ShadowComparisonStateV1::Matched
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cognitive.consumer-shadow-receipt.v1\0".to_vec();
        push_text(&mut bytes, self.comparison_id.as_str());
        push_text(&mut bytes, self.consumer.as_str());
        push_optional_digest(&mut bytes, self.legacy_digest);
        push_optional_digest(&mut bytes, self.canonical_digest);
        bytes.push(shadow_state_code(self.state));
        bytes.extend_from_slice(&self.observed_at_unix_ms.to_be_bytes());
        bytes.extend_from_slice(self.profile_revision_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub fn validate_consumer_convergence_registry_v1(
) -> Result<(), ConsumerConvergenceErrorV1> {
    if CONSUMER_CONVERGENCE_PROFILES_V1.len() != REGISTERED_CONSUMER_COUNT_V1 {
        return Err(ConsumerConvergenceErrorV1::MissingConsumer);
    }
    let mut consumers = BTreeSet::new();
    let mut metrics = BTreeSet::new();
    let mut gates = BTreeSet::new();
    for profile in CONSUMER_CONVERGENCE_PROFILES_V1 {
        if !consumers.insert(profile.consumer) {
            return Err(ConsumerConvergenceErrorV1::DuplicateConsumer);
        }
        if profile.owner.trim().is_empty() {
            return Err(ConsumerConvergenceErrorV1::EmptyOwner);
        }
        if profile.legacy_surfaces.is_empty()
            || profile
                .legacy_surfaces
                .iter()
                .any(|surface| surface.trim().is_empty())
        {
            return Err(ConsumerConvergenceErrorV1::EmptyLegacySurface);
        }
        if profile.canonical_bindings.is_empty() {
            return Err(ConsumerConvergenceErrorV1::EmptyCanonicalBinding);
        }
        let mut bindings = BTreeSet::new();
        for binding in profile.canonical_bindings {
            if !bindings.insert((binding.flow, binding.schema_id, binding.contract_id)) {
                return Err(ConsumerConvergenceErrorV1::DuplicateCanonicalBinding);
            }
            if !crate::registry::REGISTERED_CONTRACTS_V1
                .iter()
                .any(|registered| {
                    registered.schema_id == binding.schema_id
                        && registered.contract_id == binding.contract_id
                })
            {
                return Err(ConsumerConvergenceErrorV1::UnknownSchemaBinding);
            }
        }
        if !metrics.insert(profile.shadow_mismatch_metric) {
            return Err(ConsumerConvergenceErrorV1::DuplicateMetric);
        }
        if !gates.insert(profile.cutover_gate) {
            return Err(ConsumerConvergenceErrorV1::DuplicateGate);
        }
        if profile.rollback_strategy.trim().is_empty() {
            return Err(ConsumerConvergenceErrorV1::EmptyLegacySurface);
        }
    }
    Ok(())
}

pub fn decode_registered_for_consumer_v1<T: CognitiveContractV1>(
    consumer: CognitiveConsumerV1,
    flow: SchemaFlowV1,
    bytes: &[u8],
) -> Result<Validated<T>, ConsumerConvergenceErrorV1> {
    let profile = CONSUMER_CONVERGENCE_PROFILES_V1
        .iter()
        .find(|profile| profile.consumer == consumer)
        .ok_or(ConsumerConvergenceErrorV1::MissingConsumer)?;
    if !profile.canonical_bindings.iter().any(|binding| {
        binding.flow == flow
            && binding.schema_id == T::SCHEMA_ID
            && binding.contract_id == T::CONTRACT_ID
    }) {
        return Err(ConsumerConvergenceErrorV1::RequestedFlowMismatch);
    }
    let value = decode_registered_wire_v1::<T>(bytes)
        .map_err(|error| ConsumerConvergenceErrorV1::Registry(error.to_string()))?;
    Validated::from_cognitive_contract(value)
        .map_err(|error| ConsumerConvergenceErrorV1::Wire(error.to_string()))
}

const fn shadow_state_code(value: ShadowComparisonStateV1) -> u8 {
    match value {
        ShadowComparisonStateV1::Matched => 0,
        ShadowComparisonStateV1::Mismatched => 1,
        ShadowComparisonStateV1::LegacyOnly => 2,
        ShadowComparisonStateV1::CanonicalOnly => 3,
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u64::try_from(value.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}
