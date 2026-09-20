use std::error::Error;
use std::fmt;

const NEGOTIATION_MAGIC: [u8; 4] = *b"HPTN";
const NEGOTIATION_FORMAT_VERSION: u16 = 1;
const NEGOTIATION_FIXED_BYTES: usize = 4 + 2 + 1 + 1 + 8;
pub const MAX_NEGOTIATION_VERSIONS: usize = 16;

/// Wire versions implemented by this crate.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u16)]
pub enum WireVersion {
    V1 = 1,
    V2 = 2,
}

impl WireVersion {
    pub const SUPPORTED_DESCENDING: [Self; 2] = [Self::V2, Self::V1];

    pub const fn as_u16(self) -> u16 {
        self as u16
    }

    pub const fn required_capabilities(self) -> WireCapabilities {
        match self {
            Self::V1 => WireCapabilities::NONE,
            Self::V2 => WireCapabilities::METADATA_BOUND_DIGEST,
        }
    }

    const fn provided_version_semantics(self) -> WireCapabilities {
        match self {
            Self::V1 => WireCapabilities::NONE,
            Self::V2 => WireCapabilities::METADATA_BOUND_DIGEST,
        }
    }
}

/// Explicitly negotiated protocol capabilities.
///
/// Unknown bits reject instead of being silently reinterpreted. Callers that
/// rely on a security property must include its bit in the required set passed
/// to negotiate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WireCapabilities(u64);

impl WireCapabilities {
    pub const NONE: Self = Self(0);
    pub const METADATA_BOUND_DIGEST: Self = Self(1 << 0);
    pub const SCHEMA_ADMISSION: Self = Self(1 << 1);
    pub const STREAM_DECODING: Self = Self(1 << 2);
    pub const CURRENT: Self = Self(
        Self::METADATA_BOUND_DIGEST.0 | Self::SCHEMA_ADMISSION.0 | Self::STREAM_DECODING.0,
    );
    const KNOWN_MASK: u64 = Self::CURRENT.0;
    const VERSION_SCOPED: Self = Self(Self::METADATA_BOUND_DIGEST.0);

    pub const fn bits(self) -> u64 {
        self.0
    }

    pub const fn contains(self, required: Self) -> bool {
        self.0 & required.0 == required.0
    }

    pub const fn intersection(self, other: Self) -> Self {
        Self(self.0 & other.0)
    }

    pub const fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }

    fn from_bits(bits: u64) -> Result<Self, NegotiationError> {
        let unknown = bits & !Self::KNOWN_MASK;
        if unknown != 0 {
            return Err(NegotiationError::UnknownCapabilities(unknown));
        }
        Ok(Self(bits))
    }
}

/// Canonical transport-neutral version/capability advertisement.
///
/// Version numbers are stored as raw u16 values so a newer peer can advertise
/// future versions without an older peer accidentally assigning them meaning.
/// Negotiation selects only versions implemented locally.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiationOffer {
    versions: Vec<u16>,
    capabilities: WireCapabilities,
}

impl NegotiationOffer {
    pub fn new(
        mut versions: Vec<u16>,
        capabilities: WireCapabilities,
    ) -> Result<Self, NegotiationError> {
        if versions.is_empty() {
            return Err(NegotiationError::EmptyVersions);
        }
        if versions.len() > MAX_NEGOTIATION_VERSIONS {
            return Err(NegotiationError::TooManyVersions(versions.len()));
        }
        if versions.contains(&0) {
            return Err(NegotiationError::InvalidVersion(0));
        }
        versions.sort_unstable();
        versions.dedup();
        Ok(Self {
            versions,
            capabilities,
        })
    }

    pub fn current() -> Self {
        Self {
            versions: vec![WireVersion::V1.as_u16(), WireVersion::V2.as_u16()],
            capabilities: WireCapabilities::CURRENT,
        }
    }

    pub fn versions(&self) -> &[u16] {
        &self.versions
    }

    pub const fn capabilities(&self) -> WireCapabilities {
        self.capabilities
    }

