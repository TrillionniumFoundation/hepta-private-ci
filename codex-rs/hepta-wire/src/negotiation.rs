use std::error::Error;
use std::fmt;

const MAX_NEGOTIATION_ITEMS: usize = 16;

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
            WireFeature::FullFrameDigest => matches!(self, Self::V2),
            WireFeature::SchemaAdmission | WireFeature::TypedPayload => true,
        }
    }
}

impl TryFrom<u16> for WireVersion {
    type Error = NegotiationError;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::V1),
            2 => Ok(Self::V2),
            other => Err(NegotiationError::UnsupportedVersion(other)),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum WireFeature {
    FullFrameDigest,
    SchemaAdmission,
    TypedPayload,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireOffer {
    versions: Vec<WireVersion>,
    supported_features: Vec<WireFeature>,
    required_features: Vec<WireFeature>,
}

impl WireOffer {
    pub fn new(
        versions: &[WireVersion],
        supported_features: &[WireFeature],
        required_features: &[WireFeature],
    ) -> Result<Self, NegotiationError> {
        let versions = bounded_unique(versions, false)?;
        let supported_features = bounded_unique(supported_features, true)?;
        let required_features = bounded_unique(required_features, true)?;
        for feature in &required_features {
            if !supported_features.contains(feature) {
                return Err(NegotiationError::RequiredFeatureNotAdvertised(*feature));
            }
        }
        Ok(Self {
            versions,
            supported_features,
            required_features,
        })
    }

    pub fn versions(&self) -> &[WireVersion] {
        &self.versions
    }

    pub fn supported_features(&self) -> &[WireFeature] {
        &self.supported_features
    }

    pub fn required_features(&self) -> &[WireFeature] {
        &self.required_features
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiatedWire {
    version: WireVersion,
    features: Vec<WireFeature>,
}

impl NegotiatedWire {
    pub const fn version(&self) -> WireVersion {
        self.version
    }

    pub fn features(&self) -> &[WireFeature] {
        &self.features
    }
}

pub fn negotiate(
    local: &WireOffer,
    remote: &WireOffer,
) -> Result<NegotiatedWire, NegotiationError> {
    let mut required = local.required_features.clone();
    for feature in &remote.required_features {
        if !required.contains(feature) {
            required.push(*feature);
        }
    }
    required.sort_unstable();

    for feature in &required {
        if !local.supported_features.contains(feature)
            || !remote.supported_features.contains(feature)
        {
            return Err(NegotiationError::RequiredFeatureUnavailable(*feature));
        }
    }

    let version = local
        .versions
        .iter()
        .rev()
        .copied()
        .find(|candidate| {
            remote.versions.contains(candidate)
                && required.iter().all(|feature| candidate.supports(*feature))
        })
        .ok_or(NegotiationError::NoCompatibleVersion)?;

    let features = local
        .supported_features
        .iter()
        .copied()
        .filter(|feature| {
            remote.supported_features.contains(feature) && version.supports(*feature)
        })
        .collect();

    Ok(NegotiatedWire { version, features })
}

fn bounded_unique<T: Copy + Ord>(
    values: &[T],
    allow_empty: bool,
) -> Result<Vec<T>, NegotiationError> {
    if values.len() > MAX_NEGOTIATION_ITEMS || (!allow_empty && values.is_empty()) {
        return Err(NegotiationError::OfferBounds);
    }
    let mut result = values.to_vec();
    result.sort_unstable();
    result.dedup();
    if result.len() != values.len() {
        return Err(NegotiationError::DuplicateOfferItem);
    }
    Ok(result)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NegotiationError {
    OfferBounds,
    DuplicateOfferItem,
    UnsupportedVersion(u16),
    RequiredFeatureNotAdvertised(WireFeature),
    RequiredFeatureUnavailable(WireFeature),
    NoCompatibleVersion,
}

impl fmt::Display for NegotiationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NegotiationError {}

#[cfg(test)]
#[path = "negotiation_tests.rs"]
mod tests;
