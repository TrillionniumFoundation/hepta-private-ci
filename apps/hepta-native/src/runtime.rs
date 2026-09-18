use crate::backend::Backend;
use crate::backend::BackendError;
use crate::journal::DispatchDisposition;
use crate::journal::JournalError;
use crate::journal::OperationJournal;
use crate::platform::ObservationStatus;
use crate::platform::PlatformAdapter;
use crate::platform::PlatformError;
use crate::platform::validate_payload;
use crate::security::GrantError;
use crate::security::GrantVerifier;
use crate::sha256_hex;
use crate::types::DecisionStatus;
use crate::types::GrantBinding;
use crate::types::NativeSession;
use crate::types::OperationKey;
use crate::types::PlatformAction;
use crate::types::PlatformDecision;
use crate::types::PlatformPayload;
use crate::types::RuntimeManifest;
use crate::types::RuntimeView;
use crate::types::SignedPlatformGrant;
use crate::validate_stable_id;
use std::collections::HashSet;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("native shell is not connected")]
    NotConnected,
    #[error("platform request requires a coherent runtime view")]
    NoView,
    #[error("runtime view generation changed; reconnect is required")]
    GenerationChanged,
    #[error("runtime view revision is stale")]
    StaleView,
    #[error("operation or resource identity is invalid")]
    Identity,
    #[error("platform action has not been explicitly allowed for this session")]
    Permission,
    #[error("platform effect authority is not configured")]
    AuthorityUnavailable,
    #[error(transparent)]
    Backend(#[from] BackendError),
    #[error(transparent)]
    Journal(#[from] JournalError),
    #[error(transparent)]
    Platform(#[from] PlatformError),
    #[error(transparent)]
    Grant(#[from] GrantError),
    #[error("runtime JSON could not be encoded")]
    Encoding,
}

pub struct ShellRuntime<B, P> {
    backend: B,
    platform: P,
    journal: OperationJournal,
    verifier: Option<GrantVerifier>,
    session: Option<NativeSession>,
    view: Option<RuntimeView>,
    permissions: HashSet<PlatformAction>,
}

impl<B: Backend, P: PlatformAdapter> ShellRuntime<B, P> {
    pub fn new(
        backend: B,
        platform: P,
        journal: OperationJournal,
        verifier: Option<GrantVerifier>,
    ) -> Self {
        Self {
            backend,
            platform,
            journal,
            verifier,
            session: None,
            view: None,
            permissions: HashSet::new(),
        }
    }

    pub fn authority_configured(&self) -> bool {
        self.verifier.is_some()
    }

    pub fn connect(&mut self, manifest: &RuntimeManifest) -> Result<NativeSession, RuntimeError> {
        if let Some(session) = self.session.take() {
            self.backend.close(&session)?;
        }
        self.view = None;
        self.permissions.clear();
        let session = self.backend.connect(manifest)?;
        self.session = Some(session.clone());
        Ok(session)
    }

    pub fn refresh_view(&mut self) -> Result<RuntimeView, RuntimeError> {
        let session = self.session.clone().ok_or(RuntimeError::NotConnected)?;
        let body = self.backend.fetch_runtime(&session)?;
        let encoded = serde_json::to_vec(&body).map_err(|_| RuntimeError::Encoding)?;
        let digest = sha256_hex(&encoded);
        let generation = body
            .pointer("/state/runtime_snapshot_generation")
            .and_then(serde_json::Value::as_u64)
            .ok_or(RuntimeError::GenerationChanged)?;
        if generation != session.generation {
            return Err(RuntimeError::GenerationChanged);
        }
        let revision = match &self.view {
            Some(view) if view.generation != generation => {
                return Err(RuntimeError::GenerationChanged);
            }
            Some(view) if view.digest == digest => view.revision,
            Some(view) => view.revision.checked_add(1).ok_or(RuntimeError::Encoding)?,
            None => 1,
        };
        let mut modules = body
            .as_object()
            .map(|object| object.keys().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        modules.sort();
        let view = RuntimeView {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            generation,
            revision,
            digest,
            modules,
            body,
            stale: false,
        };
        self.view = Some(view.clone());
        Ok(view)
    }

    pub fn session(&self) -> Option<&NativeSession> {
        self.session.as_ref()
    }

    pub fn view(&self) -> Option<&RuntimeView> {
        self.view.as_ref()
    }

    pub fn allow_once(&mut self, action: PlatformAction) {
        self.permissions.insert(action);
    }

    pub fn prepare_binding(
        &self,
        operation_id: &str,
        action: PlatformAction,
        resource: &str,
        payload: &PlatformPayload,
        displayed_revision: u64,
    ) -> Result<GrantBinding, RuntimeError> {
        let session = self.session.as_ref().ok_or(RuntimeError::NotConnected)?;
        let view = self.view.as_ref().ok_or(RuntimeError::NoView)?;
        if displayed_revision != view.revision {
            return Err(RuntimeError::StaleView);
        }
        if !validate_stable_id(operation_id) || resource.is_empty() || resource.len() > 4096 {
            return Err(RuntimeError::Identity);
        }
        validate_payload(&action, payload)?;
        let payload_bytes = serde_json::to_vec(payload).map_err(|_| RuntimeError::Encoding)?;
        Ok(GrantBinding {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            operation_id: operation_id.to_string(),
            action,
            resource_digest: sha256_hex(resource.as_bytes()),
            payload_digest: sha256_hex(payload_bytes),
        })
    }

    pub fn request_platform_capability(
        &mut self,
        operation_id: &str,
        action: PlatformAction,
        resource: &str,
        payload: &PlatformPayload,
        displayed_revision: u64,
        signed_grant: &SignedPlatformGrant,
    ) -> Result<PlatformDecision, RuntimeError> {
        let binding = self.prepare_binding(
            operation_id,
            action.clone(),
            resource,
            payload,
            displayed_revision,
        )?;
        if !self.permissions.remove(&action) {
            return Err(RuntimeError::Permission);
        }
        let key = OperationKey {
            session_id: binding.session_id.clone(),
            session_generation: binding.session_generation,
            operation_id: binding.operation_id.clone(),
        };
        match self
            .journal
            .begin_dispatch(
                &key,
                action.clone(),
                &binding.resource_digest,
                &binding.payload_digest,
            )?
        {
            DispatchDisposition::Terminal(decision) => return Ok(decision),
            DispatchDisposition::Indeterminate => {
                return self.reconcile_open_operation(
                    key,
                    action,
                    payload,
                    &binding.resource_digest,
                    &binding.payload_digest,
                );
            }
            DispatchDisposition::Started => {}
        }

        let Some(verifier) = self.verifier.as_ref() else {
            let decision =
                rejected_decision(key, action.clone(), "platform-effect-authority-unavailable");
            self.journal.finish(
                &decision.key,
                action,
                &binding.resource_digest,
                &binding.payload_digest,
                decision.clone(),
            )?;
            return Ok(decision);
        };
        if let Err(error) = verifier.claim(signed_grant, &binding) {
            let decision =
                rejected_decision(key, action.clone(), &format!("grant-rejected:{error}"));
            self.journal.finish(
                &decision.key,
                action,
                &binding.resource_digest,
                &binding.payload_digest,
                decision.clone(),
            )?;
            return Ok(decision);
        }

        let observed = self.platform.invoke(&key, action.clone(), payload)?;
        if !observed.terminal_observed {
            return Ok(PlatformDecision::new(
                key,
                action,
                DecisionStatus::Indeterminate,
                false,
                None,
            ));
        }
        let status = match observed.status {
            Some(ObservationStatus::Succeeded) => DecisionStatus::Succeeded,
            Some(ObservationStatus::Failed) => DecisionStatus::Failed,
            None => {
                return Err(RuntimeError::Platform(PlatformError::Adapter(
                    "terminal observation omitted status".to_string(),
                )));
            }
        };
        let decision =
            PlatformDecision::new(key, action.clone(), status, true, observed.outcome_digest);
        self.journal.finish(
            &decision.key,
            action,
            &binding.resource_digest,
            &binding.payload_digest,
            decision.clone(),
        )?;
        Ok(decision)
    }

    fn reconcile_open_operation(
        &mut self,
        key: OperationKey,
        action: PlatformAction,
        payload: &PlatformPayload,
        resource_digest: &str,
        payload_digest: &str,
    ) -> Result<PlatformDecision, RuntimeError> {
        let Some(observed) = self.platform.reconcile(&key, action.clone(), payload)? else {
            return Ok(PlatformDecision::new(
                key,
                action,
                DecisionStatus::Indeterminate,
                false,
                None,
            ));
        };
        if !observed.terminal_observed {
            return Ok(PlatformDecision::new(
                key,
                action,
                DecisionStatus::Indeterminate,
                false,
                None,
            ));
        }
        let status = match observed.status {
            Some(ObservationStatus::Succeeded) => DecisionStatus::Succeeded,
            Some(ObservationStatus::Failed) => DecisionStatus::Failed,
            None => {
                return Err(RuntimeError::Platform(PlatformError::Adapter(
                    "reconciler omitted terminal status".to_string(),
                )));
            }
        };
        let decision =
            PlatformDecision::new(key, action.clone(), status, true, observed.outcome_digest);
        self.journal
            .finish(
                &decision.key,
                action,
                resource_digest,
                payload_digest,
                decision.clone(),
            )?;
        Ok(decision)
    }

    pub fn close(&mut self) -> Result<(), RuntimeError> {
        if let Some(session) = self.session.take() {
            self.backend.close(&session)?;
        }
        self.view = None;
        self.permissions.clear();
        Ok(())
    }
}

fn rejected_decision(key: OperationKey, action: PlatformAction, detail: &str) -> PlatformDecision {
    PlatformDecision::new(
        key,
        action,
        DecisionStatus::Rejected,
        true,
        Some(sha256_hex(format!(
            "hepta.native.platform.outcome.v1\0rejected\0{detail}"
        ))),
    )
}
