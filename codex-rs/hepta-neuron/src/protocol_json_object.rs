//! Require named JSON object fields while retaining Serde's duplicate/unknown checks.
//!
//! Deriving `Deserialize` for a struct also accepts positional arrays. Registered
//! neuron records and nested profiles use objects; only their vector fields use
//! arrays. Forward the original map directly so duplicate keys cannot be erased
//! by an intermediate `serde_json::Value`.

use std::fmt;
use std::marker::PhantomData;

use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::Visitor;
use serde::de::value::MapAccessDeserializer;

pub(super) fn deserialize<'de, T, D>(deserializer: D) -> Result<T, D::Error>
where
    T: Deserialize<'de>,
    D: Deserializer<'de>,
{
    struct Object<T>(PhantomData<T>);

    impl<'de, T: Deserialize<'de>> Visitor<'de> for Object<T> {
        type Value = T;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a JSON object with named fields")
        }

        fn visit_map<M: MapAccess<'de>>(self, map: M) -> Result<T, M::Error> {
            T::deserialize(MapAccessDeserializer::new(map))
        }
    }

    deserializer.deserialize_map(Object(PhantomData))
}
