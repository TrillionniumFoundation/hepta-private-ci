use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::BindingIdV1;
use super::CanonicalJsonV1;
use super::EventIdV1;
use super::HnmfContractError;
use super::MAX_BINDING_SPANS;
use super::ModalityKindV1;
use super::PrivacyClassV1;
use super::SpanIdV1;
use super::ValidateHnmfV1;
use super::increasing;
use super::ppm;
use super::validate_bounded;
use super::validate_text;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum SpanRangeV1 {
    #[non_exhaustive]
    ByteRange { start: u64, end: u64 },
    #[non_exhaustive]
    PixelRect {
        x: u32,
        y: u32,
        width: u32,
        height: u32,
    },
    #[non_exhaustive]
    SampleRange {
        start: u64,
        end: u64,
        sample_rate_hz: u32,
    },
    #[non_exhaustive]
    FrameRange {
        start: u64,
        end: u64,
        timebase_num: u32,
        timebase_den: u32,
    },
    #[non_exhaustive]
    AstPath { path: String },
    #[non_exhaustive]
    GuiNode { stable_node_id: String },
    #[non_exhaustive]
    EventRange { start: u64, end: u64 },
    #[non_exhaustive]
    JsonPointer { pointer: String },
    #[non_exhaustive]
    SensorRange {
        start: u64,
        end: u64,
        unit: String,
    },
}

impl SpanRangeV1 {
    pub fn byte_range(start: u64, end: u64) -> Result<Self, HnmfContractError> {
        let value = Self::ByteRange { start, end };
        value.validate_for(ModalityKindV1::Text)?;
        Ok(value)
    }

    pub fn pixel_rect(
        x: u32,
        y: u32,
        width: u32,
        height: u32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::PixelRect {
            x,
            y,
            width,
            height,
        };
        value.validate_for(ModalityKindV1::Image)?;
        Ok(value)
    }

    pub fn sample_range(
        start: u64,
        end: u64,
        sample_rate_hz: u32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::SampleRange {
            start,
            end,
            sample_rate_hz,
        };
        value.validate_for(ModalityKindV1::Audio)?;
        Ok(value)
    }

    pub fn frame_range(
        start: u64,
        end: u64,
        timebase_num: u32,
        timebase_den: u32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::FrameRange {
            start,
            end,
            timebase_num,
            timebase_den,
        };
        value.validate_for(ModalityKindV1::Video)?;
        Ok(value)
    }

    pub fn ast_path(path: impl Into<String>) -> Result<Self, HnmfContractError> {
        let value = Self::AstPath { path: path.into() };
        value.validate_for(ModalityKindV1::CodeAst)?;
        Ok(value)
    }

    pub fn gui_node(stable_node_id: impl Into<String>) -> Result<Self, HnmfContractError> {
        let value = Self::GuiNode {
            stable_node_id: stable_node_id.into(),
        };
        value.validate_for(ModalityKindV1::GuiState)?;
        Ok(value)
    }

    pub fn event_range(start: u64, end: u64) -> Result<Self, HnmfContractError> {
        let value = Self::EventRange { start, end };
        value.validate_for(ModalityKindV1::ToolTrajectory)?;
        Ok(value)
    }

    pub fn json_pointer(pointer: impl Into<String>) -> Result<Self, HnmfContractError> {
        let value = Self::JsonPointer {
            pointer: pointer.into(),
        };
        value.validate_for(ModalityKindV1::StructuredData)?;
        Ok(value)
    }

    pub fn sensor_range(
        start: u64,
        end: u64,
        unit: impl Into<String>,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::SensorRange {
            start,
            end,
            unit: unit.into(),
        };
        value.validate_for(ModalityKindV1::Sensor)?;
        Ok(value)
    }

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
                validate_text(path, 4096, "AST path")
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
    span_id: SpanIdV1,
    modality: ModalityKindV1,
    #[serde(with = "super::wire::digest")]
    asset_sha256: Digest32,
    range: SpanRangeV1,
    #[serde(with = "super::wire::digest")]
    preprocessor_manifest_sha256: Digest32,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "super::wire::option_digest"
    )]
    feature_blob_sha256: Option<Digest32>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "super::wire::option_digest"
    )]
    symbolic_projection_sha256: Option<Digest32>,
    uncertainty_ppm: u32,
    privacy_class: PrivacyClassV1,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "super::wire::option_digest"
    )]
    redaction_mask_sha256: Option<Digest32>,
}