    /// HPTN negotiation hello V1.
    ///
    /// Layout: magic(4), format(2), count(1), reserved(1), capabilities(8),
    /// then strictly increasing u16 wire versions.
    pub fn encode(&self) -> Vec<u8> {
        let mut encoded =
            Vec::with_capacity(NEGOTIATION_FIXED_BYTES + self.versions.len().saturating_mul(2));
        encoded.extend_from_slice(&NEGOTIATION_MAGIC);
        encoded.extend_from_slice(&NEGOTIATION_FORMAT_VERSION.to_be_bytes());
        encoded.push(self.versions.len() as u8);
        encoded.push(0);
        encoded.extend_from_slice(&self.capabilities.bits().to_be_bytes());
        for version in &self.versions {
            encoded.extend_from_slice(&version.to_be_bytes());
        }
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, NegotiationError> {
        if encoded.len() < NEGOTIATION_FIXED_BYTES {
            return Err(NegotiationError::Truncated);
        }
        if encoded[..4] != NEGOTIATION_MAGIC {
            return Err(NegotiationError::Magic);
        }
        let format = read_u16(encoded, 4)?;
        if format != NEGOTIATION_FORMAT_VERSION {
            return Err(NegotiationError::Format(format));
        }
        let count = usize::from(encoded[6]);
        if count == 0 {
            return Err(NegotiationError::EmptyVersions);
        }
        if count > MAX_NEGOTIATION_VERSIONS {
            return Err(NegotiationError::TooManyVersions(count));
        }
        if encoded[7] != 0 {
            return Err(NegotiationError::Reserved(encoded[7]));
        }
        let capabilities = WireCapabilities::from_bits(read_u64(encoded, 8)?)?;
        let expected = NEGOTIATION_FIXED_BYTES
            .checked_add(count.checked_mul(2).ok_or(NegotiationError::LengthMismatch)?)
            .ok_or(NegotiationError::LengthMismatch)?;
        if encoded.len() != expected {
            return Err(NegotiationError::LengthMismatch);
        }
        let mut versions = Vec::with_capacity(count);
        let mut offset = NEGOTIATION_FIXED_BYTES;
        for _ in 0..count {
            let version = read_u16(encoded, offset)?;
            if version == 0 {
                return Err(NegotiationError::InvalidVersion(version));
            }
            versions.push(version);
            offset += 2;
        }
        if versions.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(NegotiationError::NonCanonicalVersions);
        }
        Ok(Self {
            versions,
            capabilities,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiatedWire {
    pub version: WireVersion,
    pub capabilities: WireCapabilities,
}

/// Select the highest explicitly common implemented version that satisfies all
/// required capabilities.
///
/// A caller that needs V2 metadata binding must require
/// WireCapabilities::METADATA_BOUND_DIGEST; a V1-only peer then fails closed
/// instead of silently downgrading the security property.
pub fn negotiate(
    local: &NegotiationOffer,
    remote: &NegotiationOffer,
    required: WireCapabilities,
) -> Result<NegotiatedWire, NegotiationError> {
    WireCapabilities::from_bits(required.bits())?;
    let common_capabilities = local.capabilities.intersection(remote.capabilities);
    let mut saw_common_version = false;
    for version in WireVersion::SUPPORTED_DESCENDING {
        let raw = version.as_u16();
        if !local.versions.contains(&raw) || !remote.versions.contains(&raw) {
            continue;
        }
        saw_common_version = true;
        let required_version_semantics = required.intersection(WireCapabilities::VERSION_SCOPED);
        if !version
            .provided_version_semantics()
            .contains(required_version_semantics)
        {
            continue;
        }
        let needed = required.union(version.required_capabilities());
        if common_capabilities.contains(needed) {
            return Ok(NegotiatedWire {
                version,
                capabilities: common_capabilities,
            });
        }
    }
    if saw_common_version {
        Err(NegotiationError::MissingRequiredCapabilities {
            required: required.bits(),
            common: common_capabilities.bits(),
        })
    } else {
        Err(NegotiationError::NoCommonVersion)
    }
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, NegotiationError> {
    let end = start.checked_add(2).ok_or(NegotiationError::Truncated)?;
    let raw: [u8; 2] = bytes
        .get(start..end)
        .ok_or(NegotiationError::Truncated)?
        .try_into()
        .map_err(|_| NegotiationError::Truncated)?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, NegotiationError> {
    let end = start.checked_add(8).ok_or(NegotiationError::Truncated)?;
    let raw: [u8; 8] = bytes
        .get(start..end)
        .ok_or(NegotiationError::Truncated)?
        .try_into()
        .map_err(|_| NegotiationError::Truncated)?;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    Truncated,
    Magic,
    Format(u16),
    EmptyVersions,
    TooManyVersions(usize),
    InvalidVersion(u16),
    Reserved(u8),
    UnknownCapabilities(u64),
    LengthMismatch,
    NonCanonicalVersions,
    NoCommonVersion,
    MissingRequiredCapabilities { required: u64, common: u64 },
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire negotiation hello is truncated"),
            Self::Magic => formatter.write_str("wire negotiation magic mismatch"),
            Self::Format(version) => {
                write!(formatter, "unsupported wire negotiation format {version}")
            }
            Self::EmptyVersions => formatter.write_str("wire negotiation has no versions"),
            Self::TooManyVersions(count) => {
                write!(formatter, "wire negotiation has too many versions: {count}")
            }
            Self::InvalidVersion(version) => {
                write!(formatter, "invalid advertised wire version {version}")
            }
            Self::Reserved(value) => {
                write!(formatter, "wire negotiation reserved byte is non-zero: {value}")
            }
            Self::UnknownCapabilities(bits) => {
                write!(formatter, "unknown wire capability bits 0x{bits:016x}")
            }
            Self::LengthMismatch => formatter.write_str("wire negotiation length mismatch"),
            Self::NonCanonicalVersions => {
                formatter.write_str("wire versions must be strictly increasing")
            }
            Self::NoCommonVersion => formatter.write_str("no common wire version"),
            Self::MissingRequiredCapabilities { required, common } => write!(
                formatter,
                "common wire capabilities 0x{common:016x} do not satisfy 0x{required:016x}"
            ),
        }
    }
}

impl Error for NegotiationError {}

#[cfg(test)]
#[path = "version_tests.rs"]
mod tests;
