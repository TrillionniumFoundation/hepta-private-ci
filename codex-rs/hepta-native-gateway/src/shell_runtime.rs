use std::collections::HashMap;
use std::hash::Hash;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;

const MAX_RESOURCE_BYTES: usize = 4096;
const MAX_MODULES: usize = 512;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum PlatformAction {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) struct SessionKey {
    pub(crate) session_id: String,
    pub(crate) generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct EndpointManifest {
    pub(crate) endpoint_id: String,
    pub(crate) manifest_digest: String,
    pub(crate) protocol_version: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct BackendSession {
    pub(crate) authenticated: bool,
    pub(crate) protocol_version: u64,
    pub(crate) session_id: String,
    pub(crate) generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ViewInput {
    pub(crate) session: SessionKey,
    pub(crate) generation: u64,
    pub(crate) revision: u64,
    pub(crate) digest: String,
    pub(crate) modules: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ViewState {
    pub(crate) generation: u64,
    pub(crate) revision: u64,
    pub(crate) digest: String,
    pub(crate) modules: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PlatformRequest {
    pub(crate) operation_id: String,
    pub(crate) action: PlatformAction,
    pub(crate) resource: String,
    pub(crate) displayed_revision: u64,
    pub(crate) payload_digest: String,
    pub(crate) grant: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct VerifiedPlatformGrant {
    pub(crate) session: SessionKey,
    pub(crate) operation_id: String,
    pub(crate) action: PlatformAction,
    pub(crate) payload_digest: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TerminalStatus {
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum PermissionDecision {
    Allowed,
    Denied { outcome_digest: String },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ReconcileObservation {
    NotFound,
    Indeterminate,
    Terminal {
        status: TerminalStatus,
        outcome_digest: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum InvokeObservation {
    Indeterminate,
    Terminal {
        status: TerminalStatus,
        outcome_digest: String,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PlatformStatus {
    Rejected,
    Indeterminate,
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PlatformReceipt {
    pub(crate) session: SessionKey,
    pub(crate) operation_id: String,
    pub(crate) action: PlatformAction,
    pub(crate) status: PlatformStatus,
    pub(crate) terminal_observed: bool,
    pub(crate) outcome_digest: Option<String>,
}

pub(crate) trait BackendConnector: Send + Sync {
    fn connect(&self, manifest: &EndpointManifest) -> Result<BackendSession>;
    fn close(&self, session: &SessionKey) -> Result<()>;
}

pub(crate) trait PlatformAdapter: Send + Sync {
    fn permission(&self, request: &PlatformRequest) -> Result<PermissionDecision>;
    fn reconcile(
        &self,
        session: &SessionKey,
        request: &PlatformRequest,
    ) -> Result<ReconcileObservation>;
    fn invoke(&self, session: &SessionKey, request: &PlatformRequest) -> Result<InvokeObservation>;
}

pub(crate) trait GrantVerifier: Send + Sync {
    fn verify(&self, session: &SessionKey, request: &PlatformRequest)
    -> Result<VerifiedPlatformGrant>;
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct OperationKey {
    session: SessionKey,
    operation_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct OperationRecord {
    payload_digest: String,
    receipt: PlatformReceipt,
}

pub(crate) struct NativeShellRuntime<B, P, G> {
    backend: B,
    platform: P,
    grants: G,
    session: Option<SessionKey>,
    view: Option<ViewState>,
    operations: HashMap<OperationKey, OperationRecord>,
}

impl<B, P, G> NativeShellRuntime<B, P, G>
where
    B: BackendConnector,
    P: PlatformAdapter,
    G: GrantVerifier,
{
    pub(crate) fn new(backend: B, platform: P, grants: G) -> Self {
        Self {
            backend,
            platform,
            grants,
            session: None,
            view: None,
            operations: HashMap::new(),
        }
    }

    pub(crate) fn connect_runtime(&mut self, manifest: EndpointManifest) -> Result<SessionKey> {
        validate_stable_id(&manifest.endpoint_id, "endpoint_id")?;
        validate_digest(&manifest.manifest_digest, "manifest_digest")?;
        validate_positive(manifest.protocol_version, "protocol_version")?;
        let observed = self.backend.connect(&manifest)?;
        if !observed.authenticated {
            bail!("backend connection is not authenticated");
        }
        if observed.protocol_version != manifest.protocol_version {
            bail!("backend protocol version mismatch");
        }
        validate_stable_id(&observed.session_id, "session_id")?;
        validate_positive(observed.generation, "session generation")?;

        let session = SessionKey {
            session_id: observed.session_id,
            generation: observed.generation,
        };
        self.session = Some(session.clone());
        self.view = None;
        self.operations.clear();
        Ok(session)
    }

    pub(crate) fn render_runtime_view(&mut self, input: ViewInput) -> Result<ViewState> {
        let session = self.require_session()?;
        if &input.session != session {
            bail!("view session mismatch");
        }
        validate_positive(input.generation, "view generation")?;
        validate_positive(input.revision, "view revision")?;
        validate_digest(&input.digest, "view digest")?;
        if input.modules.len() > MAX_MODULES {
            bail!("view module count exceeds {MAX_MODULES}");
        }
        for module in &input.modules {
            validate_stable_id(module, "module id")?;
        }
        if let Some(previous) = &self.view {
            if input.generation < previous.generation {
                bail!("view generation regressed");
            }
            if input.generation == previous.generation && input.revision <= previous.revision {
                bail!("view revision did not advance");
            }
        }
        let view = ViewState {
            generation: input.generation,
            revision: input.revision,
            digest: input.digest,
            modules: input.modules,
        };
        self.view = Some(view.clone());
        Ok(view)
    }

    pub(crate) fn request_platform_capability(
        &mut self,
        request: PlatformRequest,
    ) -> Result<PlatformReceipt> {
        let session = self.require_session()?.clone();
        let view = self.view.as_ref().context("platform request requires a coherent runtime view")?;
        validate_stable_id(&request.operation_id, "operation_id")?;
        validate_bounded_text(&request.resource, "resource")?;
        validate_digest(&request.payload_digest, "payload_digest")?;
        if request.displayed_revision != view.revision {
            bail!("platform request was confirmed against a stale view");
        }
        let grant = self.grants.verify(&session, &request)?;
        if grant.session != session
            || grant.operation_id != request.operation_id
            || grant.action != request.action
            || grant.payload_digest != request.payload_digest
        {
            bail!("verified grant does not bind the final platform request");
        }

        let key = OperationKey {
            session: session.clone(),
            operation_id: request.operation_id.clone(),
        };
        if let Some(prior) = self.operations.get(&key) {
            if prior.payload_digest != request.payload_digest {
                bail!("operation identity was reused with changed payload");
            }
            if prior.receipt.terminal_observed {
                return Ok(prior.receipt.clone());
            }
            return self.reconcile_indeterminate(key, request);
        }

        match self.platform.reconcile(&session, &request)? {
            ReconcileObservation::NotFound => {}
            ReconcileObservation::Indeterminate => {
                let receipt = indeterminate_receipt(&session, &request);
                self.remember(key, &request, receipt.clone());
                return Ok(receipt);
            }
            ReconcileObservation::Terminal {
                status,
                outcome_digest,
            } => {
                validate_digest(&outcome_digest, "outcome_digest")?;
                let receipt = terminal_receipt(&session, &request, status, outcome_digest);
                self.remember(key, &request, receipt.clone());
                return Ok(receipt);
            }
        }

        match self.platform.permission(&request)? {
            PermissionDecision::Denied { outcome_digest } => {
                validate_digest(&outcome_digest, "outcome_digest")?;
                let receipt = PlatformReceipt {
                    session,
                    operation_id: request.operation_id.clone(),
                    action: request.action,
                    status: PlatformStatus::Rejected,
                    terminal_observed: true,
                    outcome_digest: Some(outcome_digest),
                };
                self.remember(key, &request, receipt.clone());
                Ok(receipt)
            }
            PermissionDecision::Allowed => {
                let receipt = match self.platform.invoke(&session, &request)? {
                    InvokeObservation::Indeterminate => indeterminate_receipt(&session, &request),
                    InvokeObservation::Terminal {
                        status,
                        outcome_digest,
                    } => {
                        validate_digest(&outcome_digest, "outcome_digest")?;
                        terminal_receipt(&session, &request, status, outcome_digest)
                    }
                };
                self.remember(key, &request, receipt.clone());
                Ok(receipt)
            }
        }
    }

    pub(crate) fn close(&mut self) -> Result<()> {
        if let Some(session) = self.session.take() {
            self.backend.close(&session)?;
        }
        self.view = None;
        self.operations.clear();
        Ok(())
    }

    fn reconcile_indeterminate(
        &mut self,
        key: OperationKey,
        request: PlatformRequest,
    ) -> Result<PlatformReceipt> {
        let session = key.session.clone();
        let receipt = match self.platform.reconcile(&session, &request)? {
            ReconcileObservation::Terminal {
                status,
                outcome_digest,
            } => {
                validate_digest(&outcome_digest, "outcome_digest")?;
                terminal_receipt(&session, &request, status, outcome_digest)
            }
            ReconcileObservation::NotFound | ReconcileObservation::Indeterminate => {
                indeterminate_receipt(&session, &request)
            }
        };
        self.remember(key, &request, receipt.clone());
        Ok(receipt)
    }

    fn remember(&mut self, key: OperationKey, request: &PlatformRequest, receipt: PlatformReceipt) {
        self.operations.insert(
            key,
            OperationRecord {
                payload_digest: request.payload_digest.clone(),
                receipt,
            },
        );
    }

    fn require_session(&self) -> Result<&SessionKey> {
        self.session.as_ref().context("native shell is not connected")
    }
}

fn terminal_receipt(
    session: &SessionKey,
    request: &PlatformRequest,
    status: TerminalStatus,
    outcome_digest: String,
) -> PlatformReceipt {
    PlatformReceipt {
        session: session.clone(),
        operation_id: request.operation_id.clone(),
        action: request.action,
        status: match status {
            TerminalStatus::Succeeded => PlatformStatus::Succeeded,
            TerminalStatus::Failed => PlatformStatus::Failed,
        },
        terminal_observed: true,
        outcome_digest: Some(outcome_digest),
    }
}

fn indeterminate_receipt(session: &SessionKey, request: &PlatformRequest) -> PlatformReceipt {
    PlatformReceipt {
        session: session.clone(),
        operation_id: request.operation_id.clone(),
        action: request.action,
        status: PlatformStatus::Indeterminate,
        terminal_observed: false,
        outcome_digest: None,
    }
}

fn validate_positive(value: u64, name: &str) -> Result<()> {
    if value == 0 {
        bail!("{name} must be positive");
    }
    Ok(())
}

fn validate_stable_id(value: &str, name: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        bail!("{name} must be a bounded stable identifier");
    }
    Ok(())
}

fn validate_digest(value: &str, name: &str) -> Result<()> {
    if value.len() != 64
        || value == ZERO_DIGEST
        || !value.bytes().all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("{name} must be a non-zero lowercase SHA-256 digest");
    }
    Ok(())
}

fn validate_bounded_text(value: &str, name: &str) -> Result<()> {
    if value.is_empty() || value.len() > MAX_RESOURCE_BYTES || value.contains('\0') {
        bail!("{name} must be non-empty, NUL-free and at most {MAX_RESOURCE_BYTES} bytes");
    }
    Ok(())
}
