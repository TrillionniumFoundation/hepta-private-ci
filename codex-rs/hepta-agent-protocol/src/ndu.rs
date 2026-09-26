//! Bounded local control transport, never a substitute for final-use authority.
use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const NDU_CONTROL_REQUEST_DIGEST_DOMAIN_V2: &[u8] =
    b"hepta.agentd.ndu-control-request.v2\0";
const NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION: u32 = 2;
const MAX_NDU_EXTERNAL_ADMISSION_BYTES: usize = 32 * 1024;
const MAX_NDU_CRITICAL_EXTENSIONS: usize = 16;
const MAX_REQUEST_ID_BYTES: usize = 128;
const MAX_CALLER_ID_BYTES: usize = 256;
const MAX_EXTENSION_NAME_BYTES: usize = 64;
const MAX_ADMISSION_LIFETIME_MS: u64 = 5 * 60 * 1000;
const MAX_CLOCK_SKEW_MS: u64 = 30 * 1000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NduMutationOperationV1 {
    AppendPreference,
    AppendUtility,
    Select,
    Revoke,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduMutationV1 {
    pub operation: NduMutationOperationV1,
    pub identity: [u8; 32],
    pub objective: [u8; 32],
    pub subject: [u8; 32],
    pub projection: [u8; 32],
    pub expected_predecessor: Option<[u8; 32]>,
}

/// Public NDU control protocol carried by the existing bounded Agentd socket.
///
/// `ExternalAdmissionV2` is an additive, explicitly versioned ingress wrapper.
/// It binds caller/idempotency identity, deadline, host generation, owner fence,
/// revocation frontier, extensions and the exact canonical digest of the inner
/// request. The inner request cannot itself be another admission wrapper. Final
/// use authority is still required by `Apply`; admission never mints authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum NduControlRequestV1 {
    Context,
    Prepare {
        mutation: NduMutationV1,
        expected_head: [u8; 32],
    },
    Apply {
        mutation: NduMutationV1,
        expected_head: [u8; 32],
        grant: SignedFinalUseGrant,
    },
    Selection {
        objective: [u8; 32],
        subject: [u8; 32],
    },
    Outcome {
        identity: [u8; 32],
    },
    ExternalAdmissionV2 {
        schema_version: u32,
        request_id: String,
        idempotency_key: String,
        caller_id: String,
        issued_at_unix_ms: u64,
        deadline_unix_ms: u64,
        host_generation: u64,
        fence_digest: [u8; 32],
        revocation_head_digest: [u8; 32],
        payload_digest: [u8; 32],
        request: Box<NduControlRequestV1>,
        /// Canonically sorted, duplicate-free `(name, critical, value_digest)`
        /// entries. Unknown critical names fail closed.
        #[serde(default)]
        extensions: Vec<(String, bool, [u8; 32])>,
    },
}

impl NduControlRequestV1 {
    pub const EXTERNAL_ADMISSION_SCHEMA_VERSION_V2: u32 =
        NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION;
    pub const MAX_EXTERNAL_ADMISSION_BYTES_V2: usize = MAX_NDU_EXTERNAL_ADMISSION_BYTES;
    pub const MAX_EXTERNAL_ADMISSION_EXTENSIONS_V2: usize = MAX_NDU_CRITICAL_EXTENSIONS;

    /// Whether this request, including an admission wrapper's exact inner
    /// request, can prepare or apply a durable mutation. Product lifecycle
    /// gates must use this recursive classification rather than inspect only
    /// the outer enum discriminant.
    #[must_use]
    pub fn requires_mutation_admission(&self) -> bool {
        match self {
            Self::Prepare { .. } | Self::Apply { .. } => true,
            Self::ExternalAdmissionV2 { request, .. } => {
                request.requires_mutation_admission()
            }
            Self::Context | Self::Selection { .. } | Self::Outcome { .. } => false,
        }
    }

    /// SHA-256 of the exact canonical V2 payload. This is defined only for an
    /// inner control request; nested admission wrappers are rejected.
    pub fn canonical_payload_digest_v2(&self) -> Result<[u8; 32], &'static str> {
        canonical_ndu_control_request_digest_v2(self).map_err(NduExternalAdmissionErrorV2::code)
    }

    /// Validate a complete V2 wrapper independently of host-owned identity.
    /// Agentd additionally compares generation/fence/revocation fields with its
    /// live owner context and applies its bounded replay window.
    pub fn validate_external_admission_v2(
        &self,
        encoded_len: usize,
        now_unix_ms: u64,
        supported_critical_extensions: &BTreeSet<String>,
    ) -> Result<(), &'static str> {
        validate_ndu_external_admission_v2(
            self,
            encoded_len,
            now_unix_ms,
            supported_critical_extensions,
        )
        .map_err(NduExternalAdmissionErrorV2::code)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NduExternalAdmissionErrorV2 {
    UnsupportedSchema,
    EnvelopeTooLarge,
    InvalidIdentity,
    InvalidDeadline,
    Expired,
    InvalidHostContext,
    InvalidPayload,
    TooManyExtensions,
    NonCanonicalExtensions,
    UnknownCriticalExtension,
}

