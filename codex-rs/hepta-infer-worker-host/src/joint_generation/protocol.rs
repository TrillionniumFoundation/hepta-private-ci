//! Bounded one-request ABI. Asset bytes come from the admitting host, never paths.

use crate::codec::Result;
use crate::codec::sha256;

pub(crate) const MAX_STATE_BYTES: usize = 65_536;
pub(crate) const MAX_DELTA_BYTES: usize = 65_536;
pub(crate) const MAX_PREFIX_BYTES: usize = 262_144;
const MAX_WEIGHTS_BYTES: usize = 8 * 1024 * 1024;
const MAX_PUBLIC_BYTES: usize = 1024 * 1024;
pub(crate) const MAX_REQUEST_BYTES: usize =
    8 + 32 + 16 + MAX_WEIGHTS_BYTES + MAX_PUBLIC_BYTES + MAX_STATE_BYTES + MAX_PREFIX_BYTES + 10;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Sampler {
    Mean,
    SplitmixNormal,
}

impl Sampler {
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Mean => "mean",
            Self::SplitmixNormal => "splitmix-normal-v1",
        }
    }
    pub(crate) fn parse(name: &str) -> Result<Self> {
        match name {
            "mean" => Ok(Self::Mean),
            "splitmix-normal-v1" => Ok(Self::SplitmixNormal),
            _ => Err("unknown sampler".into()),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct EmissionLaw {
    pub(crate) seed: u64,
    pub(crate) sampler: Sampler,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Command {
    Init(EmissionLaw),
    Advance(u8),
    Auto(u32),
    Commit { modality: u8, units: u32 },
}

pub(crate) struct Request<'a> {
    pub(crate) digest: [u8; 32],
    pub(crate) weights: &'a [u8],
    pub(crate) public: &'a [u8],
    pub(crate) state: &'a [u8],
    pub(crate) prefix: &'a [u8],
    pub(crate) command: Command,
}

pub(crate) fn parse(bytes: &[u8]) -> Result<Request<'_>> {
    if bytes.len() > MAX_REQUEST_BYTES {
        return Err("request too large".into());
    }
    let mut reader = Reader::new(bytes);
    if reader.take(8)? != b"HJREQV01" {
        return Err("unknown request ABI".into());
    }
    let digest = reader
        .take(32)?
        .try_into()
        .map_err(|_| "request digest width")?;
    if digest == [0; 32] {
        return Err("empty request digest".into());
    }
    let weights = reader.blob(MAX_WEIGHTS_BYTES)?;
    let public = reader.blob(MAX_PUBLIC_BYTES)?;
    let state = reader.blob(MAX_STATE_BYTES)?;
    let prefix = reader.blob(MAX_PREFIX_BYTES)?;
    let command = match reader.byte()? {
        0 => {
            let seed = u64::from_le_bytes(reader.take(8)?.try_into().map_err(|_| "seed width")?);
            let sampler = match reader.byte()? {
                0 => Sampler::Mean,
                1 => Sampler::SplitmixNormal,
                _ => return Err("unknown sampler tag".into()),
            };
            Command::Init(EmissionLaw { seed, sampler })
        }
        1 => {
            let action = reader.byte()?;
            if action >= 7 {
                return Err("unknown action".into());
            }
            Command::Advance(action)
        }
        2 => {
            let remaining = reader.u32()?;
            if remaining > 1_000_000 {
                return Err("remaining budget fraction".into());
            }
            Command::Auto(remaining)
        }
        3 => {
            let modality = reader.byte()?;
            let units = reader.u32()?;
            if modality >= 4 || units == 0 {
                return Err("invalid commit command".into());
            }
            Command::Commit { modality, units }
        }
        _ => return Err("unknown command".into()),
    };
    if !reader.is_empty() {
        return Err("request trailing bytes".into());
    }
    Ok(Request {
        digest,
        weights,
        public,
        state,
        prefix,
        command,
    })
}

#[derive(Debug)]
pub(crate) struct Response {
    pub(crate) digest: [u8; 32],
    pub(crate) stopped: bool,
    /// Disjoint observed wall intervals: codec, encoder, inference, planning.
    pub(crate) phase_micros: [u64; 4],
    pub(crate) state: Vec<u8>,
    pub(crate) delta: Vec<u8>,
}

impl Response {
    pub(crate) fn encode(&self) -> Result<Vec<u8>> {
        if self.state.len() > MAX_STATE_BYTES || self.delta.len() > MAX_DELTA_BYTES {
            return Err("response exceeds bounds".into());
        }
        let mut bytes = b"HJRESV01".to_vec();
        bytes.extend(self.digest);
        bytes.push(u8::from(self.stopped));
        for elapsed in self.phase_micros {
            bytes.extend(elapsed.to_le_bytes());
        }
        for blob in [&self.state, &self.delta] {
            bytes.extend((blob.len() as u32).to_le_bytes());
            bytes.extend(blob);
        }
        let checksum = sha256(&bytes);
        bytes.extend(checksum.as_bytes());
        Ok(bytes)
    }
}

pub(crate) struct Reader<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> Reader<'a> {
    pub(crate) fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, position: 0 }
    }
    pub(crate) fn take(&mut self, length: usize) -> Result<&'a [u8]> {
        let end = self.position.checked_add(length).ok_or("size overflow")?;
        let bytes = self
            .bytes
            .get(self.position..end)
            .ok_or("truncated frame")?;
        self.position = end;
        Ok(bytes)
    }
    pub(crate) fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    pub(crate) fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().map_err(|_| "u32 width")?,
        ))
    }
    fn blob(&mut self, maximum: usize) -> Result<&'a [u8]> {
        let length = self.u32()? as usize;
        if length > maximum {
            return Err("blob exceeds bound".into());
        }
        self.take(length)
    }
    pub(crate) fn is_empty(&self) -> bool {
        self.position == self.bytes.len()
    }
}
