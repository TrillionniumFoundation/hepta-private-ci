use std::sync::Arc;

use crate::backend::BackendAdapter;
use crate::error::ShellError;
use crate::journal::OperationJournal;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::model::EndpointManifest;
use crate::model::OperationKey;
use crate::model::PlatformObservation;
use crate::model::PlatformReceipt;
use crate::model::PlatformRequest;
use crate::model::PresentationState;
use crate::model::RuntimeView;
use crate::model::SessionIncarnation;
use crate::model::TerminalStatus;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::platform::PlatformAdapter;
use crate::security::GrantVerifier;
use crate::security::now_unix_ms;

pub struct NativeShellRuntime {
    backend: Box<dyn BackendAdapter>,
    platform: Box<dyn PlatformAdapter>,
    grant_verifier: Arc<dyn GrantVerifier>,
    journal: OperationJournal,
    session: Option<SessionIncarnation>,
    view: Option<RuntimeView>,
}

impl NativeShellRuntime {
    pub fn new(
        backend: Box<dyn BackendAdapter>,
        platform: Box<dyn PlatformAdapter>,
        grant_verifier: Arc<dyn GrantVerifier>,
        journal: OperationJournal,
    ) -> Self {
        Self {
            backend,
            platform,
            grant_verifier,
            journal,
            session: None,
            view: None,
        }
    }

    pub fn connect_runtime(
        &mut self,
        manifest: &EndpointManifest,
    ) -> Result<SessionIncarnation, ShellError> {
        manifest.validate()?;
        if let Some(previous) = self.session.take() {
            self.backend.close(&previous)?;
        }
        self.view = None;
        let session = self.backend.connect(manifest)?;
        session.validate()?;
        if session.endpoint_id != manifest.endpoint_id {
            return Err(ShellError::Backend(
                "backend session endpoint identity does not match manifest".to_owned(),
            ));
        }
        self.session = Some(session.clone());
        let _ = self.reconcile_pending()?;
        Ok(session)
    }

    pub fn render_runtime_view(
        &mut self,
        view: RuntimeView,
    ) -> Result<PresentationState, ShellError> {
        let session = self.require_session()?.clone();
        view.validate()?;
        if view.session_id != session.session_id || view.session_generation != session.generation {
            return Err(ShellError::State(
                "runtime view belongs to a different session incarnation".to_owned(),
            ));
        }
        if let Some(previous) = &self.view {
            if view.generation < previous.generation {
                return Err(ShellError::State(
                    "runtime view generation regressed".to_owned(),
                ));
            }
            if view.generation == previous.generation && view.revision <= previous.revision {
                return Err(ShellError::State(
                    "runtime view revision did not advance".to_owned(),
                ));
            }
        }
        self.view = Some(view.clone());
        Ok(PresentationState {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            generation: view.generation,
            revision: view.revision,
            digest: view.digest,
            modules: view.modules,
            stale: false,
        })
    }

    pub fn runtime_status(&mut self) -> Result<serde_json::Value, ShellError> {
        self.require_session()?;
        self.backend.runtime_status()
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformRequest,
    ) -> Result<PlatformReceipt, ShellError> {
        let session = self.require_session()?.clone();
        let view = self.require_view()?.clone();
        validate_stable_id(&request.operation_id, "operation_id")?;
        if request.displayed_revision != view.revision {
            return Err(ShellError::State(
                "platform request was confirmed against a stale runtime view".to_owned(),
            ));
        }
        request.payload.validate()?;
        let action = request.payload.action();
        let payload_digest = request.payload.digest()?;
        let now = now_unix_ms()?;
        self.grant_verifier.verify_platform_grant(
            &request.grant,
            &session.session_id,
            session.generation,
            &request.operation_id,
            action,
            &payload_digest,
            now,
        )?;
        let key = OperationKey::new(&session, &request.operation_id)?;

        if let Some(existing) = self.journal.find(&key).cloned() {
            if existing.action != action || existing.payload_digest != payload_digest {
                return Err(ShellError::State(
                    "operation identity was reused with changed payload".to_owned(),
                ));
            }
            match existing.phase {
                OperationPhase::Terminal => return Ok(existing.receipt()),
                OperationPhase::Invoking | OperationPhase::Indeterminate => {
                    return self.reconcile_record(existing);
                }
                OperationPhase::Prepared => {}
            }
        }

        let permission = self.platform.permission(&request.payload)?;
        validate_digest(&permission.outcome_digest, "permission.outcome_digest")?;
        if !permission.allowed {
            let record = OperationRecord {
                endpoint_id: session.endpoint_id,
                key,
                action,
                payload_digest,
                phase: OperationPhase::Terminal,
                terminal_status: Some(TerminalStatus::Rejected),
                outcome_digest: Some(permission.outcome_digest),
            };
            let receipt = record.receipt();
            self.journal.upsert(record)?;
            return Ok(receipt);
        }

        let prepared = OperationRecord {
            endpoint_id: session.endpoint_id.clone(),
            key: key.clone(),
            action,
            payload_digest: payload_digest.clone(),
            phase: OperationPhase::Prepared,
            terminal_status: None,
            outcome_digest: None,
        };
        self.journal.upsert(prepared)?;

        let invoking = OperationRecord {
            endpoint_id: session.endpoint_id,
            key: key.clone(),
            action,
            payload_digest: payload_digest.clone(),
            phase: OperationPhase::Invoking,
            terminal_status: None,
            outcome_digest: None,
        };
        self.journal.upsert(invoking.clone())?;

        match self.platform.invoke(&key, &request.payload) {
            Ok(observation) => self.finish_observation(invoking, observation),
            Err(_error) => {
                let indeterminate = OperationRecord {
                    phase: OperationPhase::Indeterminate,
                    ..invoking
                };
                let receipt = indeterminate.receipt();
                self.journal.upsert(indeterminate)?;
                Ok(receipt)
            }
        }
    }

