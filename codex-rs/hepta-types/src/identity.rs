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
    Execution,
    Schema,
    Normalization,
    Receipt,
    Artifact,
}

impl IdProfileV1 {
    pub const fn id(self) -> &'static str {
        match self {
            Self::Stable => "stable-v1",
            Self::Module => "module-v1",
            Self::Namespaced => "namespaced-v1",
            Self::Execution => "execution-id-v1",
            Self::Schema => "schema-id-v1",
            Self::Normalization => "normalization-id-v1",
            Self::Receipt => "receipt-id-v1",
            Self::Artifact => "artifact-id-v1",
        }
    }

    pub fn from_id(id: &str) -> Result<Self, IdentityError> {
        match id {
            "stable-v1" => Ok(Self::Stable),
            "module-v1" => Ok(Self::Module),
            "namespaced-v1" => Ok(Self::Namespaced),
            "execution-id-v1" => Ok(Self::Execution),
            "schema-id-v1" => Ok(Self::Schema),
            "normalization-id-v1" => Ok(Self::Normalization),
            "receipt-id-v1" => Ok(Self::Receipt),
            "artifact-id-v1" => Ok(Self::Artifact),
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
        IdProfileV1::Execution => validate_prefixed(raw, "execution:"),
        IdProfileV1::Schema => validate_prefixed(raw, "schema:"),
        IdProfileV1::Normalization => validate_prefixed(raw, "normalization:"),
        IdProfileV1::Receipt => validate_prefixed(raw, "receipt:"),
        IdProfileV1::Artifact => validate_prefixed(raw, "artifact:"),
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
    validate_local(local)
}

fn validate_prefixed(raw: &str, prefix: &str) -> Result<(), IdentityError> {
    let Some(local) = raw.strip_prefix(prefix) else {
        return Err(IdentityError::NonCanonical);
    };
    if local.contains(':') {
        return Err(IdentityError::NonCanonical);
    }
    validate_local(local)
}

fn validate_local(local: &str) -> Result<(), IdentityError> {
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

/// Untrusted authority flags used only at decode/admission boundaries. They are
/// never themselves an authority token and cannot be converted to a trusted
/// posture when any grant bit is set.
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

    pub const fn from_wire_mask(mask: u8) -> Self {
        Self {
            runtime: mask & 0x01 != 0,
            production_writer: mask & 0x02 != 0,
            model_invocation: mask & 0x04 != 0,
            provider_dispatch: mask & 0x08 != 0,
            external_effect: mask & 0x10 != 0,
            selection: mask & 0x20 != 0,
            promotion: mask & 0x40 != 0,
            release: mask & 0x80 != 0,
        }
    }

    pub const fn wire_mask(self) -> u8 {
        (self.runtime as u8)
            | ((self.production_writer as u8) << 1)
            | ((self.model_invocation as u8) << 2)
            | ((self.provider_dispatch as u8) << 3)
            | ((self.external_effect as u8) << 4)
            | ((self.selection as u8) << 5)
            | ((self.promotion as u8) << 6)
            | ((self.release as u8) << 7)
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

    /// Raw V1 ingress is exactly one byte. Any nonzero grant bit rejects before
    /// a trusted posture is constructed.
    pub fn try_from_wire_bytes(bytes: &[u8]) -> Result<Self, AuthorityPostureError> {
        if bytes.len() != 1 {
            return Err(AuthorityPostureError::InvalidWireLength(bytes.len()));
        }
        Self::try_from_flags(AuthorityFlagsV1::from_wire_mask(bytes[0]))
    }

    pub const fn flags(self) -> AuthorityFlagsV1 {
        AuthorityFlagsV1::from_wire_mask(0)
    }
}

/// Explicit proof type for receipts and values that are structurally unable to
/// carry runtime/effect authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NonAuthorizingPosture {
    _deny_all: (),
}

impl NonAuthorizingPosture {
    pub const DENY_ALL: Self = Self { _deny_all: () };

    pub const fn grants_any(self) -> bool {
        false
    }

    pub const fn as_legacy(self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl From<AuthorityPosture> for NonAuthorizingPosture {
    fn from(_value: AuthorityPosture) -> Self {
        Self::DENY_ALL
    }
}

impl From<NonAuthorizingPosture> for AuthorityPosture {
    fn from(_value: NonAuthorizingPosture) -> Self {
        Self::DENY_ALL
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityPostureError {
    GrantRequested,
    InvalidWireLength(usize),
}

impl fmt::Display for AuthorityPostureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GrantRequested => formatter
                .write_str("platform.types cannot construct a granting authority posture"),
            Self::InvalidWireLength(length) => {
                write!(formatter, "authority wire V1 must be exactly one byte, found {length}")
            }
        }
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
