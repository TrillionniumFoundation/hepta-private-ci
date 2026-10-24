//! Feature-local persistence codecs for authority-free validated primitives.
//!
//! Shared hepta-types deliberately has no serde contract. These private codecs
//! reuse its original constructors and canonical digest parser; decoding a
//! typed DTO does not replace the TaskFlow owner's scope/lease/frame checks.

pub(crate) mod stable_id {
    use codex_hepta_types::IdProfileV1;
    use codex_hepta_types::StableId;

    pub(crate) fn serialize<S>(value: &StableId, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(value.as_str())
    }

    pub(crate) fn deserialize<'de, D>(deserializer: D) -> Result<StableId, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        struct ValidatedId;
        impl<'de> serde::de::Visitor<'de> for ValidatedId {
            type Value = StableId;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a bounded identifier in the existing Stable V1 grammar")
            }

            fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
            where
                E: serde::de::Error,
            {
                StableId::with_profile(value, IdProfileV1::Stable).map_err(E::custom)
            }
        }
        deserializer.deserialize_str(ValidatedId)
    }
}

pub(crate) mod generation {
    use codex_hepta_types::Generation;
    use serde::Deserialize;

    #[expect(
        clippy::trivially_copy_pass_by_ref,
        reason = "Serde serialize_with requires a shared reference to the field"
    )]
    pub(crate) fn serialize<S>(value: &Generation, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_u64(value.get())
    }

    pub(crate) fn deserialize<'de, D>(deserializer: D) -> Result<Generation, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        Generation::new(u64::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

pub(crate) mod digest {
    use codex_hepta_types::Digest32;

    pub(crate) fn serialize<S>(value: &Digest32, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.collect_str(value)
    }

    pub(crate) fn deserialize<'de, D>(deserializer: D) -> Result<Digest32, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        struct CanonicalDigest;
        impl<'de> serde::de::Visitor<'de> for CanonicalDigest {
            type Value = Digest32;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("exactly 64 lowercase hexadecimal digest characters")
            }

            fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
            where
                E: serde::de::Error,
            {
                value.parse::<Digest32>().map_err(E::custom)
            }
        }
        deserializer.deserialize_str(CanonicalDigest)
    }
}
