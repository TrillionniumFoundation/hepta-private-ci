use std::collections::BTreeMap;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const MAX_OPERATION_RECORDS: usize = 24;
pub const MAX_OPERATION_ID_BYTES: usize = 128;
pub const MAX_RESOURCE_BYTES: usize = 4096;
pub const MAX_COPY_TEXT_BYTES: usize = 64 * 1024;
pub const MAX_NOTIFICATION_TITLE_BYTES: usize = 256;
pub const MAX_NOTIFICATION_BODY_BYTES: usize = 4096;

#[derive(Debug, Error)]
pub enum NativeError {
    #[error("invalid native input: {0}")]
    Invalid(String),
    #[error("native backend unavailable: {0}")]
    Backend(String),
    #[error("native platform boundary unavailable: {0}")]
    Platform(String),
    #[error("native operation journal unavailable: {0}")]
    Journal(String),
    #[error("native update boundary unavailable: {0}")]
    Update(String),
    #[error(
        "operation {operation_id} belongs to prior session {prior_session}/{prior_generation}"
    )]
    OperationFenced {
        operation_id: String,
        prior_session: String,
        prior_generation: u64,
    },
    #[error("operation {0} was reused with different semantics")]
    OperationConflict(String),
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionFence {
    pub session_id: String,
    pub generation: u64,
}

