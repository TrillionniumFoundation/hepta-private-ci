//! Contract-only seam for a provider-backed exactly-once effect.
//!
//! These types deliberately do not make any claim about a provider currently
//! supporting idempotency.  A provider must offer both a stable key transport
//! and a durable status lookup before an adapter may report the supported
//! capability.  The existing Codex HTTP and WebSocket adapters do not
//! implement this seam.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;

use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;

use crate::RequestBindingId;
use crate::Sha256Digest;
use crate::stable_id::parse_prefixed_sha256_id;

pub const PROVIDER_EFFECT_SCHEMA_VERSION: u32 = 1;

/// A pending intent that predates the coordinator call has no local witness
/// proving that this process owns the physical dispatch boundary.  Treat it
/// as an imported crash-window record and require status reconciliation before
/// any adapter call.
const PROVIDER_EFFECT_IMPORTED_PENDING_REASON: &str = "provider_imported_pending";

/// Provider capability required before a physical effect can be retried or
/// reconciled by key.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderEffectIdempotencyCapability {
    /// The provider contract does not expose key-based dedupe and lookup.
    #[default]
    Unsupported,
    /// The provider contract exposes a stable key, same-key conflict rules,
    /// and durable status lookup.  No current provider is marked this way.
    KeyAndStatusLookup,
}

/// Stable logical identity for one occurrence across physical send attempts.
///
/// The key intentionally excludes the per-send nonce and payload digest.  A
/// provider can therefore detect a same-key/different-payload conflict rather
/// than silently treating a changed payload as a new effect.  The payload
/// digest is carried separately by [`ProviderEffectIntent`] and
/// [`ProviderEffectAck`].
#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ProviderEffectKey(String);

impl ProviderEffectKey {
    /// Derives an occurrence-stable key from secret-free provider scope,
    /// caller-owned occurrence identity, and the logical request binding.
    ///
    /// `provider_scope` and `occurrence_id` must not contain credentials or
    /// request payload.  They are length-delimited before hashing.
    pub fn for_occurrence(
        provider_scope: &str,
        occurrence_id: &str,
        request_binding_id: &RequestBindingId,
    ) -> Result<Self, ProviderEffectBindingError> {
        validate_non_empty("provider scope", provider_scope)?;
        validate_non_empty("occurrence id", occurrence_id)?;
        Ok(Self(format!(
            "provider-effect:v1:{}",
            digest_parts([
                "provider-effect:v1",
                provider_scope,
                occurrence_id,
                request_binding_id.as_str(),
            ])
        )))
    }

    pub fn parse(value: impl Into<String>) -> Result<Self, ProviderEffectBindingError> {
        parse_prefixed_sha256_id(value, "provider-effect:v1:", "provider effect")
            .map(Self)
            .map_err(ProviderEffectBindingError::InvalidKey)
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Durable local intent that must exist before a provider seam is crossed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProviderEffectIntent {
    pub schema_version: u32,
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
}

impl ProviderEffectIntent {
    pub fn new(key: ProviderEffectKey, payload_sha256: Sha256Digest) -> Self {
        Self {
            schema_version: PROVIDER_EFFECT_SCHEMA_VERSION,
            key,
            payload_sha256,
        }
    }

    pub fn validate(&self) -> Result<(), ProviderEffectBindingError> {
        if self.schema_version != PROVIDER_EFFECT_SCHEMA_VERSION {
            return Err(ProviderEffectBindingError::SchemaVersion);
        }
        ProviderEffectKey::parse(self.key.as_str().to_string())?;
        Sha256Digest::parse(self.payload_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        Ok(())
    }
}

/// Provider-side terminal status carried by a key-bound acknowledgement.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderEffectAckStatus {
    /// The provider durably accepted the operation, but effect completion is
    /// not yet observed.
    Accepted,
    /// The provider contractually confirms completion for this key/payload.
    Completed,
    /// The provider rejected the operation and promises no effect occurred.
    Rejected,
}

/// Local provenance for a provider acknowledgement observation.
///
/// The provider payload itself does not carry this distinction: the same
/// key-bound acknowledgement shape may be returned by the initial dispatch
/// response or by a later authoritative status lookup.  Keeping the source
/// at the observation boundary lets the evidence store reject a late raw
/// dispatch response after an uncertainty quarantine.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderEffectAckSource {
    /// The acknowledgement came from the response to the physical dispatch.
    DispatchResponse,
    /// The acknowledgement came from a provider-owned status lookup.
    StatusLookup,
}

impl ProviderEffectAckSource {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::DispatchResponse => "dispatch_response",
            Self::StatusLookup => "status_lookup",
        }
    }

    pub fn parse(value: &str) -> Result<Self, ProviderEffectBindingError> {
        match value {
            "dispatch_response" => Ok(Self::DispatchResponse),
            "status_lookup" => Ok(Self::StatusLookup),
            _ => Err(ProviderEffectBindingError::InvalidAckSource),
        }
    }
}

/// Monotonic local state for one effect occurrence.
///
/// This is intentionally a *local* state machine.  `Accepted` means only that
/// the provider says it durably admitted the operation; it is not an external
/// effect receipt.  `Indeterminate` is represented by the absence of a
/// terminal acknowledgement or an explicit uncertainty marker.  It must
/// remain quarantined until a later status lookup (or an operator decision)
/// closes it.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderEffectState {
    /// An intent exists locally, but no provider acknowledgement is durable.
    #[default]
    Pending,
    /// The provider durably admitted the operation; completion is unknown.
    Accepted,
    /// The provider supplied a key/payload-bound completion acknowledgement.
    Completed,
    /// The provider supplied a key/payload-bound rejection acknowledgement.
    Rejected,
    /// The physical outcome cannot currently be established.
    Indeterminate,
}

impl ProviderEffectState {
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Rejected)
    }

    pub const fn is_retry_blocked(self) -> bool {
        !matches!(self, Self::Rejected)
    }
}

/// Provider acknowledgement bound to one logical key and exact payload digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProviderEffectAck {
    pub schema_version: u32,
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
    pub provider_operation_id_sha256: Sha256Digest,
    pub status: ProviderEffectAckStatus,
}

/// Durable local observation that a provider outcome cannot currently be
/// established.
///
/// An uncertainty is not an acknowledgement and cannot prove either success
/// or rejection.  Persisting it gives callers a crash-safe quarantine marker
/// so they do not turn a lost response into a blind retry.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProviderEffectUncertainty {
    pub schema_version: u32,
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
    pub reason_code: String,
}

impl ProviderEffectUncertainty {
    pub fn new(
        key: ProviderEffectKey,
        payload_sha256: Sha256Digest,
        reason_code: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: PROVIDER_EFFECT_SCHEMA_VERSION,
            key,
            payload_sha256,
            reason_code: reason_code.into(),
        }
    }

    pub fn validate_for(
        &self,
        intent: &ProviderEffectIntent,
    ) -> Result<(), ProviderEffectBindingError> {
        intent.validate()?;
        if self.schema_version != PROVIDER_EFFECT_SCHEMA_VERSION {
            return Err(ProviderEffectBindingError::SchemaVersion);
        }
        ProviderEffectKey::parse(self.key.as_str().to_string())?;
        Sha256Digest::parse(self.payload_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        validate_reason_code(&self.reason_code)?;
        if self.key != intent.key {
            return Err(ProviderEffectBindingError::KeyMismatch);
        }
        if self.payload_sha256 != intent.payload_sha256 {
            return Err(ProviderEffectBindingError::PayloadMismatch);
        }
        Ok(())
    }
}

impl ProviderEffectAck {
    pub fn new(
        key: ProviderEffectKey,
        payload_sha256: Sha256Digest,
        provider_operation_id_sha256: Sha256Digest,
        status: ProviderEffectAckStatus,
    ) -> Self {
        Self {
            schema_version: PROVIDER_EFFECT_SCHEMA_VERSION,
            key,
            payload_sha256,
            provider_operation_id_sha256,
            status,
        }
    }

    /// Verifies that an externally returned acknowledgement can close the
    /// exact local intent.  A response or request ID alone is insufficient.
    pub fn validate_for(
        &self,
        intent: &ProviderEffectIntent,
    ) -> Result<(), ProviderEffectBindingError> {
        intent.validate()?;
        if self.schema_version != PROVIDER_EFFECT_SCHEMA_VERSION {
            return Err(ProviderEffectBindingError::SchemaVersion);
        }
        ProviderEffectKey::parse(self.key.as_str().to_string())?;
        Sha256Digest::parse(self.payload_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        Sha256Digest::parse(self.provider_operation_id_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        if self.key != intent.key {
            return Err(ProviderEffectBindingError::KeyMismatch);
        }
        if self.payload_sha256 != intent.payload_sha256 {
            return Err(ProviderEffectBindingError::PayloadMismatch);
        }
        Ok(())
    }

    /// Returns the local state represented by this acknowledgement.
    pub const fn state(&self) -> ProviderEffectState {
        match self.status {
            ProviderEffectAckStatus::Accepted => ProviderEffectState::Accepted,
            ProviderEffectAckStatus::Completed => ProviderEffectState::Completed,
            ProviderEffectAckStatus::Rejected => ProviderEffectState::Rejected,
        }
    }

    /// Only a provider `Completed` acknowledgement can establish the
    /// provider-side effect terminal.  `Accepted` remains pending.
    pub const fn proves_effect_completion(&self) -> bool {
        matches!(self.status, ProviderEffectAckStatus::Completed)
    }
}

/// Provider-owned status observation with explicit local provenance.
///
/// A raw [`ProviderEffectAck`] is intentionally ambiguous: it may have come
/// from the initial dispatch response, or from a later provider-owned status
/// lookup.  This envelope is the qualification-only seam for the latter.  It
/// carries the exact key, payload digest, provider operation identity, and
/// monotonic status together with a source that must be
/// [`ProviderEffectAckSource::StatusLookup`].  No provider call or authority
/// is implied by constructing one.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProviderEffectStatusObservation {
    pub schema_version: u32,
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
    pub provider_operation_id_sha256: Sha256Digest,
    pub status: ProviderEffectAckStatus,
    pub source: ProviderEffectAckSource,
}

impl ProviderEffectStatusObservation {
    /// Constructs an observation from a provider status lookup.  The source
    /// is fixed by the constructor; deserialized or manually forged values
    /// are rechecked by [`Self::validate`].
    pub fn new(
        key: ProviderEffectKey,
        payload_sha256: Sha256Digest,
        provider_operation_id_sha256: Sha256Digest,
        status: ProviderEffectAckStatus,
    ) -> Self {
        Self {
            schema_version: PROVIDER_EFFECT_SCHEMA_VERSION,
            key,
            payload_sha256,
            provider_operation_id_sha256,
            status,
            source: ProviderEffectAckSource::StatusLookup,
        }
    }

