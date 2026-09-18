use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::BoundedValueError;

/// Stable, bounded identifier suitable for content and protocol records.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct StableId(BoundedText<128>);

impl StableId {
    pub fn new(value: impl Into<String>) -> Result<Self, IdentityError> {
        let value = value.into();
        let value = BoundedText::new(value).map_err(IdentityError::Bounded)?;
        validate_stable_id(value.as_str())?;
        Ok(Self(value))
    }

    /// Validate a borrowed identifier before allocating its bounded owned form.
    pub fn parse(value: &str) -> Result<Self, IdentityError> {
        validate_stable_id(value)?;
        let value = BoundedText::try_from_str(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

fn validate_stable_id(value: &str) -> Result<(), IdentityError> {
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err(IdentityError::InvalidCharacter);
    }
    Ok(())
}

impl fmt::Display for StableId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdProfileV1 {
    Stable,
    Execution,
    Schema,
    Receipt,
    Artifact,
    Normalization,
}

impl IdProfileV1 {
    pub const fn namespace(self) -> Option<&'static str> {
        match self {
            Self::Stable => None,
            Self::Execution => Some("execution:"),
            Self::Schema => Some("schema:"),
            Self::Receipt => Some("receipt:"),
            Self::Artifact => Some("artifact:"),
            Self::Normalization => Some("normalization:"),
        }
    }
}

/// Validate the StableId grammar plus the selected semantic namespace.
///
/// This path accepts borrowed input so callers can reject overlong or malformed
/// identifiers before allocating a second unrestricted copy.
pub fn validate_id(raw: &str, profile: IdProfileV1) -> Result<StableId, IdentityError> {
    let id = StableId::parse(raw)?;
    if let Some(namespace) = profile.namespace() {
        let suffix = raw
            .strip_prefix(namespace)
            .ok_or(IdentityError::NamespaceMismatch)?;
        if suffix.is_empty() {
            return Err(IdentityError::NamespaceMismatch);
        }
    }
    Ok(id)
}

macro_rules! monotonic_identity {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
        pub struct $name(u64);

        impl $name {
            pub fn new(value: u64) -> Result<Self, IdentityError> {
                if value == 0 {
                    return Err(IdentityError::Zero);
                }
                Ok(Self(value))
            }

            pub const fn get(self) -> u64 {
                self.0
            }

            pub fn next(self) -> Result<Self, IdentityError> {
                self.0
                    .checked_add(1)
                    .map(Self)
                    .ok_or(IdentityError::Overflow)
            }
        }
    };
}

monotonic_identity!(Generation);
monotonic_identity!(Revision);
monotonic_identity!(LogicalSequence);

/// Explicit all-negative posture embedded in qualification-only artifacts.
///
/// Fields are private so downstream callers cannot construct an authority-bearing
/// posture. The only public value is DENY_ALL.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityPosture {
    runtime: bool,
    production_writer: bool,
    model_invocation: bool,
    provider_dispatch: bool,
    external_effect: bool,
    selection: bool,
    promotion: bool,
    release: bool,
}

impl AuthorityPosture {
    pub const DENY_ALL: Self = Self {
        runtime: false,
        production_writer: false,
        model_invocation: false,
        provider_dispatch: false,
        external_effect: false,
        selection: false,
        promotion: false,
        release: false,
    };

    pub const fn grants_any(self) -> bool {
        self.runtime
            || self.production_writer
            || self.model_invocation
            || self.provider_dispatch
            || self.external_effect
            || self.selection
            || self.promotion
            || self.release
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdentityError {
    Bounded(BoundedValueError),
    InvalidCharacter,
    NamespaceMismatch,
    Zero,
    Overflow,
}

impl fmt::Display for IdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Bounded(error) => error.fmt(formatter),
            Self::InvalidCharacter => {
                formatter.write_str("identifier contains an invalid character")
            }
            Self::NamespaceMismatch => {
                formatter.write_str("identifier does not match the required namespace")
            }
            Self::Zero => formatter.write_str("monotonic identity must be non-zero"),
            Self::Overflow => formatter.write_str("monotonic identity overflow"),
        }
    }
}

impl Error for IdentityError {}

#[cfg(test)]
#[path = "identity_tests.rs"]
mod tests;
