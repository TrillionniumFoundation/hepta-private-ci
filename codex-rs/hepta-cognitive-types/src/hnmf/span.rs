use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::BindingIdV1;
use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EventIdV1;
use super::MAX_BINDING_SPANS;
use super::ModalityKindV1;
use super::PrivacyClassV1;
use super::SpanIdV1;
use super::validate_nonzero;
use super::validate_ppm;
use super::validate_text;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SpanRangeV1 {
    ByteRange { start: u64, end: u64 },
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
    AstPath { path: String },
    GuiNode { stable_node_id: String },
    EventRange { start: u64, end: u64 },
    JsonPointer { pointer: String },
    SensorRange {
        start: u64,
        end: u64,
        unit: String,
    },
}

impl SpanRangeV1 {
    pub fn validate_for(&self, modality: ModalityKindV1) -> Result<(), ContractErrorV1> {
        match (modality, self) {
            (ModalityKindV1::Text, Self::ByteRange { start, end })
            | (ModalityKindV1::ToolTrajectory, Self::EventRange { start, end })
                if end > start =>
            {
                Ok(())
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
            ) if *sample_rate_hz > 0 && end > start => Ok(()),
            (
                ModalityKindV1::Video,
                Self::FrameRange {
                    start,
                    end,
                    timebase_num,
                    timebase_den,
                },
            ) if *timebase_num > 0 && *timebase_den > 0 && end > start => Ok(()),
            (ModalityKindV1::CodeAst, Self::AstPath { path }) => {
                validate_text(path, 4096, "AST path")
            }
            (ModalityKindV1::GuiState, Self::GuiNode { stable_node_id }) => {
                validate_text(stable_node_id, 512, "GUI node id")
            }
            (ModalityKindV1::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(ContractErrorV1::Invalid(
                        "JSON pointer must be empty or begin with slash",
                    ));
                }
                if pointer.len() > 4096 || pointer.chars().any(char::is_control) {
                    return Err(ContractErrorV1::Invalid("JSON pointer"));
                }
                Ok(())
            }
            (ModalityKindV1::Sensor, Self::SensorRange { start, end, unit })
                if end > start =>
            {
                validate_text(unit, 128, "sensor unit")
            }
            _ => Err(ContractErrorV1::Invalid(
                "span range kind does not match modality",
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ModalitySpanRefV1 {
    span_id: SpanIdV1,
    modality: ModalityKindV1,
    asset_sha256: CanonicalDigestV1,
    range: SpanRangeV1,
    preprocessor_manifest_sha256: CanonicalDigestV1,
    feature_blob_sha256: Option<CanonicalDigestV1>,
    symbolic_projection_sha256: Option<CanonicalDigestV1>,
    uncertainty_ppm: u32,
    privacy_class: PrivacyClassV1,
    redaction_mask_sha256: Option<CanonicalDigestV1>,
}

impl ModalitySpanRefV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        span_id: SpanIdV1,
        modality: ModalityKindV1,
        asset_sha256: CanonicalDigestV1,
        range: SpanRangeV1,
        preprocessor_manifest_sha256: CanonicalDigestV1,
        feature_blob_sha256: Option<CanonicalDigestV1>,
        symbolic_projection_sha256: Option<CanonicalDigestV1>,
        uncertainty_ppm: u32,
        privacy_class: PrivacyClassV1,
        redaction_mask_sha256: Option<CanonicalDigestV1>,
    ) -> Result<Self, ContractErrorV1> {
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

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.span_id, "span id must be non-zero")?;
        self.range.validate_for(self.modality)?;
        validate_ppm(self.uncertainty_ppm, "span uncertainty")
    }

    #[must_use]
    pub const fn span_id(&self) -> SpanIdV1 {
        self.span_id
    }

    #[must_use]
    pub const fn modality(&self) -> ModalityKindV1 {
        self.modality
    }

    #[must_use]
    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        self.privacy_class
    }
}

impl CanonicalContractV1 for ModalitySpanRefV1 {
    const SCHEMA_ID: &'static str = "ModalitySpanRefV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AlignmentKindV1 {
    SameObservation,
    TemporalOverlap,
    EntityCoreference,
    ActionOutcome,
    DerivedSymbolic,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CrossModalBindingV1 {
    binding_id: BindingIdV1,
    event_id: EventIdV1,
    span_refs: BTreeSet<SpanIdV1>,
    alignment_kind: AlignmentKindV1,
    confidence_ppm: u32,
    producer_manifest_sha256: CanonicalDigestV1,
}

impl CrossModalBindingV1 {
    pub fn try_new(
        binding_id: BindingIdV1,
        event_id: EventIdV1,
        span_refs: BTreeSet<SpanIdV1>,
        alignment_kind: AlignmentKindV1,
        confidence_ppm: u32,
        producer_manifest_sha256: CanonicalDigestV1,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            binding_id,
            event_id,
            span_refs,
            alignment_kind,
            confidence_ppm,
            producer_manifest_sha256,
        };
        value.validate_shape()?;
        Ok(value)
    }

    pub fn validate_shape(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.binding_id, "binding id must be non-zero")?;
        validate_nonzero(self.event_id, "binding event id must be non-zero")?;
        if self.span_refs.len() < 2 || self.span_refs.len() > MAX_BINDING_SPANS {
            return Err(ContractErrorV1::BoundExceeded("binding span count"));
        }
        if self.span_refs.contains(&0) {
            return Err(ContractErrorV1::Invalid("binding span id must be non-zero"));
        }
        validate_ppm(self.confidence_ppm, "binding confidence")
    }

    #[must_use]
    pub const fn binding_id(&self) -> BindingIdV1 {
        self.binding_id
    }

    pub(crate) fn validate_against(
        &self,
        event_id: EventIdV1,
        spans: &BTreeMap<SpanIdV1, &ModalitySpanRefV1>,
    ) -> Result<(), ContractErrorV1> {
        self.validate_shape()?;
        if self.event_id != event_id {
            return Err(ContractErrorV1::Conflict("binding event id mismatches"));
        }
        let modalities = self
            .span_refs
            .iter()
            .map(|span_id| {
                spans
                    .get(span_id)
                    .map(|span| span.modality())
                    .ok_or(ContractErrorV1::Missing("binding span"))
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        if modalities.len() < 2 {
            return Err(ContractErrorV1::Invalid(
                "binding must contain at least two modalities",
            ));
        }
        Ok(())
    }
}

impl CanonicalContractV1 for CrossModalBindingV1 {
    const SCHEMA_ID: &'static str = "CrossModalBindingV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate_shape()
    }
}
