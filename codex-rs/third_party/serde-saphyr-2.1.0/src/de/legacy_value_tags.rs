//! Present only actual local tags through Serde's EnumAccess protocol.
// No node is copied, stripped, replayed or charged again here. Untagged nodes
// take the ordinary deserialize_any path, avoiding a virtual Tagged sequence
// and its recursive frames at every container depth.
use super::Error;
use super::deserializer::YamlDeserializer;
use super::events::Ev;
use granit_parser::ScalarStyle;
use serde_core::de::IntoDeserializer;
use serde_core::de::Visitor;
use serde_core::de::{self};

pub(super) fn visit<'de, V: Visitor<'de>>(
    mut de: YamlDeserializer<'de, '_>,
    tag: String,
    visitor: V,
) -> Result<V::Value, Error> {
    // This marker belongs to this one node. Child deserializers start false.
    // The raw event, including its tag, stays intact for alias retention and
    // budget accounting; scalar resolution still sees the original tag.
    de.legacy_value_tag_consumed = true;
    visitor.visit_enum(LocalTag { de, tag })
}

struct LocalTag<'de, 'e> {
    de: YamlDeserializer<'de, 'e>,
    tag: String,
}
impl<'de, 'e> de::EnumAccess<'de> for LocalTag<'de, 'e> {
    type Error = Error;
    type Variant = LocalValue<'de, 'e>;
    fn variant_seed<V: de::DeserializeSeed<'de>>(
        self,
        seed: V,
    ) -> Result<(V::Value, Self::Variant), Error> {
        Ok((
            seed.deserialize(self.tag.into_deserializer())?,
            LocalValue(self.de),
        ))
    }
}
struct LocalValue<'de, 'e>(YamlDeserializer<'de, 'e>);
impl<'de> de::VariantAccess<'de> for LocalValue<'de, '_> {
    type Error = Error;
    fn newtype_variant_seed<T: de::DeserializeSeed<'de>>(self, seed: T) -> Result<T::Value, Error> {
        seed.deserialize(self.0)
    }
    fn unit_variant(self) -> Result<(), Error> {
        // A unit enum tag accepts only a plain null payload, as the legacy
        // deserializer did after consuming the tag. Quoted null stays text.
        let is_null = match self.0.ev.peek()? {
            Some(Ev::Scalar {
                value,
                style: ScalarStyle::Plain,
                ..
            }) => value.is_empty() || matches!(value.as_ref(), "null" | "Null" | "NULL" | "~"),
            None => true,
            _ => false,
        };
        if is_null {
            let _ = self.0.ev.next()?;
            Ok(())
        } else {
            Err(Error::unexpected("null payload for a legacy unit enum")
                .with_location(self.0.ev.last_location()))
        }
    }
    fn tuple_variant<V: Visitor<'de>>(self, _len: usize, _visitor: V) -> Result<V::Value, Error> {
        Err(Error::msg(
            "a legacy YAML local tag carries a newtype value",
        ))
    }
    fn struct_variant<V: Visitor<'de>>(
        self,
        _fields: &'static [&'static str],
        _visitor: V,
    ) -> Result<V::Value, Error> {
        Err(Error::msg(
            "a legacy YAML local tag carries a newtype value",
        ))
    }
}
