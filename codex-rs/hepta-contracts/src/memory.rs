use std::cmp::Ordering;

use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::Error as _;

use crate::Sha256Digest;
use crate::canonical::length_delimited_sha256;

pub const MEMORY_CONTRACT_SCHEMA_VERSION: u32 = 1;
pub const SCORE_SCALE_PPM: u32 = 1_000_000;

const MAX_QUERY_BYTES: u32 = 16 * 1024;
const MAX_CANDIDATES_SCANNED: u32 = 512;
const MAX_ITEMS: u32 = 16;
const MAX_ITEM_TOKENS: u32 = 999;
const MAX_TOTAL_TOKENS: u32 = 999;
const MAX_CONTEXT_WINDOW_PPM: u32 = 250_000;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct MemoryId(String);

impl MemoryId {
    pub fn for_content(scope: &MemoryScope, canonical_content: &[u8]) -> Self {
        Self(format!(
            "memory:v1:{}",
            length_delimited_sha256([
                scope.binding_sha256().as_str(),
                Sha256Digest::for_bytes(canonical_content).as_str(),
            ])
            .as_str()
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RevisionStamp {
    pub revision: u64,
    pub content_sha256: Sha256Digest,
}

impl RevisionStamp {
    pub fn new(revision: u64, canonical_content: &[u8]) -> Self {
        Self {
            revision,
            content_sha256: Sha256Digest::for_bytes(canonical_content),
        }
    }
}

/// Explicit authority scope for one memory record.
///
/// Every selector is represented only by a digest. Raw installation IDs, paths,
/// principals, account IDs, and channel IDs do not belong in this contract.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MemoryScope {
    pub installation_sha256: Sha256Digest,
    pub workspace_sha256: Sha256Digest,
    pub thread_sha256: Sha256Digest,
    pub principal_sha256: Sha256Digest,
}

impl MemoryScope {
    pub fn binding_sha256(&self) -> Sha256Digest {
        let inner = length_delimited_sha256([
            self.installation_sha256.as_str(),
            self.workspace_sha256.as_str(),
            self.thread_sha256.as_str(),
            self.principal_sha256.as_str(),
        ]);
        Sha256Digest::for_bytes(inner.as_str().as_bytes())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CrossThreadScope {
    ExactSourceThread { thread_sha256: Sha256Digest },
    WorkspaceThreads,
}

/// Cross-thread recall can only be represented by a typed capability binding.
/// There is intentionally no `allow_cross_session` boolean.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "authority", rename_all = "snake_case")]
pub enum RecallAuthority {
    SameThread,
    CrossThread {
        capability_sha256: Sha256Digest,
        scope: CrossThreadScope,
    },
}

impl RecallAuthority {
    fn permits(&self, request_scope: &MemoryScope, candidate_scope: &MemoryScope) -> bool {
        match self {
            Self::SameThread => request_scope == candidate_scope,
            // Cross-thread authority requires a private, single-use witness at
            // the execution boundary. A serialized digest is evidence data,
            // not an executable capability, so v1 requests stay fail-closed.
            Self::CrossThread { .. } => false,
        }
    }

    fn validate_executable(&self) -> Result<(), String> {
        match self {
            Self::SameThread => Ok(()),
            Self::CrossThread { .. } => {
                Err("cross-thread recall requires an authorized execution witness".to_string())
            }
        }
    }

    fn binding_sha256(&self) -> Sha256Digest {
        let binding = match self {
            Self::SameThread => length_delimited_sha256(["same_thread"]),
            Self::CrossThread {
                capability_sha256,
                scope: CrossThreadScope::ExactSourceThread { thread_sha256 },
            } => length_delimited_sha256([
                "cross_thread",
                "exact_source_thread",
                capability_sha256.as_str(),
                thread_sha256.as_str(),
            ]),
            Self::CrossThread {
                capability_sha256,
                scope: CrossThreadScope::WorkspaceThreads,
            } => length_delimited_sha256([
                "cross_thread",
                "workspace_threads",
                capability_sha256.as_str(),
            ]),
        };
        Sha256Digest::for_bytes(binding.as_str().as_bytes())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemorySourceKind {
    CodexStage1Summary,
    ReviewedHeptaMemory,
    LocalKgEpisode,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MemoryProvenance {
    pub source_kind: MemorySourceKind,
    pub source_id_sha256: Sha256Digest,
    pub source_revision: RevisionStamp,
    pub observed_at_unix_seconds: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum MemoryLifecycle {
    Active,
    Superseded { successor_memory_id: MemoryId },
    Tombstoned { reason_code: String },
    Expired { expired_at_unix_seconds: i64 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MemoryRevision {
    pub schema_version: u32,
    pub memory_id: MemoryId,
    pub revision: RevisionStamp,
    pub scope: MemoryScope,
    pub provenance: MemoryProvenance,
    pub lifecycle: MemoryLifecycle,
    pub valid_until_unix_seconds: Option<i64>,
}

impl MemoryRevision {
    /// Recomputes the stable memory identity and content revision from the
    /// trusted canonical content supplied by the source adapter.
    pub fn validate_content_binding(&self, canonical_content: &[u8]) -> Result<(), String> {
        if self.schema_version != MEMORY_CONTRACT_SCHEMA_VERSION {
            return Err("unsupported memory revision schema version".to_string());
        }
        if self.revision.content_sha256 != Sha256Digest::for_bytes(canonical_content) {
            return Err("memory revision content digest does not match source content".to_string());
        }
        if self.memory_id != MemoryId::for_content(&self.scope, canonical_content) {
            return Err("memory identity does not match its scope and source content".to_string());
        }
        Ok(())
    }

    pub fn recall_eligibility(
        &self,
        request: &RecallRequest,
        now_unix_seconds: i64,
    ) -> RecallEligibility {
        if self.schema_version != MEMORY_CONTRACT_SCHEMA_VERSION {
            return RecallEligibility::UnsupportedSchema;
        }
        if !matches!(self.lifecycle, MemoryLifecycle::Active) {
            return RecallEligibility::Inactive;
        }
        if self
            .valid_until_unix_seconds
            .is_some_and(|deadline| deadline <= now_unix_seconds)
        {
            return RecallEligibility::Expired;
        }
        if !request.authority.permits(&request.scope, &self.scope) {
            return RecallEligibility::ScopeDenied;
        }
        RecallEligibility::Eligible
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallEligibility {
    Eligible,
    UnsupportedSchema,
    Inactive,
    Expired,
    ScopeDenied,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct QueryFingerprint {
    sha256: Sha256Digest,
    byte_len: u32,
}

impl QueryFingerprint {
    pub fn for_query(query: &[u8]) -> Result<Self, String> {
        let byte_len = u32::try_from(query.len())
            .map_err(|_| "memory recall query length exceeds u32".to_string())?;
        if byte_len == 0 {
            return Err("memory recall query must not be empty".to_string());
        }
        Ok(Self {
            sha256: Sha256Digest::for_bytes(query),
            byte_len,
        })
    }

    pub fn sha256(&self) -> &Sha256Digest {
        &self.sha256
    }

    pub fn byte_len(&self) -> u32 {
        self.byte_len
    }

    fn validate(&self) -> Result<(), String> {
        if self.byte_len == 0 || self.byte_len > MAX_QUERY_BYTES {
            return Err(format!(
                "memory recall query byte length must be within 1..={MAX_QUERY_BYTES}"
            ));
        }
        Ok(())
    }
}

#[derive(Deserialize)]
struct QueryFingerprintWire {
    sha256: Sha256Digest,
    byte_len: u32,
}

impl<'de> Deserialize<'de> for QueryFingerprint {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = QueryFingerprintWire::deserialize(deserializer)?;
        let query = Self {
            sha256: wire.sha256,
            byte_len: wire.byte_len,
        };
        query.validate().map_err(D::Error::custom)?;
        Ok(query)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RecallLimits {
    max_query_bytes: u32,
    max_candidates_scanned: u32,
    max_items_per_source: u32,
    max_items: u32,
    max_item_tokens: u32,
    max_total_tokens: u32,
    max_context_window_ppm: u32,
}

impl RecallLimits {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        max_query_bytes: u32,
        max_candidates_scanned: u32,
        max_items_per_source: u32,
        max_items: u32,
        max_item_tokens: u32,
        max_total_tokens: u32,
        max_context_window_ppm: u32,
    ) -> Result<Self, String> {
        let limits = Self {
            max_query_bytes,
            max_candidates_scanned,
            max_items_per_source,
            max_items,
            max_item_tokens,
            max_total_tokens,
            max_context_window_ppm,
        };
        limits.validate()?;
        Ok(limits)
    }

    pub fn conservative_default() -> Self {
        Self {
            max_query_bytes: 4 * 1024,
            max_candidates_scanned: 128,
            max_items_per_source: 2,
            max_items: 8,
            max_item_tokens: 512,
            max_total_tokens: 999,
            max_context_window_ppm: 100_000,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        let bounded = [
            ("max_query_bytes", self.max_query_bytes, MAX_QUERY_BYTES),
            (
                "max_candidates_scanned",
                self.max_candidates_scanned,
                MAX_CANDIDATES_SCANNED,
            ),
            ("max_items_per_source", self.max_items_per_source, MAX_ITEMS),
            ("max_items", self.max_items, MAX_ITEMS),
            ("max_item_tokens", self.max_item_tokens, MAX_ITEM_TOKENS),
            ("max_total_tokens", self.max_total_tokens, MAX_TOTAL_TOKENS),
            (
                "max_context_window_ppm",
                self.max_context_window_ppm,
                MAX_CONTEXT_WINDOW_PPM,
            ),
        ];
        for (name, value, maximum) in bounded {
            if value == 0 || value > maximum {
                return Err(format!("{name} must be within 1..={maximum}"));
            }
        }
        if self.max_items_per_source > self.max_items {
            return Err("max_items_per_source must not exceed max_items".to_string());
        }
        if self.max_item_tokens > self.max_total_tokens {
            return Err("max_item_tokens must not exceed max_total_tokens".to_string());
        }
        Ok(())
    }

    pub fn permits_query(&self, query: &QueryFingerprint) -> bool {
        query.byte_len <= self.max_query_bytes
    }

    pub fn max_query_bytes(&self) -> u32 {
        self.max_query_bytes
    }

    pub fn max_candidates_scanned(&self) -> u32 {
        self.max_candidates_scanned
    }

    pub fn max_items_per_source(&self) -> u32 {
        self.max_items_per_source
    }

    pub fn max_items(&self) -> u32 {
        self.max_items
    }

    pub fn max_item_tokens(&self) -> u32 {
        self.max_item_tokens
    }

    pub fn max_total_tokens(&self) -> u32 {
        self.max_total_tokens
    }

    pub fn max_context_window_ppm(&self) -> u32 {
        self.max_context_window_ppm
    }

    fn binding_sha256(&self) -> Sha256Digest {
        let max_query_bytes = self.max_query_bytes.to_string();
        let max_candidates_scanned = self.max_candidates_scanned.to_string();
        let max_items_per_source = self.max_items_per_source.to_string();
        let max_items = self.max_items.to_string();
        let max_item_tokens = self.max_item_tokens.to_string();
        let max_total_tokens = self.max_total_tokens.to_string();
        let max_context_window_ppm = self.max_context_window_ppm.to_string();
        let inner = length_delimited_sha256([
            max_query_bytes.as_str(),
            max_candidates_scanned.as_str(),
            max_items_per_source.as_str(),
            max_items.as_str(),
            max_item_tokens.as_str(),
            max_total_tokens.as_str(),
            max_context_window_ppm.as_str(),
        ]);
        Sha256Digest::for_bytes(inner.as_str().as_bytes())
    }
}

#[derive(Deserialize)]
struct RecallLimitsWire {
    max_query_bytes: u32,
    max_candidates_scanned: u32,
    max_items_per_source: u32,
    max_items: u32,
    max_item_tokens: u32,
    max_total_tokens: u32,
    max_context_window_ppm: u32,
}

impl<'de> Deserialize<'de> for RecallLimits {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = RecallLimitsWire::deserialize(deserializer)?;
        Self::new(
            wire.max_query_bytes,
            wire.max_candidates_scanned,
            wire.max_items_per_source,
            wire.max_items,
            wire.max_item_tokens,
            wire.max_total_tokens,
            wire.max_context_window_ppm,
        )
        .map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RecallRequestId(String);

impl RecallRequestId {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RecallRequest {
    pub schema_version: u32,
    pub request_id: RecallRequestId,
    pub turn_sha256: Sha256Digest,
    pub scope: MemoryScope,
    pub authority: RecallAuthority,
    pub query: QueryFingerprint,
    pub limits: RecallLimits,
}

impl RecallRequest {
    pub fn new(
        turn_id: &str,
        scope: MemoryScope,
        authority: RecallAuthority,
        query: &[u8],
        limits: RecallLimits,
    ) -> Result<Self, String> {
        limits.validate()?;
        authority.validate_executable()?;
        let query = QueryFingerprint::for_query(query)?;
        if !limits.permits_query(&query) {
            return Err("memory recall query exceeds configured byte budget".to_string());
        }
        let turn_sha256 = Sha256Digest::for_bytes(turn_id.as_bytes());
        let mut request = Self {
            schema_version: MEMORY_CONTRACT_SCHEMA_VERSION,
            request_id: RecallRequestId(String::new()),
            turn_sha256,
            scope,
            authority,
            query,
            limits,
        };
        request.request_id = request.expected_request_id();
        Ok(request)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != MEMORY_CONTRACT_SCHEMA_VERSION {
            return Err("unsupported memory recall schema version".to_string());
        }
        self.query.validate()?;
        self.limits.validate()?;
        self.authority.validate_executable()?;
        if !self.limits.permits_query(&self.query) {
            return Err("memory recall query exceeds configured byte budget".to_string());
        }
        if self.request_id != self.expected_request_id() {
            return Err("memory recall request identity does not match its binding".to_string());
        }
        Ok(())
    }

    fn expected_request_id(&self) -> RecallRequestId {
        RecallRequestId(format!(
            "memory-recall:v1:{}",
            length_delimited_sha256([
                self.schema_version.to_string().as_str(),
                self.turn_sha256.as_str(),
                self.scope.binding_sha256().as_str(),
                self.authority.binding_sha256().as_str(),
                self.query.sha256().as_str(),
                self.limits.binding_sha256().as_str(),
            ])
            .as_str()
        ))
    }
}

#[derive(Deserialize)]
struct RecallRequestWire {
    schema_version: u32,
    request_id: RecallRequestId,
    turn_sha256: Sha256Digest,
    scope: MemoryScope,
    authority: RecallAuthority,
    query: QueryFingerprint,
    limits: RecallLimits,
}

impl<'de> Deserialize<'de> for RecallRequest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = RecallRequestWire::deserialize(deserializer)?;
        let request = Self {
            schema_version: wire.schema_version,
            request_id: wire.request_id,
            turn_sha256: wire.turn_sha256,
            scope: wire.scope,
            authority: wire.authority,
            query: wire.query,
            limits: wire.limits,
        };
        request.validate().map_err(D::Error::custom)?;
        Ok(request)
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RecallScorePpm(u32);

impl RecallScorePpm {
    pub fn new(value: u32) -> Result<Self, String> {
        if value > SCORE_SCALE_PPM {
            return Err(format!("recall score must be within 0..={SCORE_SCALE_PPM}"));
        }
        Ok(Self(value))
    }

    pub fn get(self) -> u32 {
        self.0
    }
}

impl<'de> Deserialize<'de> for RecallScorePpm {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(u32::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RankedMemoryRef {
    pub memory_id: MemoryId,
    pub revision: RevisionStamp,
    pub score_ppm: RecallScorePpm,
    pub source_updated_at_unix_seconds: i64,
}

impl RankedMemoryRef {
    /// Ordering for deterministic ranking: score descending, source recency
    /// descending, then stable memory identity ascending.
    pub fn stable_cmp(left: &Self, right: &Self) -> Ordering {
        right
            .score_ppm
            .cmp(&left.score_ppm)
            .then_with(|| {
                right
                    .source_updated_at_unix_seconds
                    .cmp(&left.source_updated_at_unix_seconds)
            })
            .then_with(|| left.memory_id.cmp(&right.memory_id))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AttachmentTrust {
    QuotedUntrustedReference,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MemoryAttachmentMetadata {
    pub schema_version: u32,
    pub request_id: RecallRequestId,
    pub memory_id: MemoryId,
    pub revision: RevisionStamp,
    pub provenance: MemoryProvenance,
    pub rendered_content_sha256: Sha256Digest,
    pub rendered_tokens: u32,
    pub trust: AttachmentTrust,
}

impl MemoryAttachmentMetadata {
    pub fn citation(&self) -> String {
        format!(
            "{}@{}:{}",
            self.memory_id.as_str(),
            self.revision.revision,
            self.revision.content_sha256.as_str()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(value.as_bytes())
    }

    fn scope(thread: &str) -> MemoryScope {
        MemoryScope {
            installation_sha256: digest("installation"),
            workspace_sha256: digest("workspace"),
            thread_sha256: digest(thread),
            principal_sha256: digest("principal"),
        }
    }

    fn request(authority: RecallAuthority) -> RecallRequest {
        RecallRequest::new(
            "turn-1",
            scope("thread-1"),
            authority,
            b"bounded query",
            RecallLimits::conservative_default(),
        )
        .expect("valid request")
    }

    fn revision(candidate_scope: MemoryScope, lifecycle: MemoryLifecycle) -> MemoryRevision {
        MemoryRevision {
            schema_version: MEMORY_CONTRACT_SCHEMA_VERSION,
            memory_id: MemoryId::for_content(&candidate_scope, b"reviewed summary"),
            revision: RevisionStamp::new(1, b"reviewed summary"),
            scope: candidate_scope,
            provenance: MemoryProvenance {
                source_kind: MemorySourceKind::CodexStage1Summary,
                source_id_sha256: digest("source"),
                source_revision: RevisionStamp::new(1, b"stage1"),
                observed_at_unix_seconds: 100,
            },
            lifecycle,
            valid_until_unix_seconds: Some(200),
        }
    }

    #[test]
    fn cross_thread_recall_stays_disabled_without_an_execution_witness() {
        let candidate = revision(scope("thread-2"), MemoryLifecycle::Active);
        assert_eq!(
            candidate.recall_eligibility(&request(RecallAuthority::SameThread), 150),
            RecallEligibility::ScopeDenied
        );

        assert!(
            RecallRequest::new(
                "turn-1",
                scope("thread-1"),
                RecallAuthority::CrossThread {
                    capability_sha256: digest("caller-controlled-digest"),
                    scope: CrossThreadScope::ExactSourceThread {
                        thread_sha256: digest("thread-2"),
                    },
                },
                b"bounded query",
                RecallLimits::conservative_default(),
            )
            .is_err(),
            "a serialized digest must not act as cross-thread authority"
        );

        let mut forged = request(RecallAuthority::SameThread);
        forged.authority = RecallAuthority::CrossThread {
            capability_sha256: digest("caller-controlled-digest"),
            scope: CrossThreadScope::WorkspaceThreads,
        };
        forged.request_id = forged.expected_request_id();
        let serialized = serde_json::to_value(forged).expect("serialize forged request");
        assert!(
            serde_json::from_value::<RecallRequest>(serialized).is_err(),
            "deserialization must not rehydrate executable cross-thread authority"
        );
    }

    #[test]
    fn inactive_and_expired_revisions_are_not_recalled() {
        let same_thread = request(RecallAuthority::SameThread);
        let tombstoned = revision(
            scope("thread-1"),
            MemoryLifecycle::Tombstoned {
                reason_code: "operator_delete".to_string(),
            },
        );
        assert_eq!(
            tombstoned.recall_eligibility(&same_thread, 150),
            RecallEligibility::Inactive
        );

        let expired = revision(scope("thread-1"), MemoryLifecycle::Active);
        assert_eq!(
            expired.recall_eligibility(&same_thread, 200),
            RecallEligibility::Expired
        );
    }

    #[test]
    fn limits_reject_zero_unbounded_and_incoherent_values() {
        assert!(RecallLimits::new(0, 1, 1, 1, 1, 1, 1).is_err());
        assert!(RecallLimits::new(1, MAX_CANDIDATES_SCANNED + 1, 1, 1, 1, 1, 1).is_err());
        assert!(RecallLimits::new(1, 1, 2, 1, 1, 1, 1).is_err());
        assert!(RecallLimits::new(1, 1, 1, 1, 2, 1, 1).is_err());
        assert!(RecallScorePpm::new(SCORE_SCALE_PPM + 1).is_err());
    }

    #[test]
    fn request_identity_is_stable_and_query_is_only_fingerprinted() {
        let first = request(RecallAuthority::SameThread);
        let second = request(RecallAuthority::SameThread);
        assert_eq!(first.request_id, second.request_id);
        assert!(first.request_id.as_str().starts_with("memory-recall:v1:"));
        assert_eq!(first.query.byte_len(), "bounded query".len() as u32);
        assert_eq!(first.query.sha256(), &digest("bounded query"));
        assert!(first.validate().is_ok());

        assert!(
            RecallRequest::new(
                "turn-1",
                scope("thread-1"),
                RecallAuthority::CrossThread {
                    capability_sha256: digest("capability"),
                    scope: CrossThreadScope::WorkspaceThreads,
                },
                b"bounded query",
                RecallLimits::conservative_default(),
            )
            .is_err()
        );

        let serialized = serde_json::to_string(&first).expect("serialize recall request");
        assert!(!serialized.contains("bounded query"));
    }

    #[test]
    fn memory_ids_and_legacy_nested_bindings_have_fixed_canonical_oracles() {
        let exact_scope = scope("thread-1");
        let same_thread = RecallAuthority::SameThread;
        let exact_source_thread = RecallAuthority::CrossThread {
            capability_sha256: digest("capability"),
            scope: CrossThreadScope::ExactSourceThread {
                thread_sha256: digest("thread-2"),
            },
        };
        let workspace_threads = RecallAuthority::CrossThread {
            capability_sha256: digest("capability"),
            scope: CrossThreadScope::WorkspaceThreads,
        };
        let limits = RecallLimits::conservative_default();
        let recall = request(RecallAuthority::SameThread);

        // These v1 bindings intentionally freeze H(hex(H(framed parts)))
        // compatibility. A future single-SHA helper must not flatten them
        // without a new schema/domain and corresponding ID version.
        assert_eq!(
            exact_scope.binding_sha256().as_str(),
            "ced71284e7542b2db6686bc3b9c37e54a27c4d88135094a5b70c0e92354e623d"
        );
        assert_eq!(
            MemoryId::for_content(&exact_scope, b"reviewed summary").as_str(),
            "memory:v1:aef81743b474c2324e8d04904ad491a7d768be99831ce400d71c395e05453b1a"
        );
        assert_eq!(
            same_thread.binding_sha256().as_str(),
            "1caf4a2a9681366d26f4f072c36e0e264b072e8a2673297aed91fb8a2de7ccdd"
        );
        assert_eq!(
            exact_source_thread.binding_sha256().as_str(),
            "eeafcebef8c6e9c8ce177a7b563f726085ccce620755df04805ac8ce7eb6ba0b"
        );
        assert_eq!(
            workspace_threads.binding_sha256().as_str(),
            "eb30574f30db2ee50fb14527e12e266975fe09670b286e30e886137657ecebd4"
        );
        assert_eq!(
            limits.binding_sha256().as_str(),
            "660381145bcfc930e963af3e9f206df70546a8bbab899d46d610b0b5ab8e2128"
        );
        assert_eq!(
            recall.request_id.as_str(),
            "memory-recall:v1:14fafb6f3ab3e75219c2641c9dc1d1db301094ed0b86b6450af4655cbbc25e82"
        );
    }

    #[test]
    fn deserialization_rejects_invalid_limits_scores_and_request_binding() {
        assert!(serde_json::from_str::<RecallScorePpm>("1000001").is_err());
        assert!(
            serde_json::from_str::<RecallLimits>(
                r#"{
                    "max_query_bytes":4096,
                    "max_candidates_scanned":128,
                    "max_items_per_source":9,
                    "max_items":8,
                    "max_item_tokens":512,
                    "max_total_tokens":999,
                    "max_context_window_ppm":100000
                }"#,
            )
            .is_err()
        );

        let mut value = serde_json::to_value(request(RecallAuthority::SameThread))
            .expect("serialize recall request");
        value["request_id"] =
            serde_json::Value::String(format!("memory-recall:v1:{}", "0".repeat(64)));
        assert!(serde_json::from_value::<RecallRequest>(value).is_err());
    }

    #[test]
    fn ranking_is_integer_and_has_stable_tie_breaks() {
        let candidate_scope = scope("thread-1");
        let mut ranked = [
            RankedMemoryRef {
                memory_id: MemoryId::for_content(&candidate_scope, b"b"),
                revision: RevisionStamp::new(1, b"b"),
                score_ppm: RecallScorePpm::new(700_000).expect("score"),
                source_updated_at_unix_seconds: 20,
            },
            RankedMemoryRef {
                memory_id: MemoryId::for_content(&candidate_scope, b"high"),
                revision: RevisionStamp::new(1, b"high"),
                score_ppm: RecallScorePpm::new(800_000).expect("score"),
                source_updated_at_unix_seconds: 10,
            },
            RankedMemoryRef {
                memory_id: MemoryId::for_content(&candidate_scope, b"a"),
                revision: RevisionStamp::new(1, b"a"),
                score_ppm: RecallScorePpm::new(700_000).expect("score"),
                source_updated_at_unix_seconds: 20,
            },
        ];
        ranked.sort_by(RankedMemoryRef::stable_cmp);

        assert_eq!(ranked[0].score_ppm.get(), 800_000);
        assert!(ranked[1].memory_id < ranked[2].memory_id);
    }

    #[test]
    fn attachment_is_always_typed_as_quoted_untrusted_reference() {
        let candidate_scope = scope("thread-1");
        let memory_id = MemoryId::for_content(&candidate_scope, b"reviewed summary");
        let metadata = MemoryAttachmentMetadata {
            schema_version: MEMORY_CONTRACT_SCHEMA_VERSION,
            request_id: request(RecallAuthority::SameThread).request_id,
            memory_id: memory_id.clone(),
            revision: RevisionStamp::new(1, b"reviewed summary"),
            provenance: revision(candidate_scope, MemoryLifecycle::Active).provenance,
            rendered_content_sha256: digest("quoted content"),
            rendered_tokens: 10,
            trust: AttachmentTrust::QuotedUntrustedReference,
        };
        assert_eq!(metadata.trust, AttachmentTrust::QuotedUntrustedReference);
        assert!(metadata.citation().starts_with(memory_id.as_str()));
    }
}
