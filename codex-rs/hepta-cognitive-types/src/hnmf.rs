//! Canonical HNMF V1 cognitive and multimodal memory contracts.
//!
//! These values are authority-free domain contracts. They carry bounded,
//! versioned semantics only; constructing or validating one never grants a
//! writer, model, provider, external-effect, selection, promotion or release
//! capability.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::{Digest32, Generation, StableId};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

pub const PPM: u32 = 1_000_000;
pub const MAX_MODALITY_SPANS: usize = 32;
pub const MAX_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 64;
pub const MAX_CAUSAL_REFERENCES: usize = 64;
pub const MAX_PATH_BYTES: usize = 4_096;
pub const MAX_LABEL_BYTES: usize = 128;

/// Stable identifier with the repository's canonical \`StableId\` grammar and a
/// JSON string representation.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ContractIdV1(StableId);

impl ContractIdV1 {
    pub fn new(value: impl Into<String>) -> Result<Self, HnmfContractError> {
        StableId::new(value)
            .map(Self)
            .map_err(|_| HnmfContractError::Invalid("stable identifier"))
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    pub fn as_stable_id(&self) -> &StableId {
        &self.0
    }
}

impl fmt::Display for ContractIdV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Serialize for ContractIdV1 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for ContractIdV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

/// Exact lowercase SHA-256 digest with a JSON string representation.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ContractDigestV1(Digest32);

impl ContractDigestV1 {
    pub fn parse(value: &str) -> Result<Self, HnmfContractError> {
        let digest = Digest32::from_str(value)
            .map_err(|_| HnmfContractError::Invalid("lowercase sha256 digest"))?;
        if digest.is_zero() {
            return Err(HnmfContractError::Invalid("zero digest"));
        }
        Ok(Self(digest))
    }

    pub fn from_digest(value: Digest32) -> Result<Self, HnmfContractError> {
        if value.is_zero() {
            return Err(HnmfContractError::Invalid("zero digest"));
        }
        Ok(Self(value))
    }

    pub const fn digest(self) -> Digest32 {
        self.0
    }
}

impl fmt::Display for ContractDigestV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Serialize for ContractDigestV1 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

impl<'de> Deserialize<'de> for ContractDigestV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(&value).map_err(serde::de::Error::custom)
    }
}

/// Non-zero generation with an exact JSON unsigned-integer representation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContractGenerationV1(Generation);

impl ContractGenerationV1 {
    pub fn new(value: u64) -> Result<Self, HnmfContractError> {
        Generation::new(value)
            .map(Self)
            .map_err(|_| HnmfContractError::Invalid("generation"))
    }

    pub const fn get(self) -> u64 {
        self.0.get()
    }

    pub fn next(self) -> Result<Self, HnmfContractError> {
        self.0
            .next()
            .map(Self)
            .map_err(|_| HnmfContractError::Invalid("generation overflow"))
    }
}

impl Serialize for ContractGenerationV1 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(self.get())
    }
}

