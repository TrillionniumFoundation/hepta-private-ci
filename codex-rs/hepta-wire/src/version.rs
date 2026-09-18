use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

const NEGOTIATION_BINDING_DOMAIN: &[u8] = b"hepta.platform.wire.negotiation.v1\0";
pub const MAX_NEGOTIATION_VERSIONS: usize = 16;
pub const MAX_REQUIRED_CAPABILITIES: usize = 16;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum WireCapability {
    MetadataBoundIntegrity,
}

impl WireCapability {
    const fn tag(self) -> u8 {
        match self {
            Self::MetadataBoundIntegrity => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u16)]
pub enum WireVersion {
    V1 = 1,
    V2 = 2,
}

impl WireVersion {
    pub const fn as_u16(self) -> u16 {
        self as u16
    }

    pub const fn supports(self, capability: WireCapability) -> bool {
        match (self, capability) {
            (Self::V1, WireCapability::MetadataBoundIntegrity) => false,
            (Self::V2, WireCapability::MetadataBoundIntegrity) => true,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiatedVersion {
    version: WireVersion,
    binding_digest: Digest32,
}

impl NegotiatedVersion {
    pub const fn version(self) -> WireVersion {
        self.version
    }

    /// Digest of the role-ordered negotiation transcript.
    ///
    /// This digest is not authentication. A transport or session owner that
    /// needs downgrade resistance must authenticate this exact value.
    pub const fn binding_digest(self) -> Digest32 {
        self.binding_digest
    }
}

pub fn negotiate(
    initiator_versions: &[WireVersion],
    responder_versions: &[WireVersion],
    required_capabilities: &[WireCapability],
) -> Result<NegotiatedVersion, NegotiationError> {
    validate_bounds(
        initiator_versions,
        responder_versions,
        required_capabilities,
    )?;
    let selected = initiator_versions
        .iter()
        .copied()
        .filter(|candidate| responder_versions.contains(candidate))
        .filter(|candidate| {
            required_capabilities
                .iter()
                .all(|capability| candidate.supports(*capability))
        })
        .max()
        .ok_or(NegotiationError::NoCompatibleVersion)?;
    let binding_digest = negotiation_binding(
        initiator_versions,
        responder_versions,
        required_capabilities,
        selected,
    );
    Ok(NegotiatedVersion {
        version: selected,
        binding_digest,
    })
}

fn validate_bounds(
    initiator_versions: &[WireVersion],
    responder_versions: &[WireVersion],
    required_capabilities: &[WireCapability],
) -> Result<(), NegotiationError> {
    if initiator_versions.is_empty() || responder_versions.is_empty() {
        return Err(NegotiationError::EmptyVersionSet);
    }
    if initiator_versions.len() > MAX_NEGOTIATION_VERSIONS
        || responder_versions.len() > MAX_NEGOTIATION_VERSIONS
    {
        return Err(NegotiationError::VersionLimitExceeded);
    }
    if required_capabilities.len() > MAX_REQUIRED_CAPABILITIES {
        return Err(NegotiationError::CapabilityLimitExceeded);
    }
    Ok(())
}

fn negotiation_binding(
    initiator_versions: &[WireVersion],
    responder_versions: &[WireVersion],
    required_capabilities: &[WireCapability],
    selected: WireVersion,
) -> Digest32 {
    let mut initiator = initiator_versions.to_vec();
    initiator.sort_unstable();
    initiator.dedup();
    let mut responder = responder_versions.to_vec();
    responder.sort_unstable();
    responder.dedup();
    let mut required = required_capabilities.to_vec();
    required.sort_unstable();
    required.dedup();

    let mut bytes = Vec::with_capacity(
        NEGOTIATION_BINDING_DOMAIN.len()
            + 1
            + initiator.len() * 2
            + 1
            + responder.len() * 2
            + 1
            + required.len()
            + 2,
    );
    bytes.extend_from_slice(NEGOTIATION_BINDING_DOMAIN);
    bytes.push(u8::try_from(initiator.len()).unwrap_or(u8::MAX));
    for version in initiator {
        bytes.extend_from_slice(&version.as_u16().to_be_bytes());
    }
    bytes.push(u8::try_from(responder.len()).unwrap_or(u8::MAX));
    for version in responder {
        bytes.extend_from_slice(&version.as_u16().to_be_bytes());
    }
    bytes.push(u8::try_from(required.len()).unwrap_or(u8::MAX));
    for capability in required {
        bytes.push(capability.tag());
    }
    bytes.extend_from_slice(&selected.as_u16().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    EmptyVersionSet,
    VersionLimitExceeded,
    CapabilityLimitExceeded,
    NoCompatibleVersion,
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyVersionSet => formatter.write_str("wire negotiation version set is empty"),
            Self::VersionLimitExceeded => {
                formatter.write_str("wire negotiation version set exceeds its bound")
            }
            Self::CapabilityLimitExceeded => {
                formatter.write_str("wire negotiation capability set exceeds its bound")
            }
            Self::NoCompatibleVersion => {
                formatter.write_str("wire negotiation found no compatible version")
            }
        }
    }
}

impl Error for NegotiationError {}

#[cfg(test)]
#[path = "version_tests.rs"]
mod tests;
