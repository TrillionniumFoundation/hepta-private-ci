use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::BoundedValueError;

const STABLE_ID_MAX_BYTES: usize = 128;

/// Registered identifier grammars. `Stable` preserves the original permissive
/// StableId contract; the namespace-specific profiles make protocol intent
/// explicit without normalizing caller input.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum IdProfileV1 {
    Stable,
    Namespaced,
    Execution,
    Schema,
    Normalization,
    Receipt,
    Artifact,
}

impl IdProfileV1 {
    pub fn from_id(id: &str) -> Result<Self, IdentityError> {
        match id {
            "stable-id-v1" => Ok(Self::Stable),
            "namespaced-id-v1" => Ok(Self::Namespaced),
            "execution-id-v1" => Ok(Self::Execution),
            "schema-id-v1" => Ok(Self::Schema),
            "normalization-id-v1" => Ok(Self::Normalization),
            "receipt-id-v1" => Ok(Self::Receipt),
            "artifact-id-v1" => Ok(Self::Artifact),
            _ => Err(IdentityError::UnknownProfile),
        }
    }

    pub const fn id(self) -> &'static str {
        match self {
            Self::Stable => "stable-id-v1",
            Self::Namespaced => "namespaced-id-v1",
            Self::Execution => "execution-id-v1",
            Self::Schema => "schema-id-v1",
            Self::Normalization => "normalization-id-v1",
            Self::Receipt => "receipt-id-v1",
            Self::Artifact => "artifact-id-v1",
        }
    }
}

/// Stable, bounded identifier suitable for content and protocol records.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct StableId(BoundedText<STABLE_ID_MAX_BYTES>);

impl StableId {
    pub fn new(value: impl Into<String>) -> Result<Self, IdentityError> {
        Self::new_profiled(value, IdProfileV1::Stable)
    }

    pub fn new_profiled(
        value: impl Into<String>,
        profile: IdProfileV1,
    ) -> Result<Self, IdentityError> {
        let value = value.into();
        validate_id_text(&value, profile)?;
        let value = BoundedText::new(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    /// Validates borrowed input before allocating its bounded owned form.
    pub fn parse_profiled(value: &str, profile: IdProfileV1) -> Result<Self, IdentityError> {
        validate_id_text(value, profile)?;
        let value = BoundedText::try_from_str(value).map_err(IdentityError::Bounded)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

/// Target-contract entrypoint from the Platform Types dossier.
pub fn validate_id(raw: &str, profile: IdProfileV1) -> Result<StableId, IdentityError> {
    StableId::parse_profiled(raw, profile)
}

fn validate_id_text(raw: &str, profile: IdProfileV1) -> Result<(), IdentityError> {
    if raw.is_empty() {
        return Err(IdentityError::Bounded(BoundedValueError::Empty));
    }
    if raw.len() > STABLE_ID_MAX_BYTES {
        return Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: raw.len(),
            maximum: STABLE_ID_MAX_BYTES,
        }));
    }
    if !raw
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err(IdentityError::InvalidCharacter);
    }
    validate_profile(raw, profile)
}

fn validate_profile(raw: &str, profile: IdProfileV1) -> Result<(), IdentityError> {
    match profile {
        IdProfileV1::Stable => Ok(()),
        IdProfileV1::Namespaced => {
            let Some((namespace, local)) = raw.split_once(':') else {
                return Err(IdentityError::ProfileMismatch(profile));
            };
            if namespace.is_empty() || local.is_empty() || local.contains(':') {
                return Err(IdentityError::ProfileMismatch(profile));
            }
            Ok(())
        }
        IdProfileV1::Execution => validate_prefix(raw, "execution:", profile),
        IdProfileV1::Schema => validate_prefix(raw, "schema:", profile),
        IdProfileV1::Normalization => validate_prefix(raw, "normalization:", profile),
        IdProfileV1::Receipt => validate_prefix(raw, "receipt:", profile),
        IdProfileV1::Artifact => validate_prefix(raw, "artifact:", profile),
    }
}

fn validate_prefix(
    raw: &str,
    prefix: &str,
    profile: IdProfileV1,
) -> Result<(), IdentityError> {
    let Some(local) = raw.strip_prefix(prefix) else {
        return Err(IdentityError::ProfileMismatch(profile));
    };
    if local.is_empty() || local.contains(':') {
        return Err(IdentityError::ProfileMismatch(profile));
    }
    Ok(())
}

impl fmt::Display for StableId {
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

/// Compatibility/tamper representation of authority flags.
///
/// This value is not an authority token. Security-sensitive Platform Types
/// outputs should expose `NonAuthorizingPosture`, which cannot represent a
/// granted flag. Public fields remain for backwards-compatible negative tests
/// and legacy record decoding.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityPosture {
    pub runtime: bool,
    pub production_writer: bool,
    pub model_invocation: bool,
    pub provider_dispatch: bool,
    pub external_effect: bool,
    pub selection: bool,
    pub promotion: bool,
    pub release: bool,
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

/// Type-level proof that a value carries no runtime/effect/selection authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NonAuthorizingPosture(());

impl NonAuthorizingPosture {
    pub const DENY_ALL: Self = Self(());

    pub const fn grants_any(self) -> bool {
        false
    }

    pub const fn as_legacy(self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl TryFrom<AuthorityPosture> for NonAuthorizingPosture {
    type Error = NonAuthorizingPostureError;

    fn try_from(value: AuthorityPosture) -> Result<Self, Self::Error> {
        if value.grants_any() {
            return Err(NonAuthorizingPostureError::AuthorityGranted);
        }
        Ok(Self::DENY_ALL)
    }
}

impl From<NonAuthorizingPosture> for AuthorityPosture {
    fn from(value: NonAuthorizingPosture) -> Self {
        value.as_legacy()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NonAuthorizingPostureError {
    AuthorityGranted,
}

impl fmt::Display for NonAuthorizingPostureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("authority-bearing posture cannot enter a non-authorizing boundary")
    }
}

impl Error for NonAuthorizingPostureError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdentityError {
    Bounded(BoundedValueError),
    InvalidCharacter,
    UnknownProfile,
    ProfileMismatch(IdProfileV1),
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
            Self::UnknownProfile => formatter.write_str("unknown identifier profile"),
            Self::ProfileMismatch(profile) => {
                write!(formatter, "identifier does not match profile {}", profile.id())
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