impl ModalitySpanRefV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        span_id: SpanIdV1,
        modality: ModalityKindV1,
        asset_sha256: Digest32,
        range: SpanRangeV1,
        preprocessor_manifest_sha256: Digest32,
        feature_blob_sha256: Option<Digest32>,
        symbolic_projection_sha256: Option<Digest32>,
        uncertainty_ppm: u32,
        privacy_class: PrivacyClassV1,
        redaction_mask_sha256: Option<Digest32>,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            span_id,
            modality,
            asset_sha256,
            range,
            preprocessor_manifest_sha256,
            feature_blob_sha256,
            symbolic_projection_sha256,
            uncertainty_ppm,
            privacy_class,
            redaction_mask_sha256,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn span_id(&self) -> SpanIdV1 {
        self.span_id
    }

    pub const fn modality(&self) -> ModalityKindV1 {
        self.modality
    }

    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        self.privacy_class
    }
}

impl ValidateHnmfV1 for ModalitySpanRefV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.span_id == 0 {
            return Err(HnmfContractError::Invalid("span id must be non-zero"));
        }
        if self.asset_sha256.is_zero() || self.preprocessor_manifest_sha256.is_zero() {
            return Err(HnmfContractError::Invalid(
                "span asset and preprocessor digests must be non-zero",
            ));
        }
        for optional in [
            self.feature_blob_sha256,
            self.symbolic_projection_sha256,
            self.redaction_mask_sha256,
        ] {
            if optional.is_some_and(Digest32::is_zero) {
                return Err(HnmfContractError::Invalid(
                    "optional span digest must be non-zero when present",
                ));
            }
        }
        self.range.validate_for(self.modality)?;
        ppm(self.uncertainty_ppm, "span uncertainty")
    }
}

impl CanonicalJsonV1 for ModalitySpanRefV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.modality-span-ref.v1";
    const MAX_ENCODED_BYTES: usize = 32_768;
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
    binding_id: BindingIdV1,
    event_id: EventIdV1,
    span_ids: BTreeSet<SpanIdV1>,
    alignment_kind: AlignmentKindV1,
    confidence_ppm: u32,
    #[serde(with = "super::wire::digest")]
    producer_manifest_sha256: Digest32,
}

impl CrossModalBindingV1 {
    pub fn try_new(
        binding_id: BindingIdV1,
        event_id: EventIdV1,
        span_ids: BTreeSet<SpanIdV1>,
        alignment_kind: AlignmentKindV1,
        confidence_ppm: u32,
        producer_manifest_sha256: Digest32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            binding_id,
            event_id,
            span_ids,
            alignment_kind,
            confidence_ppm,
            producer_manifest_sha256,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn binding_id(&self) -> BindingIdV1 {
        self.binding_id
    }

    pub const fn event_id(&self) -> EventIdV1 {
        self.event_id
    }

    pub(crate) fn validate_against(
        &self,
        event_id: EventIdV1,
        spans: &BTreeMap<SpanIdV1, &ModalitySpanRefV1>,
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        if self.event_id != event_id {
            return Err(HnmfContractError::Invalid("binding event id mismatch"));
        }
        let modalities = self
            .span_ids
            .iter()
            .map(|span_id| {
                spans
                    .get(span_id)
                    .map(|span| span.modality())
                    .ok_or(HnmfContractError::Missing("binding span"))
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        if modalities.len() < 2 {
            return Err(HnmfContractError::Invalid(
                "binding must contain at least two modalities",
            ));
        }
        Ok(())
    }
}

impl ValidateHnmfV1 for CrossModalBindingV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.binding_id == 0 || self.event_id == 0 {
            return Err(HnmfContractError::Invalid(
                "binding and event ids must be non-zero",
            ));
        }
        if self.span_ids.len() < 2 || self.span_ids.len() > MAX_BINDING_SPANS {
            return Err(HnmfContractError::BoundExceeded("binding span count"));
        }
        if self.span_ids.contains(&0) {
            return Err(HnmfContractError::Invalid("binding span id must be non-zero"));
        }
        if self.producer_manifest_sha256.is_zero() {
            return Err(HnmfContractError::Invalid(
                "binding producer manifest digest must be non-zero",
            ));
        }
        ppm(self.confidence_ppm, "binding confidence")
    }
}

impl CanonicalJsonV1 for CrossModalBindingV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.cross-modal-binding.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}
