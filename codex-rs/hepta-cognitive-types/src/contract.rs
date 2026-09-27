//! Checked construction, structured violations and digest-domain metadata.
//!
//! This module is intentionally additive. Existing public structs remain
//! source compatible while authority-bearing consumers can require
//! `Validated<T>` before hashing, encoding or persisting a contract.

use std::fmt;
use std::ops::Deref;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::wire::CognitiveContractV1;
use crate::wire::CognitiveWireError;
use crate::wire::encode_payload_canonical_v1;
use crate::wire::encode_wire_v1;

pub const MAX_CONTRACT_FIELD_PATH_BYTES: usize = 256;
pub const MAX_CONTRACT_DETAIL_BYTES: usize = 512;
pub const CANONICAL_JSON_V1_ID: &str =
    "canonical-json/sorted-keys/utf8/integer-only/no-whitespace/v1";
pub const UNICODE_POLICY_V1_ID: &str = "preserve-code-points/no-normalization/v1";
pub const DIGEST_ALGORITHM_V1_ID: &str = "sha-256/v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContractErrorCodeV1 {
    ZeroValue,
    EmptyValue,
    LimitExceeded,
    DuplicateIdentity,
    InvalidState,
    DigestMismatch,
    BindingMismatch,
    SchemaMismatch,
    VersionMismatch,
    NonCanonicalInput,
    UnicodePolicyViolation,
    SelectorUnresolved,
    AuthorityGranted,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ContractFieldPathV1(String);

impl ContractFieldPathV1 {
    pub fn new(value: impl Into<String>) -> Result<Self, ContractViolationV1> {
        let value = value.into();
        if value.is_empty()
            || value.len() > MAX_CONTRACT_FIELD_PATH_BYTES
            || value.chars().any(char::is_control)
        {
            return Err(ContractViolationV1::new_unchecked(
                ContractErrorCodeV1::InvalidState,
                "contract.fieldPath",
                "field path must be non-empty, bounded and control-free",
            ));
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ContractFieldPathV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContractViolationV1 {
    pub code: ContractErrorCodeV1,
    pub field_path: ContractFieldPathV1,
    pub detail: String,
    pub actual: Option<u64>,
    pub maximum: Option<u64>,
}

impl ContractViolationV1 {
    pub fn new(
        code: ContractErrorCodeV1,
        field_path: impl Into<String>,
        detail: impl Into<String>,
    ) -> Result<Self, Self> {
        let detail = detail.into();
        if detail.len() > MAX_CONTRACT_DETAIL_BYTES || detail.chars().any(char::is_control) {
            return Err(Self::new_unchecked(
                ContractErrorCodeV1::LimitExceeded,
                "contract.detail",
                "detail must be bounded and control-free",
            ));
        }
        let field_path = ContractFieldPathV1::new(field_path)?;
        Ok(Self {
            code,
            field_path,
            detail,
            actual: None,
            maximum: None,
        })
    }

    #[must_use]
    pub fn with_limit(mut self, actual: usize, maximum: usize) -> Self {
        self.actual = Some(u64::try_from(actual).unwrap_or(u64::MAX));
        self.maximum = Some(u64::try_from(maximum).unwrap_or(u64::MAX));
        self
    }

    fn new_unchecked(
        code: ContractErrorCodeV1,
        field_path: &'static str,
        detail: &'static str,
    ) -> Self {
        Self {
            code,
            field_path: ContractFieldPathV1(field_path.to_string()),
            detail: detail.to_string(),
            actual: None,
            maximum: None,
        }
    }
}

impl fmt::Display for ContractViolationV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?} at {}: {}", self.code, self.field_path, self.detail)
    }
}

impl std::error::Error for ContractViolationV1 {}

pub trait ValidateContractV1 {
    fn validate_contract_v1(&self) -> Result<(), ContractViolationV1>;
}

/// A value that has passed the current contract validator.
///
/// The inner value is private so callers cannot accidentally treat an unchecked
/// deserialization result as safe-to-digest or safe-to-persist.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Validated<T>(T);

impl<T: ValidateContractV1> Validated<T> {
    pub fn new(value: T) -> Result<Self, ContractViolationV1> {
        value.validate_contract_v1()?;
        Ok(Self(value))
    }
}

