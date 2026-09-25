use std::fmt;
use std::str::FromStr;

use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use serde::de::Error as _;

const AGENT_ID_LENGTH: usize = 36;
const UUID_HYPHEN_OFFSETS: [usize; 4] = [8, 13, 18, 23];

/// Stable identity for one independently supervised Hepta workspace agent.
///
/// The wire and directory representation is a canonical lowercase RFC 9562
/// UUID. Restricting the alphabet to lowercase hexadecimal digits and hyphens
/// makes the same value safe as one filesystem path component on every
/// supported platform.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AgentId(String);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentIdParseError {
    message: &'static str,
}

impl AgentIdParseError {
    fn new(message: &'static str) -> Self {
        Self { message }
    }
}

impl fmt::Display for AgentIdParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for AgentIdParseError {}

impl AgentId {
    pub fn parse(value: impl Into<String>) -> Result<Self, AgentIdParseError> {
        let value = value.into();
        let bytes = value.as_bytes();
        if bytes.len() != AGENT_ID_LENGTH {
            return Err(AgentIdParseError::new(
                "agent id must be a canonical 36-byte UUID",
            ));
        }

        for (offset, byte) in bytes.iter().copied().enumerate() {
            let hyphen_expected = UUID_HYPHEN_OFFSETS.contains(&offset);
            if (hyphen_expected && byte != b'-')
                || (!hyphen_expected && !matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
            {
                return Err(AgentIdParseError::new(
                    "agent id must be a canonical lowercase UUID",
                ));
            }
        }

        if !matches!(bytes[14], b'1'..=b'8') {
            return Err(AgentIdParseError::new(
                "agent id UUID must declare a supported version",
            ));
        }
        if !matches!(bytes[19], b'8'..=b'9' | b'a'..=b'b') {
            return Err(AgentIdParseError::new(
                "agent id UUID must use the RFC 9562 variant",
            ));
        }

        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for AgentId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for AgentId {
    type Err = AgentIdParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

impl Serialize for AgentId {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for AgentId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(D::Error::custom)
    }
}

#[cfg(test)]
#[path = "agent_id_tests.rs"]
mod tests;
