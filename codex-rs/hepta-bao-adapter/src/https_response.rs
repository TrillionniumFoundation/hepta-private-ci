//! Bounded-body KV v2 decoding with unambiguous secret-field selection.

use std::collections::BTreeMap;
use std::collections::btree_map::Entry;
use std::fmt;

use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::Visitor;
use zeroize::Zeroizing;

#[derive(Deserialize)]
pub(super) struct KvResponse {
    pub(super) data: KvPayload,
}

#[derive(Deserialize)]
pub(super) struct KvPayload {
    #[serde(deserialize_with = "deserialize_secret_data")]
    pub(super) data: BTreeMap<String, Zeroizing<String>>,
    pub(super) metadata: KvMetadata,
}

#[derive(Deserialize)]
pub(super) struct KvMetadata {
    pub(super) version: u64,
}

fn deserialize_secret_data<'de, D>(
    deserializer: D,
) -> Result<BTreeMap<String, Zeroizing<String>>, D::Error>
where
    D: Deserializer<'de>,
{
    struct SecretDataVisitor;

    impl<'de> Visitor<'de> for SecretDataVisitor {
        type Value = BTreeMap<String, Zeroizing<String>>;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a KV secret object with unique string fields")
        }

        fn visit_map<A>(self, mut access: A) -> Result<Self::Value, A::Error>
        where
            A: MapAccess<'de>,
        {
            let mut data = BTreeMap::new();
            while let Some(key) = access.next_key::<String>()? {
                // Check decoded keys, including escaped aliases, before
                // accepting a duplicate value or replacing a secret.
                match data.entry(key) {
                    Entry::Occupied(_) => {
                        return Err(serde::de::Error::custom("duplicate KV secret field"));
                    }
                    Entry::Vacant(entry) => {
                        entry.insert(access.next_value::<Zeroizing<String>>()?);
                    }
                }
            }
            Ok(data)
        }
    }

    deserializer.deserialize_map(SecretDataVisitor)
}