impl<T> Validated<T> {
    #[must_use]
    pub fn as_ref(&self) -> &T {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> T {
        self.0
    }
}

impl<T: CognitiveContractV1> Validated<T> {
    pub fn from_cognitive_contract(value: T) -> Result<Self, CognitiveWireError> {
        value
            .validate_contract()
            .map_err(CognitiveWireError::Contract)?;
        Ok(Self(value))
    }

    pub fn encode_wire_v1(&self) -> Result<Vec<u8>, CognitiveWireError> {
        encode_wire_v1(&self.0)
    }

    pub fn domain_bound_digest_v1(&self) -> Result<Digest32, CognitiveWireError> {
        canonical_contract_digest_domain_bound_v1(&self.0)
    }
}

impl<T> Deref for Validated<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ContractDigestDomainV1 {
    pub schema_id: &'static str,
    pub schema_version: u32,
    pub contract_id: &'static str,
    pub canonicalization_id: &'static str,
    pub unicode_policy_id: &'static str,
    pub digest_algorithm_id: &'static str,
}

impl ContractDigestDomainV1 {
    #[must_use]
    pub fn digest(self, canonical_payload: &[u8]) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cognitive.contract-domain.v1\0",
            self.schema_id.as_bytes(),
            b"\0",
            &self.schema_version.to_be_bytes(),
            b"\0",
            self.contract_id.as_bytes(),
            b"\0",
            self.canonicalization_id.as_bytes(),
            b"\0",
            self.unicode_policy_id.as_bytes(),
            b"\0",
            self.digest_algorithm_id.as_bytes(),
            b"\0",
            canonical_payload,
        ])
    }
}

/// Explicitly validates the repository-wide V1 Unicode rule: code points are
/// preserved exactly and never silently normalized. This checks only bounds and
/// control characters; NFC/NFD equivalence is intentionally *not* introduced.
pub fn validate_preserved_text_v1(
    value: &str,
    maximum_bytes: usize,
    field_path: &'static str,
) -> Result<(), ContractViolationV1> {
    if value.len() > maximum_bytes {
        return Err(
            ContractViolationV1::new(
                ContractErrorCodeV1::LimitExceeded,
                field_path,
                "text exceeds the declared byte bound",
            )
            .unwrap_or_else(|error| error)
            .with_limit(value.len(), maximum_bytes),
        );
    }
    if value.chars().any(char::is_control) {
        return Err(
            ContractViolationV1::new(
                ContractErrorCodeV1::UnicodePolicyViolation,
                field_path,
                "control characters are forbidden; Unicode code points are otherwise preserved",
            )
            .unwrap_or_else(|error| error),
        );
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundedVecV1<T, const MAXIMUM: usize> {
    values: Vec<T>,
}

impl<T, const MAXIMUM: usize> BoundedVecV1<T, MAXIMUM> {
    pub fn new(values: Vec<T>, field_path: &'static str) -> Result<Self, ContractViolationV1> {
        if values.len() > MAXIMUM {
            return Err(
                ContractViolationV1::new(
                    ContractErrorCodeV1::LimitExceeded,
                    field_path,
                    "collection exceeds the declared element bound",
                )
                .unwrap_or_else(|error| error)
                .with_limit(values.len(), MAXIMUM),
            );
        }
        Ok(Self { values })
    }

    #[must_use]
    pub fn as_slice(&self) -> &[T] {
        &self.values
    }

    #[must_use]
    pub fn into_vec(self) -> Vec<T> {
        self.values
    }
}

/// Domain-bound digest for every canonical cognitive contract.
///
/// Unlike the legacy compatibility digest, this profile commits to the schema
/// id, schema version, contract id, canonicalization profile, Unicode policy
/// and digest algorithm. The existing V1 digest remains unchanged for callers
/// that need byte-for-byte compatibility.
pub fn canonical_contract_digest_domain_bound_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok(ContractDigestDomainV1 {
        schema_id: T::SCHEMA_ID,
        schema_version: crate::wire::COGNITIVE_WIRE_VERSION_V1,
        contract_id: T::CONTRACT_ID,
        canonicalization_id: CANONICAL_JSON_V1_ID,
        unicode_policy_id: UNICODE_POLICY_V1_ID,
        digest_algorithm_id: DIGEST_ALGORITHM_V1_ID,
    }
    .digest(&payload))
}
