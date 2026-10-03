//! Shared validation, error-code and canonical-text policy primitives.
//!
//! These values are deliberately authority-free. `Validated<T>` proves only
//! that the wrapped value passed its type-local structural validator; it does
//! not authenticate a producer, grant a writer, or establish runtime freshness.

use std::fmt;
use std::ops::Deref;

use serde::Deserialize;
use serde::Serialize;

/// Frozen canonicalization profile used by cognitive contract Wire V1.
pub const CANONICALIZATION_ALGORITHM_V1: &str =
    "canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1";

/// Wire V1 preserves the exact Unicode scalar sequence supplied by the caller.
///
/// In particular, Wire V1 never rewrites NFC to NFD or NFD to NFC. Producers
/// that own identifier grammars may impose a stronger profile before creating
/// a contract value, but the generic cognitive codec does not silently change
/// text and therefore cannot make two byte-distinct identifiers compare equal.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UnicodeNormalizationPolicyV1 {
    PreserveCodePoints,
}

pub const UNICODE_NORMALIZATION_POLICY_V1: UnicodeNormalizationPolicyV1 =
    UnicodeNormalizationPolicyV1::PreserveCodePoints;

/// Stable, machine-readable validation categories shared across contract
/// families. New variants may be appended, but the meaning of an existing
/// variant must never change in place.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContractErrorCodeV1 {
    EmptyCollection,
    ZeroValue,
    EmptyDigest,
    InvalidValue,
    MissingValue,
    DuplicateIdentity,
    DigestMismatch,
    StateConflict,
    AuthorityGranted,
    LimitExceeded,
    NonCanonicalEncoding,
    SchemaMismatch,
    VersionMismatch,
    ContractMismatch,
}

/// Stable error code plus the canonical field path that failed validation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContractViolationV1 {
    pub code: ContractErrorCodeV1,
    pub field_path: String,
    pub message: String,
}

impl ContractViolationV1 {
    #[must_use]
    pub fn new(
        code: ContractErrorCodeV1,
        field_path: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            code,
            field_path: field_path.into(),
            message: message.into(),
        }
    }
}

impl fmt::Display for ContractViolationV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{:?} at {}: {}",
            self.code, self.field_path, self.message
        )
    }
}

impl std::error::Error for ContractViolationV1 {}

/// Type-local structural validation used to create `Validated<T>`.
pub trait ValidateContractV1 {
    type Error;

    fn validate_contract_v1(&self) -> Result<(), Self::Error>;
}

/// A value that has passed its complete type-local structural validator.
///
/// Construction is checked; callers cannot obtain a `Validated<T>` through a
/// public unchecked constructor. Contextual checks (for example, selector
/// membership in an asset manifest) remain explicit and must be performed by
/// the owner of that context.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Validated<T>(T);

impl<T> Validated<T>
where
    T: ValidateContractV1,
{
    pub fn new(value: T) -> Result<Self, T::Error> {
        value.validate_contract_v1()?;
        Ok(Self(value))
    }
}

impl<T> Validated<T> {
    #[must_use]
    pub const fn as_inner(&self) -> &T {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> T {
        self.0
    }
}

impl<T> AsRef<T> for Validated<T> {
    fn as_ref(&self) -> &T {
        self.as_inner()
    }
}

impl<T> Deref for Validated<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        self.as_inner()
    }
}
