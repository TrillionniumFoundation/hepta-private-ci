//! Serde adapters with the legacy canonical UTC wire shape and parsing grammar.
//!
//! Unlike `CanonicalUtcTimestamp`, instant adapters reject leap seconds explicitly.
//! Optional adapters preserve `null`; add `#[serde(default)]` when absent fields are valid.

use ::serde::Deserialize;
use ::serde::Deserializer;
use ::serde::Serialize;
use ::serde::Serializer;

use crate::CanonicalUtcTimestamp;

impl Serialize for CanonicalUtcTimestamp {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.canonical_wire())
    }
}

impl<'de> Deserialize<'de> for CanonicalUtcTimestamp {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse_legacy(&value).map_err(::serde::de::Error::custom)
    }
}

pub mod rfc3339 {
    use ::serde::Deserialize;
    use ::serde::Deserializer;
    use ::serde::Serialize;
    use ::serde::Serializer;
    use time::OffsetDateTime;

    use crate::CanonicalUtcTimestamp;

    pub fn serialize<S>(value: &OffsetDateTime, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        CanonicalUtcTimestamp::from_instant(*value)
            .map_err(::serde::ser::Error::custom)?
            .serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<OffsetDateTime, D::Error>
    where
        D: Deserializer<'de>,
    {
        CanonicalUtcTimestamp::deserialize(deserializer)?
            .try_into_instant()
            .map_err(::serde::de::Error::custom)
    }
}

pub mod optional_rfc3339 {
    use ::serde::Deserialize;
    use ::serde::Deserializer;
    use ::serde::Serialize;
    use ::serde::Serializer;
    use time::OffsetDateTime;

    use crate::CanonicalUtcTimestamp;

    pub fn serialize<S>(value: &Option<OffsetDateTime>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        value
            .map(CanonicalUtcTimestamp::from_instant)
            .transpose()
            .map_err(::serde::ser::Error::custom)?
            .serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<OffsetDateTime>, D::Error>
    where
        D: Deserializer<'de>,
    {
        Option::<CanonicalUtcTimestamp>::deserialize(deserializer)?
            .map(CanonicalUtcTimestamp::try_into_instant)
            .transpose()
            .map_err(::serde::de::Error::custom)
    }
}
