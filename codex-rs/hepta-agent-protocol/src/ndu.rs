//! Bounded local control transport, never a substitute for final-use authority.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;

pub const NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION: u32 = 2;
pub const MAX_NDU_EXTERNAL_ADMISSION_BYTES: usize = 32 * 1024;
pub const MAX_NDU_CRITICAL_EXTENSIONS: usize = 16;
pub const MAX_NDU_REPLAY_ENTRIES: usize = 4096;
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
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduAdmissionExtensionV2 {
    pub name: String,
    pub critical: bool,
    pub value_digest: [u8; 32],
}

/// Versioned external admission envelope. It binds transport replay identity,
/// caller, host fence/revocation context and the canonical payload digest. A
/// final-use grant is still required inside `Apply`; this envelope never mints
/// or widens authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduExternalAdmissionEnvelopeV2 {
    pub schema_version: u32,
    pub request_id: String,
    pub idempotency_key: String,
    pub caller_id: String,
    pub issued_at_unix_ms: u64,
    pub deadline_unix_ms: u64,
    pub host_generation: u64,
    pub fence_digest: [u8; 32],
    pub revocation_head_digest: [u8; 32],
    pub payload_digest: [u8; 32],
    pub request: NduControlRequestV1,
    #[serde(default)]
    pub extensions: Vec<NduAdmissionExtensionV2>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NduExternalAdmissionErrorV2 {
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
    ReplayConflict,
    ReplayWindowFull,
}

impl NduExternalAdmissionErrorV2 {
    #[must_use]
    pub const fn code(self) -> &'static str {
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
            Self::ReplayConflict => "NDU-ADMIT-008",
            Self::ReplayWindowFull => "NDU-ADMIT-009",
        }
    }
}

impl fmt::Display for NduExternalAdmissionErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {self:?}", self.code())
    }
}

impl StdError for NduExternalAdmissionErrorV2 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduReplayDispositionV2 {
    Accepted,
    ExactDuplicate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ReplayBindingV2 {
    request_id: String,
    payload_digest: [u8; 32],
    host_generation: u64,
    fence_digest: [u8; 32],
    revocation_head_digest: [u8; 32],
    deadline_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduReplayWindowV2 {
    entries: BTreeMap<(String, String), ReplayBindingV2>,
    capacity: usize,
}

impl Default for NduReplayWindowV2 {
    fn default() -> Self {
        Self::new(MAX_NDU_REPLAY_ENTRIES)
    }
}

impl NduReplayWindowV2 {
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            entries: BTreeMap::new(),
            capacity: capacity.clamp(1, MAX_NDU_REPLAY_ENTRIES),
        }
    }

    pub fn admit(
        &mut self,
        envelope: &NduExternalAdmissionEnvelopeV2,
        encoded_len: usize,
        now_unix_ms: u64,
        supported_critical_extensions: &BTreeSet<String>,
    ) -> Result<NduReplayDispositionV2, NduExternalAdmissionErrorV2> {
        validate_ndu_external_admission_v2(
            envelope,
            encoded_len,
            now_unix_ms,
            supported_critical_extensions,
        )?;
        self.entries
            .retain(|_, binding| binding.deadline_unix_ms >= now_unix_ms);
        let key = (
            envelope.caller_id.clone(),
            envelope.idempotency_key.clone(),
        );
        let incoming = ReplayBindingV2 {
            request_id: envelope.request_id.clone(),
            payload_digest: envelope.payload_digest,
            host_generation: envelope.host_generation,
            fence_digest: envelope.fence_digest,
            revocation_head_digest: envelope.revocation_head_digest,
            deadline_unix_ms: envelope.deadline_unix_ms,
        };
        if let Some(existing) = self.entries.get(&key) {
            if existing == &incoming {
                return Ok(NduReplayDispositionV2::ExactDuplicate);
            }
            return Err(NduExternalAdmissionErrorV2::ReplayConflict);
        }
        if self.entries.len() >= self.capacity {
            return Err(NduExternalAdmissionErrorV2::ReplayWindowFull);
        }
        self.entries.insert(key, incoming);
        Ok(NduReplayDispositionV2::Accepted)
    }
}