    pub fn from_ack(ack: &ProviderEffectAck) -> Self {
        Self::new(
            ack.key.clone(),
            ack.payload_sha256.clone(),
            ack.provider_operation_id_sha256.clone(),
            ack.status,
        )
    }

    /// Converts the envelope to the provider payload carried by the durable
    /// ACK table.  Callers must validate the envelope before using this value.
    pub fn to_ack(&self) -> ProviderEffectAck {
        ProviderEffectAck::new(
            self.key.clone(),
            self.payload_sha256.clone(),
            self.provider_operation_id_sha256.clone(),
            self.status,
        )
    }

    pub fn validate(&self) -> Result<(), ProviderEffectBindingError> {
        if self.schema_version != PROVIDER_EFFECT_SCHEMA_VERSION {
            return Err(ProviderEffectBindingError::SchemaVersion);
        }
        if self.source != ProviderEffectAckSource::StatusLookup {
            return Err(ProviderEffectBindingError::StatusObservationSourceRequired);
        }
        ProviderEffectKey::parse(self.key.as_str().to_string())?;
        Sha256Digest::parse(self.payload_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        Sha256Digest::parse(self.provider_operation_id_sha256.as_str().to_string())
            .map_err(ProviderEffectBindingError::InvalidDigest)?;
        Ok(())
    }

    /// Verifies that this status is for the exact local intent.  This binds
    /// key, payload, operation and schema before it can advance local state.
    pub fn validate_for(
        &self,
        intent: &ProviderEffectIntent,
    ) -> Result<(), ProviderEffectBindingError> {
        self.validate()?;
        self.to_ack().validate_for(intent)
    }
}

/// Result of asking a provider for the current state of a key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum ProviderEffectLookup {
    Ack(ProviderEffectAck),
    NotFound,
    Conflict {
        observed_payload_sha256: Option<Sha256Digest>,
    },
    /// Network/process failure leaves the provider state unknown.  Callers
    /// must quarantine the intent and must not blind-retry.
    Unknown,
}

/// Result of one provider dispatch attempt.  This is intentionally separate
/// from [`ProviderEffectLookup`]: a dispatch response may be lost even when a
/// later status lookup can reconcile it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum ProviderEffectDispatch {
    Ack(ProviderEffectAck),
    Rejected { reason_code: String },
    NotDispatched { reason_code: String },
    Unknown,
}

/// Errors returned while reconciling a provider lookup against local intent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderEffectBindingError {
    EmptyField(&'static str),
    InvalidKey(String),
    InvalidDigest(String),
    SchemaVersion,
    KeyMismatch,
    PayloadMismatch,
    UnsupportedCapability,
    NotFound,
    Unknown,
    Conflict,
    AckConflict,
    InvalidAckSource,
    StatusObservationSourceRequired,
    InvalidReasonCode,
}

/// Append-only disposition used by local effect journals and durable stores.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderEffectAppendDisposition {
    Inserted,
    AlreadyPresent,
}

/// A small serializable journal for one Agent's provider-effect intents and
/// acknowledgements.
///
/// The journal is deliberately storage-agnostic.  It is useful for adapters
/// that need to validate and bind an ACK before handing it to a durable store;
/// [`codex_hepta_evidence::HeptaEvidenceStore`] provides the production SQLite
/// persistence layer.  A journal never turns an unknown result into a retry.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct ProviderEffectJournal {
    intents: BTreeMap<String, ProviderEffectIntent>,
    acknowledgements: BTreeMap<String, Vec<ProviderEffectAck>>,
    /// Source is kept separately from the provider ACK payload because it is
    /// a local observation about how that payload was obtained.
    ack_sources: BTreeMap<String, Vec<ProviderEffectAckSource>>,
    #[serde(default)]
    uncertainties: BTreeMap<String, Vec<ProviderEffectUncertainty>>,
    /// Exact envelopes for ACKs observed through a provider-owned status
    /// lookup.  Keeping these separate from the provider payload preserves
    /// the local provenance boundary while making the status evidence
    /// independently auditable.
    #[serde(default)]
    status_observations: BTreeMap<String, Vec<ProviderEffectStatusObservation>>,
    #[serde(default)]
    quarantined: BTreeMap<String, bool>,
}

/// Wire representation used to keep old journals that contain no ACKs
/// readable while refusing to infer provenance for any persisted ACK.
///
/// `ack_sources` is optional only for that empty-ACK compatibility case.  A
/// journal with one or more acknowledgements must carry an exact source vector
/// for every acknowledgement; otherwise a caller could deserialize a
/// terminal-looking ACK and accidentally treat it as authoritative.
#[derive(Deserialize)]
struct ProviderEffectJournalWire {
    intents: BTreeMap<String, ProviderEffectIntent>,
    acknowledgements: BTreeMap<String, Vec<ProviderEffectAck>>,
    #[serde(default)]
    ack_sources: Option<BTreeMap<String, Vec<ProviderEffectAckSource>>>,
    #[serde(default)]
    uncertainties: BTreeMap<String, Vec<ProviderEffectUncertainty>>,
    #[serde(default)]
    status_observations: Option<BTreeMap<String, Vec<ProviderEffectStatusObservation>>>,
    #[serde(default)]
    quarantined: BTreeMap<String, bool>,
}

impl<'de> Deserialize<'de> for ProviderEffectJournal {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = ProviderEffectJournalWire::deserialize(deserializer)?;
        let ack_sources = wire.ack_sources.unwrap_or_default();
        let status_observations = wire.status_observations.unwrap_or_default();
        validate_ack_provenance_maps(&wire.acknowledgements, &ack_sources).map_err(|error| {
            serde::de::Error::custom(format!("invalid ACK provenance: {error:?}"))
        })?;
        validate_status_observation_maps(
            &wire.acknowledgements,
            &ack_sources,
            &status_observations,
        )
        .map_err(|error| {
            serde::de::Error::custom(format!("invalid provider status provenance: {error:?}"))
        })?;
        validate_journal_contents(
            &wire.intents,
            &wire.acknowledgements,
            &ack_sources,
            &wire.uncertainties,
            &status_observations,
            &wire.quarantined,
        )
        .map_err(|error| {
            serde::de::Error::custom(format!("invalid provider journal: {error:?}"))
        })?;
        Ok(Self {
            intents: wire.intents,
            acknowledgements: wire.acknowledgements,
            ack_sources,
            uncertainties: wire.uncertainties,
            status_observations,
            quarantined: wire.quarantined,
        })
    }
}

