//! Coordinates refer to the original source, while the host supplies only an
//! already admitted actor view. No constructor opens a file or acquires data.

use std::error::Error;
use std::fmt;
use std::ops::Range;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub(crate) const MAX_PERCEPTION_RAW_BYTES: usize = 8_192;
const MAX_SOURCE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PerceptionSourceLayoutV1 {
    Bytes { origin_offset: u64, origin_length: u64 },
    /// Tightly packed, interleaved pixels; encoded image files use Bytes.
    Raster { width: u32, height: u32, channels: u8 },
    /// Tightly packed frames with a fixed, declared presentation period.
    Frames {
        width: u32,
        height: u32,
        channels: u8,
        frame_count: u32,
        frame_period_micros: u64,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionSourcePinV1 {
    pub source_id: String,
    pub origin_digest: [u8; 32],
    pub content_digest: [u8; 32],
    pub byte_length: u64,
    pub observed_at_micros: u64,
    pub layout: PerceptionSourceLayoutV1,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PerceptionCoordinatesV1 {
    /// Half-open offsets in the original source, not in its captured window.
    Bytes { start: u64, end: u64 },
    ImageRegion { x: u32, y: u32, width: u32, height: u32 },
    VideoRegion {
        frame_index: u32,
        timestamp_micros: u64,
        x: u32,
        y: u32,
        width: u32,
        height: u32,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionEvidenceV1 {
    pub evidence_id: String,
    pub source: PerceptionSourcePinV1,
    pub coordinates: PerceptionCoordinatesV1,
    pub raw_bytes: Vec<u8>,
}

impl PerceptionEvidenceV1 {
    /// Frozen field-order JSON with a domain prefix; includes exact bytes,
    /// source pins and original coordinates. IDs alone never bind a latent.
    pub fn digest(&self) -> Result<Digest32, PerceptionErrorV1> {
        if StableId::new(self.evidence_id.as_str()).is_err()
            || self.raw_bytes.is_empty() || self.raw_bytes.len() > MAX_PERCEPTION_RAW_BYTES
        {
            return Err(PerceptionErrorV1::InvalidEvidence);
        }
        let length: usize = self.source.raw_ranges(&self.coordinates)?.iter().map(|range| range.end - range.start).sum();
        if length != self.raw_bytes.len() {
            return Err(PerceptionErrorV1::InvalidEvidence);
        }
        let bytes = serde_json::to_vec(self).map_err(|_| PerceptionErrorV1::InvalidWire)?;
        let mut domain = b"hepta.perception.evidence.v1\0".to_vec();
        domain.extend_from_slice(&bytes);
        Ok(Digest32::of_bytes(&domain))
    }
}

/// A borrowed actor-visible capture supplied by the host's admission boundary.
/// The host must exclude teacher/evaluator data. Digest checks establish byte
/// integrity against that capture; they do not authenticate origin or permission.
/// The host also checks capture time against its admission clock; the Cell
/// encoder request does not carry a clock with which to prove availability.
#[derive(Clone, Debug)]
pub struct PerceptionActorSourceV1<'a> {
    pin: PerceptionSourcePinV1,
    bytes: &'a [u8],
}

impl<'a> PerceptionActorSourceV1<'a> {
    pub fn new(pin: PerceptionSourcePinV1, bytes: &'a [u8]) -> Result<Self, PerceptionErrorV1> {
        pin.validate()?;
        if pin.byte_length != bytes.len() as u64
            || pin.content_digest != Digest32::of_bytes(bytes).into_array()
        {
            return Err(PerceptionErrorV1::SourceMismatch);
        }
        Ok(Self { pin, bytes })
    }

    pub fn pin(&self) -> &PerceptionSourcePinV1 {
        &self.pin
    }

    pub fn evidence(
        &self,
        evidence_id: &str,
        coordinates: PerceptionCoordinatesV1,
    ) -> Result<PerceptionEvidenceV1, PerceptionErrorV1> {
        let ranges = self.pin.raw_ranges(&coordinates)?;
        let mut raw_bytes = Vec::new();
        for range in ranges {
            raw_bytes.extend_from_slice(&self.bytes[range]);
        }
        let result = PerceptionEvidenceV1 {
            evidence_id: evidence_id.to_owned(),
            source: self.pin.clone(),
            coordinates,
            raw_bytes,
        };
        result.digest()?;
        Ok(result)
    }

    pub(crate) fn matches(&self, evidence: &PerceptionEvidenceV1) -> Result<(), PerceptionErrorV1> {
        if self.pin != evidence.source {
            return Err(PerceptionErrorV1::SourceMismatch);
        }
        let actual = self.evidence(&evidence.evidence_id, evidence.coordinates)?;
        if actual != *evidence {
            return Err(PerceptionErrorV1::SourceMismatch);
        }
        Ok(())
    }
}

impl PerceptionSourcePinV1 {
    pub(crate) fn validate(&self) -> Result<(), PerceptionErrorV1> {
        if StableId::new(self.source_id.as_str()).is_err()
            || self.origin_digest == [0; 32]
            || self.content_digest == [0; 32]
            || !(1..=MAX_SOURCE_BYTES).contains(&self.byte_length)
            || self.observed_at_micros == 0
        {
            return Err(PerceptionErrorV1::InvalidSource);
        }
        let expected = match self.layout {
            PerceptionSourceLayoutV1::Bytes { origin_offset, origin_length } => {
                if origin_offset.checked_add(self.byte_length).is_none_or(|end| end > origin_length) {
                    return Err(PerceptionErrorV1::InvalidSource);
                }
                self.byte_length
            }
            PerceptionSourceLayoutV1::Raster { width, height, channels } => {
                raster_bytes(width, height, channels)?
            }
            PerceptionSourceLayoutV1::Frames { width, height, channels, frame_count, frame_period_micros } => {
                if frame_count == 0 || frame_period_micros == 0
                    || u64::from(frame_count).checked_mul(frame_period_micros).is_none()
                {
                    return Err(PerceptionErrorV1::InvalidSource);
                }
                raster_bytes(width, height, channels)?
                    .checked_mul(u64::from(frame_count))
                    .ok_or(PerceptionErrorV1::InvalidSource)?
            }
        };
        if expected != self.byte_length {
            return Err(PerceptionErrorV1::InvalidSource);
        }
        Ok(())
    }

    pub(crate) fn raw_ranges(&self, coordinates: &PerceptionCoordinatesV1) -> Result<Vec<Range<usize>>, PerceptionErrorV1> {
        self.validate()?;
        let (frame, source_width, source_height, channels, x, y, width, height) = match (&self.layout, coordinates) {
            (PerceptionSourceLayoutV1::Bytes { origin_offset, .. }, PerceptionCoordinatesV1::Bytes { start, end }) => {
                let start = start.checked_sub(*origin_offset).ok_or(PerceptionErrorV1::InvalidCoordinates)?;
                let end = end.checked_sub(*origin_offset).ok_or(PerceptionErrorV1::InvalidCoordinates)?;
                if start >= end || end > self.byte_length || end - start > MAX_PERCEPTION_RAW_BYTES as u64 {
                    return Err(PerceptionErrorV1::InvalidCoordinates);
                }
                return Ok(vec![start as usize..end as usize]);
            }
            (PerceptionSourceLayoutV1::Raster { width: sw, height: sh, channels }, PerceptionCoordinatesV1::ImageRegion { x, y, width, height }) => {
                (0, *sw, *sh, *channels, *x, *y, *width, *height)
            }
            (PerceptionSourceLayoutV1::Frames { width: sw, height: sh, channels, frame_count, frame_period_micros }, PerceptionCoordinatesV1::VideoRegion { frame_index, timestamp_micros, x, y, width, height }) => {
                if frame_index >= frame_count || u64::from(*frame_index).checked_mul(*frame_period_micros) != Some(*timestamp_micros) {
                    return Err(PerceptionErrorV1::InvalidCoordinates);
                }
                (*frame_index, *sw, *sh, *channels, *x, *y, *width, *height)
            }
            _ => return Err(PerceptionErrorV1::InvalidCoordinates),
        };
        let length = raster_bytes(width, height, channels)?;
        if x.checked_add(width).is_none_or(|end| end > source_width)
            || y.checked_add(height).is_none_or(|end| end > source_height)
            || length > MAX_PERCEPTION_RAW_BYTES as u64
        {
            return Err(PerceptionErrorV1::InvalidCoordinates);
        }
        let stride = u64::from(source_width) * u64::from(channels);
        let base = u64::from(frame) * u64::from(source_height) * stride;
        let row_length = u64::from(width) * u64::from(channels);
        let mut ranges = Vec::with_capacity(height as usize);
        for row in y..y + height {
            let start = base + u64::from(row) * stride + u64::from(x) * u64::from(channels);
            let end = start + row_length;
            if end > self.byte_length {
                return Err(PerceptionErrorV1::InvalidCoordinates);
            }
            ranges.push(start as usize..end as usize);
        }
        Ok(ranges)
    }
}

fn raster_bytes(width: u32, height: u32, channels: u8) -> Result<u64, PerceptionErrorV1> {
    if width == 0 || height == 0 || !(1..=4).contains(&channels) {
        return Err(PerceptionErrorV1::InvalidCoordinates);
    }
    u64::from(width).checked_mul(u64::from(height))
        .and_then(|value| value.checked_mul(u64::from(channels)))
        .ok_or(PerceptionErrorV1::InvalidCoordinates)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PerceptionErrorV1 {
    InvalidWire, Capacity, InvalidSource, InvalidCoordinates, InvalidEvidence,
    SourceMismatch, InvalidLatent, BindingMismatch,
}

impl fmt::Display for PerceptionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { write!(formatter, "{self:?}") }
}
impl Error for PerceptionErrorV1 {}

#[cfg(test)]
#[path = "perception_source_tests.rs"]
mod tests;
