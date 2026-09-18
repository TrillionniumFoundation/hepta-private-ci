use std::collections::BTreeMap;
use std::fmt;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::journal::DurableShellJournal;
use crate::platform::PermissionDecision;
use crate::platform::PlatformAction;
use crate::platform::PlatformAdapter;
use crate::platform::PlatformObservation;
use crate::platform::PlatformPayload;

const MAX_VIEW_MODULES: usize = 256;
const MAX_GRANT_REPLAY_SUBJECTS: usize = 4_096;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct SessionOperationKey {
    pub session_id: StableId,
    pub session_generation: Generation,
    pub operation_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EndpointManifest {
    pub endpoint_id: StableId,
    pub manifest_digest: Digest32,
    pub protocol_version: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendSessionObservation {
    pub authenticated: bool,
    pub protocol_version: u32,
    pub session_id: StableId,
    pub generation: Generation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeSession {
    pub endpoint_id: StableId,
    pub manifest_digest: Digest32,
    pub protocol_version: u32,
    pub session_id: StableId,
    pub generation: Generation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeView {
    pub session_id: StableId,
    pub session_generation: Generation,
    pub generation: u64,
    pub revision: u64,
    pub digest: Digest32,
    pub modules: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativePresentationState {
    pub session_id: StableId,
    pub session_generation: Generation,
    pub generation: u64,
    pub revision: u64,
    pub digest: Digest32,
    pub modules: Vec<StableId>,
    pub stale: bool,
}

pub struct PlatformCapabilityRequest {
    pub operation_id: StableId,
    pub displayed_revision: u64,
    pub payload: PlatformPayload,
    pub grant: SignedMessage,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformDecisionStatus {
    Rejected,
    Indeterminate,
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlatformDecision {
    pub key: SessionOperationKey,
    pub action: PlatformAction,
    pub payload_digest: Digest32,
    pub status: PlatformDecisionStatus,
    pub terminal_observed: bool,
    pub outcome_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OperationRecord {
    pub(crate) key: SessionOperationKey,
    pub(crate) action: PlatformAction,
    pub(crate) payload_digest: Digest32,
    pub(crate) grant_receipt_digest: Digest32,
    pub(crate) decision: PlatformDecision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ShellError {
    InvalidProtocolVersion,
    BackendUnauthenticated,
    BackendProtocolMismatch,
    NotConnected,
    ViewRequired,
    ViewSessionMismatch,
    ViewGenerationMismatch,
    ViewRegressed,
    ViewRevisionDidNotAdvance,
    ViewDigestZero,
    ViewTooLarge,
    DisplayedRevisionStale,
    OperationPayloadChanged,
    GrantIssuerMismatch,
    GrantSubjectMismatch,
    GrantReplay,
    GrantReplayCapacity,
    GrantRejected(String),
    Platform(String),
    Journal(String),
    Clock,
}

impl fmt::Display for ShellError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ShellError {}

/// Verifies a signed, session/operation/final-payload-bound grant.
///
/// The verifier owns the trusted issuer registration and a bounded replay
/// window. The signed payload digest includes the current session identity and
/// generation, so a grant cannot be moved to a replacement session even when
/// the operation id and platform payload are identical.
pub struct TrustedGrantVerifier {
    issuer: IssuerRegistration,
    highest_sequence: BTreeMap<StableId, u64>,
    maximum_subjects: usize,
}

impl TrustedGrantVerifier {
    pub fn new(issuer: IssuerRegistration) -> Self {
        Self {
            issuer,
            highest_sequence: BTreeMap::new(),
            maximum_subjects: MAX_GRANT_REPLAY_SUBJECTS,
        }
    }

    fn verify(
        &mut self,
        grant: &SignedMessage,
        key: &SessionOperationKey,
        action: PlatformAction,
        payload_digest: Digest32,
        now_ms: u64,
    ) -> Result<Digest32, ShellError> {
        let expected_scope = action.scope_digest();
        let expected_payload = platform_grant_binding_digest(key, action, payload_digest);
        let authenticated = grant
            .authenticate(&self.issuer, expected_scope, expected_payload, now_ms)
            .map_err(|error| ShellError::GrantRejected(error.to_string()))?;
        if authenticated.claims().issuer_id != self.issuer.issuer_id {
            return Err(ShellError::GrantIssuerMismatch);
        }
        if authenticated.claims().subject_id != key.operation_id {
            return Err(ShellError::GrantSubjectMismatch);
        }
        let sequence = authenticated.claims().sequence;
        if self
            .highest_sequence
            .get(&key.operation_id)
            .is_some_and(|highest| *highest >= sequence)
        {
            return Err(ShellError::GrantReplay);
        }
        if !self.highest_sequence.contains_key(&key.operation_id)
            && self.highest_sequence.len() >= self.maximum_subjects
        {
            return Err(ShellError::GrantReplayCapacity);
        }
        self.highest_sequence
            .insert(key.operation_id.clone(), sequence);
        Ok(authenticated.receipt().envelope_digest)
    }
}

/// Session-fenced native shell core.
///
/// Operation identity is `(session_id, session_generation, operation_id)`.
/// An indeterminate dispatch record is synced before an OS effect is invoked.
/// A duplicate or recovered operation therefore reconciles instead of
/// replaying the effect. Terminal receipts are idempotent only inside the same
/// session incarnation and for the same canonical payload digest.
pub struct NativeShellRuntime<P: PlatformAdapter> {
    pub(crate) platform: P,
    grant_verifier: TrustedGrantVerifier,
    session: Option<NativeSession>,
    view: Option<NativePresentationState>,
    operations: BTreeMap<SessionOperationKey, OperationRecord>,
    journal: Option<DurableShellJournal>,
}

impl<P: PlatformAdapter> NativeShellRuntime<P> {
    pub fn new(platform: P, grant_verifier: TrustedGrantVerifier) -> Self {
        Self {
            platform,
            grant_verifier,
            session: None,
            view: None,
            operations: BTreeMap::new(),
            journal: None,
        }
    }

    pub fn open_with_journal(
        platform: P,
        grant_verifier: TrustedGrantVerifier,
        journal_path: impl Into<PathBuf>,
    ) -> Result<Self, ShellError> {
        let (journal, operations) = DurableShellJournal::open(journal_path)
            .map_err(|error| ShellError::Journal(error.to_string()))?;
        Ok(Self {
            platform,
            grant_verifier,
            session: None,
            view: None,
            operations,
            journal: Some(journal),
        })
    }

    pub fn connect_runtime(
        &mut self,
        manifest: EndpointManifest,
        observed: BackendSessionObservation,
    ) -> Result<NativeSession, ShellError> {
        if manifest.protocol_version == 0 {
            return Err(ShellError::InvalidProtocolVersion);
        }
        if !observed.authenticated {
            return Err(ShellError::BackendUnauthenticated);
        }
        if observed.protocol_version != manifest.protocol_version {
            return Err(ShellError::BackendProtocolMismatch);
        }
        let session = NativeSession {
            endpoint_id: manifest.endpoint_id,
            manifest_digest: manifest.manifest_digest,
            protocol_version: manifest.protocol_version,
            session_id: observed.session_id,
            generation: observed.generation,
        };
        self.session = Some(session.clone());
        self.view = None;
        Ok(session)
    }

    pub fn close(&mut self) {
        self.session = None;
        self.view = None;
        // Historical records deliberately remain fenced by session identity.
        // They may be reconciled, but can never satisfy a replacement session.
    }

    pub fn render_runtime_view(
        &mut self,
        view: RuntimeView,
    ) -> Result<NativePresentationState, ShellError> {
        let session = self.session.as_ref().ok_or(ShellError::NotConnected)?;
        if view.session_id != session.session_id {
            return Err(ShellError::ViewSessionMismatch);
        }
        if view.session_generation != session.generation {
            return Err(ShellError::ViewGenerationMismatch);
        }
        if view.generation == 0 || view.revision == 0 {
            return Err(ShellError::ViewRegressed);
        }
        if view.digest.is_zero() {
            return Err(ShellError::ViewDigestZero);
        }
        if view.modules.len() > MAX_VIEW_MODULES {
            return Err(ShellError::ViewTooLarge);
        }
        if let Some(current) = &self.view {
            if view.generation < current.generation {
                return Err(ShellError::ViewRegressed);
            }
            if view.generation == current.generation && view.revision <= current.revision {
                return Err(ShellError::ViewRevisionDidNotAdvance);
            }
        }
        let presentation = NativePresentationState {
            session_id: view.session_id,
            session_generation: view.session_generation,
            generation: view.generation,
            revision: view.revision,
            digest: view.digest,
            modules: view.modules,
            stale: false,
        };
        self.view = Some(presentation.clone());
        Ok(presentation)
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformCapabilityRequest,
    ) -> Result<PlatformDecision, ShellError> {
        self.request_platform_capability_at(request, now_unix_ms()?)
    }

    pub fn request_platform_capability_at(
        &mut self,
        request: PlatformCapabilityRequest,
        now_ms: u64,
    ) -> Result<PlatformDecision, ShellError> {
        let session = self.session.as_ref().ok_or(ShellError::NotConnected)?;
        let view = self.view.as_ref().ok_or(ShellError::ViewRequired)?;
        if request.displayed_revision != view.revision {
            return Err(ShellError::DisplayedRevisionStale);
        }
        let action = request.payload.action();
        let payload_digest = request.payload.digest();
        let key = SessionOperationKey {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            operation_id: request.operation_id.clone(),
        };

        if let Some(prior) = self.operations.get(&key).cloned() {
            if prior.payload_digest != payload_digest {
                return Err(ShellError::OperationPayloadChanged);
            }
            if prior.decision.terminal_observed {
                return Ok(prior.decision);
            }
            return self.reconcile_one(prior);
        }

        request
            .payload
            .validate()
            .map_err(|error| ShellError::Platform(error.to_string()))?;
        let grant_receipt_digest = self.grant_verifier.verify(
            &request.grant,
            &key,
            action,
            payload_digest,
            now_ms,
        )?;
        match self
            .platform
            .permission(action, &request.payload)
            .map_err(|error| ShellError::Platform(error.to_string()))?
        {
            PermissionDecision::Denied { outcome_digest } => {
                let decision = PlatformDecision {
                    key: key.clone(),
                    action,
                    payload_digest,
                    status: PlatformDecisionStatus::Rejected,
                    terminal_observed: true,
                    outcome_digest: Some(outcome_digest),
                };
                let record = OperationRecord {
                    key,
                    action,
                    payload_digest,
                    grant_receipt_digest,
                    decision: decision.clone(),
                };
                self.store_record(record)?;
                return Ok(decision);
            }
            PermissionDecision::Allowed => {}
        }

        // Persist uncertainty before crossing the platform boundary. If the
        // process exits after this point, reopen must reconcile and may never
        // blindly invoke the same operation again.
        let dispatch_intent = PlatformDecision {
            key: key.clone(),
            action,
            payload_digest,
            status: PlatformDecisionStatus::Indeterminate,
            terminal_observed: false,
            outcome_digest: None,
        };
        self.store_record(OperationRecord {
            key: key.clone(),
            action,
            payload_digest,
            grant_receipt_digest,
            decision: dispatch_intent,
        })?;

        let observed = self
            .platform
            .invoke(&key, &request.payload, payload_digest)
            .map_err(|error| ShellError::Platform(error.to_string()))?;
        let decision = decision_from_observation(key.clone(), action, payload_digest, observed);
        let prior = self
            .operations
            .get(&key)
            .cloned()
            .ok_or_else(|| ShellError::Journal("dispatch intent disappeared".to_string()))?;
        self.store_record(OperationRecord {
            decision: decision.clone(),
            ..prior
        })?;
        Ok(decision)
    }

    /// Reconcile every recovered/non-terminal operation without replaying its
    /// platform invocation. This is safe to call before connecting a new
    /// session because each record carries its own historical session fence.
    pub fn reconcile_indeterminate(&mut self) -> Result<Vec<PlatformDecision>, ShellError> {
        let keys = self
            .operations
            .iter()
            .filter_map(|(key, record)| {
                (!record.decision.terminal_observed).then_some(key.clone())
            })
            .collect::<Vec<_>>();
        let mut decisions = Vec::with_capacity(keys.len());
        for key in keys {
            let Some(prior) = self.operations.get(&key).cloned() else {
                continue;
            };
            decisions.push(self.reconcile_one(prior)?);
        }
        Ok(decisions)
    }

    pub fn current_session(&self) -> Option<&NativeSession> {
        self.session.as_ref()
    }

    pub fn current_view(&self) -> Option<&NativePresentationState> {
        self.view.as_ref()
    }

    pub fn operation_count(&self) -> usize {
        self.operations.len()
    }

    pub fn journal_path(&self) -> Option<&std::path::Path> {
        self.journal.as_ref().map(DurableShellJournal::path)
    }

    fn reconcile_one(&mut self, prior: OperationRecord) -> Result<PlatformDecision, ShellError> {
        let observed = self
            .platform
            .reconcile(&prior.key, prior.action, prior.payload_digest)
            .map_err(|error| ShellError::Platform(error.to_string()))?;
        let decision = decision_from_observation(
            prior.key.clone(),
            prior.action,
            prior.payload_digest,
            observed,
        );
        if decision != prior.decision {
            self.store_record(OperationRecord {
                decision: decision.clone(),
                ..prior
            })?;
        }
        Ok(decision)
    }

    fn store_record(&mut self, record: OperationRecord) -> Result<(), ShellError> {
        if let Some(journal) = &mut self.journal {
            journal
                .append(&record)
                .map_err(|error| ShellError::Journal(error.to_string()))?;
        }
        self.operations.insert(record.key.clone(), record);
        Ok(())
    }
}

pub fn platform_grant_binding_digest(
    key: &SessionOperationKey,
    action: PlatformAction,
    payload_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ui.native.platform-grant-binding.v1\0".to_vec();
    push_text(&mut bytes, key.session_id.as_str());
    bytes.extend_from_slice(&key.session_generation.get().to_be_bytes());
    push_text(&mut bytes, key.operation_id.as_str());
    push_text(&mut bytes, action.as_str());
    bytes.extend_from_slice(payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

fn decision_from_observation(
    key: SessionOperationKey,
    action: PlatformAction,
    payload_digest: Digest32,
    observed: PlatformObservation,
) -> PlatformDecision {
    match observed {
        PlatformObservation::Succeeded { outcome_digest } => PlatformDecision {
            key,
            action,
            payload_digest,
            status: PlatformDecisionStatus::Succeeded,
            terminal_observed: true,
            outcome_digest: Some(outcome_digest),
        },
        PlatformObservation::Failed { outcome_digest } => PlatformDecision {
            key,
            action,
            payload_digest,
            status: PlatformDecisionStatus::Failed,
            terminal_observed: true,
            outcome_digest: Some(outcome_digest),
        },
        PlatformObservation::Indeterminate => PlatformDecision {
            key,
            action,
            payload_digest,
            status: PlatformDecisionStatus::Indeterminate,
            terminal_observed: false,
            outcome_digest: None,
        },
    }
}

pub(crate) fn now_unix_ms() -> Result<u64, ShellError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| ShellError::Clock)?;
    u64::try_from(duration.as_millis()).map_err(|_| ShellError::Clock)
}

#[cfg(test)]
#[path = "shell_tests.rs"]
mod tests;
