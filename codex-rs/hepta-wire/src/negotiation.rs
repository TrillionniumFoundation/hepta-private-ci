use std::error::Error;
use std::fmt;

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

    pub const fn capabilities(self) -> &'static [WireCapability] {
        match self {
            Self::V1 => &[],
            Self::V2 => &[WireCapability::FullFrameIntegrity],
        }
    }

    pub fn supports(self, capability: WireCapability) -> bool {
        self.capabilities().contains(&capability)
    }
}

impl TryFrom<u16> for WireVersion {
    type Error = NegotiationError;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::V1),
            2 => Ok(Self::V2),
            other => Err(NegotiationError::UnknownVersion(other)),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WireCapability {
    FullFrameIntegrity,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiatedWire {
    version: WireVersion,
}

impl NegotiatedWire {
    pub const fn version(self) -> WireVersion {
        self.version
    }

    pub const fn capabilities(self) -> &'static [WireCapability] {
        self.version.capabilities()
    }

    pub fn ensure_version(self, observed: u16) -> Result<(), NegotiationError> {
        if observed == self.version.as_u16() {
            Ok(())
        } else {
            Err(NegotiationError::VersionMismatch {
                expected: self.version,
                observed,
            })
        }
    }
}

/// Select the highest explicitly common version satisfying every required
/// capability. Requiring full-frame integrity prevents silent downgrade to V1.
pub fn negotiate(
    local_versions: &[WireVersion],
    remote_versions: &[WireVersion],
    required_capabilities: &[WireCapability],
) -> Result<NegotiatedWire, NegotiationError> {
    let mut saw_common = false;
    for candidate in [WireVersion::V2, WireVersion::V1] {
        if !local_versions.contains(&candidate) || !remote_versions.contains(&candidate) {
            continue;
        }
        saw_common = true;
        if required_capabilities
            .iter()
            .all(|capability| candidate.supports(*capability))
        {
            return Ok(NegotiatedWire { version: candidate });
        }
    }

    if saw_common {
        Err(NegotiationError::RequiredCapabilitiesUnavailable)
    } else {
        Err(NegotiationError::NoCommonVersion)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    UnknownVersion(u16),
    NoCommonVersion,
    RequiredCapabilitiesUnavailable,
    VersionMismatch {
        expected: WireVersion,
        observed: u16,
    },
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownVersion(version) => write!(formatter, "unknown wire version {version}"),
            Self::NoCommonVersion => formatter.write_str("no common wire version"),
            Self::RequiredCapabilitiesUnavailable => {
                formatter.write_str("no common wire version satisfies required capabilities")
            }
            Self::VersionMismatch { expected, observed } => {
                write!(
                    formatter,
                    "negotiated wire version {} but observed {observed}",
                    expected.as_u16()
                )
            }
        }
    }
}

impl Error for NegotiationError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn highest_common_version_is_selected() {
        let negotiated = negotiate(
            &[WireVersion::V1, WireVersion::V2],
            &[WireVersion::V2, WireVersion::V1],
            &[],
        )
        .expect("negotiate");
        assert_eq!(negotiated.version(), WireVersion::V2);
    }

    #[test]
    fn integrity_requirement_prevents_v1_downgrade() {
        assert_eq!(
            negotiate(
                &[WireVersion::V1, WireVersion::V2],
                &[WireVersion::V1],
                &[WireCapability::FullFrameIntegrity],
            ),
            Err(NegotiationError::RequiredCapabilitiesUnavailable)
        );
    }

    #[test]
    fn no_common_version_fails_closed() {
        assert_eq!(
            negotiate(&[WireVersion::V2], &[WireVersion::V1], &[]),
            Err(NegotiationError::NoCommonVersion)
        );
    }

    #[test]
    fn negotiated_version_rejects_session_downgrade() {
        let negotiated = negotiate(
            &[WireVersion::V1, WireVersion::V2],
            &[WireVersion::V1, WireVersion::V2],
            &[WireCapability::FullFrameIntegrity],
        )
        .expect("negotiate");
        assert_eq!(
            negotiated.ensure_version(WireVersion::V1.as_u16()),
            Err(NegotiationError::VersionMismatch {
                expected: WireVersion::V2,
                observed: 1,
            })
        );
    }
}
