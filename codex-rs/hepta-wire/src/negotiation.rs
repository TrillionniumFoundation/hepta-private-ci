use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

pub const HPTA_V1: u16 = 1;
pub const HPTA_V2: u16 = 2;
pub const CAP_FRAME_DIGEST_V2: &str = "hpta.frame-digest.v2";
pub const CAP_SCHEMA_ADMISSION_V1: &str = "hpta.schema-admission.v1";
pub const CAP_STREAMING_FRAMES_V1: &str = "hpta.streaming-frames.v1";
const MAX_OFFERED_VERSIONS: usize = 16;
const MAX_CRITICAL_CAPABILITIES: usize = 32;
const V2_CAPABILITIES: &[&str] = &[
    CAP_FRAME_DIGEST_V2,
    CAP_SCHEMA_ADMISSION_V1,
    CAP_STREAMING_FRAMES_V1,
];
const V1_CAPABILITIES: &[&str] = &[];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiatedProtocol {
    version: u16,
    capabilities: Vec<&'static str>,
}

impl NegotiatedProtocol {
    pub const fn version(&self) -> u16 {
        self.version
    }

    pub fn capabilities(&self) -> &[&'static str] {
        &self.capabilities
    }

    pub fn supports(&self, capability: &str) -> bool {
        self.capabilities.contains(&capability)
    }
}

/// Select the highest explicitly common implemented version.
///
/// Critical capabilities are fail-closed: negotiation never falls back to a
/// version that omits a caller-declared critical capability.
pub fn negotiate(
    local_versions: &[u16],
    remote_versions: &[u16],
    critical_features: &[StableId],
) -> Result<NegotiatedProtocol, NegotiationError> {
    if local_versions.is_empty() {
        return Err(NegotiationError::EmptyLocalOffer);
    }
    if remote_versions.is_empty() {
        return Err(NegotiationError::EmptyRemoteOffer);
    }
    if local_versions.len() > MAX_OFFERED_VERSIONS
        || remote_versions.len() > MAX_OFFERED_VERSIONS
    {
        return Err(NegotiationError::VersionOfferLimit);
    }
    if critical_features.len() > MAX_CRITICAL_CAPABILITIES {
        return Err(NegotiationError::CriticalCapabilityLimit);
    }

    let mut missing_critical = None;
    for version in [HPTA_V2, HPTA_V1] {
        if !local_versions.contains(&version) || !remote_versions.contains(&version) {
            continue;
        }
        let capabilities = capabilities_for(version);
        if let Some(missing) = critical_features
            .iter()
            .find(|feature| !capabilities.contains(&feature.as_str()))
        {
            if missing_critical.is_none() {
                missing_critical = Some(missing.to_string());
            }
            continue;
        }
        return Ok(NegotiatedProtocol {
            version,
            capabilities: capabilities.to_vec(),
        });
    }

    if let Some(capability) = missing_critical {
        Err(NegotiationError::MissingCriticalCapability(capability))
    } else {
        Err(NegotiationError::NoCommonImplementedVersion)
    }
}

pub fn capabilities_for(version: u16) -> &'static [&'static str] {
    match version {
        HPTA_V1 => V1_CAPABILITIES,
        HPTA_V2 => V2_CAPABILITIES,
        _ => &[],
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    EmptyLocalOffer,
    EmptyRemoteOffer,
    VersionOfferLimit,
    CriticalCapabilityLimit,
    NoCommonImplementedVersion,
    MissingCriticalCapability(String),
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyLocalOffer => formatter.write_str("local wire version offer is empty"),
            Self::EmptyRemoteOffer => formatter.write_str("remote wire version offer is empty"),
            Self::VersionOfferLimit => formatter.write_str("wire version offer exceeds limit"),
            Self::CriticalCapabilityLimit => {
                formatter.write_str("critical wire capability set exceeds limit")
            }
            Self::NoCommonImplementedVersion => {
                formatter.write_str("no common implemented wire version")
            }
            Self::MissingCriticalCapability(capability) => {
                write!(formatter, "negotiated version lacks critical capability {capability}")
            }
        }
    }
}

impl Error for NegotiationError {}