impl NduExternalAdmissionErrorV2 {
    const fn code(self) -> &'static str {
        match self {
            Self::UnsupportedSchema => "NDU-ADMIT-001",
            Self::EnvelopeTooLarge => "NDU-ADMIT-002",
            Self::InvalidIdentity => "NDU-ADMIT-003",
            Self::InvalidDeadline | Self::Expired => "NDU-ADMIT-004",
            Self::InvalidHostContext => "NDU-ADMIT-005",
            Self::InvalidPayload => "NDU-ADMIT-006",
            Self::TooManyExtensions
            | Self::NonCanonicalExtensions
            | Self::UnknownCriticalExtension => "NDU-ADMIT-007",
        }
    }
}

fn validate_ndu_external_admission_v2(
    envelope: &NduControlRequestV1,
    encoded_len: usize,
    now_unix_ms: u64,
    supported_critical_extensions: &BTreeSet<String>,
) -> Result<(), NduExternalAdmissionErrorV2> {
    let NduControlRequestV1::ExternalAdmissionV2 {
        schema_version,
        request_id,
        idempotency_key,
        caller_id,
        issued_at_unix_ms,
        deadline_unix_ms,
        host_generation,
        fence_digest,
        revocation_head_digest,
        payload_digest,
        request,
        extensions,
    } = envelope
    else {
        return Err(NduExternalAdmissionErrorV2::UnsupportedSchema);
    };

    if *schema_version != NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION {
        return Err(NduExternalAdmissionErrorV2::UnsupportedSchema);
    }
    if encoded_len == 0 || encoded_len > MAX_NDU_EXTERNAL_ADMISSION_BYTES {
        return Err(NduExternalAdmissionErrorV2::EnvelopeTooLarge);
    }
    validate_text(request_id, MAX_REQUEST_ID_BYTES)?;
    validate_text(idempotency_key, MAX_REQUEST_ID_BYTES)?;
    validate_text(caller_id, MAX_CALLER_ID_BYTES)?;
    if *host_generation == 0 || is_zero(fence_digest) || is_zero(revocation_head_digest) {
        return Err(NduExternalAdmissionErrorV2::InvalidHostContext);
    }
    let calculated = canonical_ndu_control_request_digest_v2(request)?;
    if is_zero(payload_digest) || *payload_digest != calculated {
        return Err(NduExternalAdmissionErrorV2::InvalidPayload);
    }
    if *deadline_unix_ms <= *issued_at_unix_ms
        || *deadline_unix_ms - *issued_at_unix_ms > MAX_ADMISSION_LIFETIME_MS
        || *issued_at_unix_ms > now_unix_ms.saturating_add(MAX_CLOCK_SKEW_MS)
    {
        return Err(NduExternalAdmissionErrorV2::InvalidDeadline);
    }
    if now_unix_ms > *deadline_unix_ms {
        return Err(NduExternalAdmissionErrorV2::Expired);
    }
    if extensions.len() > MAX_NDU_CRITICAL_EXTENSIONS {
        return Err(NduExternalAdmissionErrorV2::TooManyExtensions);
    }
    for (name, critical, value_digest) in extensions {
        validate_text(name, MAX_EXTENSION_NAME_BYTES)?;
        if is_zero(value_digest) {
            return Err(NduExternalAdmissionErrorV2::InvalidPayload);
        }
        if *critical && !supported_critical_extensions.contains(name) {
            return Err(NduExternalAdmissionErrorV2::UnknownCriticalExtension);
        }
    }
    if extensions
        .windows(2)
        .any(|pair| pair[0].0.as_str() >= pair[1].0.as_str())
    {
        return Err(NduExternalAdmissionErrorV2::NonCanonicalExtensions);
    }
    Ok(())
}