    pub fn reconcile_pending(&mut self) -> Result<Vec<PlatformReceipt>, ShellError> {
        let pending: Vec<OperationRecord> = self.journal.pending().cloned().collect();
        let mut receipts = Vec::with_capacity(pending.len());
        for record in pending {
            match record.phase {
                OperationPhase::Prepared => {
                    let belongs_to_current = self.session.as_ref().is_some_and(|session| {
                        record.key.session_id == session.session_id
                            && record.key.session_generation == session.generation
                    });
                    if belongs_to_current {
                        receipts.push(record.receipt());
                    } else {
                        let outcome_digest = crate::model::sha256_hex(format!(
                            "hepta.prepared-operation-abandoned.v1:{}:{}",
                            record.key.session_id, record.key.operation_id
                        ));
                        let terminal = OperationRecord {
                            phase: OperationPhase::Terminal,
                            terminal_status: Some(TerminalStatus::Quarantined),
                            outcome_digest: Some(outcome_digest),
                            ..record
                        };
                        let receipt = terminal.receipt();
                        self.journal.upsert(terminal)?;
                        receipts.push(receipt);
                    }
                }
                OperationPhase::Invoking | OperationPhase::Indeterminate => {
                    receipts.push(self.reconcile_record(record)?);
                }
                OperationPhase::Terminal => {}
            }
        }
        Ok(receipts)
    }

    pub fn pending_operations(&self) -> Vec<PlatformReceipt> {
        self.journal.pending().map(OperationRecord::receipt).collect()
    }

    pub fn operation_history(&self) -> Vec<PlatformReceipt> {
        self.journal.all().iter().map(OperationRecord::receipt).collect()
    }

    pub fn compact_terminal_history(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.journal.compact_terminal(keep_latest)
    }

    pub fn close(&mut self) -> Result<(), ShellError> {
        if let Some(session) = self.session.take() {
            self.backend.close(&session)?;
        }
        self.view = None;
        Ok(())
    }

    pub fn session(&self) -> Option<&SessionIncarnation> {
        self.session.as_ref()
    }

    pub fn view(&self) -> Option<&RuntimeView> {
        self.view.as_ref()
    }

    fn reconcile_record(
        &mut self,
        record: OperationRecord,
    ) -> Result<PlatformReceipt, ShellError> {
        match self.platform.reconcile(&record) {
            Ok(observation) => self.finish_observation(record, observation),
            Err(_error) => {
                let indeterminate = OperationRecord {
                    phase: OperationPhase::Indeterminate,
                    terminal_status: None,
                    outcome_digest: None,
                    ..record
                };
                let receipt = indeterminate.receipt();
                self.journal.upsert(indeterminate)?;
                Ok(receipt)
            }
        }
    }

    fn finish_observation(
        &mut self,
        record: OperationRecord,
        observation: PlatformObservation,
    ) -> Result<PlatformReceipt, ShellError> {
        let next = if let Some(status) = observation.terminal_status {
            let outcome_digest = observation.outcome_digest.ok_or_else(|| {
                ShellError::Platform("terminal platform observation lacks outcome digest".to_owned())
            })?;
            validate_digest(&outcome_digest, "platform.outcome_digest")?;
            OperationRecord {
                phase: OperationPhase::Terminal,
                terminal_status: Some(status),
                outcome_digest: Some(outcome_digest),
                ..record
            }
        } else {
            OperationRecord {
                phase: OperationPhase::Indeterminate,
                terminal_status: None,
                outcome_digest: None,
                ..record
            }
        };
        let receipt = next.receipt();
        self.journal.upsert(next)?;
        Ok(receipt)
    }

    fn require_session(&self) -> Result<&SessionIncarnation, ShellError> {
        self.session
            .as_ref()
            .ok_or_else(|| ShellError::State("native shell is not connected".to_owned()))
    }

    fn require_view(&self) -> Result<&RuntimeView, ShellError> {
        self.require_session()?;
        self.view.as_ref().ok_or_else(|| {
            ShellError::State("platform request requires a coherent runtime view".to_owned())
        })
    }
}
