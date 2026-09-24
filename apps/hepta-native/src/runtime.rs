use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;

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
use crate::security::KernelFinalUseGate;
use crate::security::platform_final_use_binding;

pub struct NativeShellRuntime {
    backend: Box<dyn BackendAdapter>,
    platform: Box<dyn PlatformAdapter>,
    final_use: Option<Arc<KernelFinalUseGate>>,
    journal: OperationJournal,
    session: Option<SessionIncarnation>,
    view: Option<RuntimeView>,
}

impl NativeShellRuntime {
    pub fn new(
        backend: Box<dyn BackendAdapter>,
        platform: Box<dyn PlatformAdapter>,
        final_use: Option<Arc<KernelFinalUseGate>>,
        journal: OperationJournal,
    ) -> Self {
        Self {
            backend,
            platform,
            final_use,
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

    fn accept_runtime_view(&mut self, view: RuntimeView) -> Result<PresentationState, ShellError> {
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

    pub fn refresh_runtime_view(
        &mut self,
    ) -> Result<(PresentationState, serde_json::Value), ShellError> {
        let session = self.require_session()?.clone();
        let observed = self.backend.runtime_status()?;
        validate_digest(&observed.body_digest, "backend.runtime_status_digest")?;
        let observed_generation = observed
            .value
            .pointer("/state/runtime_snapshot_generation")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| {
                ShellError::Backend(
                    "authenticated runtime status lacks runtime_snapshot_generation".to_owned(),
                )
            })?;
        let generation = observed_generation.max(1);
        let revision = match &self.view {
            Some(previous) if previous.generation == generation => previous
                .revision
                .checked_add(1)
                .ok_or_else(|| ShellError::State("runtime view revision overflow".to_owned()))?,
            _ => 1,
        };
        let view = RuntimeView {
            session_id: session.session_id,
            session_generation: session.generation,
            generation,
            revision,
            digest: observed.body_digest,
            modules: vec!["runtime.agentd".to_owned(), "ui.native".to_owned()],
        };
        let presentation = self.accept_runtime_view(view)?;
        Ok((presentation, observed.value))
    }

    pub fn prepare_platform_binding(
        &self,
        subject_id: &str,
        operation_id: &str,
        payload: &crate::model::PlatformPayload,
    ) -> Result<FinalUseBinding, ShellError> {
        let session = self.require_session()?;
        let view = self.require_view()?;
        platform_final_use_binding(subject_id, session, operation_id, view.revision, payload)
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformRequest,
    ) -> Result<PlatformReceipt, ShellError> {
        let session = self.require_session()?.clone();
        let view = self.require_view()?.clone();
        validate_stable_id(&request.subject_id, "subject_id")?;
        validate_stable_id(&request.operation_id, "operation_id")?;
        if request.displayed_revision != view.revision {
            return Err(ShellError::State(
                "platform request was confirmed against a stale runtime view".to_owned(),
            ));
        }
        request.payload.validate()?;
        let action = request.payload.action();
        let payload_digest = request.payload.digest()?;
        let binding = platform_final_use_binding(
            &request.subject_id,
            &session,
            &request.operation_id,
            request.displayed_revision,
            &request.payload,
        )?;
        let binding_digest = crate::model::sha256_hex(serde_json::to_vec(&binding)?);
        let grant_digest = crate::model::sha256_hex(serde_json::to_vec(&request.grant)?);
        let key = OperationKey::new(&session, &request.operation_id)?;

        if let Some(existing) = self.journal.find(&key).cloned() {
            if existing.subject_id != request.subject_id
                || existing.displayed_revision != request.displayed_revision
                || existing.action != action
                || existing.payload_digest != payload_digest
                || existing.binding_digest != binding_digest
                || existing.grant_digest != grant_digest
            {
                return Err(ShellError::State(
                    "operation identity was reused with changed semantics".to_owned(),
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
                subject_id: request.subject_id.clone(),
                displayed_revision: request.displayed_revision,
                action,
                payload_digest,
                binding_digest: binding_digest.clone(),
                grant_digest: grant_digest.clone(),
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
            subject_id: request.subject_id.clone(),
            displayed_revision: request.displayed_revision,
            action,
            payload_digest: payload_digest.clone(),
            binding_digest: binding_digest.clone(),
            grant_digest: grant_digest.clone(),
            phase: OperationPhase::Prepared,
            terminal_status: None,
            outcome_digest: None,
        };
        self.journal.upsert(prepared.clone())?;

        let Some(final_use) = self.final_use.clone() else {
            return self.reject_without_dispatch(
                prepared,
                "kernel final-use authority is not composed for this native host",
            );
        };
        let permit = match final_use.claim_platform(&request.grant, binding) {
            Ok(permit) => permit,
            Err(error) => {
                return self.reject_without_dispatch(prepared, &error.to_string());
            }
        };

        let invoking = OperationRecord {
            endpoint_id: session.endpoint_id,
            key: key.clone(),
            subject_id: request.subject_id,
            displayed_revision: request.displayed_revision,
            action,
            payload_digest: payload_digest.clone(),
            binding_digest,
            grant_digest,
            phase: OperationPhase::Invoking,
            terminal_status: None,
            outcome_digest: None,
        };
        self.journal.upsert(invoking.clone())?;

        match final_use.with_platform_use(permit, || self.platform.invoke(&key, &request.payload)) {
            Ok(Ok(observation)) => self.finish_observation(invoking, observation),
            Ok(Err(_error)) => {
                let indeterminate = OperationRecord {
                    phase: OperationPhase::Indeterminate,
                    ..invoking
                };
                let receipt = indeterminate.receipt();
                self.journal.upsert(indeterminate)?;
                Ok(receipt)
            }
            Err(error) => self.reject_without_dispatch(invoking, &error.to_string()),
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
        self.journal
            .pending()
            .map(OperationRecord::receipt)
            .collect()
    }

    pub fn operation_history(&self) -> Vec<PlatformReceipt> {
        self.journal
            .all()
            .iter()
            .map(OperationRecord::receipt)
            .collect()
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

    fn reconcile_record(&mut self, record: OperationRecord) -> Result<PlatformReceipt, ShellError> {
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
                ShellError::Platform(
                    "terminal platform observation lacks outcome digest".to_owned(),
                )
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

    fn reject_without_dispatch(
        &mut self,
        record: OperationRecord,
        reason: &str,
    ) -> Result<PlatformReceipt, ShellError> {
        let terminal = OperationRecord {
            phase: OperationPhase::Terminal,
            terminal_status: Some(TerminalStatus::Rejected),
            outcome_digest: Some(crate::model::sha256_hex(format!(
                "hepta.native.no-dispatch.v1:{reason}"
            ))),
            ..record
        };
        let receipt = terminal.receipt();
        self.journal.upsert(terminal)?;
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
