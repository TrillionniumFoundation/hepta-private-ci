//! Semantic key identity for YAML's scalar and composite mapping keys.

use crate::Kind;
use crate::Node;

#[derive(Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(super) enum Key {
    String(String),
    Scalar(String),
    Null,
    Sequence(Vec<Key>),
    Mapping(Vec<(Key, Key)>),
    Tagged(String, Box<Key>),
}

impl Node {
    pub(super) fn identity(&self) -> Key {
        let identity = match &self.kind {
            Kind::String(value) => Key::String(value.clone()),
            // Floating zero signs compare equal in the previous YAML Number.
            // Keep their original spelling for display, normalize only identity.
            Kind::Scalar(value) => Key::Scalar(if value == "-0.0" {
                "0.0".to_string()
            } else {
                value.clone()
            }),
            Kind::Null => Key::Null,
            Kind::Sequence(values) => Key::Sequence(values.iter().map(Node::identity).collect()),
            Kind::Mapping(entries) => {
                let mut values: Vec<_> = entries
                    .iter()
                    .map(|(key, value)| (key.identity(), value.identity()))
                    .collect();
                values.sort_unstable();
                Key::Mapping(values)
            }
        };
        match &self.application_tag {
            Some(tag) => Key::Tagged(tag.clone(), Box::new(identity)),
            None => identity,
        }
    }
}