fn canonical_ndu_control_request_digest_v2(
    request: &NduControlRequestV1,
) -> Result<[u8; 32], NduExternalAdmissionErrorV2> {
    let mut bytes = NDU_CONTROL_REQUEST_DIGEST_DOMAIN_V2.to_vec();
    match request {
        NduControlRequestV1::Context => bytes.push(0),
        NduControlRequestV1::Prepare {
            mutation,
            expected_head,
        } => {
            bytes.push(1);
            push_mutation(&mut bytes, mutation)?;
            require_digest(expected_head)?;
            bytes.extend_from_slice(expected_head);
        }
        NduControlRequestV1::Apply {
            mutation,
            expected_head,
            grant,
        } => {
            bytes.push(2);
            push_mutation(&mut bytes, mutation)?;
            require_digest(expected_head)?;
            bytes.extend_from_slice(expected_head);
            let signing_bytes = grant
                .grant
                .signing_bytes()
                .map_err(|_| NduExternalAdmissionErrorV2::InvalidPayload)?;
            if grant.signature.len() != 64 {
                return Err(NduExternalAdmissionErrorV2::InvalidPayload);
            }
            push_bytes(&mut bytes, &signing_bytes)?;
            push_bytes(&mut bytes, &grant.signature)?;
        }
        NduControlRequestV1::Selection { objective, subject } => {
            bytes.push(3);
            require_digest(objective)?;
            require_digest(subject)?;
            bytes.extend_from_slice(objective);
            bytes.extend_from_slice(subject);
        }
        NduControlRequestV1::Outcome { identity } => {
            bytes.push(4);
            require_digest(identity)?;
            bytes.extend_from_slice(identity);
        }
        NduControlRequestV1::ExternalAdmissionV2 { .. } => {
            return Err(NduExternalAdmissionErrorV2::InvalidPayload);
        }
    }
    let digest = Sha256::digest(&bytes);
    let mut result = [0_u8; 32];
    result.copy_from_slice(&digest);
    Ok(result)
}

fn push_mutation(
    bytes: &mut Vec<u8>,
    mutation: &NduMutationV1,
) -> Result<(), NduExternalAdmissionErrorV2> {
    for value in [
        &mutation.identity,
        &mutation.objective,
        &mutation.subject,
        &mutation.projection,
    ] {
        require_digest(value)?;
    }
    bytes.push(match mutation.operation {
        NduMutationOperationV1::AppendPreference => 0,
        NduMutationOperationV1::AppendUtility => 1,
        NduMutationOperationV1::Select => 2,
        NduMutationOperationV1::Revoke => 3,
    });
    bytes.extend_from_slice(&mutation.identity);
    bytes.extend_from_slice(&mutation.objective);
    bytes.extend_from_slice(&mutation.subject);
    bytes.extend_from_slice(&mutation.projection);
    match (mutation.operation, mutation.expected_predecessor) {
        (NduMutationOperationV1::Select, Some(predecessor)) => {
            require_digest(&predecessor)?;
            bytes.push(1);
            bytes.extend_from_slice(&predecessor);
        }
        (NduMutationOperationV1::Select, None) | (_, None) => bytes.push(0),
        (_, Some(_)) => return Err(NduExternalAdmissionErrorV2::InvalidPayload),
    }
    Ok(())
}

