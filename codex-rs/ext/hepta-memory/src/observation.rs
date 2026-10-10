use std::sync::Mutex;
use std::sync::PoisonError;

use codex_extension_api::ExtensionData;
use codex_hepta_contracts::RankedMemoryRef;
use codex_hepta_contracts::RecallRequest;
use codex_hepta_contracts::RecallRequestId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::RecallCounts;
use codex_hepta_memory::RecallObservation;
use codex_hepta_memory::RecallObservationReason;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::framing::hash_part;

pub const HEPTA_MEMORY_SHADOW_OBSERVATION_SCHEMA_VERSION: u32 = 1;

const UNSCANNED_CANDIDATE_SET_DOMAIN: &[u8] = b"hepta-memory-extension:candidate-set:v1:unscanned";

/// Digest-only identity for one shadow turn observation.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ShadowRecallTurnObservationId(String);

impl ShadowRecallTurnObservationId {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Terminal reason for one shadow recall attempt.
///
/// Backend failures are distinct from a valid recall that selected no memory;
/// this prevents shadow telemetry from misclassifying unavailable state as an
/// empty candidate set.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ShadowRecallTurnReason {
    Recall { reason: RecallObservationReason },
    BackendMissing,
    BackendUnavailable,
    BackendTimeout,
    SourceBindingMismatch,
    InvalidSourceTime,
}

impl ShadowRecallTurnReason {
    pub(crate) fn stable_tag(&self) -> &'static str {
        match self {
            Self::Recall { reason } => match reason {
                RecallObservationReason::Ranked => "recall:ranked",
                RecallObservationReason::EmptyQuery => "recall:empty_query",
                RecallObservationReason::SecretLikeQuery => "recall:secret_like_query",
                RecallObservationReason::InvalidRequest => "recall:invalid_request",
                RecallObservationReason::QueryBudgetExceeded => "recall:query_budget_exceeded",
                RecallObservationReason::QueryBindingMismatch => "recall:query_binding_mismatch",
                RecallObservationReason::CandidateBudgetExceeded => {
                    "recall:candidate_budget_exceeded"
                }
                RecallObservationReason::CandidateIdentityConflict => {
                    "recall:candidate_identity_conflict"
                }
                RecallObservationReason::NoEligibleCandidates => "recall:no_eligible_candidates",
                RecallObservationReason::NoLexicalMatch => "recall:no_lexical_match",
            },
            Self::BackendMissing => "backend_missing",
            Self::BackendUnavailable => "backend_unavailable",
            Self::BackendTimeout => "backend_timeout",
            Self::SourceBindingMismatch => "source_binding_mismatch",
            Self::InvalidSourceTime => "invalid_source_time",
        }
    }
}

/// Digest-only turn observation retained in [`ExtensionData`].
///
/// The ranked material is collapsed into `ranked_refs_sha256`; raw query,
/// summary, path, principal, installation, and source identifiers never enter
/// this value.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ShadowRecallTurnObservation {
    pub schema_version: u32,
    pub observation_id: ShadowRecallTurnObservationId,
    pub request_id: RecallRequestId,
    pub candidate_set_sha256: Sha256Digest,
    pub ranked_refs_sha256: Sha256Digest,
    pub counts: RecallCounts,
    pub reason: ShadowRecallTurnReason,
}

impl ShadowRecallTurnObservation {
    pub(crate) fn from_recall(observation: RecallObservation) -> Self {
        let ranked_refs_sha256 = ranked_refs_digest(&observation.ranked);
        let reason = ShadowRecallTurnReason::Recall {
            reason: observation.reason,
        };
        let observation_id = shadow_observation_id(
            &observation.request_id,
            &observation.candidate_set_sha256,
            &ranked_refs_sha256,
            &observation.counts,
            &reason,
        );
        Self {
            schema_version: HEPTA_MEMORY_SHADOW_OBSERVATION_SCHEMA_VERSION,
            observation_id,
            request_id: observation.request_id,
            candidate_set_sha256: observation.candidate_set_sha256,
            ranked_refs_sha256,
            counts: observation.counts,
            reason,
        }
    }

