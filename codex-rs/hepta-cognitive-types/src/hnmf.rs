//! Canonical HNMF cognitive/memory contracts.
//!
//! This module is the single production owner for the versioned multimodal
//! memory contracts described by docs/hnmf.  The values are bounded,
//! authority-free and serde-ready so Rust and canonical JSON share one semantic
//! definition instead of maintaining a second qualification-only type system.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::Error as _;

use crate::wire::CanonicalContractV1;

pub const PPM: u32 = 1_000_000;
pub const MAX_EVENT_SPANS: usize = 32;
pub const MAX_EVENT_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_EVENT_REFERENCES: usize = 64;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 64;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_CUE_MODALITIES: usize = 9;
pub const MAX_RECALL_EVENTS: usize = 16;
pub const MAX_ACTIVATION_PATHS: usize = 32;
pub const MAX_ACTIVE_NODES: usize = 4_096;
pub const MAX_REPLAY_SELECTION: usize = 256;
pub const MAX_REPLAY_CANDIDATES: u32 = 4_096;
pub const MAX_CANDIDATE_EVENTS: u32 = 512;
pub const MAX_ENGRAM_NODES: u32 = 4_096;
pub const MAX_SYNAPSES: u32 = 32_768;
pub const MAX_SETTLING_STEPS: u8 = 4;
pub const MAX_WEIGHT_DELTA_PPM: i32 = 50_000;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct CanonicalIdV1(String);

