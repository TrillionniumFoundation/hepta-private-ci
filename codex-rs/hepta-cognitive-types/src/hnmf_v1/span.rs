use super::*;
use std::collections::{BTreeMap, BTreeSet};

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
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyClassV1 {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
pub enum MemoryScopeV1 {
    AgentPrivate { agent_id: String },
    WorkspacePrivate {
        agent_id: String,
        workspace_sha256: Sha256DigestV1,
    },
}

impl MemoryScopeV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        match self {
            Self::AgentPrivate { agent_id } | Self::WorkspacePrivate { agent_id, .. } => {
                validate_text(agent_id, 128, "scope agent id")
            }
        }
    }

    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        match self {
            Self::AgentPrivate { .. } => PrivacyClassV1::AgentPrivate,
            Self::WorkspacePrivate { .. } => PrivacyClassV1::WorkspacePrivate,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TimeIntervalV1 {
    #[serde(with = "super::exact_i64")]
    pub start_unix_ms: i64,
    #[serde(with = "super::exact_i64_option")]
    pub end_unix_ms: Option<i64>,
}

impl TimeIntervalV1 {
    fn validate(self) -> Result<(), HnmfContractError> {
        if self.end_unix_ms.is_some_and(|end| end <= self.start_unix_ms) {
            return Err(HnmfContractError::Invalid(
                "time interval end must be greater than start",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
pub enum SpanRangeV1 {
    ByteRange {
        #[serde(with = "super::exact_u64")]
        start: u64,
        #[serde(with = "super::exact_u64")]
        end: u64,
    },
    PixelRect {
        x: u32,
        y: u32,
        width: u32,
        height: u32,
        image_width: u32,
        image_height: u32,
    },
    SampleRange {
        #[serde(with = "super::exact_u64")]
        start: u64,
        #[serde(with = "super::exact_u64")]
        end: u64,
        sample_rate_hz: u32,
    },
    FrameRange {
        #[serde(with = "super::exact_u64")]
        start: u64,
        #[serde(with = "super::exact_u64")]
        end: u64,
        #[serde(with = "super::exact_u64")]
        frame_count: u64,
        timebase_num: u32,
        timebase_den: u32,
    },
    AstPath { path: Vec<u32>, node_count: u32 },
    GuiNode { stable_node_id: String },
    EventRange {
        #[serde(with = "super::exact_u64")]
        start: u64,
        #[serde(with = "super::exact_u64")]
        end: u64,
    },
    JsonPointer { pointer: String },
    SensorRange {
        #[serde(with = "super::exact_u64")]
        start: u64,
        #[serde(with = "super::exact_u64")]
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
            (
                ModalityKindV1::Image,
                Self::PixelRect {
                    x,
                    y,
                    width,
                    height,
                    image_width,
                    image_height,
                },
            ) => {
                if *width == 0 || *height == 0 || *image_width == 0 || *image_height == 0 {
                    return Err(HnmfContractError::Invalid("image region has zero extent"));
                }
                let right = x.checked_add(*width).ok_or(HnmfContractError::Invalid("image x overflow"))?;
                let bottom = y.checked_add(*height).ok_or(HnmfContractError::Invalid("image y overflow"))?;
                if right > *image_width || bottom > *image_height {
                    return Err(HnmfContractError::Invalid("image region exceeds asset bounds"));
                }
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
                    frame_count,
                    timebase_num,
                    timebase_den,
                },
            ) if *timebase_num > 0 && *timebase_den > 0 && *frame_count > 0 => {
                increasing(*start, *end, "video frame range")?;
                if *end > *frame_count {
                    return Err(HnmfContractError::Invalid("video frame range exceeds asset bounds"));
                }
                Ok(())
            }
            (ModalityKindV1::CodeAst, Self::AstPath { path, node_count }) => {
                if path.is_empty() || path.len() > 64 || *node_count == 0 {
                    return Err(HnmfContractError::BoundExceeded("AST path"));
                }
                if path.iter().any(|index| *index >= *node_count) {
                    return Err(HnmfContractError::Invalid("AST selector exceeds asset bounds"));
                }
                Ok(())
            }
            (ModalityKindV1::GuiState, Self::GuiNode { stable_node_id }) => {
                validate_text(stable_node_id, 512, "GUI node id")
            }
            (ModalityKindV1::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(HnmfContractError::Invalid(
                        "JSON pointer must be empty or begin with slash",
                    ));
                }
                validate_bounded(pointer, 4096, "JSON pointer")
            }
            (ModalityKindV1::Sensor, Self::SensorRange { start, end, unit }) => {
                increasing(*start, *end, "sensor range")?;
                validate_text(unit, 128, "sensor unit")
            }
            _ => Err(HnmfContractError::Invalid(
                "span range kind does not match modality",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModalitySpanRefV1 {
    #[serde(with = "super::exact_u64")]
    pub span_id: SpanIdV1,
    pub modality: ModalityKindV1,
    pub asset_sha256: Sha256DigestV1,
    pub range: SpanRangeV1,
    pub preprocessor_manifest_sha256: Sha256DigestV1,
    pub feature_blob_sha256: Option<Sha256DigestV1>,
    pub symbolic_projection_sha256: Option<Sha256DigestV1>,
    pub uncertainty_ppm: u32,
    pub privacy_class: PrivacyClassV1,
    pub redaction_mask_sha256: Option<Sha256DigestV1>,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for ModalitySpanRefV1 {
    const SCHEMA_ID: &'static str = "ModalitySpanRefV1";
    const MAX_ENCODED_BYTES: usize = 32_768;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.span_id == 0 {
            return Err(HnmfContractError::Invalid("span id must be non-zero"));
        }
        self.range.validate_for(self.modality)?;
        ppm(self.uncertainty_ppm, "span uncertainty")?;
        self.authority.validate()
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
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CrossModalBindingV1 {
    #[serde(with = "super::exact_u64")]
    pub binding_id: BindingIdV1,
    #[serde(with = "super::exact_u64")]
    pub event_id: EventIdV1,
    #[serde(with = "super::exact_u64_vec")]
    pub span_refs: Vec<SpanIdV1>,
    pub alignment_kind: AlignmentKindV1,
    pub confidence_ppm: u32,
    pub producer_manifest_sha256: Sha256DigestV1,
    pub authority: AuthorityPostureV1,
}

impl CrossModalBindingV1 {
    fn validate_against(
        &self,
        event_id: EventIdV1,
        spans: &BTreeMap<SpanIdV1, &ModalitySpanRefV1>,
    ) -> Result<(), HnmfContractError> {
        if self.binding_id == 0 || self.event_id != event_id {
            return Err(HnmfContractError::Invalid(
                "binding id is zero or event id mismatches",
            ));
        }
        if self.span_refs.len() < 2 || self.span_refs.len() > MAX_BINDING_SPANS {
            return Err(HnmfContractError::BoundExceeded("binding span count"));
        }
        validate_sorted_unique_u64(&self.span_refs, "binding span refs")?;
        ppm(self.confidence_ppm, "binding confidence")?;
        let modalities = self
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
                "binding must contain at least two modalities",
            ));
        }
        self.authority.validate()
    }
}

impl CanonicalJsonV1 for CrossModalBindingV1 {
    const SCHEMA_ID: &'static str = "CrossModalBindingV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.binding_id == 0 || self.event_id == 0 {
            return Err(HnmfContractError::Invalid("binding/event id must be non-zero"));
        }
        if self.span_refs.len() < 2 || self.span_refs.len() > MAX_BINDING_SPANS {
            return Err(HnmfContractError::BoundExceeded("binding span count"));
        }
        validate_sorted_unique_u64(&self.span_refs, "binding span refs")?;
        ppm(self.confidence_ppm, "binding confidence")?;
        self.authority.validate()
    }
}
