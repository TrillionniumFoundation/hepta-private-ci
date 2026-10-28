//! YAML parsing for plugin manifests and imported frontmatter.
//!
//! Keep YAML 1.2 scalar resolution and explicit merge handling consistent across
//! consumers. The private visitor accepts arbitrary YAML mapping keys and keeps
//! application tags distinct from ordinary scalar values.

use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_saphyr::MergeKeyPolicy;
use serde_saphyr::NonFiniteFloatPolicy;
use serde_saphyr::Options;
use serde_saphyr::Tagged;
use std::collections::HashSet;
use std::fmt;

mod key;

pub use serde_saphyr::Error;

/// Ordered string keys and their ordinary scalar values. A missing value means
/// that the YAML node is null, a collection, or an application-tagged scalar.
pub type ScalarMapping = Vec<(String, Option<String>)>;

fn options() -> Options {
    let mut options = Options::default();
    options.strict_booleans = true;
    options.merge_keys = MergeKeyPolicy::AsOrdinary;
    options.non_finite_float_policy = NonFiniteFloatPolicy::PassThrough;
    options.ignore_binary_tag_for_string = true;
    options
}

/// Deserialize a typed YAML document using the shared compatibility options.
pub fn from_str<'de, T: Deserialize<'de>>(input: &'de str) -> Result<T, Error> {
    serde_saphyr::from_str_with_options(input, options())
}

/// Deserialize a UTF-8 YAML document using the same options as [`from_str`].
pub fn from_slice<'de, T: Deserialize<'de>>(input: &'de [u8]) -> Result<T, Error> {
    serde_saphyr::from_slice_with_options(input, options())
}

/// Validate a complete YAML value, including nested mappings and non-string keys.
pub fn validate(input: &str) -> Result<(), Error> {
    from_str::<Node>(input).map(|_| ())
}

/// Extract string-keyed scalar frontmatter while accepting other valid YAML.
/// Non-string keys are ignored; their values are still fully parsed. Root and
/// key tags are transparent, as in the previous Value accessors. Application
/// tags on values are retained as non-scalar values, rather than silently lost.
pub fn scalar_mapping(input: &str) -> Result<Option<ScalarMapping>, Error> {
    let root: Node = from_str(input)?;
    let Kind::Mapping(entries) = root.kind else {
        return Ok(None);
    };
    let fields = entries
        .into_iter()
        .filter_map(|(key, value)| {
            let Kind::String(key) = key.kind else {
                return None;
            };
            let scalar = if value.application_tag.is_some() {
                None
            } else {
                match value.kind {
                    Kind::String(text) => Some(text.trim().to_string()),
                    Kind::Scalar(text) => Some(text),
                    Kind::Mapping(_) | Kind::Sequence(_) | Kind::Null => None,
                }
            };
            Some((key, scalar))
        })
        .collect();
    Ok(Some(fields))
}

struct Node {
    kind: Kind,
    application_tag: Option<String>,
}

enum Kind {
    String(String),
    Scalar(String),
    Mapping(Vec<(Node, Node)>),
    Sequence(Vec<Node>),
    Null,
}

impl<'de> Deserialize<'de> for Node {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let Tagged(kind, tag) = Tagged::<Kind>::deserialize(deserializer)?;
        let ordinary_tag = matches!(
            tag.as_deref(),
            None | Some(
                "!"
                    | "tag:yaml.org,2002:str"
                    | "tag:yaml.org,2002:bool"
                    | "tag:yaml.org,2002:int"
                    | "tag:yaml.org,2002:float"
                    | "tag:yaml.org,2002:null"
                    | "tag:yaml.org,2002:seq"
                    | "tag:yaml.org,2002:map"
                    | "tag:yaml.org,2002:binary"
            )
        );
        Ok(Self {
            kind,
            application_tag: if ordinary_tag { None } else { tag },
        })
    }
}

impl<'de> Deserialize<'de> for Kind {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(NodeVisitor)
    }
}

struct NodeVisitor;

impl<'de> Visitor<'de> for NodeVisitor {
    type Value = Kind;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a YAML value")
    }

    fn visit_unit<E>(self) -> Result<Kind, E> {
        Ok(Kind::Null)
    }

    fn visit_none<E>(self) -> Result<Kind, E> {
        Ok(Kind::Null)
    }

    fn visit_bool<E>(self, value: bool) -> Result<Kind, E> {
        Ok(Kind::Scalar(value.to_string()))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Kind, E> {
        Ok(Kind::Scalar(value.to_string()))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Kind, E> {
        Ok(Kind::Scalar(value.to_string()))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Kind, E> {
        let text = if value.is_nan() {
            ".nan".to_string()
        } else if value == f64::INFINITY {
            ".inf".to_string()
        } else if value == f64::NEG_INFINITY {
            "-.inf".to_string()
        } else {
            ryu::Buffer::new().format_finite(value).to_string()
        };
        Ok(Kind::Scalar(text))
    }

    fn visit_str<E>(self, value: &str) -> Result<Kind, E> {
        Ok(Kind::String(value.to_string()))
    }

    fn visit_string<E>(self, value: String) -> Result<Kind, E> {
        Ok(Kind::String(value))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Kind, A::Error> {
        let mut entries = Vec::new();
        while let Some(entry) = sequence.next_element::<Node>()? {
            entries.push(entry);
        }
        Ok(Kind::Sequence(entries))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut mapping: A) -> Result<Kind, A::Error> {
        let mut entries = Vec::new();
        let mut keys = HashSet::new();
        while let Some((key, value)) = mapping.next_entry::<Node, Node>()? {
            if !keys.insert(key.identity()) {
                return Err(serde::de::Error::custom("duplicate YAML mapping key"));
            }
            entries.push((key, value));
        }
        Ok(Kind::Mapping(entries))
    }
}

#[cfg(test)]
#[path = "yaml_tests.rs"]
mod tests;
