use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::BoundedValueError;

/// Stable, bounded identifier suitable for content and protocol records.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct StableId(BoundedText<128>);

impl StableId {
    pub const MAX_BYTES: usize = 128;

    pub fn new(value: impl Into<String>) -> Result<Self, IdentityError> {
        let value = value.into();
        validate_stable_id(&value)?;
        let value = BoundedText::new(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    /// Validates a borrowed identifier before allocating its one owned copy.
    pub fn parse(value: &str) -> Result<Self, IdentityError> {
        validate_stable_id(value)?;
        let value = BoundedText::copy_from_str(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

impl fmt::Display for StableId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

fn validate_stable_id(value: &str) -> Result<(), IdentityError> {
    if value.is_empty() {
        return Err(IdentityError::Bounded(BoundedValueError::Empty));
    }
    if value.len() > StableId::MAX_BYTES {
        return Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: value.len(),
            maximum: StableId::MAX_BYTES,
        }));
    }
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err(IdentityError::InvalidCharacter);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum IdNamespaceV1 {
    Execution,
    Schema,
    Receipt,
    Artifact,
    Producer,
    Normalization,
}

impl IdNamespaceV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Execution => "execution",
            Self::Schema => "schema",
            Self::Receipt => "receipt",
            Self::Artifact => "artifact",
            Self::Producer => "producer",
            Self::Normalization => "normalization",
        }
    }
}

/// Closed identifier profile. A profile binds one namespace and forbids nested
/// namespace separators in the local component.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IdProfileV1 {
    namespace: IdNamespaceV1,
}

impl IdProfileV1 {
    pub const EXECUTION: Self = Self::new(IdNamespaceV1::Execution);
    pub const SCHEMA: Self = Self::new(IdNamespaceV1::Schema);
    pub const RECEIPT: Self = Self::new(IdNamespaceV1::Receipt);
    pub const ARTIFACT: Self = Self::new(IdNamespaceV1::Artifact);
    pub const PRODUCER: Self = Self::new(IdNamespaceV1::Producer);
    pub const NORMALIZATION: Self = Self::new(IdNamespaceV1::Normalization);

    const fn new(namespace: IdNamespaceV1) -> Self {
        Self { namespace }
    }

    pub const fn namespace(self) -> IdNamespaceV1 {
        self.namespace
    }

    pub fn validate(self, raw: &str) -> Result<StableId, IdentityError> {
        validate_id(raw, self)
    }
}

/// Validates a namespaced V1 identifier without normalizing it. Borrowed input
/// is checked before the bounded owned StableId is created.
pub fn validate_id(raw: &str, profile: IdProfileV1) -> Result<StableId, IdentityError> {
    if raw.is_empty() {
        return Err(IdentityError::Bounded(BoundedValueError::Empty));
    }
    if raw.len() > StableId::MAX_BYTES {
        return Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: raw.len(),
            maximum: StableId::MAX_BYTES,
        }));
    }

    let namespace = profile.namespace().as_str();
    let Some(local) = raw
        .strip_prefix(namespace)
        .and_then(|remainder| remainder.strip_prefix(':'))
    else {
        return Err(IdentityError::NamespaceMismatch);
    };
    if local.is_empty() {
        return Err(IdentityError::MissingLocalPart);
    }
    if !local
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(IdentityError::InvalidCharacter);
    }
    StableId::new(raw.to_owned())
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DenyAllAuthorityMarker;

/// Authority posture carried by qualification-only artifacts. V1 has exactly
/// one representable value: deny-all. Untrusted encodings with any authority
/// bit set are rejected before this type can be constructed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityPosture {
    marker: DenyAllAuthorityMarker,
}

impl AuthorityPosture {
    pub const DENY_ALL: Self = Self {
        marker: DenyAllAuthorityMarker,
    };

    pub const fn from_untrusted_bits(bits: u8) -> Result<Self, AuthorityPostureError> {
        if bits == 0 {
            Ok(Self::DENY_ALL)
        } else {
            Err(AuthorityPostureError::GrantedBits(bits))
        }
    }

    pub const fn encoded_bits(self) -> u8 {
        0
    }

    pub const fn grants_any(self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityPostureError {
    GrantedBits(u8),
}

impl fmt::Display for AuthorityPostureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GrantedBits(bits) => {
                write!(formatter, "authority posture contains granted bits: {bits:#04x}")
            }
        }
    }
}

impl Error for AuthorityPostureError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdentityError {
    Bounded(BoundedValueError),
    InvalidCharacter,
    NamespaceMismatch,
    MissingLocalPart,
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
            Self::NamespaceMismatch => formatter.write_str("identifier namespace does not match"),
            Self::MissingLocalPart => formatter.write_str("identifier local component is empty"),
            Self::Zero => formatter.write_str("monotonic identity must be non-zero"),
            Self::Overflow => formatter.write_str("monotonic identity overflow"),
        }
    }
}

impl Error for IdentityError {}

#[cfg(test)]
#[path = "identity_tests.rs"]
mod tests;