impl SessionFence {
    pub fn validate(&self) -> Result<(), NativeError> {
        stable_id(&self.session_id, "session_id")?;
        if self.generation == 0 {
            return Err(NativeError::Invalid(
                "session generation must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EndpointManifest {
    pub endpoint_id: String,
    pub manifest_digest: Sha256Digest,
    pub protocol_version: u32,
}

impl EndpointManifest {
    pub fn validate(&self) -> Result<(), NativeError> {
        stable_id(&self.endpoint_id, "endpoint_id")?;
        if self.protocol_version == 0 {
            return Err(NativeError::Invalid(
                "protocol_version must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendSession {
    pub fence: SessionFence,
    pub endpoint_id: String,
    pub manifest_digest: Sha256Digest,
    pub protocol_version: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendView {
    pub fence: SessionFence,
    pub generation: u64,
    pub revision: u64,
    pub digest: Sha256Digest,
    pub modules: Vec<String>,
    pub summary: String,
}

pub trait BackendPort: Send {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<BackendSession, NativeError>;
    fn read_view(&mut self, session: &BackendSession) -> Result<BackendView, NativeError>;
    fn close(&mut self, session: &BackendSession) -> Result<(), NativeError>;
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlatformActionKind {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

impl PlatformActionKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OpenPath => "open_path",
            Self::RevealPath => "reveal_path",
            Self::CopyText => "copy_text",
            Self::Notify => "notify",
        }
    }
}

impl fmt::Display for PlatformActionKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum PlatformAction {
    OpenPath { path: PathBuf },
    RevealPath { path: PathBuf },
    CopyText { text: String },
    Notify { title: String, body: String },
}

impl PlatformAction {
    pub fn kind(&self) -> PlatformActionKind {
        match self {
            Self::OpenPath { .. } => PlatformActionKind::OpenPath,
            Self::RevealPath { .. } => PlatformActionKind::RevealPath,
            Self::CopyText { .. } => PlatformActionKind::CopyText,
            Self::Notify { .. } => PlatformActionKind::Notify,
        }
    }

    pub fn validate(&self) -> Result<(), NativeError> {
        match self {
            Self::OpenPath { path } | Self::RevealPath { path } => {
                if !path.is_absolute() {
                    return Err(NativeError::Invalid(
                        "platform path must be absolute".to_string(),
                    ));
                }
                let rendered = path.to_string_lossy();
                bounded(&rendered, "platform path", MAX_RESOURCE_BYTES)?;
            }
            Self::CopyText { text } => {
                bounded(text, "clipboard text", MAX_COPY_TEXT_BYTES)?;
            }
            Self::Notify { title, body } => {
                bounded(title, "notification title", MAX_NOTIFICATION_TITLE_BYTES)?;
                bounded(body, "notification body", MAX_NOTIFICATION_BODY_BYTES)?;
            }
        }
        Ok(())
    }

    pub fn resource_label(&self) -> String {
        match self {
            Self::OpenPath { path } | Self::RevealPath { path } => {
                path.to_string_lossy().into_owned()
            }
            Self::CopyText { .. } => "system.clipboard".to_string(),
            Self::Notify { title, .. } => {
                let digest = Sha256Digest::for_bytes(title.as_bytes());
                format!("notification:{}", &digest.as_str()[..16])
            }
        }
    }

    pub fn payload_digest(&self) -> Result<Sha256Digest, NativeError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self)
            .map_err(|error| NativeError::Invalid(format!("serialize platform payload: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationStatus {
    Pending,
    Indeterminate,
    Succeeded,
    Failed,
    Rejected,
}

impl OperationStatus {
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Rejected)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperationKey {
    pub session_id: String,
    pub session_generation: u64,
    pub operation_id: String,
}

impl OperationKey {
    pub fn from_fence(fence: &SessionFence, operation_id: String) -> Self {
        Self {
            session_id: fence.session_id.clone(),
            session_generation: fence.generation,
            operation_id,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperationRecord {
    pub key: OperationKey,
    pub action: PlatformActionKind,
    pub resource: String,
    pub payload_digest: Sha256Digest,
    pub displayed_revision: u64,
    pub status: OperationStatus,
    pub outcome_digest: Option<Sha256Digest>,
    pub last_error: Option<String>,
    pub reconciliation_attempts: u16,
}

impl OperationRecord {
    pub fn receipt(&self) -> OperationReceipt {
        OperationReceipt {
            key: self.key.clone(),
            action: self.action,
            status: self.status,
            outcome_digest: self.outcome_digest.clone(),
            last_error: self.last_error.clone(),
            terminal_observed: self.status.is_terminal(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationReceipt {
    pub key: OperationKey,
    pub action: PlatformActionKind,
    pub status: OperationStatus,
    pub outcome_digest: Option<Sha256Digest>,
    pub last_error: Option<String>,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlatformObservation {
    pub status: OperationStatus,
    pub outcome_digest: Option<Sha256Digest>,
    pub detail: Option<String>,
}

impl PlatformObservation {
    pub fn indeterminate(detail: impl Into<String>) -> Self {
        Self {
            status: OperationStatus::Indeterminate,
            outcome_digest: None,
            detail: Some(detail.into()),
        }
    }

    pub fn terminal(
        status: OperationStatus,
        outcome_digest: Sha256Digest,
        detail: Option<String>,
    ) -> Result<Self, NativeError> {
        if !status.is_terminal() {
            return Err(NativeError::Invalid(
                "terminal observation must use a terminal status".to_string(),
            ));
        }
        Ok(Self {
            status,
            outcome_digest: Some(outcome_digest),
            detail,
        })
    }
}

#[derive(Clone, Debug)]
pub struct PlatformRequest {
    pub session: SessionFence,
    pub operation_id: String,
    pub displayed_revision: u64,
    pub action: PlatformAction,
    pub grant: SignedFinalUseGrant,
}

pub trait PlatformEffectPort: Send {
    fn dispatch(&mut self, request: &PlatformRequest) -> Result<PlatformObservation, NativeError>;
    fn reconcile(&mut self, record: &OperationRecord)
    -> Result<PlatformObservation, NativeError>;
}

pub trait OperationStore: Send {
    fn load(&self) -> Result<Vec<OperationRecord>, NativeError>;
    fn insert_new(&self, record: &OperationRecord) -> Result<(), NativeError>;
    fn update(&self, record: &OperationRecord) -> Result<(), NativeError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeSession {
    pub fence: SessionFence,
    pub endpoint_id: String,
    pub manifest_digest: Sha256Digest,
    pub protocol_version: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativePresentationState {
    pub fence: SessionFence,
    pub generation: u64,
    pub revision: u64,
    pub digest: Sha256Digest,
    pub modules: Vec<String>,
    pub summary: String,
    pub stale: bool,
}

pub struct NativeShellRuntime {
    backend: Box<dyn BackendPort>,
    platform: Box<dyn PlatformEffectPort>,
    store: Box<dyn OperationStore>,
    session: Option<BackendSession>,
    view: Option<NativePresentationState>,
    operations: BTreeMap<OperationKey, OperationRecord>,
}

impl NativeShellRuntime {
    pub fn new(
        backend: Box<dyn BackendPort>,
        platform: Box<dyn PlatformEffectPort>,
        store: Box<dyn OperationStore>,
    ) -> Result<Self, NativeError> {
        let records = store.load()?;
        if records.len() > MAX_OPERATION_RECORDS {
            return Err(NativeError::Journal(format!(
                "operation journal contains more than {MAX_OPERATION_RECORDS} records"
            )));
        }
        let mut operations = BTreeMap::new();
        for record in records {
            validate_record(&record)?;
            if operations.insert(record.key.clone(), record).is_some() {
                return Err(NativeError::Journal(
                    "operation journal contains a duplicate key".to_string(),
                ));
            }
        }
        Ok(Self {
            backend,
            platform,
            store,
            session: None,
            view: None,
            operations,
        })
    }

    pub fn connect(&mut self, manifest: &EndpointManifest) -> Result<NativeSession, NativeError> {
        manifest.validate()?;
        if let Some(existing) = self.session.take() {
            self.backend.close(&existing)?;
            self.view = None;
        }
        let session = self.backend.connect(manifest)?;
        session.fence.validate()?;
        if session.endpoint_id != manifest.endpoint_id
            || session.manifest_digest != manifest.manifest_digest
            || session.protocol_version != manifest.protocol_version
        {
            return Err(NativeError::Backend(
                "backend session does not bind the requested manifest".to_string(),
            ));
        }
        self.session = Some(session.clone());
        self.view = None;
        self.reconcile_recovered()?;
        Ok(NativeSession {
            fence: session.fence,
            endpoint_id: session.endpoint_id,
            manifest_digest: session.manifest_digest,
            protocol_version: session.protocol_version,
        })
    }

    pub fn refresh_view(&mut self) -> Result<NativePresentationState, NativeError> {
        let session = self
            .session
            .clone()
            .ok_or_else(|| NativeError::Invalid("native shell is not connected".to_string()))?;
        let view = self.backend.read_view(&session)?;
        self.render_backend_view(view)
    }

    pub fn render_backend_view(
        &mut self,
        view: BackendView,
    ) -> Result<NativePresentationState, NativeError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| NativeError::Invalid("native shell is not connected".to_string()))?;
        if view.fence != session.fence {
            return Err(NativeError::Backend(
                "backend view crossed the active session fence".to_string(),
            ));
        }
        if view.generation != session.fence.generation || view.revision == 0 {
            return Err(NativeError::Backend(
                "backend view generation/revision is invalid".to_string(),
            ));
        }
        if view.modules.len() > 256
            || view.modules.iter().any(|module| {
                module.is_empty()
                    || module.len() > 256
                    || !module.is_ascii()
                    || module.as_bytes().contains(&0)
            })
            || view.summary.len() > 64 * 1024
        {
            return Err(NativeError::Backend(
                "backend view exceeds native presentation bounds".to_string(),
            ));
        }

        if let Some(prior) = &self.view {
            if view.generation < prior.generation {
                return Err(NativeError::Backend(
                    "backend view generation regressed".to_string(),
                ));
            }
            if view.generation == prior.generation {
                if view.revision < prior.revision {
                    return Err(NativeError::Backend(
                        "backend view revision regressed".to_string(),
                    ));
                }
                if view.revision == prior.revision {
                    if view.digest != prior.digest {
                        return Err(NativeError::Backend(
                            "same backend revision changed digest".to_string(),
                        ));
                    }
                    return Ok(prior.clone());
                }
            }
        }

        let state = NativePresentationState {
            fence: view.fence,
            generation: view.generation,
            revision: view.revision,
            digest: view.digest,
            modules: view.modules,
            summary: view.summary,
            stale: false,
        };
        self.view = Some(state.clone());
        Ok(state)
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformRequest,
    ) -> Result<OperationReceipt, NativeError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| NativeError::Invalid("native shell is not connected".to_string()))?;
        let view = self.view.as_ref().ok_or_else(|| {
            NativeError::Invalid("platform request requires a coherent runtime view".to_string())
        })?;
        if request.session != session.fence {
            return Err(NativeError::Invalid(
                "platform request crossed the active session fence".to_string(),
            ));
        }
        if request.displayed_revision != view.revision {
            return Err(NativeError::Invalid(
                "platform request was confirmed against a stale view".to_string(),
            ));
        }
        stable_id(&request.operation_id, "operation_id")?;
        request.action.validate()?;
        let payload_digest = request.action.payload_digest()?;
        let resource = request.action.resource_label();
        bounded(&resource, "resource", MAX_RESOURCE_BYTES)?;

        for (key, prior) in &self.operations {
            if key.operation_id == request.operation_id
                && (key.session_id != session.fence.session_id
                    || key.session_generation != session.fence.generation)
            {
                return Err(NativeError::OperationFenced {
                    operation_id: request.operation_id,
                    prior_session: prior.key.session_id.clone(),
                    prior_generation: prior.key.session_generation,
                });
            }
        }

        let key = OperationKey::from_fence(&session.fence, request.operation_id.clone());
        if let Some(prior) = self.operations.get(&key).cloned() {
            if prior.payload_digest != payload_digest
                || prior.action != request.action.kind()
                || prior.resource != resource
            {
                return Err(NativeError::OperationConflict(request.operation_id));
            }
            if prior.status.is_terminal() {
                return Ok(prior.receipt());
            }
            return self.reconcile_key(&key);
        }

        if self.operations.len() >= MAX_OPERATION_RECORDS {
            return Err(NativeError::Journal(format!(
                "operation journal reached its {MAX_OPERATION_RECORDS} record bound"
            )));
        }

        let record = OperationRecord {
            key: key.clone(),
            action: request.action.kind(),
            resource,
            payload_digest,
            displayed_revision: request.displayed_revision,
            status: OperationStatus::Pending,
            outcome_digest: None,
            last_error: None,
            reconciliation_attempts: 0,
        };
        self.store.insert_new(&record)?;
        self.operations.insert(key.clone(), record);

        let observation = match self.platform.dispatch(&request) {
            Ok(observation) => observation,
            Err(error) => PlatformObservation::indeterminate(format!(
                "dispatch returned without a trusted terminal observation: {error}"
            )),
        };
        self.apply_observation(&key, observation)
    }

    pub fn reconcile_recovered(&mut self) -> Result<Vec<OperationReceipt>, NativeError> {
        let keys: Vec<_> = self
            .operations
            .iter()
            .filter(|(_, record)| !record.status.is_terminal())
            .map(|(key, _)| key.clone())
            .collect();
        let mut receipts = Vec::with_capacity(keys.len());
        for key in keys {
            receipts.push(self.reconcile_key(&key)?);
        }
        Ok(receipts)
    }

    pub fn operations(&self) -> Vec<OperationReceipt> {
        self.operations.values().map(OperationRecord::receipt).collect()
    }

    pub fn close(&mut self) -> Result<(), NativeError> {
        if let Some(session) = self.session.take() {
            self.backend.close(&session)?;
        }
        self.view = None;
        Ok(())
    }

    fn reconcile_key(&mut self, key: &OperationKey) -> Result<OperationReceipt, NativeError> {
        let prior = self
            .operations
            .get(key)
            .cloned()
            .ok_or_else(|| NativeError::Journal("operation disappeared during reconcile".to_string()))?;
        if prior.status.is_terminal() {
            return Ok(prior.receipt());
        }
        let observation = match self.platform.reconcile(&prior) {
            Ok(observation) => observation,
            Err(error) => PlatformObservation::indeterminate(format!(
                "reconciliation did not yield a trusted terminal observation: {error}"
            )),
        };
        self.apply_observation(key, observation)
    }

    fn apply_observation(
        &mut self,
        key: &OperationKey,
        observation: PlatformObservation,
    ) -> Result<OperationReceipt, NativeError> {
        if observation.status.is_terminal() && observation.outcome_digest.is_none() {
            return Err(NativeError::Platform(
                "terminal platform observation omitted outcome digest".to_string(),
            ));
        }
        if !observation.status.is_terminal() && observation.outcome_digest.is_some() {
            return Err(NativeError::Platform(
                "indeterminate platform observation supplied terminal digest".to_string(),
            ));
        }
        let record = self
            .operations
            .get_mut(key)
            .ok_or_else(|| NativeError::Journal("operation disappeared before commit".to_string()))?;
        record.status = observation.status;
        record.outcome_digest = observation.outcome_digest;
        record.last_error = observation.detail;
        record.reconciliation_attempts = record.reconciliation_attempts.saturating_add(1);
        self.store.update(record)?;
        Ok(record.receipt())
    }
}

impl Drop for NativeShellRuntime {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

fn validate_record(record: &OperationRecord) -> Result<(), NativeError> {
    stable_id(&record.key.session_id, "journal session_id")?;
    stable_id(&record.key.operation_id, "journal operation_id")?;
    if record.key.session_generation == 0 || record.displayed_revision == 0 {
        return Err(NativeError::Journal(
            "journal record contains a zero generation/revision".to_string(),
        ));
    }
    bounded(&record.resource, "journal resource", MAX_RESOURCE_BYTES)?;
    if record.status.is_terminal() != record.outcome_digest.is_some() {
        return Err(NativeError::Journal(
            "journal terminal state and outcome digest disagree".to_string(),
        ));
    }
    Ok(())
}

fn stable_id(value: &str, label: &str) -> Result<(), NativeError> {
    if value.is_empty()
        || value.len() > MAX_OPERATION_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(NativeError::Invalid(format!(
            "{label} must be a bounded stable identifier"
        )));
    }
    Ok(())
}

fn bounded(value: &str, label: &str, max: usize) -> Result<(), NativeError> {
    if value.is_empty() || value.len() > max || value.as_bytes().contains(&0) {
        return Err(NativeError::Invalid(format!(
            "{label} must contain 1..={max} non-NUL bytes"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::PoisonError;

    const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";

    #[derive(Clone)]
    struct SharedStore(Arc<Mutex<Vec<OperationRecord>>>);

    impl SharedStore {
        fn empty() -> Self {
            Self(Arc::new(Mutex::new(Vec::new())))
        }
    }

    impl OperationStore for SharedStore {
        fn load(&self) -> Result<Vec<OperationRecord>, NativeError> {
            Ok(self
                .0
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .clone())
        }

        fn insert_new(&self, record: &OperationRecord) -> Result<(), NativeError> {
            let mut records = self.0.lock().unwrap_or_else(PoisonError::into_inner);
            records.push(record.clone());
            Ok(())
        }

        fn update(&self, record: &OperationRecord) -> Result<(), NativeError> {
            let mut records = self.0.lock().unwrap_or_else(PoisonError::into_inner);
            let Some(existing) = records.iter_mut().find(|item| item.key == record.key) else {
                return Err(NativeError::Journal("missing test record".to_string()));
            };
            *existing = record.clone();
            Ok(())
        }
    }

    struct FixtureBackend {
        next_session: u64,
    }

    impl FixtureBackend {
        fn new() -> Self {
            Self { next_session: 1 }
        }
    }

    impl BackendPort for FixtureBackend {
        fn connect(&mut self, manifest: &EndpointManifest) -> Result<BackendSession, NativeError> {
            let session = BackendSession {
                fence: SessionFence {
                    session_id: format!("session.{}", self.next_session),
                    generation: self.next_session,
                },
                endpoint_id: manifest.endpoint_id.clone(),
                manifest_digest: manifest.manifest_digest.clone(),
                protocol_version: manifest.protocol_version,
            };
            self.next_session += 1;
            Ok(session)
        }

        fn read_view(&mut self, session: &BackendSession) -> Result<BackendView, NativeError> {
            Ok(BackendView {
                fence: session.fence.clone(),
                generation: session.fence.generation,
                revision: 1,
                digest: Sha256Digest::parse(D2).map_err(NativeError::Invalid)?,
                modules: vec!["runtime.agentd".to_string()],
                summary: "ready".to_string(),
            })
        }

        fn close(&mut self, _session: &BackendSession) -> Result<(), NativeError> {
            Ok(())
        }
    }

    struct FixturePlatform {
        dispatches: Arc<Mutex<u64>>,
        reconcile_terminal: bool,
    }

    impl PlatformEffectPort for FixturePlatform {
        fn dispatch(&mut self, _request: &PlatformRequest) -> Result<PlatformObservation, NativeError> {
            let mut dispatches = self
                .dispatches
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            *dispatches += 1;
            Ok(PlatformObservation::indeterminate("ack lost"))
        }

        fn reconcile(
            &mut self,
            _record: &OperationRecord,
        ) -> Result<PlatformObservation, NativeError> {
            if self.reconcile_terminal {
                PlatformObservation::terminal(
                    OperationStatus::Succeeded,
                    Sha256Digest::parse(D2).map_err(NativeError::Invalid)?,
                    Some("independent observation".to_string()),
                )
            } else {
                Ok(PlatformObservation::indeterminate("still unknown"))
            }
        }
    }

    fn manifest() -> Result<EndpointManifest, NativeError> {
        Ok(EndpointManifest {
            endpoint_id: "runtime.1".to_string(),
            manifest_digest: Sha256Digest::parse(D1).map_err(NativeError::Invalid)?,
            protocol_version: 1,
        })
    }

    fn dummy_grant() -> SignedFinalUseGrant {
        use codex_hepta_contracts::FinalUseBinding;
        use codex_hepta_contracts::FinalUseGrant;
        SignedFinalUseGrant {
            grant: FinalUseGrant {
                schema_version: 1,
                signer_id: "signer".to_string(),
                authority_epoch: 1,
                grant_id: "grant.1".to_string(),
                nonce: [1; 32],
                binding: FinalUseBinding {
                    subject_id: "operation.1".to_string(),
                    destination_id: "ui.native/copy_text".to_string(),
                    request_sha256: [1; 32],
                    scope_sha256: [2; 32],
                    payload_sha256: [3; 32],
                },
                not_before_unix_ms: 1,
                expires_at_unix_ms: 2,
            },
            signature: vec![0; 64],
        }
    }

    fn request(session: &SessionFence, revision: u64) -> PlatformRequest {
        PlatformRequest {
            session: session.clone(),
            operation_id: "operation.1".to_string(),
            displayed_revision: revision,
            action: PlatformAction::CopyText {
                text: "hello".to_string(),
            },
            grant: dummy_grant(),
        }
    }

    #[test]
    fn retry_reconciles_indeterminate_without_duplicate_dispatch() -> Result<(), NativeError> {
        let dispatches = Arc::new(Mutex::new(0));
        let store = SharedStore::empty();
        let mut runtime = NativeShellRuntime::new(
            Box::new(FixtureBackend::new()),
            Box::new(FixturePlatform {
                dispatches: Arc::clone(&dispatches),
                reconcile_terminal: false,
            }),
            Box::new(store),
        )?;
        let session = runtime.connect(&manifest()?)?;
        let view = runtime.refresh_view()?;
        let first = runtime.request_platform_capability(request(&session.fence, view.revision))?;
        assert_eq!(first.status, OperationStatus::Indeterminate);
        let second = runtime.request_platform_capability(request(&session.fence, view.revision))?;
        assert_eq!(second.status, OperationStatus::Indeterminate);
        assert_eq!(
            *dispatches.lock().unwrap_or_else(PoisonError::into_inner),
            1
        );
        Ok(())
    }

    #[test]
    fn restart_recovers_and_reconciles_without_replaying_effect() -> Result<(), NativeError> {
        let dispatches = Arc::new(Mutex::new(0));
        let store = SharedStore::empty();
        {
            let mut runtime = NativeShellRuntime::new(
                Box::new(FixtureBackend::new()),
                Box::new(FixturePlatform {
                    dispatches: Arc::clone(&dispatches),
                    reconcile_terminal: false,
                }),
                Box::new(store.clone()),
            )?;
            let session = runtime.connect(&manifest()?)?;
            let view = runtime.refresh_view()?;
            let receipt =
                runtime.request_platform_capability(request(&session.fence, view.revision))?;
            assert_eq!(receipt.status, OperationStatus::Indeterminate);
        }
        let mut recovered = NativeShellRuntime::new(
            Box::new(FixtureBackend::new()),
            Box::new(FixturePlatform {
                dispatches: Arc::clone(&dispatches),
                reconcile_terminal: true,
            }),
            Box::new(store),
        )?;
        let receipts = recovered.reconcile_recovered()?;
        assert_eq!(receipts.len(), 1);
        assert_eq!(receipts[0].status, OperationStatus::Succeeded);
        assert_eq!(
            *dispatches.lock().unwrap_or_else(PoisonError::into_inner),
            1
        );
        Ok(())
    }

    #[test]
    fn operation_identity_is_fenced_across_sessions() -> Result<(), NativeError> {
        let dispatches = Arc::new(Mutex::new(0));
        let mut runtime = NativeShellRuntime::new(
            Box::new(FixtureBackend::new()),
            Box::new(FixturePlatform {
                dispatches,
                reconcile_terminal: false,
            }),
            Box::new(SharedStore::empty()),
        )?;
        let first = runtime.connect(&manifest()?)?;
        let first_view = runtime.refresh_view()?;
        let _ = runtime.request_platform_capability(request(&first.fence, first_view.revision))?;
        runtime.close()?;

        let second = runtime.connect(&manifest()?)?;
        let second_view = runtime.refresh_view()?;
        let error = runtime
            .request_platform_capability(request(&second.fence, second_view.revision))
            .err()
            .ok_or_else(|| NativeError::Invalid("expected prior-session fence".to_string()))?;
        assert!(matches!(error, NativeError::OperationFenced { .. }));
        Ok(())
    }

    #[test]
    fn identical_view_revision_is_idempotent_but_digest_drift_rejects(
    ) -> Result<(), NativeError> {
        let mut runtime = NativeShellRuntime::new(
            Box::new(FixtureBackend::new()),
            Box::new(FixturePlatform {
                dispatches: Arc::new(Mutex::new(0)),
                reconcile_terminal: false,
            }),
            Box::new(SharedStore::empty()),
        )?;
        let _ = runtime.connect(&manifest()?)?;
        let first = runtime.refresh_view()?;
        let same = runtime.refresh_view()?;
        assert_eq!(same, first);

        let error = runtime
            .render_backend_view(BackendView {
                fence: first.fence.clone(),
                generation: first.generation,
                revision: first.revision,
                digest: Sha256Digest::parse(D1).map_err(NativeError::Invalid)?,
                modules: first.modules.clone(),
                summary: first.summary.clone(),
            })
            .err()
            .ok_or_else(|| NativeError::Invalid("expected view digest drift failure".to_string()))?;
        assert!(error.to_string().contains("same backend revision changed digest"));
        Ok(())
    }
}
