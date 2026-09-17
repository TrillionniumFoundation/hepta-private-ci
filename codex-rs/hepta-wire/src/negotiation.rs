use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum WireVersion {
    V1,
    V2,
}

impl WireVersion {
    pub const fn as_u16(self) -> u16 {
        match self {
            Self::V1 => 1,
            Self::V2 => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CapabilitySet(u64);

impl CapabilitySet {
    pub const NONE: Self = Self(0);
    pub const FULL_FRAME_INTEGRITY: Self = Self(1 << 0);
    pub const SCHEMA_ADMISSION: Self = Self(1 << 1);
    pub const STREAMING_DECODE: Self = Self(1 << 2);
    pub const SUPPORTED: Self =
        Self(Self::FULL_FRAME_INTEGRITY.0 | Self::SCHEMA_ADMISSION.0 | Self::STREAMING_DECODE.0);

    pub const fn from_bits(bits: u64) -> Self {
        Self(bits)
    }

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

    pub const fn unknown_bits(self) -> u64 {
        self.0 & !Self::SUPPORTED.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct VersionOffer {
    pub version: WireVersion,
    pub capabilities: CapabilitySet,
}

impl VersionOffer {
    pub const fn new(version: WireVersion, capabilities: CapabilitySet) -> Self {
        Self {
            version,
            capabilities,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiationOffer {
    versions: Vec<VersionOffer>,
    required_capabilities: CapabilitySet,
}

impl NegotiationOffer {
    pub fn new(
        mut versions: Vec<VersionOffer>,
        required_capabilities: CapabilitySet,
    ) -> Result<Self, NegotiationError> {
        if versions.is_empty() {
            return Err(NegotiationError::EmptyOffer);
        }
        let required_unknown = required_capabilities.unknown_bits();
        if required_unknown != 0 {
            return Err(NegotiationError::UnknownCapabilityBits(required_unknown));
        }
        for entry in &versions {
            let unknown = entry.capabilities.unknown_bits();
            if unknown != 0 {
                return Err(NegotiationError::UnknownCapabilityBits(unknown));
            }
        }
        versions.sort_by_key(|entry| entry.version);
        for pair in versions.windows(2) {
            if pair[0].version == pair[1].version {
                return Err(NegotiationError::DuplicateVersion(pair[0].version));
            }
        }
        if !versions
            .iter()
            .any(|entry| entry.capabilities.contains(required_capabilities))
        {
            return Err(NegotiationError::RequiredCapabilitiesUnavailable);
        }
        Ok(Self {
            versions,
            required_capabilities,
        })
    }

    pub fn versions(&self) -> &[VersionOffer] {
        &self.versions
    }

    pub const fn required_capabilities(&self) -> CapabilitySet {
        self.required_capabilities
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiatedWire {
    version: WireVersion,
    capabilities: CapabilitySet,
    transcript_digest: Digest32,
}

impl NegotiatedWire {
    pub const fn version(self) -> WireVersion {
        self.version
    }

    pub const fn capabilities(self) -> CapabilitySet {
        self.capabilities
    }

    /// Canonical digest of both offers and the selected result.
    ///
    /// Authenticating this digest at the secure-channel/session boundary gives
    /// callers a stable downgrade-detection binding. The digest itself is not
    /// an authenticator.
    pub const fn transcript_digest(self) -> Digest32 {
        self.transcript_digest
    }
}

pub fn negotiate(
    local: &NegotiationOffer,
    remote: &NegotiationOffer,
) -> Result<NegotiatedWire, NegotiationError> {
    let required = local
        .required_capabilities
        .union(remote.required_capabilities);

    for local_version in local.versions.iter().rev() {
        let Some(remote_version) = remote
            .versions
            .iter()
            .find(|entry| entry.version == local_version.version)
        else {
            continue;
        };
        let capabilities = local_version
            .capabilities
            .intersection(remote_version.capabilities);
        if !capabilities.contains(required) {
            continue;
        }
        let version = local_version.version;
        let transcript_digest = negotiation_transcript_digest(local, remote, version, capabilities);
        return Ok(NegotiatedWire {
            version,
            capabilities,
            transcript_digest,
        });
    }

    Err(NegotiationError::Incompatible)
}

fn negotiation_transcript_digest(
    left: &NegotiationOffer,
    right: &NegotiationOffer,
    version: WireVersion,
    capabilities: CapabilitySet,
) -> Digest32 {
    let mut left_bytes = encode_offer(left);
    let mut right_bytes = encode_offer(right);
    if right_bytes < left_bytes {
        std::mem::swap(&mut left_bytes, &mut right_bytes);
    }

    let mut bytes = Vec::with_capacity(
        32 + left_bytes.len() + right_bytes.len() + std::mem::size_of::<u16>() + 8,
    );
    bytes.extend_from_slice(b"hepta.wire.negotiation.v1\0");
    bytes.extend_from_slice(&(left_bytes.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&left_bytes);
    bytes.extend_from_slice(&(right_bytes.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&right_bytes);
    bytes.extend_from_slice(&version.as_u16().to_be_bytes());
    bytes.extend_from_slice(&capabilities.bits().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn encode_offer(offer: &NegotiationOffer) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(16 + offer.versions.len() * 10);
    bytes.extend_from_slice(&offer.required_capabilities.bits().to_be_bytes());
    bytes.extend_from_slice(&(offer.versions.len() as u32).to_be_bytes());
    for entry in &offer.versions {
        bytes.extend_from_slice(&entry.version.as_u16().to_be_bytes());
        bytes.extend_from_slice(&entry.capabilities.bits().to_be_bytes());
    }
    bytes
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    EmptyOffer,
    DuplicateVersion(WireVersion),
    UnknownCapabilityBits(u64),
    RequiredCapabilitiesUnavailable,
    Incompatible,
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyOffer => formatter.write_str("wire negotiation offer is empty"),
            Self::DuplicateVersion(version) => {
                write!(
                    formatter,
                    "wire negotiation repeats version {}",
                    version.as_u16()
                )
            }
            Self::UnknownCapabilityBits(bits) => {
                write!(
                    formatter,
                    "wire negotiation contains unknown capability bits 0x{bits:x}"
                )
            }
            Self::RequiredCapabilitiesUnavailable => formatter
                .write_str("wire negotiation offer cannot satisfy its own required capabilities"),
            Self::Incompatible => formatter.write_str("wire negotiation has no compatible version"),
        }
    }
}

impl Error for NegotiationError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn full_v2() -> CapabilitySet {
        CapabilitySet::FULL_FRAME_INTEGRITY
            .union(CapabilitySet::SCHEMA_ADMISSION)
            .union(CapabilitySet::STREAMING_DECODE)
    }

    #[test]
    fn negotiation_selects_highest_common_version_and_binds_transcript() {
        let local = NegotiationOffer::new(
            vec![
                VersionOffer::new(WireVersion::V1, CapabilitySet::NONE),
                VersionOffer::new(WireVersion::V2, full_v2()),
            ],
            CapabilitySet::FULL_FRAME_INTEGRITY,
        )
        .expect("local offer");
        let remote = NegotiationOffer::new(
            vec![VersionOffer::new(WireVersion::V2, full_v2())],
            CapabilitySet::SCHEMA_ADMISSION,
        )
        .expect("remote offer");

        let selected = negotiate(&local, &remote).expect("compatible negotiation");
        let reverse = negotiate(&remote, &local).expect("reverse negotiation");
        assert_eq!(selected.version(), WireVersion::V2);
        assert!(
            selected
                .capabilities()
                .contains(CapabilitySet::FULL_FRAME_INTEGRITY)
        );
        assert_eq!(selected.transcript_digest(), reverse.transcript_digest());
    }

    #[test]
    fn required_v2_integrity_prevents_v1_downgrade() {
        let local = NegotiationOffer::new(
            vec![
                VersionOffer::new(WireVersion::V1, CapabilitySet::NONE),
                VersionOffer::new(WireVersion::V2, CapabilitySet::FULL_FRAME_INTEGRITY),
            ],
            CapabilitySet::FULL_FRAME_INTEGRITY,
        )
        .expect("local offer");
        let remote = NegotiationOffer::new(
            vec![VersionOffer::new(WireVersion::V1, CapabilitySet::NONE)],
            CapabilitySet::NONE,
        )
        .expect("remote offer");
        assert_eq!(
            negotiate(&local, &remote),
            Err(NegotiationError::Incompatible)
        );
    }

    #[test]
    fn unknown_capability_bits_fail_closed() {
        let unknown = CapabilitySet::from_bits(1_u64 << 63);
        assert_eq!(
            NegotiationOffer::new(
                vec![VersionOffer::new(WireVersion::V2, unknown)],
                CapabilitySet::NONE,
            ),
            Err(NegotiationError::UnknownCapabilityBits(1_u64 << 63))
        );
        assert_eq!(
            NegotiationOffer::new(vec![VersionOffer::new(WireVersion::V2, full_v2())], unknown,),
            Err(NegotiationError::UnknownCapabilityBits(1_u64 << 63))
        );
    }
}