fn validate_ack_provenance_maps(
    acknowledgements: &BTreeMap<String, Vec<ProviderEffectAck>>,
    ack_sources: &BTreeMap<String, Vec<ProviderEffectAckSource>>,
) -> Result<(), ProviderEffectBindingError> {
    // Empty journals are backward-compatible: an older serialized journal
    // had no source map because it had no ACK observations to explain.
    if acknowledgements.values().all(Vec::is_empty) {
        if ack_sources.is_empty() {
            return Ok(());
        }
        return Err(ProviderEffectBindingError::AckConflict);
    }

    if acknowledgements.len() != ack_sources.len() {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    for (key, acknowledgements) in acknowledgements {
        if acknowledgements.is_empty() {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        let Some(sources) = ack_sources.get(key) else {
            return Err(ProviderEffectBindingError::AckConflict);
        };
        if sources.len() != acknowledgements.len() {
            return Err(ProviderEffectBindingError::AckConflict);
        }
    }
    if ack_sources
        .keys()
        .any(|key| !acknowledgements.contains_key(key))
    {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    Ok(())
}

fn validate_status_observation_maps(
    acknowledgements: &BTreeMap<String, Vec<ProviderEffectAck>>,
    ack_sources: &BTreeMap<String, Vec<ProviderEffectAckSource>>,
    status_observations: &BTreeMap<String, Vec<ProviderEffectStatusObservation>>,
) -> Result<(), ProviderEffectBindingError> {
    let mut expected = BTreeMap::<String, Vec<&ProviderEffectAck>>::new();
    for (key, acknowledgements) in acknowledgements {
        let Some(sources) = ack_sources.get(key) else {
            // The ACK/source validator reports the more precise error.
            continue;
        };
        for (index, ack) in acknowledgements.iter().enumerate() {
            if sources.get(index) == Some(&ProviderEffectAckSource::StatusLookup) {
                expected.entry(key.clone()).or_default().push(ack);
            }
        }
    }

    if expected.len() != status_observations.len() {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    for (key, expected_acks) in expected {
        let Some(observations) = status_observations.get(&key) else {
            return Err(ProviderEffectBindingError::AckConflict);
        };
        if observations.len() != expected_acks.len() {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        for (ack, observation) in expected_acks.into_iter().zip(observations) {
            observation
                .validate()
                .map_err(|_| ProviderEffectBindingError::AckConflict)?;
            if observation.to_ack() != *ack {
                return Err(ProviderEffectBindingError::AckConflict);
            }
        }
    }
    if status_observations
        .keys()
        .any(|key| !acknowledgements.contains_key(key))
    {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    Ok(())
}

/// Validate the contents behind the journal's provenance shape.
///
/// The source-vector length check above prevents a deserializer from
/// inventing a missing observation path, but it is not enough on its own:
/// malformed ACKs, intents, uncertainty markers, or map keys could still be
/// loaded and then exposed through the legacy infallible read APIs.  Keep this
/// check independent of the journal object so both deserialization and
/// in-memory callers share the same fail-closed boundary.
fn validate_journal_contents(
    intents: &BTreeMap<String, ProviderEffectIntent>,
    acknowledgements: &BTreeMap<String, Vec<ProviderEffectAck>>,
    ack_sources: &BTreeMap<String, Vec<ProviderEffectAckSource>>,
    uncertainties: &BTreeMap<String, Vec<ProviderEffectUncertainty>>,
    status_observations: &BTreeMap<String, Vec<ProviderEffectStatusObservation>>,
    quarantined: &BTreeMap<String, bool>,
) -> Result<(), ProviderEffectBindingError> {
    for (map_key, intent) in intents {
        if map_key != intent.key.as_str() || intent.validate().is_err() {
            return Err(ProviderEffectBindingError::AckConflict);
        }
    }

    // Every auxiliary map is keyed by a previously recorded intent.  An
    // unknown key must not become a free-standing terminal-looking record.
    if acknowledgements
        .keys()
        .chain(uncertainties.keys())
        .chain(status_observations.keys())
        .any(|key| !intents.contains_key(key))
        || quarantined.keys().any(|key| !intents.contains_key(key))
    {
        return Err(ProviderEffectBindingError::AckConflict);
    }

    for (key, acknowledgements_for_key) in acknowledgements {
        let Some(intent) = intents.get(key) else {
            return Err(ProviderEffectBindingError::AckConflict);
        };
        let Some(sources) = ack_sources.get(key) else {
            // The shape validator normally catches this first; retain the
            // guard here so direct in-memory validation is equally strict.
            if acknowledgements_for_key.is_empty() {
                continue;
            }
            return Err(ProviderEffectBindingError::AckConflict);
        };
        if sources.len() != acknowledgements_for_key.len() {
            return Err(ProviderEffectBindingError::AckConflict);
        }

        let uncertainty_present = uncertainties
            .get(key)
            .is_some_and(|entries| !entries.is_empty());
        let mut quarantined_before = false;
        for (index, acknowledgement) in acknowledgements_for_key.iter().enumerate() {
            acknowledgement
                .validate_for(intent)
                .map_err(|_| ProviderEffectBindingError::AckConflict)?;
            let source = sources[index];
            // An uncertainty marker is stored out-of-band from the ACK
            // sequence.  Treat a status-sourced ACK as following that marker
            // so the accepted -> completed operation-id rebinding used by
            // reconciliation remains valid during replay validation.
            if uncertainty_present && source == ProviderEffectAckSource::StatusLookup {
                quarantined_before = true;
            }
            if index > 0 {
                // Once a provider-owned status lookup has been observed, a
                // later raw dispatch response is not an authoritative
                // continuation.  It may be a delayed response from the
                // original call and must not advance the local state machine
                // even when its operation id and status look monotonic.
                if source == ProviderEffectAckSource::DispatchResponse
                    && sources.get(index - 1) == Some(&ProviderEffectAckSource::StatusLookup)
                {
                    return Err(ProviderEffectBindingError::AckConflict);
                }
                validate_ack_transition(
                    &acknowledgements_for_key[..index],
                    acknowledgement,
                    quarantined_before,
                    source,
                )?;
            }
        }
    }

    for (key, uncertainties_for_key) in uncertainties {
        let Some(intent) = intents.get(key) else {
            return Err(ProviderEffectBindingError::AckConflict);
        };
        for uncertainty in uncertainties_for_key {
            uncertainty
                .validate_for(intent)
                .map_err(|_| ProviderEffectBindingError::AckConflict)?;
        }
    }

    // A quarantine marker is meaningful only when backed by an uncertainty
    // record, and a terminal ACK must clear it.  Missing false entries remain
    // compatible with pre-provenance journals.  A status-sourced ACK is an
    // explicit reconciliation and may clear an earlier uncertainty even when
    // the resulting state is still `Accepted`.
    for (key, is_quarantined) in quarantined {
        let uncertainty_present = uncertainties
            .get(key)
            .is_some_and(|entries| !entries.is_empty());
        let terminal = acknowledgements
            .get(key)
            .and_then(|entries| entries.last())
            .is_some_and(|ack| ack.state().is_terminal());
        if *is_quarantined && (!uncertainty_present || terminal) {
            return Err(ProviderEffectBindingError::AckConflict);
        }
    }
    for (key, uncertainties_for_key) in uncertainties {
        if uncertainties_for_key.is_empty() {
            continue;
        }
        let latest_source = acknowledgements
            .get(key)
            .and_then(|entries| entries.len().checked_sub(1))
            .and_then(|index| ack_sources.get(key).and_then(|sources| sources.get(index)))
            .copied();
        let terminal = acknowledgements
            .get(key)
            .and_then(|entries| entries.last())
            .is_some_and(|ack| ack.state().is_terminal());
        let is_quarantined = quarantined.get(key).copied().unwrap_or(false);
        if terminal {
            // A terminal status is allowed to close an uncertainty only when
            // it came from the provider-owned lookup path.  A dispatch
            // terminal plus an uncertainty marker is an impossible local
            // history and must not be trusted after deserialization.
            if latest_source != Some(ProviderEffectAckSource::StatusLookup) {
                return Err(ProviderEffectBindingError::AckConflict);
            }
        } else if !is_quarantined && latest_source != Some(ProviderEffectAckSource::StatusLookup) {
            return Err(ProviderEffectBindingError::AckConflict);
        }
    }

    // This call also checks each status envelope and its exact equality with
    // the corresponding status-sourced ACK.
    validate_status_observation_maps(acknowledgements, ack_sources, status_observations)
}

impl ProviderEffectJournal {
    /// Verifies that every durable ACK observation has a one-to-one local
    /// provenance entry.  This is intentionally separate from provider ACK
    /// payload validation: source is process-local evidence, not provider
    /// data, and must never be inferred from an old journal.
    pub fn validate(&self) -> Result<(), ProviderEffectBindingError> {
        validate_ack_provenance_maps(&self.acknowledgements, &self.ack_sources)?;
        validate_journal_contents(
            &self.intents,
            &self.acknowledgements,
            &self.ack_sources,
            &self.uncertainties,
            &self.status_observations,
            &self.quarantined,
        )
    }

    pub fn record_intent(
        &mut self,
        intent: ProviderEffectIntent,
    ) -> Result<ProviderEffectAppendDisposition, ProviderEffectBindingError> {
        self.validate()?;
        intent.validate()?;
        let key = intent.key.as_str().to_string();
        if let Some(existing) = self.intents.get(&key) {
            if existing == &intent {
                return Ok(ProviderEffectAppendDisposition::AlreadyPresent);
            }
            return Err(ProviderEffectBindingError::AckConflict);
        }
        self.intents.insert(key, intent);
        Ok(ProviderEffectAppendDisposition::Inserted)
    }

    /// Records a provider-owned status observation.  The envelope is the only
    /// qualification API that may introduce a `StatusLookup` ACK; callers
    /// cannot silently relabel a dispatch response as authoritative status.
    pub fn record_status_observation(
        &mut self,
        observation: ProviderEffectStatusObservation,
    ) -> Result<ProviderEffectAppendDisposition, ProviderEffectBindingError> {
        self.validate()?;
        let key = observation.key.clone();
        let intent = self
            .intents
            .get(key.as_str())
            .cloned()
            .ok_or(ProviderEffectBindingError::NotFound)?;
        observation.validate_for(&intent)?;
        self.record_ack_from_source(observation.to_ack(), ProviderEffectAckSource::StatusLookup)
    }

    pub fn record_ack(
        &mut self,
        ack: ProviderEffectAck,
    ) -> Result<ProviderEffectAppendDisposition, ProviderEffectBindingError> {
        self.record_ack_from_source(ack, ProviderEffectAckSource::DispatchResponse)
    }

    /// Records an acknowledgement together with the path that produced it.
    /// A dispatch response can never close an occurrence after it has been
    /// quarantined; only a later status lookup may do so.
    pub fn record_ack_from_source(
        &mut self,
        ack: ProviderEffectAck,
        source: ProviderEffectAckSource,
    ) -> Result<ProviderEffectAppendDisposition, ProviderEffectBindingError> {
        self.validate()?;
        let key = ack.key.as_str().to_string();
        let intent = self
            .intents
            .get(&key)
            .ok_or(ProviderEffectBindingError::NotFound)?;
        ack.validate_for(intent)?;
        let status_observation = (source == ProviderEffectAckSource::StatusLookup)
            .then(|| ProviderEffectStatusObservation::from_ack(&ack));
        let was_quarantined = self
            .quarantined
            .get(ack.key.as_str())
            .copied()
            .unwrap_or(false);
        // Check the quarantine fence before creating any auxiliary map
        // entries.  A late raw dispatch ACK is rejected, but that rejection
        // must not leave empty ACK/source vectors behind and poison the
        // journal's provenance shape for every later reopen/reconcile.
        if was_quarantined && source != ProviderEffectAckSource::StatusLookup {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        // Inspect the existing vectors immutably until every rejection path
        // has passed.  In particular, `validate_ack_transition` can reject a
        // conflicting operation/status; creating empty map entries before
        // that check would leave an otherwise valid journal with mismatched
        // ACK/source cardinality and prevent the quarantine below from being
        // persisted.
        let observations = self
            .acknowledgements
            .get(key.as_str())
            .map_or(&[][..], Vec::as_slice);
        let sources = self
            .ack_sources
            .get(key.as_str())
            .map_or(&[][..], Vec::as_slice);
        if let Some(index) = observations.iter().position(|existing| existing == &ack) {
            let Some(existing_source) = sources.get(index).copied() else {
                // A journal serialized before provenance was introduced has
                // no safe way to infer how an existing ACK was observed.
                return Err(ProviderEffectBindingError::AckConflict);
            };
            if source == ProviderEffectAckSource::DispatchResponse
                && existing_source == ProviderEffectAckSource::StatusLookup
            {
                // A raw dispatch response that arrives after a provider-owned
                // status observation is not an authoritative replay.  Keep
                // the first status provenance and reject the late path.
                return Err(ProviderEffectBindingError::AckConflict);
            }
            // A duplicate observation is idempotent even when a later status
            // lookup confirms an ACK first seen in a dispatch response.  The
            // first stored source remains authoritative; quarantine rules
            // above still reject a late raw dispatch ACK.
            let _ = (existing_source, source);
            return Ok(ProviderEffectAppendDisposition::AlreadyPresent);
        }
        // A status lookup is the only authoritative observation after the
        // provider boundary becomes uncertain.  Do not let a delayed raw
        // dispatch response advance an Accepted status to Completed after
        // that lookup has already been recorded.
        if source == ProviderEffectAckSource::DispatchResponse
            && sources.last() == Some(&ProviderEffectAckSource::StatusLookup)
        {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        validate_ack_transition(observations, &ack, was_quarantined, source)?;
        self.acknowledgements
            .entry(key.clone())
            .or_default()
            .push(ack);
        self.ack_sources
            .entry(key.clone())
            .or_default()
            .push(source);
        self.quarantined.insert(key.clone(), false);
        if let Some(status_observation) = status_observation {
            self.status_observations
                .entry(key)
                .or_default()
                .push(status_observation);
        }
        Ok(ProviderEffectAppendDisposition::Inserted)
    }

    /// Records an explicit fail-closed quarantine marker.
    ///
    /// The marker is idempotent for an unchanged reason.  A later validated
    /// provider acknowledgement may reconcile it; a terminal acknowledgement
    /// can never be replaced by uncertainty.
    pub fn mark_indeterminate(
        &mut self,
        key: &ProviderEffectKey,
        reason_code: impl Into<String>,
    ) -> Result<ProviderEffectAppendDisposition, ProviderEffectBindingError> {
        self.validate()?;
        let reason_code = reason_code.into();
        validate_reason_code(&reason_code)?;
        let intent = self
            .intents
            .get(key.as_str())
            .ok_or(ProviderEffectBindingError::NotFound)?;
        if self
            .acknowledgements
            .get(key.as_str())
            .and_then(|items| items.last())
            .is_some_and(|ack| ack.state().is_terminal())
        {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        let uncertainty =
            ProviderEffectUncertainty::new(key.clone(), intent.payload_sha256.clone(), reason_code);
        uncertainty.validate_for(intent)?;
        let observations = self
            .uncertainties
            .entry(key.as_str().to_string())
            .or_default();
        if observations.iter().any(|existing| existing == &uncertainty) {
            self.quarantined.insert(key.as_str().to_string(), true);
            return Ok(ProviderEffectAppendDisposition::AlreadyPresent);
        }
        observations.push(uncertainty);
        self.quarantined.insert(key.as_str().to_string(), true);
        Ok(ProviderEffectAppendDisposition::Inserted)
    }

    pub fn state(&self, key: &ProviderEffectKey) -> Option<ProviderEffectState> {
        if self.validate().is_err() {
            // The API predates fallible state reads.  Preserve that API while
            // making malformed provenance fail closed rather than exposing a
            // terminal-looking ACK.
            return Some(ProviderEffectState::Indeterminate);
        }
        let intent = self.intents.get(key.as_str())?;
        if self.quarantined.get(key.as_str()).copied().unwrap_or(false) {
            return Some(ProviderEffectState::Indeterminate);
        }
        let observations = self.acknowledgements.get(key.as_str());
        let state = observations
            .and_then(|items| items.last())
            .map_or(ProviderEffectState::Pending, ProviderEffectAck::state);
        if intent.key == *key {
            Some(state)
        } else {
            None
        }
    }

    pub fn intent(&self, key: &ProviderEffectKey) -> Option<&ProviderEffectIntent> {
        self.intents.get(key.as_str())
    }

    pub fn acknowledgements(&self, key: &ProviderEffectKey) -> &[ProviderEffectAck] {
        if self.validate().is_err() {
            return &[];
        }
        self.acknowledgements
            .get(key.as_str())
            .map_or(&[], Vec::as_slice)
    }

    pub fn acknowledgement_sources(&self, key: &ProviderEffectKey) -> &[ProviderEffectAckSource] {
        if self.validate().is_err() {
            return &[];
        }
        self.ack_sources
            .get(key.as_str())
            .map_or(&[], Vec::as_slice)
    }

    pub fn uncertainties(&self, key: &ProviderEffectKey) -> &[ProviderEffectUncertainty] {
        self.uncertainties
            .get(key.as_str())
            .map_or(&[], Vec::as_slice)
    }

    pub fn status_observations(
        &self,
        key: &ProviderEffectKey,
    ) -> &[ProviderEffectStatusObservation] {
        if self.validate().is_err() {
            return &[];
        }
        self.status_observations
            .get(key.as_str())
            .map_or(&[], Vec::as_slice)
    }

    pub fn reconcile(
        &mut self,
        capability: ProviderEffectIdempotencyCapability,
        key: &ProviderEffectKey,
        lookup: ProviderEffectLookup,
    ) -> Result<ProviderEffectState, ProviderEffectBindingError> {
        self.validate()?;
        let intent = self
            .intents
            .get(key.as_str())
            .ok_or(ProviderEffectBindingError::NotFound)?
            .clone();
        if capability == ProviderEffectIdempotencyCapability::Unsupported {
            self.mark_indeterminate(key, "provider_capability_unsupported")?;
            return Err(ProviderEffectBindingError::UnsupportedCapability);
        }
        match lookup {
            ProviderEffectLookup::Ack(ack) => {
                ack.validate_for(&intent)?;
                self.record_ack_from_source(ack, ProviderEffectAckSource::StatusLookup)?;
                Ok(self
                    .state(key)
                    .unwrap_or(ProviderEffectState::Indeterminate))
            }
            ProviderEffectLookup::NotFound => {
                self.mark_indeterminate(key, "provider_status_not_found")?;
                Ok(ProviderEffectState::Indeterminate)
            }
            ProviderEffectLookup::Conflict { .. } => {
                self.mark_indeterminate(key, "provider_payload_conflict")?;
                Ok(ProviderEffectState::Indeterminate)
            }
            ProviderEffectLookup::Unknown => {
                self.mark_indeterminate(key, "provider_lookup_unknown")?;
                Ok(ProviderEffectState::Indeterminate)
            }
        }
    }

    /// Reconciles one already-observed provider status without performing a
    /// network call.  Unknown/not-found outcomes must use [`Self::reconcile`]
    /// and remain quarantined; this API accepts only a key/payload/operation
    /// bound status envelope.
    pub fn reconcile_status_observation(
        &mut self,
        observation: ProviderEffectStatusObservation,
    ) -> Result<ProviderEffectState, ProviderEffectBindingError> {
        let key = observation.key.clone();
        self.record_status_observation(observation)?;
        Ok(self
            .state(&key)
            .unwrap_or(ProviderEffectState::Indeterminate))
    }
}

fn validate_ack_transition(
    observations: &[ProviderEffectAck],
    next: &ProviderEffectAck,
    was_quarantined: bool,
    source: ProviderEffectAckSource,
) -> Result<(), ProviderEffectBindingError> {
    let Some(previous) = observations.last() else {
        return Ok(());
    };
    if previous.state().is_terminal() {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    // A status lookup after an explicit unknown observation is allowed to
    // bind the provider's authoritative operation identity.  It does not,
    // however, relax the state machine: an already accepted operation may
    // only remain accepted or advance to completed.  In particular,
    // accepted -> rejected must stay fail-closed because the earlier
    // admission proves that the provider may already have applied it.
    if was_quarantined {
        if source != ProviderEffectAckSource::StatusLookup {
            return Err(ProviderEffectBindingError::AckConflict);
        }
        return match (previous.status, next.status) {
            (ProviderEffectAckStatus::Accepted, ProviderEffectAckStatus::Accepted)
            | (ProviderEffectAckStatus::Accepted, ProviderEffectAckStatus::Completed) => Ok(()),
            _ => Err(ProviderEffectBindingError::AckConflict),
        };
    }
    if previous.provider_operation_id_sha256 != next.provider_operation_id_sha256 {
        return Err(ProviderEffectBindingError::AckConflict);
    }
    match (previous.status, next.status) {
        (ProviderEffectAckStatus::Accepted, ProviderEffectAckStatus::Completed) => Ok(()),
        (ProviderEffectAckStatus::Accepted, ProviderEffectAckStatus::Accepted) => Ok(()),
        (ProviderEffectAckStatus::Completed, ProviderEffectAckStatus::Completed)
        | (ProviderEffectAckStatus::Rejected, ProviderEffectAckStatus::Rejected) => {
            Err(ProviderEffectBindingError::AckConflict)
        }
        // A terminal result must never be replaced by another result.  In
        // particular, `accepted -> rejected` is unsafe because the provider
        // may already have applied the operation.
        _ if previous.status != next.status => Err(ProviderEffectBindingError::AckConflict),
        _ => Err(ProviderEffectBindingError::AckConflict),
    }
}

/// Reconciles one provider lookup without ever retrying the physical send.
///
/// This helper is deliberately synchronous and network-agnostic so contract
/// tests can exercise the fail-closed state machine without a provider fixture.
pub fn reconcile_provider_lookup(
    capability: ProviderEffectIdempotencyCapability,
    intent: &ProviderEffectIntent,
    lookup: ProviderEffectLookup,
) -> Result<ProviderEffectAck, ProviderEffectBindingError> {
    intent.validate()?;
    if capability == ProviderEffectIdempotencyCapability::Unsupported {
        return Err(ProviderEffectBindingError::UnsupportedCapability);
    }
    match lookup {
        ProviderEffectLookup::Ack(ack) => {
            ack.validate_for(intent)?;
            Ok(ack)
        }
        ProviderEffectLookup::NotFound => Err(ProviderEffectBindingError::NotFound),
        ProviderEffectLookup::Conflict { .. } => Err(ProviderEffectBindingError::Conflict),
        ProviderEffectLookup::Unknown => Err(ProviderEffectBindingError::Unknown),
    }
}

/// Async adapter seam for a future provider implementation.
///
/// No current HTTP or WebSocket provider implements this trait. An adapter may
/// report `KeyAndStatusLookup` only after its provider contract proves stable
/// key transport, same-key conflict/dedupe, and durable lookup semantics.
pub type ProviderEffectFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

pub trait ProviderEffectAdapter: Send + Sync {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::Unsupported
    }

    fn dispatch<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch>;

    /// Dispatch the intent with the exact wire payload whose digest is bound
    /// by `intent.payload_sha256`.
    ///
    /// The legacy `dispatch` method remains available for adapters that own
    /// their payload construction. A transport adapter which sends caller
    /// supplied bytes must override this method; the default deliberately
    /// falls back to the legacy seam so existing qualification adapters keep
    /// compiling without gaining an implicit send path.
    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        _wire_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.dispatch(intent)
    }

    fn lookup<'a>(
        &'a self,
        key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup>;

    /// Ask for the status of an exact durable intent.
    ///
    /// The legacy key-only method remains available for compatibility with
    /// adapters that predate payload-bound status queries.  New coordinators
    /// call this intent-bound seam so a provider can receive the exact
    /// payload digest along with the occurrence key and reject a key collision
    /// before returning an acknowledgement.  The default delegates to the
    /// legacy method, preserving existing qualification adapters while making
    /// the stronger binding opt-in for transports that support it.
    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        self.lookup(&intent.key)
    }
}

/// Error returned by the local dispatch/reconcile coordinator.
///
/// The coordinator is deliberately storage-local: it makes the no-blind-retry
/// decision around a [`ProviderEffectAdapter`], but it does not turn an
/// adapter's claim into production authority.  A real adapter must still be
/// backed by a provider-owned durable occurrence key, status lookup, and
/// payload-bound operation receipt before it may report the supported
/// capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderEffectCoordinatorError {
    Binding(ProviderEffectBindingError),
}

impl From<ProviderEffectBindingError> for ProviderEffectCoordinatorError {
    fn from(error: ProviderEffectBindingError) -> Self {
        Self::Binding(error)
    }
}

/// Result of one coordinator call. `physical_dispatch_attempted` is an
/// observation of the adapter call, not a claim that an external effect was
/// applied.  `false` means the local journal already had a non-pending state
/// and the coordinator intentionally did not call the adapter again.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderEffectDispatchReceipt {
    pub state: ProviderEffectState,
    pub physical_dispatch_attempted: bool,
}

/// Local state-machine wrapper that enforces intent-before-send and
/// no-blind-retry semantics for any provider adapter.
///
/// This is useful for qualification and for embedding a future provider-owned
/// adapter.  It never upgrades `Unsupported` to `KeyAndStatusLookup`, never
/// retries an `Accepted`/`Indeterminate` occurrence, and never treats a lost
/// response as a successful effect.
pub struct ProviderEffectCoordinator<A> {
    adapter: A,
    journal: ProviderEffectJournal,
}

impl<A> ProviderEffectCoordinator<A>
where
    A: ProviderEffectAdapter,
{
    pub fn new(adapter: A) -> Self {
        Self {
            adapter,
            journal: ProviderEffectJournal::default(),
        }
    }

    pub fn with_journal(adapter: A, journal: ProviderEffectJournal) -> Self {
        Self { adapter, journal }
    }

    pub fn journal(&self) -> &ProviderEffectJournal {
        &self.journal
    }

    pub fn journal_mut(&mut self) -> &mut ProviderEffectJournal {
        &mut self.journal
    }

    pub fn adapter(&self) -> &A {
        &self.adapter
    }

    pub fn adapter_mut(&mut self) -> &mut A {
        &mut self.adapter
    }

    pub fn into_parts(self) -> (A, ProviderEffectJournal) {
        (self.adapter, self.journal)
    }

    /// Record the intent and make at most one physical dispatch attempt.
    ///
    /// Pending is the only state that permits a send.  Accepted and
    /// Indeterminate are quarantined until [`Self::reconcile`] obtains a
    /// provider lookup; terminal states are returned without touching the
    /// adapter.  A Pending intent already present in a restored journal is
    /// treated as an imported crash-window record and is quarantined before
    /// the adapter can be called.
    /// A provider response that cannot be bound to the exact intent
    /// is an error and never advances the journal.
    pub async fn dispatch_once(
        &mut self,
        intent: ProviderEffectIntent,
    ) -> Result<ProviderEffectDispatchReceipt, ProviderEffectCoordinatorError> {
        self.journal.validate()?;
        let key = intent.key.clone();
        let intent_disposition = self.journal.record_intent(intent.clone())?;
        let current = self
            .journal
            .state(&key)
            .unwrap_or(ProviderEffectState::Indeterminate);
        if current == ProviderEffectState::Pending
            && intent_disposition == ProviderEffectAppendDisposition::AlreadyPresent
        {
            self.journal
                .mark_indeterminate(&key, PROVIDER_EFFECT_IMPORTED_PENDING_REASON)?;
            return Ok(ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            });
        }
        if current != ProviderEffectState::Pending {
            return Ok(ProviderEffectDispatchReceipt {
                state: current,
                physical_dispatch_attempted: false,
            });
        }

        let dispatch = self.adapter.dispatch(&intent).await;
        let state = match dispatch {
            ProviderEffectDispatch::Ack(ack) => {
                // The adapter boundary was crossed even when its response is
                // malformed or conflicts with the durable intent.  Preserve
                // a local quarantine before returning the binding error so a
                // caller cannot blindly retry and send a second effect.
                if let Err(error) = self.journal.record_ack(ack) {
                    self.journal
                        .mark_indeterminate(&key, "provider_dispatch_ack_invalid")
                        .map_err(ProviderEffectCoordinatorError::from)?;
                    return Err(ProviderEffectCoordinatorError::from(error));
                }
                self.journal
                    .state(&key)
                    .unwrap_or(ProviderEffectState::Indeterminate)
            }
            ProviderEffectDispatch::Rejected { reason_code } => {
                self.journal.mark_indeterminate(
                    &key,
                    validated_reason_code(&reason_code, "provider_dispatch_rejected"),
                )?;
                ProviderEffectState::Indeterminate
            }
            ProviderEffectDispatch::NotDispatched { reason_code } => {
                // The adapter says it did not send, but the coordinator has
                // no independent physical boundary proof.  Quarantine rather
                // than silently converting this observation into a safe
                // retry or a terminal rejection.
                self.journal.mark_indeterminate(
                    &key,
                    validated_reason_code(&reason_code, "provider_not_dispatched"),
                )?;
                ProviderEffectState::Indeterminate
            }
            ProviderEffectDispatch::Unknown => {
                self.journal
                    .mark_indeterminate(&key, "provider_dispatch_unknown")?;
                ProviderEffectState::Indeterminate
            }
        };
        Ok(ProviderEffectDispatchReceipt {
            state,
            physical_dispatch_attempted: true,
        })
    }

    /// Record the intent and make at most one physical dispatch attempt using
    /// an exact caller-supplied wire payload.
    ///
    /// The digest is checked before the adapter is called. A mismatch is a
    /// local binding error and therefore cannot cross a provider boundary. A
    /// Pending intent already present in a restored journal is treated as an
    /// imported crash-window record and is quarantined before the adapter can
    /// be called.
    pub async fn dispatch_once_with_payload(
        &mut self,
        intent: ProviderEffectIntent,
        wire_payload: &[u8],
    ) -> Result<ProviderEffectDispatchReceipt, ProviderEffectCoordinatorError> {
        intent.validate()?;
        if Sha256Digest::for_bytes(wire_payload) != intent.payload_sha256 {
            return Err(ProviderEffectBindingError::PayloadMismatch.into());
        }
        self.journal.validate()?;
        let key = intent.key.clone();
        let intent_disposition = self.journal.record_intent(intent.clone())?;
        let current = self
            .journal
            .state(&key)
            .unwrap_or(ProviderEffectState::Indeterminate);
        if current == ProviderEffectState::Pending
            && intent_disposition == ProviderEffectAppendDisposition::AlreadyPresent
        {
            self.journal
                .mark_indeterminate(&key, PROVIDER_EFFECT_IMPORTED_PENDING_REASON)?;
            return Ok(ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            });
        }
        if current != ProviderEffectState::Pending {
            return Ok(ProviderEffectDispatchReceipt {
                state: current,
                physical_dispatch_attempted: false,
            });
        }

        let dispatch = self
            .adapter
            .dispatch_with_payload(&intent, wire_payload)
            .await;
        let (state, physical_dispatch_attempted) = match dispatch {
            ProviderEffectDispatch::Ack(ack) => {
                // As above, an invalid ACK after a physical attempt is an
                // unknown outcome, not a safe retry.  Persist the quarantine
                // before exposing the binding error to the caller.
                if let Err(error) = self.journal.record_ack(ack) {
                    self.journal
                        .mark_indeterminate(&key, "provider_dispatch_ack_invalid")
                        .map_err(ProviderEffectCoordinatorError::from)?;
                    return Err(ProviderEffectCoordinatorError::from(error));
                }
                (
                    self.journal
                        .state(&key)
                        .unwrap_or(ProviderEffectState::Indeterminate),
                    true,
                )
            }
            ProviderEffectDispatch::Rejected { reason_code } => {
                self.journal.mark_indeterminate(
                    &key,
                    validated_reason_code(&reason_code, "provider_dispatch_rejected"),
                )?;
                (ProviderEffectState::Indeterminate, true)
            }
            ProviderEffectDispatch::NotDispatched { reason_code } => {
                self.journal.mark_indeterminate(
                    &key,
                    validated_reason_code(&reason_code, "provider_not_dispatched"),
                )?;
                (ProviderEffectState::Indeterminate, false)
            }
            ProviderEffectDispatch::Unknown => {
                self.journal
                    .mark_indeterminate(&key, "provider_dispatch_unknown")?;
                (ProviderEffectState::Indeterminate, true)
            }
        };
        Ok(ProviderEffectDispatchReceipt {
            state,
            physical_dispatch_attempted,
        })
    }

    /// Ask the adapter for a key-bound status and reconcile it locally.
    ///
    /// Terminal local state is authoritative and avoids an unnecessary
    /// provider call.  Unsupported adapters still quarantine the occurrence
    /// and return `UnsupportedCapability` through the coordinator error.
    pub async fn reconcile(
        &mut self,
        key: &ProviderEffectKey,
    ) -> Result<ProviderEffectState, ProviderEffectCoordinatorError> {
        self.journal.validate()?;
        if let Some(state) = self.journal.state(key)
            && state.is_terminal()
        {
            return Ok(state);
        }
        // Capability is a local contract gate, not a result of a provider
        // call.  An adapter that cannot prove key-based status lookup must be
        // quarantined without touching its lookup path; otherwise a caller
        // could perform an unsupported remote read and only then discover
        // that the result is unusable.  Feed an inert Unknown observation to
        // the journal so it records the same fail-closed Indeterminate state
        // and typed UnsupportedCapability error as the old path.
        let capability = self.adapter.capability();
        if capability == ProviderEffectIdempotencyCapability::Unsupported {
            return self
                .journal
                .reconcile(capability, key, ProviderEffectLookup::Unknown)
                .map_err(ProviderEffectCoordinatorError::from);
        }
        let intent = self
            .journal
            .intent(key)
            .cloned()
            .ok_or(ProviderEffectBindingError::NotFound)?;
        let lookup = self.adapter.lookup_for_intent(&intent).await;
        self.journal
            .reconcile(capability, key, lookup)
            .map_err(ProviderEffectCoordinatorError::from)
    }
}

fn validated_reason_code<'a>(value: &'a str, fallback: &'static str) -> &'a str {
    if value.len() <= 128
        && !value.is_empty()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        value
    } else {
        fallback
    }
}

fn validate_non_empty(label: &'static str, value: &str) -> Result<(), ProviderEffectBindingError> {
    if value.trim().is_empty() {
        return Err(ProviderEffectBindingError::EmptyField(label));
    }
    Ok(())
}

fn validate_reason_code(value: &str) -> Result<(), ProviderEffectBindingError> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        return Err(ProviderEffectBindingError::InvalidReasonCode);
    }
    Ok(())
}

fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    use sha2::Digest;
    use sha2::Sha256;

    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::PROVIDER_EVIDENCE_SCHEMA_VERSION;
    use crate::ProviderRequestBinding;
    use crate::ProviderRequestKind;
    use crate::ProviderTransport;

    fn request_binding_id() -> RequestBindingId {
        RequestBindingId::for_request(&ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request"),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "provider-1".to_string(),
            provider_config_sha256: Sha256Digest::for_bytes(b"config"),
            model: "model-1".to_string(),
            transport: ProviderTransport::Http,
            endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
            logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
            wire_semantic_sha256: Sha256Digest::for_bytes(b"wire"),
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
    }

    fn intent(payload: &[u8]) -> ProviderEffectIntent {
        let key = ProviderEffectKey::for_occurrence(
            "provider-1/config-v1",
            "hepta.automation.v1:agent-a:task-a:1",
            &request_binding_id(),
        )
        .expect("effect key");
        ProviderEffectIntent::new(key, Sha256Digest::for_bytes(payload))
    }

    fn ack(intent: &ProviderEffectIntent, payload: &[u8]) -> ProviderEffectAck {
        ProviderEffectAck::new(
            intent.key.clone(),
            Sha256Digest::for_bytes(payload),
            Sha256Digest::for_bytes(b"provider-operation-1"),
            ProviderEffectAckStatus::Completed,
        )
    }

    #[test]
    fn occurrence_key_is_stable_across_physical_retries_and_excludes_payload() {
        let binding = request_binding_id();
        let first = ProviderEffectKey::for_occurrence("provider-1/config-v1", "occ-1", &binding)
            .expect("first key");
        let retry = ProviderEffectKey::for_occurrence("provider-1/config-v1", "occ-1", &binding)
            .expect("retry key");
        let changed_payload =
            ProviderEffectKey::for_occurrence("provider-1/config-v1", "occ-1", &binding)
                .expect("changed payload key");
        let changed_occurrence =
            ProviderEffectKey::for_occurrence("provider-1/config-v1", "occ-2", &binding)
                .expect("changed occurrence key");

        assert_eq!(first, retry);
        assert_eq!(first, changed_payload);
        assert_ne!(first, changed_occurrence);
    }

    #[test]
    fn same_key_different_payload_is_rejected() {
        let intent = intent(b"payload-a");
        let mismatched = ack(&intent, b"payload-b");
        assert_eq!(
            mismatched.validate_for(&intent),
            Err(ProviderEffectBindingError::PayloadMismatch)
        );
        assert_eq!(
            reconcile_provider_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &intent,
                ProviderEffectLookup::Ack(mismatched),
            ),
            Err(ProviderEffectBindingError::PayloadMismatch)
        );
    }

    #[test]
    fn matching_ack_binds_key_payload_and_operation() {
        let intent = intent(b"payload-a");
        let matching = ack(&intent, b"payload-a");
        assert!(matching.validate_for(&intent).is_ok());
        assert!(matching.proves_effect_completion());
        let reconciled = reconcile_provider_lookup(
            ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            &intent,
            ProviderEffectLookup::Ack(matching.clone()),
        )
        .expect("matching lookup");
        assert_eq!(reconciled, matching);
    }

    #[test]
    fn unsupported_capability_fails_closed_even_with_matching_ack() {
        let intent = intent(b"payload-a");
        let matching = ack(&intent, b"payload-a");
        assert_eq!(
            reconcile_provider_lookup(
                ProviderEffectIdempotencyCapability::Unsupported,
                &intent,
                ProviderEffectLookup::Ack(matching),
            ),
            Err(ProviderEffectBindingError::UnsupportedCapability)
        );
    }

    #[test]
    fn unknown_and_not_found_lookup_remain_quarantined() {
        let intent = intent(b"payload-a");
        for lookup in [
            ProviderEffectLookup::Unknown,
            ProviderEffectLookup::NotFound,
        ] {
            let error = reconcile_provider_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &intent,
                lookup,
            )
            .expect_err("lookup must not close intent");
            assert!(matches!(
                error,
                ProviderEffectBindingError::Unknown | ProviderEffectBindingError::NotFound
            ));
        }
    }

    #[test]
    fn conflict_lookup_is_not_a_success() {
        let intent = intent(b"payload-a");
        assert_eq!(
            reconcile_provider_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &intent,
                ProviderEffectLookup::Conflict {
                    observed_payload_sha256: Some(Sha256Digest::for_bytes(b"payload-b")),
                },
            ),
            Err(ProviderEffectBindingError::Conflict)
        );
    }

    #[test]
    fn accepted_ack_does_not_prove_effect_completion() {
        let intent = intent(b"payload-a");
        let accepted = ProviderEffectAck::new(
            intent.key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"provider-operation-1"),
            ProviderEffectAckStatus::Accepted,
        );
        assert!(!accepted.proves_effect_completion());
        assert!(accepted.validate_for(&intent).is_ok());
    }

    #[test]
    fn default_capability_is_unsupported() {
        assert_eq!(
            ProviderEffectIdempotencyCapability::default(),
            ProviderEffectIdempotencyCapability::Unsupported
        );
    }

    #[test]
    fn journal_persists_intent_and_monotonic_ack_observations() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let accepted = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-1"),
            ProviderEffectAckStatus::Accepted,
        );
        let completed = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-1"),
            ProviderEffectAckStatus::Completed,
        );
        let mut journal = ProviderEffectJournal::default();
        assert_eq!(
            journal.record_intent(intent.clone()),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(
            journal.record_intent(intent),
            Ok(ProviderEffectAppendDisposition::AlreadyPresent)
        );
        assert_eq!(
            journal.record_ack(accepted.clone()),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
        assert_eq!(
            journal.record_ack(completed.clone()),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Completed));
        assert!(journal.state(&key).expect("state").is_terminal());
        assert_eq!(
            journal.record_ack(accepted),
            Ok(ProviderEffectAppendDisposition::AlreadyPresent)
        );
        let conflicting_accepted = ProviderEffectAck::new(
            key,
            Sha256Digest::for_bytes(b"payload-a"),
            Sha256Digest::for_bytes(b"operation-2"),
            ProviderEffectAckStatus::Accepted,
        );
        assert_eq!(
            journal.record_ack(conflicting_accepted),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.record_ack(completed),
            Ok(ProviderEffectAppendDisposition::AlreadyPresent)
        );
    }

    #[test]
    fn journal_rejects_terminal_ack_replacement_and_unknown_lookup() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let completed = ack(&intent, b"payload-a");
        let rejected = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            completed.provider_operation_id_sha256.clone(),
            ProviderEffectAckStatus::Rejected,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal.record_ack(completed).expect("completed");
        assert_eq!(
            journal.record_ack(rejected),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.reconcile(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            ),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Completed));
    }

    #[test]
    fn journal_unknown_lookup_persists_quarantine_until_reconciled() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let accepted = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-1"),
            ProviderEffectAckStatus::Accepted,
        );
        let completed = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-2"),
            ProviderEffectAckStatus::Completed,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal.record_ack(accepted).expect("accepted");
        assert_eq!(
            journal.reconcile(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            ),
            Ok(ProviderEffectState::Indeterminate)
        );
        assert!(
            journal
                .state(&key)
                .is_some_and(ProviderEffectState::is_retry_blocked)
        );
        assert_eq!(journal.uncertainties(&key).len(), 1);
        assert_eq!(
            journal.record_ack_from_source(completed, ProviderEffectAckSource::StatusLookup),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Completed));
    }

    #[test]
    fn journal_status_acceptance_can_close_prior_quarantine() {
        let intent = intent(b"status-accepted-after-unknown");
        let key = intent.key.clone();
        let accepted_before_unknown = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-before-unknown"),
            ProviderEffectAckStatus::Accepted,
        );
        let accepted_after_unknown = ProviderEffectStatusObservation::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-after-unknown"),
            ProviderEffectAckStatus::Accepted,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal
            .record_ack(accepted_before_unknown)
            .expect("accepted ACK");
        journal
            .mark_indeterminate(&key, "provider_dispatch_unknown")
            .expect("quarantine");
        assert_eq!(
            journal.record_status_observation(accepted_after_unknown),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
        assert!(journal.validate().is_ok());
    }

    #[test]
    fn journal_rejects_late_dispatch_ack_after_quarantine() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let accepted = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-1"),
            ProviderEffectAckStatus::Accepted,
        );
        let late = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-2"),
            ProviderEffectAckStatus::Completed,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal.record_ack(accepted).expect("dispatch ACK");
        journal
            .mark_indeterminate(&key, "provider_dispatch_unknown")
            .expect("quarantine");
        assert_eq!(
            journal.record_ack(late),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
    }

    #[test]
    fn journal_late_dispatch_ack_after_pending_quarantine_is_side_effect_free() {
        let intent = intent(b"pending-quarantine-payload");
        let key = intent.key.clone();
        let late_ack = ack(&intent, b"pending-quarantine-payload");
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal
            .mark_indeterminate(&key, "provider_imported_pending")
            .expect("quarantine");
        let before = serde_json::to_vec(&journal).expect("serialize before late ACK");

        // There is no prior ACK vector for an imported Pending intent.  A
        // delayed raw response must be rejected without creating empty ACK or
        // provenance entries that would make the journal permanently invalid.
        assert_eq!(
            journal.record_ack(late_ack),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert!(journal.validate().is_ok());
        assert_eq!(
            serde_json::to_vec(&journal).expect("serialize after late ACK"),
            before
        );
        assert_eq!(journal.acknowledgements(&key), &[]);
        assert_eq!(journal.acknowledgement_sources(&key), &[]);
        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
    }

    #[test]
    fn status_observation_binds_exact_payload_and_requires_lookup_source() {
        let intent = intent(b"status-payload");
        let key = intent.key.clone();
        let operation = Sha256Digest::for_bytes(b"status-operation-1");
        let observation = ProviderEffectStatusObservation::new(
            key.clone(),
            intent.payload_sha256.clone(),
            operation,
            ProviderEffectAckStatus::Accepted,
        );
        assert!(observation.validate_for(&intent).is_ok());

        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        assert_eq!(
            journal.record_status_observation(observation.clone()),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        assert_eq!(
            journal.status_observations(&key),
            std::slice::from_ref(&observation)
        );

        let mut forged_source = observation.clone();
        forged_source.source = ProviderEffectAckSource::DispatchResponse;
        assert_eq!(
            journal.record_status_observation(forged_source),
            Err(ProviderEffectBindingError::StatusObservationSourceRequired)
        );

        let mut forged_payload = observation.clone();
        forged_payload.payload_sha256 = Sha256Digest::for_bytes(b"different-payload");
        assert_eq!(
            journal.record_status_observation(forged_payload),
            Err(ProviderEffectBindingError::PayloadMismatch)
        );

        let mut forged_operation = observation;
        forged_operation.provider_operation_id_sha256 =
            Sha256Digest::for_bytes(b"status-operation-forged");
        assert_eq!(
            journal.record_status_observation(forged_operation),
            Err(ProviderEffectBindingError::AckConflict)
        );
    }

    #[test]
    fn status_observation_is_monotonic_and_rejects_late_dispatch_or_unknown() {
        let intent = intent(b"status-monotonic-payload");
        let key = intent.key.clone();
        let operation = Sha256Digest::for_bytes(b"status-monotonic-operation");
        let accepted = ProviderEffectStatusObservation::new(
            key.clone(),
            intent.payload_sha256.clone(),
            operation.clone(),
            ProviderEffectAckStatus::Accepted,
        );
        let completed = ProviderEffectStatusObservation::new(
            key.clone(),
            intent.payload_sha256.clone(),
            operation,
            ProviderEffectAckStatus::Completed,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal
            .record_status_observation(accepted)
            .expect("accepted status");
        assert_eq!(
            journal.reconcile_status_observation(completed.clone()),
            Ok(ProviderEffectState::Completed)
        );
        assert_eq!(
            journal.record_status_observation(completed.clone()),
            Ok(ProviderEffectAppendDisposition::AlreadyPresent)
        );
        assert_eq!(
            journal.record_ack(completed.to_ack()),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.reconcile(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            ),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(journal.status_observations(&key).len(), 2);
    }

    #[test]
    fn status_accepted_fences_late_dispatch_transition() {
        let intent = intent(b"status-accepted-late-dispatch");
        let key = intent.key.clone();
        let operation = Sha256Digest::for_bytes(b"status-accepted-operation");
        let accepted = ProviderEffectStatusObservation::new(
            key.clone(),
            intent.payload_sha256.clone(),
            operation.clone(),
            ProviderEffectAckStatus::Accepted,
        );
        let late_completed = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            operation,
            ProviderEffectAckStatus::Completed,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal
            .record_status_observation(accepted)
            .expect("status Accepted");

        // The response may be a delayed result from the original dispatch.
        // Even with the same operation id and a monotonic status, it cannot
        // supersede the provider-owned status observation.
        assert_eq!(
            journal.record_ack(late_completed),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
        assert_eq!(
            journal.acknowledgement_sources(&key),
            &[ProviderEffectAckSource::StatusLookup]
        );
        assert!(journal.validate().is_ok());
    }

    #[test]
    fn journal_unknown_lookup_cannot_turn_accepted_into_rejected() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let accepted = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-accepted"),
            ProviderEffectAckStatus::Accepted,
        );
        let rejected = ProviderEffectAck::new(
            key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"operation-authoritative"),
            ProviderEffectAckStatus::Rejected,
        );
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent).expect("intent");
        journal.record_ack(accepted).expect("accepted");
        journal
            .reconcile(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            )
            .expect("unknown is quarantined");
        assert_eq!(
            journal.record_ack(rejected),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
    }

    #[test]
    fn journal_round_trip_is_serializable_without_plain_payloads() {
        let intent = intent(b"secret-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"secret-payload"))
            .expect("ack");
        let encoded = serde_json::to_vec(&journal).expect("serialize journal");
        assert!(!String::from_utf8_lossy(&encoded).contains("secret-payload"));
        let decoded: ProviderEffectJournal =
            serde_json::from_slice(&encoded).expect("deserialize journal");
        assert_eq!(decoded.state(&key), Some(ProviderEffectState::Completed));
        assert_eq!(decoded, journal);
    }

    #[test]
    fn journal_without_ack_sources_remains_compatible_when_empty() {
        let journal = ProviderEffectJournal::default();
        let mut encoded = serde_json::to_value(&journal).expect("serialize empty journal");
        encoded
            .as_object_mut()
            .expect("journal object")
            .remove("ack_sources");
        let decoded: ProviderEffectJournal =
            serde_json::from_value(encoded).expect("empty legacy journal remains readable");
        assert_eq!(decoded, journal);
    }

    #[test]
    fn journal_with_ack_requires_exact_ack_source_provenance() {
        let intent = intent(b"legacy-ack-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"legacy-ack-payload"))
            .expect("ACK");

        let encoded = serde_json::to_value(&journal).expect("serialize journal");
        let mut missing_sources = encoded.clone();
        missing_sources
            .as_object_mut()
            .expect("journal object")
            .remove("ack_sources");
        assert!(serde_json::from_value::<ProviderEffectJournal>(missing_sources).is_err());

        let mut misaligned_sources = encoded;
        misaligned_sources
            .get_mut("ack_sources")
            .and_then(|sources| sources.get_mut(key.as_str()))
            .and_then(serde_json::Value::as_array_mut)
            .expect("source vector")
            .clear();
        assert!(serde_json::from_value::<ProviderEffectJournal>(misaligned_sources).is_err());

        let mut unknown_source = serde_json::to_value(&journal).expect("serialize journal");
        *unknown_source
            .get_mut("ack_sources")
            .and_then(|sources| sources.get_mut(key.as_str()))
            .and_then(serde_json::Value::as_array_mut)
            .and_then(|sources| sources.first_mut())
            .expect("source vector entry") = serde_json::Value::String("forged_source".into());
        assert!(serde_json::from_value::<ProviderEffectJournal>(unknown_source).is_err());
    }

    #[test]
    fn journal_deserialization_rejects_malformed_ack_contents() {
        let intent = intent(b"nested-ack-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"nested-ack-payload"))
            .expect("ACK");

        let mut encoded = serde_json::to_value(&journal).expect("serialize journal");
        *encoded
            .get_mut("acknowledgements")
            .and_then(|acks| acks.get_mut(key.as_str()))
            .and_then(serde_json::Value::as_array_mut)
            .and_then(|acks| acks.first_mut())
            .and_then(|ack| ack.get_mut("payload_sha256"))
            .expect("ACK payload") = serde_json::Value::String(
            Sha256Digest::for_bytes(b"forged-payload")
                .as_str()
                .to_string(),
        );
        assert!(serde_json::from_value::<ProviderEffectJournal>(encoded).is_err());
    }

    #[test]
    fn malformed_in_memory_journal_contents_fail_closed_before_state_or_append() {
        let intent = intent(b"in-memory-journal-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"in-memory-journal-payload"))
            .expect("ACK");
        journal
            .acknowledgements
            .get_mut(key.as_str())
            .expect("ACK vector")
            .first_mut()
            .expect("ACK")
            .payload_sha256 = Sha256Digest::for_bytes(b"forged-payload");

        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
        assert_eq!(journal.acknowledgements(&key), &[]);
        assert_eq!(
            journal.record_intent(intent),
            Err(ProviderEffectBindingError::AckConflict)
        );
    }

    #[test]
    fn malformed_in_memory_ack_provenance_fails_closed_before_state_or_record() {
        let intent = intent(b"in-memory-provenance-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"in-memory-provenance-payload"))
            .expect("ACK");
        journal
            .ack_sources
            .get_mut(key.as_str())
            .expect("source vector")
            .clear();

        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
        assert_eq!(journal.acknowledgements(&key), &[]);
        assert_eq!(
            journal.record_intent(intent),
            Err(ProviderEffectBindingError::AckConflict)
        );
    }

    #[tokio::test]
    async fn coordinator_rejects_malformed_ack_provenance_before_adapter_call() {
        let intent = intent(b"coordinator-provenance-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal.record_intent(intent.clone()).expect("intent");
        journal
            .record_ack(ack(&intent, b"coordinator-provenance-payload"))
            .expect("ACK");
        journal
            .ack_sources
            .get_mut(key.as_str())
            .expect("source vector")
            .clear();

        let mut coordinator =
            ProviderEffectCoordinator::with_journal(ScriptedAdapter::default(), journal);
        assert_eq!(
            coordinator.dispatch_once(intent).await,
            Err(ProviderEffectCoordinatorError::Binding(
                ProviderEffectBindingError::AckConflict
            ))
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            0
        );
    }

    #[derive(Default)]
    struct ScriptedAdapter {
        capability: ProviderEffectIdempotencyCapability,
        dispatches: std::sync::atomic::AtomicU32,
        lookups: std::sync::atomic::AtomicU32,
        intent_lookups: std::sync::atomic::AtomicU32,
        dispatch_result: Option<ProviderEffectDispatch>,
        lookup_result: Option<ProviderEffectLookup>,
    }

    impl ProviderEffectAdapter for ScriptedAdapter {
        fn capability(&self) -> ProviderEffectIdempotencyCapability {
            self.capability
        }

        fn dispatch<'a>(
            &'a self,
            _intent: &'a ProviderEffectIntent,
        ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
            self.dispatches
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let result = self
                .dispatch_result
                .clone()
                .unwrap_or(ProviderEffectDispatch::Unknown);
            Box::pin(std::future::ready(result))
        }

        fn lookup<'a>(
            &'a self,
            _key: &'a ProviderEffectKey,
        ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
            self.lookups
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let result = self
                .lookup_result
                .clone()
                .unwrap_or(ProviderEffectLookup::Unknown);
            Box::pin(std::future::ready(result))
        }

        fn lookup_for_intent<'a>(
            &'a self,
            intent: &'a ProviderEffectIntent,
        ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
            self.intent_lookups
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            self.lookup(&intent.key)
        }
    }

    #[tokio::test]
    async fn coordinator_quarantines_unknown_and_never_blind_retries() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let operation = Sha256Digest::for_bytes(b"operation-1");
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            dispatch_result: Some(ProviderEffectDispatch::Unknown),
            lookup_result: Some(ProviderEffectLookup::Ack(ProviderEffectAck::new(
                key.clone(),
                intent.payload_sha256.clone(),
                operation,
                ProviderEffectAckStatus::Completed,
            ))),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::new(adapter);
        let first = coordinator
            .dispatch_once(intent.clone())
            .await
            .expect("first dispatch");
        assert_eq!(
            first,
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: true,
            }
        );
        let second = coordinator
            .dispatch_once(intent)
            .await
            .expect("quarantined replay");
        assert_eq!(
            second,
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            }
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
        assert_eq!(
            coordinator.reconcile(&key).await,
            Ok(ProviderEffectState::Completed)
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
        assert_eq!(
            coordinator
                .adapter()
                .intent_lookups
                .load(std::sync::atomic::Ordering::Relaxed),
            1,
            "reconcile must pass the exact durable intent to the adapter"
        );
        assert_eq!(coordinator.journal().acknowledgements(&key).len(), 1);
    }

    #[tokio::test]
    async fn coordinator_quarantines_malformed_dispatch_ack_before_returning_error() {
        let intent = intent(b"malformed-dispatch-ack-payload");
        let key = intent.key.clone();
        let malformed = ProviderEffectAck::new(
            key.clone(),
            Sha256Digest::for_bytes(b"wrong-payload"),
            Sha256Digest::for_bytes(b"operation-malformed"),
            ProviderEffectAckStatus::Completed,
        );
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            dispatch_result: Some(ProviderEffectDispatch::Ack(malformed)),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::new(adapter);

        assert_eq!(
            coordinator.dispatch_once(intent.clone()).await,
            Err(ProviderEffectCoordinatorError::Binding(
                ProviderEffectBindingError::PayloadMismatch
            ))
        );
        assert_eq!(
            coordinator.journal().state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
        assert!(coordinator.journal().validate().is_ok());
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );

        // The failed response is an unknown physical outcome.  A replay must
        // stay quarantined and never invoke the adapter a second time.
        let replay = coordinator
            .dispatch_once(intent)
            .await
            .expect("malformed ACK replay remains fail-closed");
        assert_eq!(
            replay,
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            }
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }

    #[tokio::test]
    async fn payload_coordinator_quarantines_malformed_dispatch_ack_before_retry() {
        let intent = intent(b"malformed-payload-dispatch-ack");
        let key = intent.key.clone();
        let malformed = ProviderEffectAck::new(
            key.clone(),
            Sha256Digest::for_bytes(b"wrong-payload"),
            Sha256Digest::for_bytes(b"operation-malformed-payload"),
            ProviderEffectAckStatus::Completed,
        );
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            dispatch_result: Some(ProviderEffectDispatch::Ack(malformed)),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::new(adapter);

        assert_eq!(
            coordinator
                .dispatch_once_with_payload(intent.clone(), b"malformed-payload-dispatch-ack")
                .await,
            Err(ProviderEffectCoordinatorError::Binding(
                ProviderEffectBindingError::PayloadMismatch
            ))
        );
        assert_eq!(
            coordinator.journal().state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
        assert!(coordinator.journal().validate().is_ok());
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );

        let replay = coordinator
            .dispatch_once_with_payload(intent, b"malformed-payload-dispatch-ack")
            .await
            .expect("malformed payload ACK replay remains fail-closed");
        assert!(!replay.physical_dispatch_attempted);
        assert_eq!(replay.state, ProviderEffectState::Indeterminate);
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }

    #[tokio::test]
    async fn coordinator_restored_pending_is_quarantined_before_dispatch() {
        let intent = intent(b"restored-pending-payload");
        let key = intent.key.clone();
        let mut journal = ProviderEffectJournal::default();
        journal
            .record_intent(intent.clone())
            .expect("persist intent before simulated crash");

        // Round-tripping the journal models a process restart after the
        // intent was durable but before the coordinator could record its
        // dispatch-boundary witness.  The restored Pending state is therefore
        // not proof that this coordinator owns a safe physical send.
        let encoded = serde_json::to_vec(&journal).expect("serialize pending journal");
        let restored: ProviderEffectJournal =
            serde_json::from_slice(&encoded).expect("restore pending journal");
        let completion = ack(&intent, b"restored-pending-payload");
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            dispatch_result: Some(ProviderEffectDispatch::Ack(completion.clone())),
            lookup_result: Some(ProviderEffectLookup::Ack(completion)),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::with_journal(adapter, restored);

        let dispatch = coordinator
            .dispatch_once(intent.clone())
            .await
            .expect("restored pending must quarantine");
        assert_eq!(
            dispatch,
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            }
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            0,
            "a restored Pending intent must never be blindly resent"
        );
        assert_eq!(
            coordinator.journal().uncertainties(&key),
            &[ProviderEffectUncertainty::new(
                key.clone(),
                intent.payload_sha256.clone(),
                PROVIDER_EFFECT_IMPORTED_PENDING_REASON,
            )]
        );

        // Reconciliation remains the only path that may close the imported
        // occurrence, and it must retain the adapter's status provenance.
        assert_eq!(
            coordinator.reconcile(&key).await,
            Ok(ProviderEffectState::Completed)
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            0
        );
        assert_eq!(
            coordinator
                .adapter()
                .lookups
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
        assert_eq!(
            coordinator.journal().acknowledgement_sources(&key),
            &[ProviderEffectAckSource::StatusLookup]
        );
    }

    #[tokio::test]
    async fn coordinator_restored_pending_payload_path_is_quarantined_before_dispatch() {
        let intent = intent(b"restored-pending-payload-path");
        let mut journal = ProviderEffectJournal::default();
        journal
            .record_intent(intent.clone())
            .expect("persist intent before simulated crash");
        let encoded = serde_json::to_vec(&journal).expect("serialize pending journal");
        let restored: ProviderEffectJournal =
            serde_json::from_slice(&encoded).expect("restore pending journal");
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            dispatch_result: Some(ProviderEffectDispatch::Ack(ack(
                &intent,
                b"restored-pending-payload-path",
            ))),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::with_journal(adapter, restored);

        let dispatch = coordinator
            .dispatch_once_with_payload(intent, b"restored-pending-payload-path")
            .await
            .expect("restored pending payload path must quarantine");
        assert_eq!(
            dispatch,
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            }
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            0,
            "payload dispatch must not bypass imported Pending quarantine"
        );
    }

    #[tokio::test]
    async fn coordinator_unsupported_capability_stays_quarantined() {
        let intent = intent(b"payload-a");
        let key = intent.key.clone();
        let mut coordinator = ProviderEffectCoordinator::new(ScriptedAdapter {
            dispatch_result: Some(ProviderEffectDispatch::Ack(ack(&intent, b"payload-a"))),
            ..Default::default()
        });
        let receipt = coordinator
            .dispatch_once(intent)
            .await
            .expect("local ACK can be recorded");
        assert_eq!(receipt.state, ProviderEffectState::Completed);
        // A terminal local state is not reopened by an unsupported adapter.
        assert_eq!(
            coordinator.reconcile(&key).await,
            Ok(ProviderEffectState::Completed)
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }

    #[tokio::test]
    async fn coordinator_unsupported_capability_never_calls_lookup() {
        let intent = intent(b"unsupported-lookup-payload");
        let key = intent.key.clone();
        let adapter = ScriptedAdapter {
            capability: ProviderEffectIdempotencyCapability::Unsupported,
            dispatch_result: Some(ProviderEffectDispatch::Unknown),
            // If the unsupported lookup were incorrectly called, this ACK
            // would appear to close the effect.  The capability pre-gate must
            // prevent that path entirely.
            lookup_result: Some(ProviderEffectLookup::Ack(ack(
                &intent,
                b"unsupported-lookup-payload",
            ))),
            ..Default::default()
        };
        let mut coordinator = ProviderEffectCoordinator::new(adapter);
        assert_eq!(
            coordinator
                .dispatch_once(intent)
                .await
                .expect("dispatch quarantine")
                .state,
            ProviderEffectState::Indeterminate
        );
        assert_eq!(
            coordinator.reconcile(&key).await,
            Err(ProviderEffectCoordinatorError::Binding(
                ProviderEffectBindingError::UnsupportedCapability
            ))
        );
        assert_eq!(
            coordinator
                .adapter()
                .lookups
                .load(std::sync::atomic::Ordering::Relaxed),
            0
        );
        assert_eq!(
            coordinator.journal().state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
    }

    #[tokio::test]
    async fn payload_coordinator_rejects_mismatch_before_adapter_call() {
        let intent = intent(b"payload-a");
        let mut coordinator = ProviderEffectCoordinator::new(ScriptedAdapter::default());
        assert_eq!(
            coordinator
                .dispatch_once_with_payload(intent, b"payload-b")
                .await,
            Err(ProviderEffectCoordinatorError::Binding(
                ProviderEffectBindingError::PayloadMismatch
            ))
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            0
        );
    }

    #[tokio::test]
    async fn payload_coordinator_marks_explicit_not_dispatched_without_physical_attempt() {
        let intent = intent(b"payload-a");
        let mut coordinator = ProviderEffectCoordinator::new(ScriptedAdapter {
            dispatch_result: Some(ProviderEffectDispatch::NotDispatched {
                reason_code: "provider_effect_capability_unsupported".to_string(),
            }),
            ..Default::default()
        });
        assert_eq!(
            coordinator
                .dispatch_once_with_payload(intent, b"payload-a")
                .await
                .expect("quarantine receipt"),
            ProviderEffectDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                physical_dispatch_attempted: false,
            }
        );
        assert_eq!(
            coordinator
                .adapter()
                .dispatches
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }
}
