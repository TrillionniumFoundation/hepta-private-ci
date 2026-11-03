//! Experimental adapter for the four legacy consumers, not a production migration.
//! The parser, source decoding, aliases and resource budgets remain upstream.
use std::collections::hash_map::DefaultHasher;
use std::fmt;
use std::hash::{Hash, Hasher};
use indexmap::IndexMap;
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
pub use serde_saphyr::Error;

pub fn from_str<'de, T: Deserialize<'de>>(input: &'de str) -> Result<T, Error> {
    serde_saphyr::from_str_with_options(input, options())
}
pub fn from_slice<'de, T: Deserialize<'de>>(input: &'de [u8]) -> Result<T, Error> {
    serde_saphyr::from_slice_with_options(input, options())
}
fn options() -> serde_saphyr::Options {
    serde_saphyr::options! {
        merge_keys: serde_saphyr::MergeKeyPolicy::AsOrdinary,
        strict_booleans: true,
        duplicate_keys: serde_saphyr::DuplicateKeyPolicy::PassThrough,
        preserve_local_application_tags: true,
        legacy_string_semantics: true,
        legacy_serde_yaml_scalars: true,
        legacy_serde_yaml_node_tags: true,
        ignore_binary_tag_for_string: true,
    }
}

#[derive(Debug, Clone)]
pub enum Number { Unsigned(u64), Negative(i64), Float(f64) }
impl PartialEq for Number {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Unsigned(a), Self::Unsigned(b)) => a == b,
            (Self::Negative(a), Self::Negative(b)) => a == b,
            (Self::Float(a), Self::Float(b)) => a == b || (a.is_nan() && b.is_nan()),
            _ => false,
        }
    }
}
impl Eq for Number {}
impl Hash for Number {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::mem::discriminant(self).hash(state);
        match self {
            Self::Unsigned(v) => v.hash(state),
            Self::Negative(v) => v.hash(state),
            Self::Float(v) => {
                let bits = if v.is_nan() { f64::NAN.to_bits() } else if *v == 0.0 { 0 } else { v.to_bits() };
                bits.hash(state);
            }
        }
    }
}
impl fmt::Display for Number {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unsigned(v) => v.fmt(f),
            Self::Negative(v) => v.fmt(f),
            Self::Float(v) if v.is_nan() => f.write_str(".nan"),
            Self::Float(v) if v.is_infinite() => f.write_str(if v.is_sign_negative() { "-.inf" } else { ".inf" }),
            Self::Float(v) => f.write_str(ryu::Buffer::new().format_finite(*v)),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Tag(String);
fn unbang(tag: &str) -> &str {
    match tag.strip_prefix('!') { Some("") | None => tag, Some(rest) => rest }
}
impl PartialEq for Tag { fn eq(&self, other: &Self) -> bool { unbang(&self.0) == unbang(&other.0) } }
impl Eq for Tag {}
impl Hash for Tag { fn hash<H: Hasher>(&self, state: &mut H) { unbang(&self.0).hash(state); } }
impl fmt::Display for Tag { fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "!{}", unbang(&self.0)) } }

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Value {
    Null, Bool(bool), Number(Number), String(String), Sequence(Vec<Value>),
    Mapping(IndexMap<Value, Value>), Tagged(Box<TaggedValue>),
}
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct TaggedValue { pub tag: Tag, pub value: Value }
impl Hash for Value {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::mem::discriminant(self).hash(state);
        match self {
            Self::Null => {}, Self::Bool(v) => v.hash(state), Self::Number(v) => v.hash(state),
            Self::String(v) => v.hash(state), Self::Sequence(v) => v.hash(state), Self::Tagged(v) => v.hash(state),
            Self::Mapping(entries) => {
                // Mapping equality ignores insertion order, while iteration preserves it.
                let mut combined = 0;
                for (key, value) in entries {
                    let mut pair = DefaultHasher::new(); key.hash(&mut pair); value.hash(&mut pair);
                    combined ^= pair.finish();
                }
                combined.hash(state);
            }
        }
    }
}
impl Value {
    fn untag(&self) -> &Self {
        let mut value = self;
        while let Self::Tagged(tag) = value { value = &tag.value; }
        value
    }
    pub fn as_str(&self) -> Option<&str> { match self.untag() { Self::String(v) => Some(v), _ => None } }
    pub fn as_mapping(&self) -> Option<&IndexMap<Self, Self>> { match self.untag() { Self::Mapping(v) => Some(v), _ => None } }
}
impl<'de> Deserialize<'de> for Value {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(ValueVisitor)
    }
}
struct ValueVisitor;
impl<'de> Visitor<'de> for ValueVisitor {
    type Value = Value;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("a YAML value") }
    fn visit_enum<A: serde::de::EnumAccess<'de>>(self, access: A) -> Result<Value, A::Error> {
        use serde::de::VariantAccess;
        let (tag, value) = access.variant::<String>()?;
        let value = value.newtype_variant::<Value>()?;
        Ok(Value::Tagged(Box::new(TaggedValue { tag: Tag(unbang(&tag).to_owned()), value })))
    }
    fn visit_unit<E: serde::de::Error>(self) -> Result<Value, E> { Ok(Value::Null) }
    fn visit_none<E: serde::de::Error>(self) -> Result<Value, E> { Ok(Value::Null) }
    fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Value, E> { Ok(Value::Bool(v)) }
    fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Value, E> {
        Ok(Value::Number(if v < 0 { Number::Negative(v) } else { Number::Unsigned(v as u64) }))
    }
    fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Value, E> { Ok(Value::Number(Number::Unsigned(v))) }
    fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Value, E> { Ok(Value::Number(Number::Float(v))) }
    fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Value, E> { Ok(Value::String(v.to_owned())) }
    fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Value, E> { Ok(Value::String(v)) }
    fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut values = Vec::new(); while let Some(value) = access.next_element()? { values.push(value); }
        Ok(Value::Sequence(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut values = IndexMap::new();
        while let Some(key) = access.next_key()? {
            match values.entry(key) {
                indexmap::map::Entry::Occupied(_) => return Err(serde::de::Error::custom("duplicate entry in YAML map")),
                indexmap::map::Entry::Vacant(entry) => { entry.insert(access.next_value()?); }
            }
        }
        Ok(Value::Mapping(values))
    }
}