impl<'de> Deserialize<'de> for ContractGenerationV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(u64::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ModalityKindV1 {
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

impl ModalityKindV1 {
    pub const ALL: [Self; 9] = [
        Self::Text,
        Self::Image,
        Self::Audio,
        Self::Video,
        Self::CodeAst,
        Self::GuiState,
        Self::ToolTrajectory,
        Self::StructuredData,
        Self::Sensor,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Text => "text",
            Self::Image => "image",
            Self::Audio => "audio",
            Self::Video => "video",
            Self::CodeAst => "code_ast",
            Self::GuiState => "gui_state",
            Self::ToolTrajectory => "tool_trajectory",
            Self::StructuredData => "structured_data",
            Self::Sensor => "sensor",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyClassV1 {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MemoryScopeV1 {
    AgentPrivate {
        agent_id: ContractIdV1,
    },
    WorkspacePrivate {
        agent_id: ContractIdV1,
        workspace_sha256: ContractDigestV1,
    },
}

impl MemoryScopeV1 {
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
    pub fn validate(self) -> Result<(), HnmfContractError> {
        if self.start_unix_ms == 0 {
            return Err(HnmfContractError::ZeroValue("observedInterval.startUnixMs"));
        }
        if self
            .end_unix_ms
            .is_some_and(|end| end <= self.start_unix_ms)
        {
            return Err(HnmfContractError::Invalid("observed interval"));
        }
        Ok(())
    }
}

/// Modality-specific span coordinates. A coordinate representation is valid
/// only for its matching modality; validation never coerces one unit into
/// another.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
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
        stable_node_id: ContractIdV1,
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
    pub fn validate_for(&self, modality: ModalityKindV1) -> Result<(), HnmfContractError> {
        match (modality, self) {
            (ModalityKindV1::Text, Self::ByteRange { start, end })
            | (ModalityKindV1::ToolTrajectory, Self::EventRange { start, end }) => {
                increasing(*start, *end, "ordered span range")
            }
            (ModalityKindV1::Image, Self::PixelRect { width, height, .. })
                if *width > 0 && *height > 0 =>
            {
                Ok(())
            }
            (
                ModalityKindV1::Audio,
                Self::SampleRange {
                    start,
                    end,
                    sample_rate_hz,
                },
            ) if *sample_rate_hz > 0 => increasing(*start, *end, "audio sample range"),
            (
                ModalityKindV1::Video,
                Self::FrameRange {
                    start,
                    end,
                    timebase_num,
                    timebase_den,
                },
            ) if *timebase_num > 0 && *timebase_den > 0 => {
                increasing(*start, *end, "video frame range")
            }
            (ModalityKindV1::CodeAst, Self::AstPath { path }) => {
                validate_text(path, MAX_PATH_BYTES, "AST path")
            }
            (ModalityKindV1::GuiState, Self::GuiNode { .. }) => Ok(()),
            (ModalityKindV1::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(HnmfContractError::Invalid("JSON pointer"));
                }
                validate_bounded(pointer, MAX_PATH_BYTES, "JSON pointer")
            }
            (ModalityKindV1::Sensor, Self::SensorRange { start, end, unit }) => {
                increasing(*start, *end, "sensor range")?;
                validate_text(unit, MAX_LABEL_BYTES, "sensor unit")
            }
            _ => Err(HnmfContractError::Invalid(
                "span range kind does not match modality",
            )),
        }
    }
}

/// Exact asset extent supplied by the authoritative asset owner when a span is
/// admitted. It is not serialized inside the span itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AssetExtentV1 {
    Bytes {
        byte_len: u64,
    },
    Image {
        width: u32,
        height: u32,
    },
    Audio {
        sample_count: u64,
        sample_rate_hz: u32,
    },
    Video {
        frame_count: u64,
        timebase_num: u32,
        timebase_den: u32,
    },
    CodeAst,
    GuiState,
    ToolTrajectory {
        event_count: u64,
    },
    StructuredData,
    Sensor {
        sample_count: u64,
        unit: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetManifestV1 {
    pub asset_sha256: ContractDigestV1,
    pub modality: ModalityKindV1,
    pub extent: AssetExtentV1,
    pub preprocessor_manifest_sha256: ContractDigestV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModalitySpanRefV1 {
    pub span_id: ContractIdV1,
    pub modality: ModalityKindV1,
    pub asset_sha256: ContractDigestV1,
    pub range: SpanRangeV1,
    pub preprocessor_manifest_sha256: ContractDigestV1,
    pub feature_blob_sha256: Option<ContractDigestV1>,
    pub symbolic_projection_sha256: Option<ContractDigestV1>,
    pub uncertainty_ppm: u32,
    pub privacy_class: PrivacyClassV1,
    pub redaction_mask_sha256: Option<ContractDigestV1>,
}

impl ModalitySpanRefV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.range.validate_for(self.modality)?;
        ppm(self.uncertainty_ppm, "span uncertainty")
    }
}

/// Validate a modality span against the exact current asset manifest before
/// any asset bytes are read. This closes unit-confusion and out-of-bounds
/// selectors without making \`cognitive.types\` an asset authority.
pub fn validate_span_against_manifest_v1(
    manifest: &AssetManifestV1,
    span: &ModalitySpanRefV1,
) -> Result<(), HnmfContractError> {
    span.validate()?;
    if span.asset_sha256 != manifest.asset_sha256
        || span.preprocessor_manifest_sha256 != manifest.preprocessor_manifest_sha256
        || span.modality != manifest.modality
    {
        return Err(HnmfContractError::Conflict("asset/span binding"));
    }
    match (&manifest.extent, &span.range, span.modality) {
        (
            AssetExtentV1::Bytes { byte_len },
            SpanRangeV1::ByteRange { end, .. },
            ModalityKindV1::Text,
        ) if *end <= *byte_len => Ok(()),
        (
            AssetExtentV1::Image { width, height },
            SpanRangeV1::PixelRect {
                x,
                y,
                width: w,
                height: h,
            },
            ModalityKindV1::Image,
        ) if x.checked_add(*w).is_some_and(|end| end <= *width)
            && y.checked_add(*h).is_some_and(|end| end <= *height) =>
        {
            Ok(())
        }
        (
            AssetExtentV1::Audio {
                sample_count,
                sample_rate_hz,
            },
            SpanRangeV1::SampleRange {
                end,
                sample_rate_hz: span_rate,
                ..
            },
            ModalityKindV1::Audio,
        ) if end <= sample_count && span_rate == sample_rate_hz => Ok(()),
        (
            AssetExtentV1::Video {
                frame_count,
                timebase_num,
                timebase_den,
            },
            SpanRangeV1::FrameRange {
                end,
                timebase_num: span_num,
                timebase_den: span_den,
                ..
            },
            ModalityKindV1::Video,
        ) if end <= frame_count && span_num == timebase_num && span_den == timebase_den => Ok(()),
        (AssetExtentV1::CodeAst, SpanRangeV1::AstPath { .. }, ModalityKindV1::CodeAst)
        | (AssetExtentV1::GuiState, SpanRangeV1::GuiNode { .. }, ModalityKindV1::GuiState)
        | (
            AssetExtentV1::StructuredData,
            SpanRangeV1::JsonPointer { .. },
            ModalityKindV1::StructuredData,
        ) => Ok(()),
        (
            AssetExtentV1::ToolTrajectory { event_count },
            SpanRangeV1::EventRange { end, .. },
            ModalityKindV1::ToolTrajectory,
        ) if end <= event_count => Ok(()),
        (
            AssetExtentV1::Sensor { sample_count, unit },
            SpanRangeV1::SensorRange {
                end,
                unit: span_unit,
                ..
            },
            ModalityKindV1::Sensor,
        ) if end <= sample_count && span_unit == unit => Ok(()),
        _ => Err(HnmfContractError::Invalid("span exceeds asset extent")),
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
    pub binding_id: ContractIdV1,
    pub event_id: ContractIdV1,
    pub span_refs: BTreeSet<ContractIdV1>,
    pub alignment_kind: AlignmentKindV1,
    pub confidence_ppm: u32,
    pub producer_manifest_sha256: ContractDigestV1,
}

impl CrossModalBindingV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.span_refs.len() < 2 || self.span_refs.len() > MAX_BINDING_SPANS {
            return Err(HnmfContractError::LimitExceeded {
                field: "spanRefs",
                actual: self.span_refs.len(),
                maximum: MAX_BINDING_SPANS,
            });
        }
        ppm(self.confidence_ppm, "binding confidence")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProvenanceRefV1 {
    pub source_id: ContractIdV1,
    pub source_revision: u64,
    pub source_sha256: ContractDigestV1,
    pub observed_at_unix_ms: u64,
}

impl ProvenanceRefV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_revision == 0 || self.observed_at_unix_ms == 0 {
            return Err(HnmfContractError::ZeroValue("provenance revision/time"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryVerificationStateV1 {
    Unverified,
    Verified,
    Contradicted,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum RetentionPolicyV1 {
    Session,
    Persistent { retain_until_unix_ms: Option<u64> },
    LegalHold { policy_digest: ContractDigestV1 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "state",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MemoryLifecycleV1 {
    Active,
    Superseded { by_event_id: ContractIdV1 },
    Tombstoned { reason_sha256: ContractDigestV1 },
}

impl MemoryLifecycleV1 {
    fn validate_for(&self, event_id: &ContractIdV1) -> Result<(), HnmfContractError> {
        match self {
            Self::Active | Self::Tombstoned { .. } => Ok(()),
            Self::Superseded { by_event_id } if by_event_id != event_id => Ok(()),
            Self::Superseded { .. } => Err(HnmfContractError::Invalid(
                "superseding event must be distinct",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryEventV1 {
    pub event_id: ContractIdV1,
    pub episode_id: ContractIdV1,
    pub scope: MemoryScopeV1,
    pub observed_interval: ObservedIntervalV1,
    pub modality_spans: Vec<ModalitySpanRefV1>,
    pub cross_modal_bindings: Vec<CrossModalBindingV1>,
    pub semantic_keys: BTreeSet<String>,
    pub provenance: Vec<ProvenanceRefV1>,
    pub verification: MemoryVerificationStateV1,
    pub retention_policy: RetentionPolicyV1,
    pub objective_digest: ContractDigestV1,
    pub ndu_state_digest: ContractDigestV1,
    pub causal_parents: BTreeSet<ContractIdV1>,
    pub temporal_neighbors: BTreeSet<ContractIdV1>,
    pub behavior_propensity_ppm: Option<u32>,
    pub lifecycle: MemoryLifecycleV1,
}

impl MemoryEventV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.observed_interval.validate()?;
        self.lifecycle.validate_for(&self.event_id)?;
        if self.modality_spans.is_empty() || self.modality_spans.len() > MAX_MODALITY_SPANS {
            return Err(HnmfContractError::LimitExceeded {
                field: "modalitySpans",
                actual: self.modality_spans.len(),
                maximum: MAX_MODALITY_SPANS,
            });
        }
        if self.cross_modal_bindings.len() > MAX_BINDINGS {
            return Err(HnmfContractError::LimitExceeded {
                field: "crossModalBindings",
                actual: self.cross_modal_bindings.len(),
                maximum: MAX_BINDINGS,
            });
        }
        validate_keys(&self.semantic_keys)?;
        if self.provenance.is_empty() || self.provenance.len() > MAX_PROVENANCE {
            return Err(HnmfContractError::LimitExceeded {
                field: "provenance",
                actual: self.provenance.len(),
                maximum: MAX_PROVENANCE,
            });
        }
        if self.causal_parents.len() > MAX_CAUSAL_REFERENCES
            || self.temporal_neighbors.len() > MAX_CAUSAL_REFERENCES
        {
            return Err(HnmfContractError::LimitExceeded {
                field: "causalOrTemporalReferences",
                actual: self.causal_parents.len().max(self.temporal_neighbors.len()),
                maximum: MAX_CAUSAL_REFERENCES,
            });
        }
        if let Some(value) = self.behavior_propensity_ppm {
            if value == 0 {
                return Err(HnmfContractError::ZeroValue("behaviorPropensityPpm"));
            }
            ppm(value, "behavior propensity")?;
        }

        let mut spans = BTreeMap::new();
        let mut previous_span: Option<&ContractIdV1> = None;
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class != self.scope.privacy_class() {
                return Err(HnmfContractError::Conflict("span/event privacy"));
            }
            if previous_span.is_some_and(|previous| previous >= &span.span_id) {
                return Err(HnmfContractError::Invalid("span order"));
            }
            previous_span = Some(&span.span_id);
            if spans.insert(span.span_id.clone(), span).is_some() {
                return Err(HnmfContractError::DuplicateIdentity("spanId"));
            }
        }

        let mut binding_ids = BTreeSet::new();
        let mut previous_binding: Option<&ContractIdV1> = None;
        for binding in &self.cross_modal_bindings {
            binding.validate()?;
            if binding.event_id != self.event_id {
                return Err(HnmfContractError::Conflict("binding event"));
            }
            if previous_binding.is_some_and(|previous| previous >= &binding.binding_id) {
                return Err(HnmfContractError::Invalid("binding order"));
            }
            previous_binding = Some(&binding.binding_id);
            if !binding_ids.insert(binding.binding_id.clone()) {
                return Err(HnmfContractError::DuplicateIdentity("bindingId"));
            }
            let modalities = binding
                .span_refs
                .iter()
                .map(|span_id| {
                    spans
                        .get(span_id)
                        .map(|span| span.modality)
                        .ok_or(HnmfContractError::Missing("binding span"))
                })
                .collect::<Result<BTreeSet<_>, _>>()?;
            if modalities.len() < 2 {
                return Err(HnmfContractError::Invalid(
                    "cross-modal binding needs distinct modalities",
                ));
            }
        }

        let mut previous_provenance: Option<&ProvenanceRefV1> = None;
        for provenance in &self.provenance {
            provenance.validate()?;
            if previous_provenance.is_some_and(|previous| previous >= provenance) {
                return Err(HnmfContractError::Invalid("provenance order"));
            }
            previous_provenance = Some(provenance);
        }
        Ok(())
    }
}

pub fn validate_memory_event_v1(event: &MemoryEventV1) -> Result<(), HnmfContractError> {
    event.validate()
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HnmfContractError {
    ZeroValue(&'static str),
    Invalid(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    DuplicateIdentity(&'static str),
    LimitExceeded {
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
}

impl fmt::Display for HnmfContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for HnmfContractError {}

pub(crate) fn ppm(value: u32, name: &'static str) -> Result<(), HnmfContractError> {
    if value > PPM {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_keys(keys: &BTreeSet<String>) -> Result<(), HnmfContractError> {
    if keys.is_empty() || keys.len() > MAX_SEMANTIC_KEYS {
        return Err(HnmfContractError::LimitExceeded {
            field: "semanticKeys",
            actual: keys.len(),
            maximum: MAX_SEMANTIC_KEYS,
        });
    }
    if keys.iter().any(|key| {
        key.trim().is_empty()
            || key.len() > MAX_LABEL_BYTES
            || key.chars().any(char::is_control)
            || key.to_lowercase() != *key
    }) {
        return Err(HnmfContractError::Invalid("semantic key"));
    }
    Ok(())
}

pub(crate) fn validate_text(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control)
    {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_bounded(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn increasing(
    start: u64,
    end: u64,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if end <= start {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}