fn push_bytes(
    bytes: &mut Vec<u8>,
    value: &[u8],
) -> Result<(), NduExternalAdmissionErrorV2> {
    let length = u32::try_from(value.len())
        .map_err(|_| NduExternalAdmissionErrorV2::InvalidPayload)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

fn validate_text(
    value: &str,
    maximum: usize,
) -> Result<(), NduExternalAdmissionErrorV2> {
    if value.is_empty() || value.len() > maximum || value.chars().any(char::is_control) {
        return Err(NduExternalAdmissionErrorV2::InvalidIdentity);
    }
    Ok(())
}

fn require_digest(value: &[u8; 32]) -> Result<(), NduExternalAdmissionErrorV2> {
    if is_zero(value) {
        return Err(NduExternalAdmissionErrorV2::InvalidPayload);
    }
    Ok(())
}

fn is_zero(value: &[u8; 32]) -> bool {
    value.iter().all(|byte| *byte == 0)
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduCommittedEntryV1 {
    pub operation: NduMutationOperationV1,
    pub sequence: u64,
    pub identity: [u8; 32],
    pub objective: [u8; 32],
    pub subject: [u8; 32],
    pub projection: [u8; 32],
    pub predecessor_entry: [u8; 32],
    pub entry_digest: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case", deny_unknown_fields)]
pub enum NduControlResultV1 {
    Context {
        journal_head: [u8; 32],
        revocation_head: [u8; 32],
        principal_id: String,
        host_generation: u64,
        policy_digest: [u8; 32],
    },
    Prepared {
        journal_head: [u8; 32],
        binding: FinalUseBinding,
    },
    Committed {
        entry: NduCommittedEntryV1,
    },
    Selection {
        journal_head: [u8; 32],
        projection: Option<[u8; 32]>,
    },
    Outcome {
        entry: Option<NduCommittedEntryV1>,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    fn nonzero(value: u8) -> [u8; 32] {
        [value; 32]
    }

    fn must_digest(request: &NduControlRequestV1) -> [u8; 32] {
        match request.canonical_payload_digest_v2() {
            Ok(digest) => digest,
            Err(error) => panic!("fixture digest failed: {error}"),
        }
    }

    fn admission() -> NduControlRequestV1 {
        let request = NduControlRequestV1::Selection {
            objective: nonzero(4),
            subject: nonzero(5),
        };
        let payload_digest = must_digest(&request);
        NduControlRequestV1::ExternalAdmissionV2 {
            schema_version: NduControlRequestV1::EXTERNAL_ADMISSION_SCHEMA_VERSION_V2,
            request_id: "request-1".to_string(),
            idempotency_key: "idem-1".to_string(),
            caller_id: "control-plane".to_string(),
            issued_at_unix_ms: 1_000,
            deadline_unix_ms: 2_000,
            host_generation: 7,
            fence_digest: nonzero(1),
            revocation_head_digest: nonzero(2),
            payload_digest,
            request: Box::new(request),
            extensions: Vec::new(),
        }
    }

    #[test]
    fn external_admission_rejects_unknown_critical_and_expired_envelopes() {
        let mut value = admission();
        if let NduControlRequestV1::ExternalAdmissionV2 { extensions, .. } = &mut value {
            extensions.push(("future-required".to_string(), true, nonzero(6)));
        } else {
            panic!("admission fixture changed")
        }
        assert_eq!(
            value.validate_external_admission_v2(512, 1_500, &BTreeSet::new()),
            Err("NDU-ADMIT-007")
        );
        if let NduControlRequestV1::ExternalAdmissionV2 {
            extensions,
            deadline_unix_ms,
            ..
        } = &mut value
        {
            extensions.clear();
            *deadline_unix_ms = 1_499;
        } else {
            panic!("admission fixture changed")
        }
        assert_eq!(
            value.validate_external_admission_v2(512, 1_500, &BTreeSet::new()),
            Err("NDU-ADMIT-004")
        );
    }

    #[test]
    fn payload_digest_binds_the_exact_inner_request() {
        let mut value = admission();
        if let NduControlRequestV1::ExternalAdmissionV2 { request, .. } = &mut value {
            *request = Box::new(NduControlRequestV1::Outcome {
                identity: nonzero(9),
            });
        } else {
            panic!("admission fixture changed")
        }
        assert_eq!(
            value.validate_external_admission_v2(512, 1_500, &BTreeSet::new()),
            Err("NDU-ADMIT-006")
        );
    }

    #[test]
    fn extension_order_is_canonical_and_duplicate_free() {
        let mut value = admission();
        if let NduControlRequestV1::ExternalAdmissionV2 { extensions, .. } = &mut value {
            *extensions = vec![
                ("z".to_string(), false, nonzero(7)),
                ("a".to_string(), false, nonzero(8)),
            ];
        } else {
            panic!("admission fixture changed")
        }
        assert_eq!(
            value.validate_external_admission_v2(512, 1_500, &BTreeSet::new()),
            Err("NDU-ADMIT-007")
        );
    }

    #[test]
    fn nested_admission_is_not_a_legal_payload() {
        let nested = admission();
        assert_eq!(nested.canonical_payload_digest_v2(), Err("NDU-ADMIT-006"));
    }

    #[test]
    fn external_admission_preserves_inner_mutation_classification() {
        let mutation = NduMutationV1 {
            operation: NduMutationOperationV1::AppendPreference,
            identity: nonzero(10),
            objective: nonzero(11),
            subject: nonzero(12),
            projection: nonzero(13),
            expected_predecessor: None,
        };
        let request = NduControlRequestV1::Prepare {
            mutation,
            expected_head: nonzero(14),
        };
        assert!(request.requires_mutation_admission());
        let payload_digest = must_digest(&request);
        let wrapped = NduControlRequestV1::ExternalAdmissionV2 {
            schema_version: NduControlRequestV1::EXTERNAL_ADMISSION_SCHEMA_VERSION_V2,
            request_id: "request-mutation".to_string(),
            idempotency_key: "idem-mutation".to_string(),
            caller_id: "control-plane".to_string(),
            issued_at_unix_ms: 1_000,
            deadline_unix_ms: 2_000,
            host_generation: 7,
            fence_digest: nonzero(1),
            revocation_head_digest: nonzero(2),
            payload_digest,
            request: Box::new(request),
            extensions: Vec::new(),
        };
        assert!(wrapped.requires_mutation_admission());
        assert!(!admission().requires_mutation_admission());
    }
}