impl CanonicalIdV1 {
    pub fn new(value: impl Into<String>) -> Result<Self, CognitiveContractError> {
        let value = value.into();
        StableId::new(value.clone())
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid id: {error}")))?;
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn to_stable_id(&self) -> Result<StableId, CognitiveContractError> {
        StableId::new(self.0.clone())
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid id: {error}")))
    }
}

impl<'de> Deserialize<'de> for CanonicalIdV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

impl From<&StableId> for CanonicalIdV1 {
    fn from(value: &StableId) -> Self {
        Self(value.as_str().to_owned())
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Sha256DigestV1(String);

impl Sha256DigestV1 {
    pub fn new(value: impl Into<String>) -> Result<Self, CognitiveContractError> {
        let value = value.into();
        let digest = Digest32::from_str(&value)
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid sha256: {error}")))?;
        if digest.is_zero() {
            return Err(CognitiveContractError::Invalid("sha256 digest must be non-zero"));
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn to_digest32(&self) -> Result<Digest32, CognitiveContractError> {
        Digest32::from_str(&self.0)
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid sha256: {error}")))
    }
}

impl<'de> Deserialize<'de> for Sha256DigestV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

impl From<Digest32> for Sha256DigestV1 {
    fn from(value: Digest32) -> Self {
        Self(value.to_string())
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct GenerationV1(u64);

impl GenerationV1 {
    pub fn new(value: u64) -> Result<Self, CognitiveContractError> {
        Generation::new(value)
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid generation: {error}")))?;
        Ok(Self(value))
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }

    pub fn next(self) -> Result<Self, CognitiveContractError> {
        let next = self
            .0
            .checked_add(1)
            .ok_or(CognitiveContractError::Invalid("generation overflow"))?;
        Self::new(next)
    }
}

impl<'de> Deserialize<'de> for GenerationV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(u64::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

impl From<Generation> for GenerationV1 {
    fn from(value: Generation) -> Self {
        Self(value.get())
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RevisionV1(u64);

impl RevisionV1 {
    pub fn new(value: u64) -> Result<Self, CognitiveContractError> {
        Revision::new(value)
            .map_err(|error| CognitiveContractError::InvalidOwned(format!("invalid revision: {error}")))?;
        Ok(Self(value))
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

impl<'de> Deserialize<'de> for RevisionV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(u64::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

impl From<Revision> for RevisionV1 {
    fn from(value: Revision) -> Self {
        Self(value.get())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveContractError {
    Invalid(&'static str),
    InvalidOwned(String),
    LimitExceeded {
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
    DuplicateIdentity(&'static str),
    MissingReference(&'static str),
    ScopeMismatch(&'static str),
}

impl fmt::Display for CognitiveContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid cognitive contract: {message}"),
            Self::InvalidOwned(message) => write!(formatter, "invalid cognitive contract: {message}"),
            Self::LimitExceeded {
                field,
                actual,
                maximum,
            } => write!(
                formatter,
                "cognitive contract limit exceeded for {field}: {actual} > {maximum}"
            ),
            Self::DuplicateIdentity(field) => {
                write!(formatter, "duplicate cognitive contract identity: {field}")
            }
            Self::MissingReference(field) => {
                write!(formatter, "missing cognitive contract reference: {field}")
            }
            Self::ScopeMismatch(field) => {
                write!(formatter, "cognitive contract scope mismatch: {field}")
            }
        }
    }
}

impl StdError for CognitiveContractError {}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ModalityV1 {
    Text,
    Image,
    Audio,
    Video,
    CodeAst,
    GuiState,
    ToolTrajectory,
    StructuredData,
    Sensor,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyClassV1 {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum MemoryScopeV1 {
    AgentPrivate {
        agent_id: CanonicalIdV1,
    },
    WorkspacePrivate {
        agent_id: CanonicalIdV1,
        workspace_sha256: Sha256DigestV1,
    },
}

impl MemoryScopeV1 {
    #[must_use]
    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        match self {
            Self::AgentPrivate { .. } => PrivacyClassV1::AgentPrivate,
            Self::WorkspacePrivate { .. } => PrivacyClassV1::WorkspacePrivate,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObservedIntervalV1 {
    pub start_unix_ms: u64,
    pub end_unix_ms: Option<u64>,
}

impl ObservedIntervalV1 {
    pub fn validate(self) -> Result<(), CognitiveContractError> {
        if self.start_unix_ms == 0 {
            return Err(CognitiveContractError::Invalid(
                "observed interval start must be non-zero",
            ));
        }
        if self
            .end_unix_ms
            .is_some_and(|end| end <= self.start_unix_ms)
        {
            return Err(CognitiveContractError::Invalid(
                "observed interval must be increasing",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SpanRangeV1 {
    ByteRange {
        start: u64,
        end: u64,
    },
    PixelRect {
        x: u32,
        y: u32,
        width: u32,
        height: u32,
    },
    SampleRange {
        start: u64,
        end: u64,
        sample_rate_hz: u32,
    },
    FrameRange {
        start: u64,
        end: u64,
        timebase_num: u32,
        timebase_den: u32,
    },
    AstPath {
        path: String,
    },
    GuiNode {
        stable_node_id: String,
    },
    EventRange {
        start: u64,
        end: u64,
    },
    JsonPointer {
        pointer: String,
    },
    SensorRange {
        start: u64,
        end: u64,
        unit: String,
    },
}

impl SpanRangeV1 {
    pub fn validate_for(&self, modality: ModalityV1) -> Result<(), CognitiveContractError> {
        match (modality, self) {
            (ModalityV1::Text, Self::ByteRange { start, end })
            | (ModalityV1::ToolTrajectory, Self::EventRange { start, end }) => {
                increasing(*start, *end, "ordered span range")
            }
            (ModalityV1::Image, Self::PixelRect { width, height, .. })
                if *width > 0 && *height > 0 =>
            {
                Ok(())
            }
            (
                ModalityV1::Audio,
                Self::SampleRange {
                    start,
                    end,
                    sample_rate_hz,
                },
            ) if *sample_rate_hz > 0 => increasing(*start, *end, "audio sample range"),
            (
                ModalityV1::Video,
                Self::FrameRange {
                    start,
                    end,
                    timebase_num,
                    timebase_den,
                },
            ) if *timebase_num > 0 && *timebase_den > 0 => {
                increasing(*start, *end, "video frame range")
            }
            (ModalityV1::CodeAst, Self::AstPath { path }) => {
                validate_text(path, 4096, "AST path")
            }
            (ModalityV1::GuiState, Self::GuiNode { stable_node_id }) => {
                validate_text(stable_node_id, 512, "GUI node id")
            }
            (ModalityV1::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(CognitiveContractError::Invalid(
                        "JSON pointer must be empty or start with slash",
                    ));
                }
                validate_bounded_text(pointer, 4096, "JSON pointer")
            }
            (ModalityV1::Sensor, Self::SensorRange { start, end, unit }) => {
                increasing(*start, *end, "sensor range")?;
                validate_text(unit, 128, "sensor unit")
            }
            _ => Err(CognitiveContractError::Invalid(
                "span range kind does not match modality",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum AssetExtentV1 {
    Bytes {
        byte_len: u64,
    },
    Pixels {
        width: u32,
        height: u32,
    },
    Samples {
        sample_count: u64,
        sample_rate_hz: u32,
    },
    Frames {
        frame_count: u64,
        timebase_num: u32,
        timebase_den: u32,
    },
    Events {
        event_count: u64,
    },
    SensorSamples {
        sample_count: u64,
        unit: String,
    },
    SelectorOnly,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AssetManifestV1 {
    pub asset_sha256: Sha256DigestV1,
    pub modality: ModalityV1,
    pub extent: AssetExtentV1,
}

impl AssetManifestV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        match (self.modality, &self.extent) {
            (ModalityV1::Text, AssetExtentV1::Bytes { byte_len }) if *byte_len > 0 => Ok(()),
            (ModalityV1::Image, AssetExtentV1::Pixels { width, height })
                if *width > 0 && *height > 0 =>
            {
                Ok(())
            }
            (
                ModalityV1::Audio,
                AssetExtentV1::Samples {
                    sample_count,
                    sample_rate_hz,
                },
            ) if *sample_count > 0 && *sample_rate_hz > 0 => Ok(()),
            (
                ModalityV1::Video,
                AssetExtentV1::Frames {
                    frame_count,
                    timebase_num,
                    timebase_den,
                },
            ) if *frame_count > 0 && *timebase_num > 0 && *timebase_den > 0 => Ok(()),
            (ModalityV1::ToolTrajectory, AssetExtentV1::Events { event_count })
                if *event_count > 0 =>
            {
                Ok(())
            }
            (
                ModalityV1::Sensor,
                AssetExtentV1::SensorSamples { sample_count, unit },
            ) if *sample_count > 0 => validate_text(unit, 128, "sensor manifest unit"),
            (
                ModalityV1::CodeAst | ModalityV1::GuiState | ModalityV1::StructuredData,
                AssetExtentV1::SelectorOnly,
            ) => Ok(()),
            _ => Err(CognitiveContractError::Invalid(
                "asset extent does not match modality",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModalitySpanRefV1 {
    pub span_id: CanonicalIdV1,
    pub modality: ModalityV1,
    pub asset_sha256: Sha256DigestV1,
    pub range: SpanRangeV1,
    pub preprocessor_manifest_sha256: Sha256DigestV1,
    pub feature_blob_sha256: Option<Sha256DigestV1>,
    pub symbolic_projection_sha256: Option<Sha256DigestV1>,
    pub uncertainty_ppm: u32,
    pub privacy_class: PrivacyClassV1,
    pub redaction_mask_sha256: Option<Sha256DigestV1>,
}

impl ModalitySpanRefV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        self.range.validate_for(self.modality)?;
        validate_ppm(self.uncertainty_ppm, "span uncertainty")
    }

    pub fn validate_against_asset(
        &self,
        asset: &AssetManifestV1,
    ) -> Result<(), CognitiveContractError> {
        self.validate()?;
        asset.validate()?;
        if self.asset_sha256 != asset.asset_sha256 || self.modality != asset.modality {
            return Err(CognitiveContractError::Invalid(
                "span asset identity or modality mismatch",
            ));
        }
        match (&self.range, &asset.extent) {
            (SpanRangeV1::ByteRange { end, .. }, AssetExtentV1::Bytes { byte_len })
                if *end <= *byte_len =>
            {
                Ok(())
            }
            (
                SpanRangeV1::PixelRect {
                    x,
                    y,
                    width,
                    height,
                },
                AssetExtentV1::Pixels {
                    width: asset_width,
                    height: asset_height,
                },
            ) => {
                let right = x.checked_add(*width).ok_or(CognitiveContractError::Invalid(
                    "image rectangle overflow",
                ))?;
                let bottom = y.checked_add(*height).ok_or(CognitiveContractError::Invalid(
                    "image rectangle overflow",
                ))?;
                if right <= *asset_width && bottom <= *asset_height {
                    Ok(())
                } else {
                    Err(CognitiveContractError::Invalid(
                        "image rectangle outside asset",
                    ))
                }
            }
            (
                SpanRangeV1::SampleRange {
                    end,
                    sample_rate_hz,
                    ..
                },
                AssetExtentV1::Samples {
                    sample_count,
                    sample_rate_hz: asset_rate,
                },
            ) if *end <= *sample_count && *sample_rate_hz == *asset_rate => Ok(()),
            (
                SpanRangeV1::FrameRange {
                    end,
                    timebase_num,
                    timebase_den,
                    ..
                },
                AssetExtentV1::Frames {
                    frame_count,
                    timebase_num: asset_num,
                    timebase_den: asset_den,
                },
            ) if *end <= *frame_count
                && *timebase_num == *asset_num
                && *timebase_den == *asset_den =>
            {
                Ok(())
            }
            (
                SpanRangeV1::EventRange { end, .. },
                AssetExtentV1::Events { event_count },
            ) if *end <= *event_count => Ok(()),
            (
                SpanRangeV1::SensorRange { end, unit, .. },
                AssetExtentV1::SensorSamples {
                    sample_count,
                    unit: asset_unit,
                },
            ) if *end <= *sample_count && unit == asset_unit => Ok(()),
            (
                SpanRangeV1::AstPath { .. }
                | SpanRangeV1::GuiNode { .. }
                | SpanRangeV1::JsonPointer { .. },
                AssetExtentV1::SelectorOnly,
            ) => Ok(()),
            _ => Err(CognitiveContractError::Invalid(
                "span range is outside asset extent",
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AlignmentKindV1 {
    SameObservation,
    TemporalOverlap,
    EntityCoreference,
    ActionOutcome,
    DerivedSymbolic,
    AlternativeObservation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CrossModalBindingV1 {
    pub binding_id: CanonicalIdV1,
    pub event_id: CanonicalIdV1,
    pub span_refs: BTreeSet<CanonicalIdV1>,
    pub alignment_kind: AlignmentKindV1,
    pub confidence_ppm: u32,
    pub producer_manifest_sha256: Sha256DigestV1,
}

impl CrossModalBindingV1 {
    fn validate_against(
        &self,
        event_id: &CanonicalIdV1,
        spans: &[ModalitySpanRefV1],
    ) -> Result<(), CognitiveContractError> {
        if &self.event_id != event_id {
            return Err(CognitiveContractError::Invalid(
                "cross-modal binding event id mismatch",
            ));
        }
        if !(2..=MAX_BINDING_SPANS).contains(&self.span_refs.len()) {
            return Err(CognitiveContractError::LimitExceeded {
                field: "binding span refs",
                actual: self.span_refs.len(),
                maximum: MAX_BINDING_SPANS,
            });
        }
        validate_ppm(self.confidence_ppm, "binding confidence")?;
        let mut modalities = BTreeSet::new();
        for span_id in &self.span_refs {
            let span = spans
                .iter()
                .find(|span| &span.span_id == span_id)
                .ok_or(CognitiveContractError::MissingReference("binding span"))?;
            modalities.insert(span.modality);
        }
        if modalities.len() < 2 {
            return Err(CognitiveContractError::Invalid(
                "cross-modal binding must contain at least two modalities",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProvenanceRefV1 {
    pub source_id: CanonicalIdV1,
    pub source_revision: RevisionV1,
    pub source_sha256: Sha256DigestV1,
    pub observed_at_unix_ms: u64,
}

impl ProvenanceRefV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.observed_at_unix_ms == 0 {
            return Err(CognitiveContractError::Invalid(
                "provenance observed time must be non-zero",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryVerificationV1 {
    Unverified,
    Verified,
    Contradicted,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RetentionPolicyV1 {
    pub policy_id: CanonicalIdV1,
    pub expires_unix_ms: Option<u64>,
    pub legal_hold: bool,
}

impl RetentionPolicyV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.legal_hold && self.expires_unix_ms.is_some() {
            return Err(CognitiveContractError::Invalid(
                "legal hold cannot carry an expiry",
            ));
        }
        if self.expires_unix_ms == Some(0) {
            return Err(CognitiveContractError::Invalid(
                "retention expiry must be non-zero",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum MemoryLifecycleV1 {
    Active,
    Correction {
        predecessor_event_id: CanonicalIdV1,
    },
    Tombstone {
        target_event_id: CanonicalIdV1,
        reason_sha256: Sha256DigestV1,
    },
}

impl MemoryLifecycleV1 {
    fn validate_for(&self, event_id: &CanonicalIdV1) -> Result<(), CognitiveContractError> {
        match self {
            Self::Active => Ok(()),
            Self::Correction {
                predecessor_event_id,
            } if predecessor_event_id != event_id => Ok(()),
            Self::Tombstone {
                target_event_id, ..
            } if target_event_id != event_id => Ok(()),
            Self::Correction { .. } => Err(CognitiveContractError::Invalid(
                "correction predecessor must differ from event id",
            )),
            Self::Tombstone { .. } => Err(CognitiveContractError::Invalid(
                "tombstone target must differ from event id",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryEventV1 {
    pub event_id: CanonicalIdV1,
    pub episode_id: CanonicalIdV1,
    pub scope: MemoryScopeV1,
    pub observed_interval: ObservedIntervalV1,
    pub modality_spans: Vec<ModalitySpanRefV1>,
    #[serde(default)]
    pub cross_modal_bindings: Vec<CrossModalBindingV1>,
    pub semantic_keys: BTreeSet<String>,
    #[serde(default)]
    pub causal_parents: BTreeSet<CanonicalIdV1>,
    #[serde(default)]
    pub temporal_neighbors: BTreeSet<CanonicalIdV1>,
    pub provenance: BTreeSet<ProvenanceRefV1>,
    pub verification: MemoryVerificationV1,
    pub retention_policy: RetentionPolicyV1,
    pub objective_digest: Sha256DigestV1,
    pub ndu_state_digest: Sha256DigestV1,
    pub lifecycle: MemoryLifecycleV1,
}

impl MemoryEventV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        self.observed_interval.validate()?;
        self.retention_policy.validate()?;
        self.lifecycle.validate_for(&self.event_id)?;
        bounded_nonempty(
            self.modality_spans.len(),
            MAX_EVENT_SPANS,
            "event modality spans",
        )?;
        if self.cross_modal_bindings.len() > MAX_EVENT_BINDINGS {
            return Err(CognitiveContractError::LimitExceeded {
                field: "event cross-modal bindings",
                actual: self.cross_modal_bindings.len(),
                maximum: MAX_EVENT_BINDINGS,
            });
        }
        validate_semantic_keys(&self.semantic_keys)?;
        bounded_set(
            self.causal_parents.len(),
            MAX_EVENT_REFERENCES,
            "event causal parents",
        )?;
        bounded_set(
            self.temporal_neighbors.len(),
            MAX_EVENT_REFERENCES,
            "event temporal neighbors",
        )?;
        bounded_nonempty(self.provenance.len(), MAX_PROVENANCE, "event provenance")?;

        let mut span_ids = BTreeSet::new();
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class != self.scope.privacy_class() {
                return Err(CognitiveContractError::ScopeMismatch(
                    "span privacy class does not match event scope",
                ));
            }
            if !span_ids.insert(span.span_id.clone()) {
                return Err(CognitiveContractError::DuplicateIdentity("span_id"));
            }
        }
        let mut binding_ids = BTreeSet::new();
        for binding in &self.cross_modal_bindings {
            if !binding_ids.insert(binding.binding_id.clone()) {
                return Err(CognitiveContractError::DuplicateIdentity("binding_id"));
            }
            binding.validate_against(&self.event_id, &self.modality_spans)?;
        }
        for provenance in &self.provenance {
            provenance.validate()?;
        }
        if self.causal_parents.contains(&self.event_id)
            || self.temporal_neighbors.contains(&self.event_id)
        {
            return Err(CognitiveContractError::Invalid(
                "memory event cannot reference itself",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngramPopulationV1 {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EngramNodeV1 {
    pub node_id: CanonicalIdV1,
    pub population: EngramPopulationV1,
    pub modality_mask: BTreeSet<ModalityV1>,
    pub semantic_keys: BTreeSet<String>,
    pub support_manifest_sha256: Sha256DigestV1,
    pub threshold_q16: i64,
    pub target_activity_ppm: u32,
    pub confidence_ppm: u32,
    pub snapshot_generation: GenerationV1,
}

impl EngramNodeV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        bounded_nonempty(
            self.modality_mask.len(),
            MAX_CUE_MODALITIES,
            "engram modality mask",
        )?;
        validate_semantic_keys(&self.semantic_keys)?;
        validate_ppm(self.target_activity_ppm, "engram target activity")?;
        validate_ppm(self.confidence_ppm, "engram confidence")
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SynapseRelationV1 {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseV1 {
    pub source_node_id: CanonicalIdV1,
    pub target_node_id: CanonicalIdV1,
    pub relation: SynapseRelationV1,
    pub weight_q16: i64,
    pub delay_steps: u8,
    pub plasticity_class: CanonicalIdV1,
    pub support_manifest_sha256: Sha256DigestV1,
    pub snapshot_generation: GenerationV1,
}

impl SynapseV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.source_node_id == self.target_node_id {
            return Err(CognitiveContractError::Invalid(
                "synapse endpoints must be distinct",
            ));
        }
        if !(-65_536..=65_536).contains(&self.weight_q16) {
            return Err(CognitiveContractError::Invalid(
                "synapse weight outside Q16 bound",
            ));
        }
        if self.delay_steps > MAX_SETTLING_STEPS {
            return Err(CognitiveContractError::Invalid(
                "synapse delay exceeds settling bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceBudgetV1 {
    pub candidate_events: u32,
    pub engram_nodes: u32,
    pub synapses: u32,
    pub settling_steps: u8,
    pub final_recalled_events: u16,
}

impl ResourceBudgetV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        bounded_u32(
            self.candidate_events,
            MAX_CANDIDATE_EVENTS,
            "candidate events",
        )?;
        bounded_u32(self.engram_nodes, MAX_ENGRAM_NODES, "engram nodes")?;
        bounded_u32(self.synapses, MAX_SYNAPSES, "synapses")?;
        if self.settling_steps == 0 || self.settling_steps > MAX_SETTLING_STEPS {
            return Err(CognitiveContractError::Invalid(
                "settling steps outside bound",
            ));
        }
        if self.final_recalled_events == 0
            || usize::from(self.final_recalled_events) > MAX_RECALL_EVENTS
        {
            return Err(CognitiveContractError::Invalid(
                "final recall count outside bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCueV1 {
    pub cue_id: CanonicalIdV1,
    pub objective_digest: Sha256DigestV1,
    pub ndu_state_digest: Sha256DigestV1,
    pub modalities: BTreeSet<ModalityV1>,
    pub semantic_keys: BTreeSet<String>,
    pub seed_node_ids: BTreeSet<CanonicalIdV1>,
    pub now_unix_ms: u64,
    pub resource_budget: ResourceBudgetV1,
}

impl MemoryCueV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        bounded_nonempty(
            self.modalities.len(),
            MAX_CUE_MODALITIES,
            "cue modalities",
        )?;
        validate_semantic_keys(&self.semantic_keys)?;
        if self.seed_node_ids.len() > MAX_CUE_SEEDS {
            return Err(CognitiveContractError::LimitExceeded {
                field: "cue seed nodes",
                actual: self.seed_node_ids.len(),
                maximum: MAX_CUE_SEEDS,
            });
        }
        if self.now_unix_ms == 0 {
            return Err(CognitiveContractError::Invalid(
                "cue time must be non-zero",
            ));
        }
        self.resource_budget.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SelectedEventV1 {
    pub event_id: CanonicalIdV1,
    pub revision: RevisionV1,
    pub event_digest: Sha256DigestV1,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActiveNodeV1 {
    pub node_id: CanonicalIdV1,
    pub activation_ppm: u32,
}

impl ActiveNodeV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        validate_ppm(self.activation_ppm, "active node activation")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivationPathV1 {
    pub node_ids: Vec<CanonicalIdV1>,
    pub support_digest: Sha256DigestV1,
}

impl ActivationPathV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.node_ids.len() < 2 || self.node_ids.len() > 64 {
            return Err(CognitiveContractError::LimitExceeded {
                field: "activation path nodes",
                actual: self.node_ids.len(),
                maximum: 64,
            });
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContradictionGroupV1 {
    pub event_ids: BTreeSet<CanonicalIdV1>,
    pub support_digest: Sha256DigestV1,
}

impl ContradictionGroupV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.event_ids.len() < 2 || self.event_ids.len() > 64 {
            return Err(CognitiveContractError::LimitExceeded {
                field: "contradiction events",
                actual: self.event_ids.len(),
                maximum: 64,
            });
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AbstainReasonV1 {
    Contradiction,
    LowCoverage,
    LowConfidence,
    OutOfDistribution,
    ResourceLimit,
    StaleSnapshot,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceReceiptV1 {
    pub candidate_events_seen: u32,
    pub engram_nodes_visited: u32,
    pub synapses_visited: u32,
    pub settling_steps: u8,
    pub recalled_events: u16,
    pub truncated: bool,
}

impl ResourceReceiptV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.candidate_events_seen > MAX_CANDIDATE_EVENTS
            || self.engram_nodes_visited > MAX_ENGRAM_NODES
            || self.synapses_visited > MAX_SYNAPSES
            || self.settling_steps > MAX_SETTLING_STEPS
            || usize::from(self.recalled_events) > MAX_RECALL_EVENTS
        {
            return Err(CognitiveContractError::Invalid(
                "resource receipt exceeds hard bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallPacketV1 {
    pub cue_digest: Sha256DigestV1,
    pub event_snapshot_digest: Sha256DigestV1,
    pub engram_snapshot_digest: Sha256DigestV1,
    pub selected_events: BTreeSet<SelectedEventV1>,
    pub active_nodes: BTreeSet<ActiveNodeV1>,
    pub activation_paths: BTreeSet<ActivationPathV1>,
    pub contradictions: BTreeSet<ContradictionGroupV1>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: Option<AbstainReasonV1>,
    pub resource_receipt: ResourceReceiptV1,
}

impl RecallPacketV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.selected_events.len() > MAX_RECALL_EVENTS {
            return Err(CognitiveContractError::LimitExceeded {
                field: "selected recall events",
                actual: self.selected_events.len(),
                maximum: MAX_RECALL_EVENTS,
            });
        }
        if self.active_nodes.len() > MAX_ACTIVE_NODES {
            return Err(CognitiveContractError::LimitExceeded {
                field: "active nodes",
                actual: self.active_nodes.len(),
                maximum: MAX_ACTIVE_NODES,
            });
        }
        if self.activation_paths.len() > MAX_ACTIVATION_PATHS {
            return Err(CognitiveContractError::LimitExceeded {
                field: "activation paths",
                actual: self.activation_paths.len(),
                maximum: MAX_ACTIVATION_PATHS,
            });
        }
        validate_ppm(self.coverage_ppm, "recall coverage")?;
        validate_ppm(self.confidence_ppm, "recall confidence")?;
        validate_ppm(self.ood_ppm, "recall OOD")?;
        for node in &self.active_nodes {
            node.validate()?;
        }
        for path in &self.activation_paths {
            path.validate()?;
        }
        for contradiction in &self.contradictions {
            contradiction.validate()?;
        }
        if self.abstain.is_none()
            && (self.selected_events.is_empty()
                || self.coverage_ppm == 0
                || self.confidence_ppm == 0)
        {
            return Err(CognitiveContractError::Invalid(
                "non-abstaining recall must contain positive supported output",
            ));
        }
        self.resource_receipt.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeSignalV1 {
    pub episode_id: CanonicalIdV1,
    pub utility_delta_ppm: i32,
    pub prediction_error_ppm: u32,
    pub novelty_ppm: u32,
    pub risk_ppm: u32,
    pub ood_ppm: u32,
    pub observer_digest: Sha256DigestV1,
}

impl OutcomeSignalV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if !(-1_000_000..=1_000_000).contains(&self.utility_delta_ppm) {
            return Err(CognitiveContractError::Invalid(
                "utility delta outside ppm range",
            ));
        }
        validate_ppm(self.prediction_error_ppm, "prediction error")?;
        validate_ppm(self.novelty_ppm, "novelty")?;
        validate_ppm(self.risk_ppm, "risk")?;
        validate_ppm(self.ood_ppm, "OOD")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceBucketCountV1 {
    pub source_id: CanonicalIdV1,
    pub selected_count: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplaySelectionReceiptV1 {
    pub candidate_set_digest: Sha256DigestV1,
    pub selected_event_ids: BTreeSet<CanonicalIdV1>,
    pub source_bucket_counts: BTreeSet<SourceBucketCountV1>,
    pub selection_policy_digest: Sha256DigestV1,
    pub resource_receipt: ResourceReceiptV1,
}

impl ReplaySelectionReceiptV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.selected_event_ids.len() > MAX_REPLAY_SELECTION {
            return Err(CognitiveContractError::LimitExceeded {
                field: "replay selection",
                actual: self.selected_event_ids.len(),
                maximum: MAX_REPLAY_SELECTION,
            });
        }
        if self.source_bucket_counts.len() > MAX_PROVENANCE {
            return Err(CognitiveContractError::LimitExceeded {
                field: "replay source buckets",
                actual: self.source_bucket_counts.len(),
                maximum: MAX_PROVENANCE,
            });
        }
        let selected = self
            .source_bucket_counts
            .iter()
            .try_fold(0_u64, |total, bucket| {
                total
                    .checked_add(u64::from(bucket.selected_count))
                    .ok_or(CognitiveContractError::Invalid(
                        "replay source bucket count overflow",
                    ))
            })?;
        if selected != self.selected_event_ids.len() as u64 {
            return Err(CognitiveContractError::Invalid(
                "replay source bucket counts must equal selected events",
            ));
        }
        self.resource_receipt.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WeightProposalV1 {
    pub source_node_id: CanonicalIdV1,
    pub target_node_id: CanonicalIdV1,
    pub proposed_weight_q16: i64,
    pub delta_ppm: i32,
    pub support_digest: Sha256DigestV1,
}

impl WeightProposalV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.source_node_id == self.target_node_id {
            return Err(CognitiveContractError::Invalid(
                "weight proposal endpoints must be distinct",
            ));
        }
        if !(-65_536..=65_536).contains(&self.proposed_weight_q16)
            || !(-MAX_WEIGHT_DELTA_PPM..=MAX_WEIGHT_DELTA_PPM).contains(&self.delta_ppm)
        {
            return Err(CognitiveContractError::Invalid(
                "weight proposal outside bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ThresholdProposalV1 {
    pub node_id: CanonicalIdV1,
    pub proposed_threshold_q16: i64,
    pub delta_ppm: i32,
    pub support_digest: Sha256DigestV1,
}

impl ThresholdProposalV1 {
    fn validate(&self) -> Result<(), CognitiveContractError> {
        if !(-65_536..=65_536).contains(&self.proposed_threshold_q16)
            || !(-MAX_WEIGHT_DELTA_PPM..=MAX_WEIGHT_DELTA_PPM).contains(&self.delta_ppm)
        {
            return Err(CognitiveContractError::Invalid(
                "threshold proposal outside bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PlasticityBatchV1 {
    pub predecessor_generation: GenerationV1,
    pub next_generation: GenerationV1,
    pub outcome_signal_digest: Sha256DigestV1,
    pub weight_proposals: Vec<WeightProposalV1>,
    pub threshold_proposals: Vec<ThresholdProposalV1>,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

impl PlasticityBatchV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.predecessor_generation.next()? != self.next_generation {
            return Err(CognitiveContractError::Invalid(
                "plasticity generation must advance exactly once",
            ));
        }
        if self.weight_proposals.len() > MAX_SYNAPSES as usize {
            return Err(CognitiveContractError::LimitExceeded {
                field: "weight proposals",
                actual: self.weight_proposals.len(),
                maximum: MAX_SYNAPSES as usize,
            });
        }
        if self.threshold_proposals.len() > MAX_ACTIVE_NODES {
            return Err(CognitiveContractError::LimitExceeded {
                field: "threshold proposals",
                actual: self.threshold_proposals.len(),
                maximum: MAX_ACTIVE_NODES,
            });
        }
        for proposal in &self.weight_proposals {
            proposal.validate()?;
        }
        for proposal in &self.threshold_proposals {
            proposal.validate()?;
        }
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(CognitiveContractError::Invalid(
                "plasticity must be next-snapshot-only and non-activating",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TopologyOperationV1 {
    Add,
    Split,
    Merge,
    Retire,
    Rewire,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryTopologyProposalV1 {
    pub predecessor_generation: GenerationV1,
    pub next_generation: GenerationV1,
    pub operation: TopologyOperationV1,
    pub subject_ids: BTreeSet<CanonicalIdV1>,
    pub capability_typed: bool,
    pub sandbox_only: bool,
    pub operator_accepted: bool,
    pub production_activation_allowed: bool,
}

impl MemoryTopologyProposalV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.predecessor_generation.next()? != self.next_generation {
            return Err(CognitiveContractError::Invalid(
                "topology generation must advance exactly once",
            ));
        }
        bounded_nonempty(self.subject_ids.len(), 64, "topology subjects")?;
        if !self.capability_typed || !self.sandbox_only || self.production_activation_allowed {
            return Err(CognitiveContractError::Invalid(
                "topology proposal must remain capability-typed sandbox-only and non-activating",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseRefV1 {
    pub source_node_id: CanonicalIdV1,
    pub target_node_id: CanonicalIdV1,
    pub relation: SynapseRelationV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ForgetPropagationReceiptV1 {
    pub event_id: CanonicalIdV1,
    pub predecessor_generation: GenerationV1,
    pub next_generation: GenerationV1,
    pub retired_node_ids: BTreeSet<CanonicalIdV1>,
    pub retired_synapses: BTreeSet<SynapseRefV1>,
    pub projection_rebuild_required: bool,
    pub artifact_revocation_required: bool,
}

impl ForgetPropagationReceiptV1 {
    pub fn validate(&self) -> Result<(), CognitiveContractError> {
        if self.predecessor_generation.next()? != self.next_generation {
            return Err(CognitiveContractError::Invalid(
                "forget propagation generation must advance exactly once",
            ));
        }
        if self.retired_node_ids.len() > MAX_ENGRAM_NODES as usize {
            return Err(CognitiveContractError::LimitExceeded {
                field: "retired nodes",
                actual: self.retired_node_ids.len(),
                maximum: MAX_ENGRAM_NODES as usize,
            });
        }
        if self.retired_synapses.len() > MAX_SYNAPSES as usize {
            return Err(CognitiveContractError::LimitExceeded {
                field: "retired synapses",
                actual: self.retired_synapses.len(),
                maximum: MAX_SYNAPSES as usize,
            });
        }
        if !self.projection_rebuild_required || !self.artifact_revocation_required {
            return Err(CognitiveContractError::Invalid(
                "forget propagation must require projection rebuild and artifact revocation",
            ));
        }
        Ok(())
    }
}

fn validate_ppm(value: u32, field: &'static str) -> Result<(), CognitiveContractError> {
    if value > PPM {
        return Err(CognitiveContractError::Invalid(field));
    }
    Ok(())
}

fn increasing(start: u64, end: u64, field: &'static str) -> Result<(), CognitiveContractError> {
    if end <= start {
        return Err(CognitiveContractError::Invalid(field));
    }
    Ok(())
}

fn validate_text(
    value: &str,
    maximum_bytes: usize,
    field: &'static str,
) -> Result<(), CognitiveContractError> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control)
    {
        return Err(CognitiveContractError::Invalid(field));
    }
    Ok(())
}

fn validate_bounded_text(
    value: &str,
    maximum_bytes: usize,
    field: &'static str,
) -> Result<(), CognitiveContractError> {
    if value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(CognitiveContractError::Invalid(field));
    }
    Ok(())
}

fn validate_semantic_keys(keys: &BTreeSet<String>) -> Result<(), CognitiveContractError> {
    bounded_nonempty(keys.len(), MAX_SEMANTIC_KEYS, "semantic keys")?;
    if keys.iter().any(|key| {
        key.trim().is_empty()
            || key.len() > 128
            || key.chars().any(char::is_control)
            || key.to_lowercase() != *key
    }) {
        return Err(CognitiveContractError::Invalid(
            "semantic keys must be lowercase bounded canonical text",
        ));
    }
    Ok(())
}

fn bounded_nonempty(
    actual: usize,
    maximum: usize,
    field: &'static str,
) -> Result<(), CognitiveContractError> {
    if actual == 0 || actual > maximum {
        return Err(CognitiveContractError::LimitExceeded {
            field,
            actual,
            maximum,
        });
    }
    Ok(())
}

fn bounded_set(
    actual: usize,
    maximum: usize,
    field: &'static str,
) -> Result<(), CognitiveContractError> {
    if actual > maximum {
        return Err(CognitiveContractError::LimitExceeded {
            field,
            actual,
            maximum,
        });
    }
    Ok(())
}

fn bounded_u32(
    actual: u32,
    maximum: u32,
    field: &'static str,
) -> Result<(), CognitiveContractError> {
    if actual == 0 || actual > maximum {
        return Err(CognitiveContractError::Invalid(field));
    }
    Ok(())
}

macro_rules! canonical_contract {
    ($ty:ty, $schema:literal, $max:expr, $validate:expr) => {
        impl CanonicalContractV1 for $ty {
            const SCHEMA_ID: &'static str = $schema;
            const MAX_ENCODED_BYTES: usize = $max;

            fn validate_contract(&self) -> Result<(), CognitiveContractError> {
                $validate(self)
            }
        }
    };
}

canonical_contract!(
    ModalitySpanRefV1,
    "ModalitySpanRefV1",
    32_768,
    ModalitySpanRefV1::validate
);
canonical_contract!(
    CrossModalBindingV1,
    "CrossModalBindingV1",
    65_536,
    |value: &CrossModalBindingV1| {
        validate_ppm(value.confidence_ppm, "binding confidence")?;
        if !(2..=MAX_BINDING_SPANS).contains(&value.span_refs.len()) {
            return Err(CognitiveContractError::LimitExceeded {
                field: "binding span refs",
                actual: value.span_refs.len(),
                maximum: MAX_BINDING_SPANS,
            });
        }
        Ok(())
    }
);
canonical_contract!(
    MemoryEventV1,
    "MemoryEventV1",
    262_144,
    MemoryEventV1::validate
);
canonical_contract!(
    EngramNodeV1,
    "EngramNodeV1",
    65_536,
    EngramNodeV1::validate
);
canonical_contract!(SynapseV1, "SynapseV1", 65_536, SynapseV1::validate);
canonical_contract!(MemoryCueV1, "MemoryCueV1", 65_536, MemoryCueV1::validate);
canonical_contract!(
    RecallPacketV1,
    "RecallPacketV1",
    262_144,
    RecallPacketV1::validate
);
canonical_contract!(
    OutcomeSignalV1,
    "OutcomeSignalV1",
    32_768,
    OutcomeSignalV1::validate
);
canonical_contract!(
    ReplaySelectionReceiptV1,
    "ReplaySelectionReceiptV1",
    65_536,
    ReplaySelectionReceiptV1::validate
);
canonical_contract!(
    PlasticityBatchV1,
    "PlasticityBatchV1",
    262_144,
    PlasticityBatchV1::validate
);
canonical_contract!(
    MemoryTopologyProposalV1,
    "MemoryTopologyProposalV1",
    65_536,
    MemoryTopologyProposalV1::validate
);
canonical_contract!(
    ForgetPropagationReceiptV1,
    "ForgetPropagationReceiptV1",
    65_536,
    ForgetPropagationReceiptV1::validate
);

#[cfg(test)]
#[path = "hnmf_tests.rs"]
mod tests;
