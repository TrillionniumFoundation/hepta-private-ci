use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::SecretReference;
use super::push_id;

pub const SECRET_BOUNDARY_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_SECRET_REFERENCE_COMPONENT_BYTES: usize = 128;
pub const MAX_SECRET_METADATA_BYTES: usize = 16 * 1024;
pub const HEPTABAO_BACKEND_ID: &str = "heptabao";
pub const HEPTABAO_DESTINATION_ID: &str = "provider:heptabao";
pub const KERNEL_AUTHORITY_PRODUCER_ID: &str = "kernel.authority";
pub const AUTHBUS_POLICY_PRODUCER_ID: &str = "auth.authbus";
pub const PROVIDER_DISPATCH_ENABLED: bool = false;

/// A reference whose variable-length components are bounded identifiers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParsedSecretReferenceV1 {
    backend_id: StableId,
    reference_id: StableId,
    version: u64,
    secret_digest: Digest32,
}

impl ParsedSecretReferenceV1 {
    /// Parse separate typed fields instead of defining an unregistered wire
    /// grammar. Bounds are checked before attacker-controlled text is owned.
    pub fn parse_parts(
        backend_id: &str,
        reference_id: &str,
        version: &str,
        secret_digest: &str,
    ) -> Result<Self, SecretBoundaryErrorV1> {
        ensure_bound(
            "backend id",
            backend_id,
            MAX_SECRET_REFERENCE_COMPONENT_BYTES,
        )?;
        ensure_bound(
            "reference id",
            reference_id,
            MAX_SECRET_REFERENCE_COMPONENT_BYTES,
        )?;
        ensure_bound("version", version, /*maximum*/ 20)?;
        ensure_bound("secret digest", secret_digest, /*maximum*/ 64)?;
        if backend_id != HEPTABAO_BACKEND_ID {
            return Err(SecretBoundaryErrorV1::UnsupportedBackend);
        }
        let backend_id = StableId::new(backend_id)
            .map_err(|_| SecretBoundaryErrorV1::InvalidField("backend id"))?;
        let reference_id = StableId::new(reference_id)
            .map_err(|_| SecretBoundaryErrorV1::InvalidField("reference id"))?;
        let version = parse_positive_u64(version)?;
        let secret_digest = secret_digest
            .parse::<Digest32>()
            .map_err(|_| SecretBoundaryErrorV1::InvalidField("secret digest"))?;
        if secret_digest.is_zero() {
            return Err(SecretBoundaryErrorV1::EmptyDigest("secret digest"));
        }
        Ok(Self {
            backend_id,
            reference_id,
            version,
            secret_digest,
        })
    }

    pub fn backend_id(&self) -> &StableId {
        &self.backend_id
    }

    pub fn reference_id(&self) -> &StableId {
        &self.reference_id
    }

    pub const fn version(&self) -> u64 {
        self.version
    }

