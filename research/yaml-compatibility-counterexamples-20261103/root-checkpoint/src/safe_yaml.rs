use std::fmt;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
pub use serde_saphyr::Error;

pub fn from_str<'de, T: Deserialize<'de>>(input: &'de str) -> Result<T, Error> {
    serde_saphyr::from_str_with_options(input, options())
}

pub fn from_slice<'de, T: Deserialize<'de>>(input: &'de [u8]) -> Result<T, Error> {
    serde_saphyr::from_slice_with_options(input, options())
}

fn options() -> serde_saphyr::Options {
    serde_saphyr::options! {
        merge_keys: serde_saphyr::options::MergeKeyPolicy::AsOrdinary,
        strict_booleans: true,
        reject_non_finite_typeless_float: false,
    }
}

#[derive(Debug)]
pub enum Value {
    Null,
    Bool(bool),
    Number(String),
    String(String),
    Sequence(Vec<Value>),
    Mapping(Vec<(Value, Value)>),
    Tagged(Box<TaggedValue>),
}

#[derive(Debug)]
pub struct TaggedValue {
    pub tag: String,
    pub value: Value,
}

impl Value {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_mapping(&self) -> Option<&Vec<(Self, Self)>> {
        match self {
            Self::Mapping(value) => Some(value),
            _ => None,
        }
    }
}

impl<'de> Deserialize<'de> for Value {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let serde_saphyr::Tagged(RawValue(value), tag) =
            serde_saphyr::Tagged::<RawValue>::deserialize(deserializer)?;
        match tag {
            Some(tag) if !is_core_tag(&tag) => Ok(Self::Tagged(Box::new(TaggedValue { tag, value }))),
            _ => Ok(value),
        }
    }
}

fn is_core_tag(tag: &str) -> bool {
    matches!(
        tag,
        "tag:yaml.org,2002:null"
            | "tag:yaml.org,2002:bool"
            | "tag:yaml.org,2002:int"
            | "tag:yaml.org,2002:float"
            | "tag:yaml.org,2002:str"
            | "tag:yaml.org,2002:seq"
            | "tag:yaml.org,2002:map"
    )
}

struct RawValue(Value);

impl<'de> Deserialize<'de> for RawValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(ValueVisitor).map(Self)
    }
}

struct ValueVisitor;

impl<'de> Visitor<'de> for ValueVisitor {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a YAML value")
    }

    fn visit_unit<E: serde::de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_none<E: serde::de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(value.to_string()))
    }

    fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(value.to_string()))
    }

    fn visit_f64<E: serde::de::Error>(self, value: f64) -> Result<Value, E> {
        let number = if value.is_nan() {
            ".nan".to_owned()
        } else if value.is_infinite() {
            if value.is_sign_negative() { "-.inf" } else { ".inf" }.to_owned()
        } else {
            ryu::Buffer::new().format_finite(value).to_owned()
        };
        Ok(Value::Number(number))
    }

    fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E: serde::de::Error>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element()? {
            values.push(value);
        }
        Ok(Value::Sequence(values))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut mapping: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(entry) = mapping.next_entry()? {
            values.push(entry);
        }
        Ok(Value::Mapping(values))
    }
}
