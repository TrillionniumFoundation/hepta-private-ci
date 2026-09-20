use crate::{
    BindingId, ContractError, Digest32, EventId, MAX_BINDING_SPANS, ModalityKind, PrivacyClass,
    SpanId, increasing, ppm, validate_bounded, validate_text,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SpanRange {
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

impl SpanRange {
    pub fn validate_for(&self, modality: ModalityKind) -> Result<(), ContractError> {
        match (modality, self) {
            (ModalityKind::Text, Self::ByteRange { start, end })
            | (ModalityKind::ToolTrajectory, Self::EventRange { start, end }) => {
                increasing(*start, *end, "ordered span range")
            }
            (ModalityKind::Image, Self::PixelRect { width, height, .. })
                if *width > 0 && *height > 0 =>
            {
                Ok(())
            }
            (
                ModalityKind::Audio,
                Self::SampleRange {
                    start,
                    end,
                    sample_rate_hz,
                },
            ) if *sample_rate_hz > 0 => increasing(*start, *end, "audio sample range"),
            (
                ModalityKind::Video,
                Self::FrameRange {
                    start,
                    end,
                    timebase_num,
                    timebase_den,
                },
            ) if *timebase_num > 0 && *timebase_den > 0 => {
                increasing(*start, *end, "video frame range")
            }
            (ModalityKind::CodeAst, Self::AstPath { path }) => {
                validate_text(path, 4096, "AST path")
            }
            (ModalityKind::GuiState, Self::GuiNode { stable_node_id }) => {
                validate_text(stable_node_id, 512, "GUI node id")
            }
            (ModalityKind::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(ContractError::Invalid(
                        "JSON pointer must be empty or begin with slash",
                    ));
                }
                validate_bounded(pointer, 4096, "JSON pointer")
            }
            (ModalityKind::Sensor, Self::SensorRange { start, end, unit }) => {
                increasing(*start, *end, "sensor range")?;
                validate_text(unit, 128, "sensor unit")
            }
            _ => Err(ContractError::Invalid(
                "span range kind does not match modality",
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModalitySpanRef {
    pub span_id: SpanId,
    pub modality: ModalityKind,
    pub asset_sha256: Digest32,
    pub range: SpanRange,
    pub preprocessor_manifest_sha256: Digest32,
    pub feature_blob_sha256: Option<Digest32>,
    pub symbolic_projection_sha256: Option<Digest32>,
    pub uncertainty_ppm: u32,
    pub privacy_class: PrivacyClass,
    pub redaction_mask_sha256: Option<Digest32>,
}

impl ModalitySpanRef {
    pub fn validate(&self) -> Result<(), ContractError> {
        if self.span_id == 0 {
            return Err(ContractError::Invalid("span id must be non-zero"));
        }
        self.range.validate_for(self.modality)?;
        ppm(self.uncertainty_ppm, "span uncertainty")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AlignmentKind {
    SameObservation,
    TemporalOverlap,
    EntityCoreference,
    ActionOutcome,
    DerivedSymbolic,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossModalBinding {
    pub binding_id: BindingId,
    pub event_id: EventId,
    pub span_ids: BTreeSet<SpanId>,
    pub alignment_kind: AlignmentKind,
    pub confidence_ppm: u32,
    pub producer_manifest_sha256: Digest32,
}

impl CrossModalBinding {
    pub(crate) fn validate_against(
        &self,
        event_id: EventId,
        spans: &BTreeMap<SpanId, &ModalitySpanRef>,
    ) -> Result<(), ContractError> {
        if self.binding_id == 0 || self.event_id != event_id {
            return Err(ContractError::Invalid(
                "binding id is zero or event id mismatches",
            ));
        }
        if self.span_ids.len() < 2 || self.span_ids.len() > MAX_BINDING_SPANS {
            return Err(ContractError::BoundExceeded("binding span count"));
        }
        ppm(self.confidence_ppm, "binding confidence")?;
        let modalities = self
            .span_ids
            .iter()
            .map(|span_id| {
                spans
                    .get(span_id)
                    .map(|span| span.modality)
                    .ok_or(ContractError::Missing("binding span"))
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        if modalities.len() < 2 {
            return Err(ContractError::Invalid(
                "binding must contain at least two modalities",
            ));
        }
        Ok(())
    }
}