    pub const fn secret_digest(&self) -> Digest32 {
        self.secret_digest
    }

    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.bao.secret-reference.v1");
        push_id(&mut bytes, &self.backend_id);
        push_id(&mut bytes, &self.reference_id);
        bytes.extend_from_slice(&self.version.to_be_bytes());
        bytes.extend_from_slice(self.secret_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    pub fn to_legacy_reference(&self) -> SecretReference {
        SecretReference {
            secret_id: self.reference_id.clone(),
            version: self.version,
            secret_digest: self.secret_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretBoundaryRequestV1 {
    pub schema_version: u32,
    pub request_id: StableId,
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub destination_id: StableId,
    pub reference: ParsedSecretReferenceV1,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum SecretPermissionStatusV1 {
    Granted,
    Denied,
    Unavailable,
    Indeterminate,
}

/// A permission projection, not a capability or provider credential.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretPermissionObservationV1 {
    pub schema_version: u32,
    pub authority_producer_id: StableId,
    pub policy_producer_id: StableId,
    pub principal_id: StableId,
    pub operation_id: StableId,
    pub destination_id: StableId,
    pub request_digest: Digest32,
    pub reference_digest: Digest32,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub grant_id: Option<StableId>,
    pub quota_reservation_id: Option<StableId>,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub policy_revision: u64,
    pub quota_revision: u64,
    pub not_before_ms: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub status: SecretPermissionStatusV1,
}

/// No variant represents success or an observed external effect.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum SecretBoundaryDispositionV1 {
    PermissionDenied,
    GrantRevoked,
    GrantNotYetValid,
    GrantExpired,
    AuthorityUnavailable,
    AuthorityIndeterminate,
    VerifiedUseTokenUnavailable,
}

/// Private fields prevent callers from altering the semantics of a decision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretBoundaryDecisionV1 {
    request_digest: Digest32,
    reference_digest: Digest32,
    permission_observation_digest: Digest32,
    disposition: SecretBoundaryDispositionV1,
}

impl SecretBoundaryDecisionV1 {
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    pub const fn reference_digest(&self) -> Digest32 {
        self.reference_digest
    }

    pub const fn permission_observation_digest(&self) -> Digest32 {
        self.permission_observation_digest
    }

    pub const fn disposition(&self) -> SecretBoundaryDispositionV1 {
        self.disposition
    }

    pub const fn contains_raw_secret(&self) -> bool {
        false
    }

    pub const fn provider_dispatch_attempted(&self) -> bool {
        false
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum SecretBoundaryErrorV1 {
    InputTooLarge { field: &'static str, maximum: usize },
    InvalidField(&'static str),
    EmptyDigest(&'static str),
    UnsupportedBackend,
    UnsupportedSchemaVersion(&'static str),
    DeadlineExpired,
    ProducerIdentityMismatch(&'static str),
    BindingMismatch(&'static str),
    IncompleteGrant,
    InvalidValidityWindow,
    MetadataTooLarge,
}

impl fmt::Display for SecretBoundaryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SecretBoundaryErrorV1 {}

pub fn secret_boundary_request_digest_v1(
    request: &SecretBoundaryRequestV1,
) -> Result<Digest32, SecretBoundaryErrorV1> {
    validate_request(request)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.bao.secret-boundary-request.v1");
    bytes.extend_from_slice(&request.schema_version.to_be_bytes());
    for value in [
        &request.request_id,
        &request.operation_id,
        &request.principal_id,
        &request.destination_id,
    ] {
        push_id(&mut bytes, value);
    }
    bytes.extend_from_slice(request.reference.digest().as_array());
    bytes.extend_from_slice(request.scope_digest.as_array());
    bytes.extend_from_slice(request.payload_digest.as_array());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    digest_bounded(&bytes)
}

/// Validate metadata immediately before the unavailable effect boundary.
/// Even `Granted` cannot replace the missing opaque final-use token.
pub fn assess_secret_boundary_v1(
    now_ms: u64,
    request: &SecretBoundaryRequestV1,
    permission: &SecretPermissionObservationV1,
) -> Result<SecretBoundaryDecisionV1, SecretBoundaryErrorV1> {
    let request_digest = secret_boundary_request_digest_v1(request)?;
    if now_ms >= request.deadline_ms {
        return Err(SecretBoundaryErrorV1::DeadlineExpired);
    }
    validate_binding(request, request_digest, permission)?;
    let permission_observation_digest = permission_digest(permission)?;
    let disposition = match permission.status {
        SecretPermissionStatusV1::Denied => SecretBoundaryDispositionV1::PermissionDenied,
        SecretPermissionStatusV1::Unavailable => SecretBoundaryDispositionV1::AuthorityUnavailable,
        SecretPermissionStatusV1::Indeterminate => {
            SecretBoundaryDispositionV1::AuthorityIndeterminate
        }
        SecretPermissionStatusV1::Granted => {
            validate_grant(permission)?;
            if permission.revoked {
                SecretBoundaryDispositionV1::GrantRevoked
            } else if now_ms < permission.not_before_ms {
                SecretBoundaryDispositionV1::GrantNotYetValid
            } else if now_ms >= permission.expires_at_ms {
                SecretBoundaryDispositionV1::GrantExpired
            } else {
                if request.deadline_ms > permission.expires_at_ms {
                    return Err(SecretBoundaryErrorV1::BindingMismatch("grant expiry"));
                }
                SecretBoundaryDispositionV1::VerifiedUseTokenUnavailable
            }
        }
    };
    Ok(SecretBoundaryDecisionV1 {
        request_digest,
        reference_digest: request.reference.digest(),
        permission_observation_digest,
        disposition,
    })
}

fn validate_request(request: &SecretBoundaryRequestV1) -> Result<(), SecretBoundaryErrorV1> {
    if request.schema_version != SECRET_BOUNDARY_SCHEMA_VERSION_V1 {
        return Err(SecretBoundaryErrorV1::UnsupportedSchemaVersion("request"));
    }
    if request.reference.backend_id.as_str() != HEPTABAO_BACKEND_ID {
        return Err(SecretBoundaryErrorV1::UnsupportedBackend);
    }
    if request.destination_id.as_str() != HEPTABAO_DESTINATION_ID {
        return Err(SecretBoundaryErrorV1::ProducerIdentityMismatch(
            "destination",
        ));
    }
    for (name, digest) in [
        ("scope", request.scope_digest),
        ("payload", request.payload_digest),
    ] {
        if digest.is_zero() {
            return Err(SecretBoundaryErrorV1::EmptyDigest(name));
        }
    }
    if request.deadline_ms == 0 {
        return Err(SecretBoundaryErrorV1::DeadlineExpired);
    }
    Ok(())
}

fn validate_binding(
    request: &SecretBoundaryRequestV1,
    request_digest: Digest32,
    permission: &SecretPermissionObservationV1,
) -> Result<(), SecretBoundaryErrorV1> {
    if permission.schema_version != SECRET_BOUNDARY_SCHEMA_VERSION_V1 {
        return Err(SecretBoundaryErrorV1::UnsupportedSchemaVersion(
            "permission",
        ));
    }
    if permission.authority_producer_id.as_str() != KERNEL_AUTHORITY_PRODUCER_ID {
        return Err(SecretBoundaryErrorV1::ProducerIdentityMismatch("authority"));
    }
    if permission.policy_producer_id.as_str() != AUTHBUS_POLICY_PRODUCER_ID {
        return Err(SecretBoundaryErrorV1::ProducerIdentityMismatch("policy"));
    }
    for (name, matches) in [
        ("principal", permission.principal_id == request.principal_id),
        ("operation", permission.operation_id == request.operation_id),
        (
            "destination",
            permission.destination_id == request.destination_id,
        ),
        ("request", permission.request_digest == request_digest),
        (
            "reference",
            permission.reference_digest == request.reference.digest(),
        ),
        ("scope", permission.scope_digest == request.scope_digest),
        (
            "payload",
            permission.payload_digest == request.payload_digest,
        ),
    ] {
        if !matches {
            return Err(SecretBoundaryErrorV1::BindingMismatch(name));
        }
    }
    Ok(())
}

fn validate_grant(permission: &SecretPermissionObservationV1) -> Result<(), SecretBoundaryErrorV1> {
    if permission.grant_id.is_none()
        || permission.quota_reservation_id.is_none()
        || [
            permission.authority_epoch,
            permission.revocation_revision,
            permission.policy_revision,
            permission.quota_revision,
        ]
        .contains(&0)
    {
        return Err(SecretBoundaryErrorV1::IncompleteGrant);
    }
    if permission.not_before_ms == 0 || permission.expires_at_ms <= permission.not_before_ms {
        return Err(SecretBoundaryErrorV1::InvalidValidityWindow);
    }
    Ok(())
}

fn permission_digest(
    permission: &SecretPermissionObservationV1,
) -> Result<Digest32, SecretBoundaryErrorV1> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.bao.secret-permission-observation.v1");
    bytes.extend_from_slice(&permission.schema_version.to_be_bytes());
    for value in [
        &permission.authority_producer_id,
        &permission.policy_producer_id,
        &permission.principal_id,
        &permission.operation_id,
        &permission.destination_id,
    ] {
        push_id(&mut bytes, value);
    }
    for digest in [
        permission.request_digest,
        permission.reference_digest,
        permission.scope_digest,
        permission.payload_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_optional_id(&mut bytes, permission.grant_id.as_ref());
    push_optional_id(&mut bytes, permission.quota_reservation_id.as_ref());
    for value in [
        permission.authority_epoch,
        permission.revocation_revision,
        permission.policy_revision,
        permission.quota_revision,
        permission.not_before_ms,
        permission.expires_at_ms,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(u8::from(permission.revoked));
    bytes.push(match permission.status {
        SecretPermissionStatusV1::Granted => 0,
        SecretPermissionStatusV1::Denied => 1,
        SecretPermissionStatusV1::Unavailable => 2,
        SecretPermissionStatusV1::Indeterminate => 3,
    });
    digest_bounded(&bytes)
}

fn digest_bounded(bytes: &[u8]) -> Result<Digest32, SecretBoundaryErrorV1> {
    if bytes.len() > MAX_SECRET_METADATA_BYTES {
        return Err(SecretBoundaryErrorV1::MetadataTooLarge);
    }
    Ok(Digest32::of_bytes(bytes))
}

fn ensure_bound(
    field: &'static str,
    value: &str,
    maximum: usize,
) -> Result<(), SecretBoundaryErrorV1> {
    if value.len() > maximum {
        return Err(SecretBoundaryErrorV1::InputTooLarge { field, maximum });
    }
    if value.is_empty() {
        return Err(SecretBoundaryErrorV1::InvalidField(field));
    }
    Ok(())
}

fn parse_positive_u64(value: &str) -> Result<u64, SecretBoundaryErrorV1> {
    if value.starts_with('0') || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(SecretBoundaryErrorV1::InvalidField("version"));
    }
    let Ok(parsed) = value.parse::<u64>() else {
        return Err(SecretBoundaryErrorV1::InvalidField("version"));
    };
    if parsed == 0 {
        return Err(SecretBoundaryErrorV1::InvalidField("version"));
    }
    Ok(parsed)
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    bytes.push(u8::from(value.is_some()));
    if let Some(value) = value {
        push_id(bytes, value);
    }
}
