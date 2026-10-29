//! Explicit versioned learning key/signature wire. Legacy hex stays classic;
//! PQ hex has a mandatory algorithm/version prefix and exact size bounds.
use super::*;
use codex_hepta_learning_ledger::LearningSignature as NativeSignature;
use codex_hepta_learning_ledger::LearningVerificationKey as NativeKey;

const PREFIX: &str = "ml-dsa-65-v2:";

#[derive(Debug)]
pub(crate) struct LearningKey(pub NativeKey);
#[derive(Debug)]
pub(crate) struct LearningSignature(pub NativeSignature);

impl<'de> Deserialize<'de> for LearningKey {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        let value = String::deserialize(decoder)?;
        let key = match value.strip_prefix(PREFIX) {
            Some(hex) => NativeKey::MlDsa65V2(
                parse_hex::<1974>(hex.to_owned())
                    .map_err(serde::de::Error::custom)?
                    .to_vec(),
            ),
            None => {
                NativeKey::ClassicalV1(parse_hex::<32>(value).map_err(serde::de::Error::custom)?)
            }
        };
        key.validate().map_err(serde::de::Error::custom)?;
        Ok(Self(key))
    }
}

impl Serialize for LearningKey {
    fn serialize<S: Serializer>(&self, encoder: S) -> Result<S::Ok, S::Error> {
        let encoded = match &self.0 {
            NativeKey::ClassicalV1(bytes) => hex(bytes),
            NativeKey::MlDsa65V2(bytes) => format!("{PREFIX}{}", hex(bytes)),
        };
        encoded.serialize(encoder)
    }
}

impl<'de> Deserialize<'de> for LearningSignature {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        let value = String::deserialize(decoder)?;
        Ok(Self(match value.strip_prefix(PREFIX) {
            Some(hex) => NativeSignature::MlDsa65V2(
                parse_hex::<3309>(hex.to_owned())
                    .map_err(serde::de::Error::custom)?
                    .to_vec(),
            ),
            None => NativeSignature::ClassicalV1(
                parse_hex::<64>(value)
                    .map_err(serde::de::Error::custom)?
                    .to_vec(),
            ),
        }))
    }
}

impl Serialize for LearningSignature {
    fn serialize<S: Serializer>(&self, encoder: S) -> Result<S::Ok, S::Error> {
        let encoded = match &self.0 {
            NativeSignature::ClassicalV1(bytes) => hex(bytes),
            NativeSignature::MlDsa65V2(bytes) => format!("{PREFIX}{}", hex(bytes)),
        };
        encoded.serialize(encoder)
    }
}

impl From<LearningKey> for NativeKey {
    fn from(value: LearningKey) -> Self {
        value.0
    }
}
impl From<NativeKey> for LearningKey {
    fn from(value: NativeKey) -> Self {
        Self(value)
    }
}
impl From<LearningSignature> for NativeSignature {
    fn from(value: LearningSignature) -> Self {
        value.0
    }
}
impl From<NativeSignature> for LearningSignature {
    fn from(value: NativeSignature) -> Self {
        Self(value)
    }
}

#[cfg(test)]
#[path = "cognitive_process_learning_auth_tests.rs"]
mod tests;