    pub(crate) fn failure(request: &RecallRequest, reason: ShadowRecallTurnReason) -> Self {
        let candidate_set_sha256 = Sha256Digest::for_bytes(UNSCANNED_CANDIDATE_SET_DOMAIN);
        let ranked_refs_sha256 = ranked_refs_digest(&[]);
        let counts = RecallCounts::default();
        let observation_id = shadow_observation_id(
            &request.request_id,
            &candidate_set_sha256,
            &ranked_refs_sha256,
            &counts,
            &reason,
        );
        Self {
            schema_version: HEPTA_MEMORY_SHADOW_OBSERVATION_SCHEMA_VERSION,
            observation_id,
            request_id: request.request_id.clone(),
            candidate_set_sha256,
            ranked_refs_sha256,
            counts,
            reason,
        }
    }
}

#[derive(Debug)]
struct ShadowRecallTurnSlot {
    observation: Mutex<Option<ShadowRecallTurnObservation>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ShadowRecallObservationCommitDisposition {
    Inserted,
    ExactReplay,
    Conflict,
}

/// Returns the immutable shadow observation committed for this exact turn.
pub fn shadow_recall_turn_observation(
    turn_store: &ExtensionData,
) -> Option<ShadowRecallTurnObservation> {
    let slot = turn_store.get::<ShadowRecallTurnSlot>()?;
    slot.observation
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .clone()
}

pub(crate) fn commit_turn_observation(
    turn_store: &ExtensionData,
    observation: ShadowRecallTurnObservation,
) -> ShadowRecallObservationCommitDisposition {
    let slot = turn_store.get_or_init(|| ShadowRecallTurnSlot {
        observation: Mutex::new(None),
    });
    let mut stored = slot
        .observation
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    match stored.as_ref() {
        None => {
            *stored = Some(observation);
            ShadowRecallObservationCommitDisposition::Inserted
        }
        Some(existing) if existing == &observation => {
            ShadowRecallObservationCommitDisposition::ExactReplay
        }
        Some(_) => ShadowRecallObservationCommitDisposition::Conflict,
    }
}

pub(crate) fn shadow_observation_id(
    request_id: &RecallRequestId,
    candidate_set_sha256: &Sha256Digest,
    ranked_refs_sha256: &Sha256Digest,
    counts: &RecallCounts,
    reason: &ShadowRecallTurnReason,
) -> ShadowRecallTurnObservationId {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, b"hepta-memory-extension:turn-observation:v1");
    hash_part(
        &mut hasher,
        &HEPTA_MEMORY_SHADOW_OBSERVATION_SCHEMA_VERSION.to_be_bytes(),
    );
    hash_part(&mut hasher, request_id.as_str().as_bytes());
    hash_part(&mut hasher, candidate_set_sha256.as_str().as_bytes());
    hash_part(&mut hasher, ranked_refs_sha256.as_str().as_bytes());
    for count in [
        counts.submitted,
        counts.scanned,
        counts.eligible,
        counts.matched,
        counts.selected,
        counts.unsupported_schema,
        counts.inactive,
        counts.expired,
        counts.scope_denied,
        counts.revision_mismatch,
        counts.invalid_binding,
        counts.summary_budget_exceeded,
        counts.secret_like_summary_excluded,
        counts.item_token_budget_exceeded,
        counts.source_budget_excluded,
        counts.total_token_budget_excluded,
    ] {
        hash_part(&mut hasher, &count.to_be_bytes());
    }
    hash_part(&mut hasher, reason.stable_tag().as_bytes());
    let digest = Sha256Digest::for_bytes(&hasher.finalize());
    ShadowRecallTurnObservationId(format!("memory-shadow:v1:{}", digest.as_str()))
}

pub(crate) fn ranked_refs_digest(ranked: &[RankedMemoryRef]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, b"hepta-memory:ranked-refs:v1");
    for ranked_ref in ranked {
        hash_part(&mut hasher, ranked_ref.memory_id.as_str().as_bytes());
        hash_part(&mut hasher, &ranked_ref.revision.revision.to_be_bytes());
        hash_part(
            &mut hasher,
            ranked_ref.revision.content_sha256.as_str().as_bytes(),
        );
        hash_part(&mut hasher, &ranked_ref.score_ppm.get().to_be_bytes());
        hash_part(
            &mut hasher,
            &ranked_ref.source_updated_at_unix_seconds.to_be_bytes(),
        );
    }
    Sha256Digest::for_bytes(&hasher.finalize())
}
