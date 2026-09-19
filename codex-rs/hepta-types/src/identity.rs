use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::BoundedValueError;

const MAX_STABLE_ID_BYTES: usize = 128;

/// Versioned identifier profiles. `Stable` preserves the original V1 grammar;
/// stricter profiles make module and namespace semantics explicit.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdProfileV1 {
    Stable,
    Module,
    Namespaced,
}

impl IdProfileV1 {
    pub const fn id(self) -> &'static str {
        match self {
            Self::Stable => "stable-v1",
            Self::Module => "module-v1",
            Self::Namespaced => "namespaced-v1",
        }
    }

    pub fn from_id(id: &str) -> Result<Self, IdentityError> {
        match id {
            "stable-v1" => Ok(Self::Stable),
            "module-v1" => Ok(Self::Module),
            "namespaced-v1" => Ok(Self::Namespaced),
            _ => Err(IdentityError::UnknownProfile),
        }
    }
}

/// Stable, bounded identifier suitable for content and protocol records.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct StableId(BoundedText<MAX_STABLE_ID_BYTES>);

impl StableId {
    /// Backward-compatible constructor using the original stable V1 grammar.
    pub fn new(value: impl Into<String>) -> Result<Self, IdentityError> {
        let value = value.into();
        validate_id_profile_raw(&value, IdProfileV1::Stable)?;
        let value = BoundedText::new(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    /// Validates a borrowed identifier under an explicit profile before the
    /// single bounded allocation used to own the accepted value.
    pub fn with_profile(value: &str, profile: IdProfileV1) -> Result<Self, IdentityError> {
        validate_id(value, profile)
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

/// Validates a borrowed identifier under the named V1 grammar.
pub fn validate_id(raw: &str, profile: IdProfileV1) -> Result<StableId, IdentityError> {
    validate_id_profile_raw(raw, profile)?;
    let value = BoundedText::try_from_str(raw).map_err(IdentityError::Bounded)?;
    Ok(StableId(value))
}

pub(crate) fn validate_id_profile_raw(
    raw: &str,
    profile: IdProfileV1,
) -> Result<(), IdentityError> {
    validate_bound(raw)?;
    match profile {
        IdProfileV1::Stable => validate_stable(raw),
        IdProfileV1::Module => validate_module(raw),
        IdProfileV1::Namespaced => validate_namespaced(raw),
    }
}

fn validate_bound(raw: &str) -> Result<(), IdentityError> {
    if raw.is_empty() {
        return Err(IdentityError::Bounded(BoundedValueError::Empty));
    }
    if raw.len() > MAX_STABLE_ID_BYTES {
        return Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: raw.len(),
            maximum: MAX_STABLE_ID_BYTES,
        }));
    }
    if raw.contains('\0') {
        return Err(IdentityError::Bounded(BoundedValueError::Nul));
    }
    Ok(())
}

fn validate_stable(raw: &str) -> Result<(), IdentityError> {
    if raw
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        Ok(())
    } else {
        Err(IdentityError::InvalidCharacter)
    }
}

fn validate_module(raw: &str) -> Result<(), IdentityError> {
    if raw.bytes().any(|byte| {
        !(byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'.' | b'_' | b'-'))
    }) {
        return Err(IdentityError::InvalidCharacter);
    }
    for segment in raw.split('.') {
        let bytes = segment.as_bytes();
        if bytes.is_empty()
            || !bytes[0].is_ascii_alphanumeric()
            || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        {
            return Err(IdentityError::NonCanonical);
        }
    }
    Ok(())
}

fn validate_namespaced(raw: &str) -> Result<(), IdentityError> {
    let Some((namespace, local)) = raw.split_once(':') else {
        return Err(IdentityError::NonCanonical);
    };
    if local.contains(':') {
        return Err(IdentityError::NonCanonical);
    }
    validate_module(namespace)?;
    let bytes = local.as_bytes();
    if bytes.is_empty()
        || !bytes[0].is_ascii_alphanumeric()
        || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        || bytes.iter().any(|byte| {
            !(byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'.' | b'_' | b'-'))
        })
    {
        return Err(IdentityError::NonCanonical);
    }
    Ok(())
}

impl fmt::Display for StableId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Canonical module namespace used to construct namespaced identifiers.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct IdNamespaceV1(StableId);

impl IdNamespaceV1 {
    pub fn new(raw: &str) -> Result<Self, IdentityError> {
        validate_id(raw, IdProfileV1::Module).map(Self)
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    pub fn qualify(&self, local: &str) -> Result<StableId, IdentityError> {
        if local.contains(':') {
            return Err(IdentityError::NonCanonical);
        }
        let combined_len = self
            .as_str()
            .len()
            .checked_add(1)
            .and_then(|value| value.checked_add(local.len()))
            .ok_or(IdentityError::Overflow)?;
        if combined_len > MAX_STABLE_ID_BYTES {
            return Err(IdentityError::Bounded(BoundedValueError::TooLarge {
                actual: combined_len,
                maximum: MAX_STABLE_ID_BYTES,
            }));
        }
        let qualified = format!("{}:{local}", self.as_str());
        validate_id(&qualified, IdProfileV1::Namespaced)
    }
}

impl fmt::Display for IdNamespaceV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
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

/// Untrusted authority flags accepted only so decoders and tests can prove that
/// any attempted grant is rejected before an `AuthorityPosture` exists.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct AuthorityFlagsV1 {
    pub runtime: bool,
    pub production_writer: bool,
    pub model_invocation: bool,
    pub provider_dispatch: bool,
    pub external_effect: bool,
    pub selection: bool,
    pub promotion: bool,
    pub release: bool,
}

impl AuthorityFlagsV1 {
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

/// Authority-free posture. The representation is sealed so a granting posture
/// cannot be constructed in this foundational crate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityPosture {
    _deny_all: (),
}

impl AuthorityPosture {
    pub const DENY_ALL: Self = Self { _deny_all: () };

    pub const fn grants_any(self) -> bool {
        false
    }

    pub fn try_from_flags(flags: AuthorityFlagsV1) -> Result<Self, AuthorityPostureError> {
        if flags.grants_any() {
            return Err(AuthorityPostureError::GrantRequested);
        }
        Ok(Self::DENY_ALL)
    }

    pub const fn flags(self) -> AuthorityFlagsV1 {
        AuthorityFlagsV1 {
            runtime: false,
            production_writer: false,
            model_invocation: false,
            provider_dispatch: false,
            external_effect: false,
            selection: false,
            promotion: false,
            release: false,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityPostureError {
    GrantRequested,
}

impl fmt::Display for AuthorityPostureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("platform.types cannot construct a granting authority posture")
    }
}

impl Error for AuthorityPostureError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdentityError {
    Bounded(BoundedValueError),
    InvalidCharacter,
    NonCanonical,
    UnknownProfile,
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
            Self::NonCanonical => {
                formatter.write_str("identifier is not canonical for its profile")
            }
            Self::UnknownProfile => formatter.write_str("unknown identifier profile"),
            Self::Zero => formatter.write_str("monotonic identity must be non-zero"),
            Self::Overflow => formatter.write_str("monotonic identity overflow"),
        }
    }
}

impl Error for IdentityError {}

#[cfg(test)]
#[path = "identity_tests.rs"]
mod tests;