pub fn validate_ndu_external_admission_v2(
    envelope: &NduExternalAdmissionEnvelopeV2,
    encoded_len: usize,
    now_unix_ms: u64,
    supported_critical_extensions: &BTreeSet<String>,
) -> Result<(), NduExternalAdmissionErrorV2> {
    if envelope.schema_version != NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION {
        return Err(NduExternalAdmissionErrorV2::UnsupportedSchema);
    }
    if encoded_len == 0 || encoded_len > MAX_NDU_EXTERNAL_ADMISSION_BYTES {
        return Err(NduExternalAdmissionErrorV2::EnvelopeTooLarge);
    }
    validate_text(&envelope.request_id, MAX_REQUEST_ID_BYTES)?;
    validate_text(&envelope.idempotency_key, MAX_REQUEST_ID_BYTES)?;
    validate_text(&envelope.caller_id, MAX_CALLER_ID_BYTES)?;
    if envelope.host_generation == 0
        || is_zero(&envelope.fence_digest)
        || is_zero(&envelope.revocation_head_digest)
    {
        return Err(NduExternalAdmissionErrorV2::InvalidHostContext);
    }
    if is_zero(&envelope.payload_digest) || !request_payload_is_bound(&envelope.request) {
        return Err(NduExternalAdmissionErrorV2::InvalidPayload);
    }
    if envelope.deadline_unix_ms <= envelope.issued_at_unix_ms
        || envelope.deadline_unix_ms - envelope.issued_at_unix_ms > MAX_ADMISSION_LIFETIME_MS
        || envelope.issued_at_unix_ms > now_unix_ms.saturating_add(MAX_CLOCK_SKEW_MS)
    {
        return Err(NduExternalAdmissionErrorV2::InvalidDeadline);
    }
    if now_unix_ms > envelope.deadline_unix_ms {
        return Err(NduExternalAdmissionErrorV2::Expired);
    }
    if envelope.extensions.len() > MAX_NDU_CRITICAL_EXTENSIONS {
        return Err(NduExternalAdmissionErrorV2::TooManyExtensions);
    }
    for extension in &envelope.extensions {
        validate_text(&extension.name, MAX_EXTENSION_NAME_BYTES)?;
        if is_zero(&extension.value_digest) {
            return Err(NduExternalAdmissionErrorV2::InvalidPayload);
        }
        if extension.critical && !supported_critical_extensions.contains(&extension.name) {
            return Err(NduExternalAdmissionErrorV2::UnknownCriticalExtension);
        }
    }
    if envelope
        .extensions
        .windows(2)
        .any(|pair| pair[0].name >= pair[1].name)
    {
        return Err(NduExternalAdmissionErrorV2::NonCanonicalExtensions);
    }
    Ok(())
}

fn validate_text(value: &str, maximum: usize) -> Result<(), NduExternalAdmissionErrorV2> {
    if value.is_empty() || value.len() > maximum || value.chars().any(char::is_control) {
        return Err(NduExternalAdmissionErrorV2::InvalidIdentity);
    }
    Ok(())
}

fn request_payload_is_bound(request: &NduControlRequestV1) -> bool {
    match request {
        NduControlRequestV1::Context => true,
        NduControlRequestV1::Prepare {
            mutation,
            expected_head,
        }
        | NduControlRequestV1::Apply {
            mutation,
            expected_head,
            ..
        } => mutation_is_bound(mutation) && !is_zero(expected_head),
        NduControlRequestV1::Selection { objective, subject } => {
            !is_zero(objective) && !is_zero(subject)
        }
        NduControlRequestV1::Outcome { identity } => !is_zero(identity),
    }
}

fn mutation_is_bound(mutation: &NduMutationV1) -> bool {
    !is_zero(&mutation.identity)
        && !is_zero(&mutation.objective)
        && !is_zero(&mutation.subject)
        && !is_zero(&mutation.projection)
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

    fn envelope() -> NduExternalAdmissionEnvelopeV2 {
        NduExternalAdmissionEnvelopeV2 {
            schema_version: NDU_EXTERNAL_ADMISSION_SCHEMA_VERSION,
            request_id: "request-1".to_string(),
            idempotency_key: "idem-1".to_string(),
            caller_id: "control-plane".to_string(),
            issued_at_unix_ms: 1_000,
            deadline_unix_ms: 2_000,
            host_generation: 7,
            fence_digest: nonzero(1),
            revocation_head_digest: nonzero(2),
            payload_digest: nonzero(3),
            request: NduControlRequestV1::Selection {
                objective: nonzero(4),
                subject: nonzero(5),
            },
            extensions: Vec::new(),
        }
    }

    #[test]
    fn external_admission_rejects_unknown_critical_and_expired_envelopes() {
        let mut value = envelope();
        value.extensions.push(NduAdmissionExtensionV2 {
            name: "future-required".to_string(),
            critical: true,
            value_digest: nonzero(6),
        });
        assert_eq!(
            validate_ndu_external_admission_v2(&value, 512, 1_500, &BTreeSet::new()),
            Err(NduExternalAdmissionErrorV2::UnknownCriticalExtension)
        );
        value.extensions.clear();
        assert_eq!(
            validate_ndu_external_admission_v2(&value, 512, 2_001, &BTreeSet::new()),
            Err(NduExternalAdmissionErrorV2::Expired)
        );
    }

    #[test]
    fn replay_window_accepts_exact_duplicate_but_rejects_conflicting_reuse() {
        let mut window = NduReplayWindowV2::new(4);
        let value = envelope();
        assert_eq!(
            window.admit(&value, 512, 1_500, &BTreeSet::new()),
            Ok(NduReplayDispositionV2::Accepted)
        );
        assert_eq!(
            window.admit(&value, 512, 1_500, &BTreeSet::new()),
            Ok(NduReplayDispositionV2::ExactDuplicate)
        );
        let mut conflict = value;
        conflict.payload_digest = nonzero(9);
        assert_eq!(
            window.admit(&conflict, 512, 1_500, &BTreeSet::new()),
            Err(NduExternalAdmissionErrorV2::ReplayConflict)
        );
    }

    #[test]
    fn extension_order_is_canonical_and_duplicate_free() {
        let mut value = envelope();
        value.extensions = vec![
            NduAdmissionExtensionV2 {
                name: "z".to_string(),
                critical: false,
                value_digest: nonzero(7),
            },
            NduAdmissionExtensionV2 {
                name: "a".to_string(),
                critical: false,
                value_digest: nonzero(8),
            },
        ];
        assert_eq!(
            validate_ndu_external_admission_v2(&value, 512, 1_500, &BTreeSet::new()),
            Err(NduExternalAdmissionErrorV2::NonCanonicalExtensions)
        );
    }
}
