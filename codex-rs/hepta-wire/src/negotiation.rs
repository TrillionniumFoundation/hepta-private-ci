use std::error::Error;
use std::fmt;

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

    pub const fn supports(self, feature: WireFeature) -> bool {
        match feature {
            WireFeature::CompleteFrameDigest => matches!(self, Self::V2),
        }
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

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum WireFeature {
    CompleteFrameDigest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireOffer {
    versions: Vec<WireVersion>,
    features: Vec<WireFeature>,
}

impl WireOffer {
    pub fn new(
        mut versions: Vec<WireVersion>,
        mut features: Vec<WireFeature>,
    ) -> Result<Self, NegotiationError> {
        if versions.is_empty() {
            return Err(NegotiationError::EmptyOffer);
        }
        versions.sort_unstable();
        versions.dedup();
        features.sort_unstable();
        features.dedup();
        Ok(Self { versions, features })
    }

    pub fn hpta_supported() -> Self {
        Self {
            versions: vec![WireVersion::V1, WireVersion::V2],
            features: vec![WireFeature::CompleteFrameDigest],
        }
    }

    pub fn versions(&self) -> &[WireVersion] {
        &self.versions
    }

    pub fn features(&self) -> &[WireFeature] {
        &self.features
    }

    fn has_version(&self, version: WireVersion) -> bool {
        self.versions.binary_search(&version).is_ok()
    }

    fn has_feature(&self, feature: WireFeature) -> bool {
        self.features.binary_search(&feature).is_ok()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiationPolicy {
    minimum_version: WireVersion,
    required_features: Vec<WireFeature>,
}

impl NegotiationPolicy {
    pub fn new(
        minimum_version: WireVersion,
        mut required_features: Vec<WireFeature>,
    ) -> Self {
        required_features.sort_unstable();
        required_features.dedup();
        Self {
            minimum_version,
            required_features,
        }
    }

    pub fn v1_compatible() -> Self {
        Self::new(WireVersion::V1, Vec::new())
    }

    pub fn require_complete_frame_digest() -> Self {
        Self::new(
            WireVersion::V2,
            vec![WireFeature::CompleteFrameDigest],
        )
    }

    pub const fn minimum_version(&self) -> WireVersion {
        self.minimum_version
    }

    pub fn required_features(&self) -> &[WireFeature] {
        &self.required_features
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiatedWire {
    version: WireVersion,
}

impl NegotiatedWire {
    pub const fn version(self) -> WireVersion {
        self.version
    }
}

pub fn negotiate(
    local: &WireOffer,
    remote: &WireOffer,
    policy: &NegotiationPolicy,
) -> Result<NegotiatedWire, NegotiationError> {
    for feature in &policy.required_features {
        if !local.has_feature(*feature) || !remote.has_feature(*feature) {
            return Err(NegotiationError::RequiredFeatureUnavailable(*feature));
        }
    }

    for version in [WireVersion::V2, WireVersion::V1] {
        if version < policy.minimum_version
            || !local.has_version(version)
            || !remote.has_version(version)
        {
            continue;
        }
        if policy
            .required_features
            .iter()
            .all(|feature| version.supports(*feature))
        {
            return Ok(NegotiatedWire { version });
        }
    }

    Err(NegotiationError::NoCompatibleVersion)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    EmptyOffer,
    UnknownVersion(u16),
    RequiredFeatureUnavailable(WireFeature),
    NoCompatibleVersion,
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyOffer => formatter.write_str("wire version offer is empty"),
            Self::UnknownVersion(version) => write!(formatter, "unknown wire version {version}"),
            Self::RequiredFeatureUnavailable(feature) => {
                write!(formatter, "required wire feature is unavailable: {feature:?}")
            }
            Self::NoCompatibleVersion => {
                formatter.write_str("no compatible wire version satisfies policy")
            }
        }
    }
}

impl Error for NegotiationError {}
