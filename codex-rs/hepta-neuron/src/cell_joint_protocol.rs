//! Wire framing for the pure, independently fingerprinted Joint proposal process.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CellGenerationErrorV2;

pub(crate) const MAX_WEIGHTS_BYTES: usize = 8 * 1024 * 1024;
pub(crate) const MAX_PUBLIC_BYTES: usize = 1024 * 1024;
pub(crate) const MAX_RESULT_BYTES: usize = 8 + 32 + 1 + 32 + 8 + 2 * 65_536 + 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JointGenerationSamplerV1 {
    Mean,
    SplitmixNormalV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JointGenerationActionV1 {
    Shared,
    Image,
    Audio,
    Video,
    Text,
    Verify,
    Stop,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JointGenerationModalityV1 {
    Image,
    Audio,
    Video,
    Text,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum JointGenerationCommandV1 {
    Init {
        seed: u64,
        sampler: JointGenerationSamplerV1,
    },
    Advance {
        action: JointGenerationActionV1,
    },
    Auto {
        remaining_millionths: u32,
    },
    Commit {
        modality: JointGenerationModalityV1,
        units: u32,
    },
}

/// The caller references an immutable, host-bound public packet. Input never
/// supplies a path, executable, shell command, weights or replacement sampler.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JointGenerationInputV1 {
    pub public_digest: [u8; 32],
    pub command: JointGenerationCommandV1,
}

pub(crate) fn request_bytes(
    request_digest: [u8; 32],
    weights: &[u8],
    public: &[u8],
    state: &[u8],
    prefix: &[u8],
    command: &JointGenerationCommandV1,
) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let mut bytes = b"HJREQV01".to_vec();
    bytes.extend(request_digest);
    for (part, maximum) in [
        (weights, MAX_WEIGHTS_BYTES),
        (public, MAX_PUBLIC_BYTES),
        (state, 65_536),
        (prefix, 262_144),
    ] {
        if part.len() > maximum {
            return Err(CellGenerationErrorV2::Capacity);
        }
        bytes.extend((part.len() as u32).to_le_bytes());
        bytes.extend(part);
    }
    match command {
        JointGenerationCommandV1::Init { seed, sampler } => {
            if !state.is_empty() || !prefix.is_empty() {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            bytes.push(0);
            bytes.extend(seed.to_le_bytes());
            bytes.push(match sampler {
                JointGenerationSamplerV1::Mean => 0,
                JointGenerationSamplerV1::SplitmixNormalV1 => 1,
            });
        }
        JointGenerationCommandV1::Advance { action } => {
            bytes.push(1);
            bytes.push(match action {
                JointGenerationActionV1::Shared => 0,
                JointGenerationActionV1::Image => 1,
                JointGenerationActionV1::Audio => 2,
                JointGenerationActionV1::Video => 3,
                JointGenerationActionV1::Text => 4,
                JointGenerationActionV1::Verify => 5,
                JointGenerationActionV1::Stop => 6,
            });
        }
        JointGenerationCommandV1::Auto {
            remaining_millionths,
        } => {
            if *remaining_millionths > 1_000_000 {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            bytes.push(2);
            bytes.extend(remaining_millionths.to_le_bytes());
        }
        JointGenerationCommandV1::Commit { modality, units } => {
            let (tag, maximum) = match modality {
                JointGenerationModalityV1::Image => (0, 16),
                JointGenerationModalityV1::Audio => (1, 1024),
                JointGenerationModalityV1::Video => (2, 4),
                JointGenerationModalityV1::Text => (3, 2),
            };
            if *units == 0 || *units > maximum {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            bytes.extend([3, tag]);
            bytes.extend(units.to_le_bytes());
        }
    }
    Ok(bytes)
}

pub(crate) struct JointProposal {
    pub state: Vec<u8>,
    pub delta: Vec<u8>,
    pub stopped: bool,
    /// Disjoint child phases: codec, encoder, inference, joint planning/critic.
    pub wall_micros: [u64; 4],
}

pub(crate) fn read_proposal(
    bytes: &[u8],
    request_digest: [u8; 32],
) -> Result<JointProposal, CellGenerationErrorV2> {
    if bytes.len() < 8 + 32 + 1 + 32 + 8 + 64 || bytes.len() > MAX_RESULT_BYTES {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let (body, checksum) = bytes.split_at(bytes.len() - 64);
    if Digest32::of_bytes(body).to_string().as_bytes() != checksum {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let mut reader = Reader { bytes: body, at: 0 };
    if reader.take(8)? != b"HJRESV01" || reader.take(32)? != request_digest {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let stopped = match reader.take(1)? {
        [0] => false,
        [1] => true,
        _ => return Err(CellGenerationErrorV2::Corrupt),
    };
    let mut wall_micros = [0; 4];
    for value in &mut wall_micros {
        *value = u64::from_le_bytes(
            reader
                .take(8)?
                .try_into()
                .map_err(|_| CellGenerationErrorV2::Corrupt)?,
        );
    }
    let state = reader.packet()?;
    let delta = reader.packet()?;
    if state.is_empty() || reader.at != body.len() {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    Ok(JointProposal {
        state,
        delta,
        stopped,
        wall_micros,
    })
}

struct Reader<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl Reader<'_> {
    fn take(&mut self, count: usize) -> Result<&[u8], CellGenerationErrorV2> {
        let end = self
            .at
            .checked_add(count)
            .ok_or(CellGenerationErrorV2::Capacity)?;
        let value = self
            .bytes
            .get(self.at..end)
            .ok_or(CellGenerationErrorV2::Corrupt)?;
        self.at = end;
        Ok(value)
    }

    fn packet(&mut self) -> Result<Vec<u8>, CellGenerationErrorV2> {
        let count = u32::from_le_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| CellGenerationErrorV2::Corrupt)?,
        ) as usize;
        if count > 65_536 {
            return Err(CellGenerationErrorV2::Capacity);
        }
        Ok(self.take(count)?.to_vec())
    }
}
