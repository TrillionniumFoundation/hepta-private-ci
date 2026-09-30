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
use crate::security::PlatformConfirmationContext;
use crate::security::platform_final_use_binding;

const MAX_OPERATION_HISTORY_PAGE_SIZE: usize = 256;

#[derive(Debug, Clone)]
pub struct OperationHistoryPage {
    pub page: usize,
    pub page_size: usize,
    pub total: usize,
    /// Newest receipt first. This is presentation only; journal ordering and
    /// replay fences remain owned by the durable operation journal.
    pub receipts: Vec<PlatformReceipt>,
}

pub struct NativeShellRuntime {
    backend: Box<dyn BackendAdapter>,
    platform: Box<dyn PlatformAdapter>,
    final_use: Option<Arc<KernelFinalUseGate>>,
    journal: OperationJournal,
    session: Option<SessionIncarnation>,
    // Rejected sessions remain owned for cleanup, never for authorization.
    cleanup_pending: Option<SessionIncarnation>,
    view: Option<RuntimeView>,
    last_snapshot_generation: Option<u64>,
    displayed_revision: u64,
    manifest: Option<EndpointManifest>,
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
            cleanup_pending: None,
            view: None,
            last_snapshot_generation: None,
            displayed_revision: 0,
            manifest: None,
        }
    }

    pub fn connect_runtime(
        &mut self,
        manifest: &EndpointManifest,
    ) -> Result<SessionIncarnation, ShellError> {
        self.journal.ensure_healthy()?;
        manifest.validate()?;
        // Close the previous owner before acquiring another. Failure retains
        // its identity and leaves presentation invalid, so retry cannot skip it.
        self.close()?;
        let session = self.backend.connect(manifest)?;
        let validation = session.validate().and_then(|()| {
            if session.endpoint_id != manifest.endpoint_id {
                return Err(ShellError::Backend(
                    "backend session endpoint identity does not match manifest".to_owned(),
                ));
            }
            Ok(())
        });
        if let Err(error) = validation {
            self.cleanup_pending = Some(session);
            if let Err(close_error) = self.close() {
                return Err(ShellError::Backend(format!(
                    "{error}; rejected session cleanup failed: {close_error}"
                )));
            }
            return Err(error);
        }
        self.session = Some(session.clone());
        self.manifest = Some(manifest.clone());
        if let Err(error) = self.reconcile_pending() {
            if let Err(close_error) = self.close() {
                return Err(ShellError::Backend(format!(
                    "{error}; failed recovery session cleanup failed: {close_error}"
                )));
            }
            return Err(error);
        }
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
            if view.revision <= previous.revision {
                return Err(ShellError::State(
                    "runtime view revision did not advance".to_owned(),
                ));
            }
        }
        self.displayed_revision = view.revision;
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
        // Retain the high-water marks, not the operation authority of the last
        // presentation. Every error below leaves the runtime non-actionable.
        self.view = None;
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
        if self
            .last_snapshot_generation
            .is_some_and(|previous| observed_generation < previous)
        {
            return Err(ShellError::State(
                "authenticated runtime snapshot generation regressed".to_owned(),
            ));
        }
        // The owner permits generation zero at genesis. Presentation uses a
        // positive generation, but fencing compares the unmodified owner value.
        let generation = observed_generation.max(1);
        // Grants bind displayed_revision. Never reuse a revision when the
        // upstream generation changes within the same session incarnation.
        let revision = self
            .displayed_revision
            .checked_add(1)
            .ok_or_else(|| ShellError::State("runtime view revision overflow".to_owned()))?;
        let view = RuntimeView {
            session_id: session.session_id,
            session_generation: session.generation,
            generation,
            revision,
            digest: observed.body_digest,
            modules: vec!["runtime.agentd".to_owned(), "ui.native".to_owned()],
        };
        let presentation = self.accept_runtime_view(view)?;
        self.last_snapshot_generation = Some(observed_generation);
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
        self.journal.ensure_healthy()?;
        let context = self.confirmation_context(payload)?;
        platform_final_use_binding(
            subject_id,
            session,
            operation_id,
            view.revision,
            payload,
            &context,
        )
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformRequest,
    ) -> Result<PlatformReceipt, ShellError> {
        self.journal.ensure_healthy()?;
        let session = self.require_session()?.clone();
        validate_stable_id(&request.subject_id, "subject_id")?;
        validate_stable_id(&request.operation_id, "operation_id")?;
        request.payload.validate()?;
        let action = request.payload.action();
        let payload_digest = request.payload.digest()?;
        // For an existing identity, compare the original signed intent rather
        // than rebuilding it against today's view. Reading an old receipt is
        // permitted without a fresh view; starting/resuming an effect is not.
        let binding_digest =
            crate::model::sha256_hex(serde_json::to_vec(&request.grant.grant.binding)?);
        let grant_digest = crate::model::sha256_hex(serde_json::to_vec(&request.grant)?);
        let key = OperationKey::new(&session, &request.operation_id)?;
        let existing = match self.journal.find(&key).cloned() {
            Some(record) => Some(record),
            None => self.journal.archived_record(&session.endpoint_id, &key)?,
        };
        if let Some(existing) = existing {
            if existing.endpoint_id != session.endpoint_id
                || existing.subject_id != request.subject_id
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
                OperationPhase::Terminal | OperationPhase::ObservationClosed => {
                    return Ok(existing.receipt());
                }
                OperationPhase::Invoking | OperationPhase::Indeterminate => {
                    return self.reconcile_record(existing);
                }
                OperationPhase::Prepared => {}
            }
        }

        // Legacy tombstones have no reconstructable receipt, but still fence
        // the identity. Historical lookup never grants permission to replay.
        self.journal
            .ensure_not_retired(&session.endpoint_id, &key)?;
        let view = self.require_view()?.clone();
        if request.displayed_revision != view.revision {
            return Err(ShellError::State(
                "platform request was confirmed against a stale runtime view".to_owned(),
            ));
        }
        let context = self.confirmation_context(&request.payload)?;
        let binding = platform_final_use_binding(
            &request.subject_id,
            &session,
            &request.operation_id,
            request.displayed_revision,
            &request.payload,
            &context,
        )?;
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
        // Reserve the immutable operation identity before even asking the
        // platform for permission. Recovery can now explain this boundary.
        self.journal.upsert(prepared.clone())?;
        let permission = match self.platform.permission(&request.payload) {
            Ok(permission) => permission,
            Err(error) => return self.reject_without_dispatch(prepared, &error.to_string()),
        };
        if let Err(error) = validate_digest(&permission.outcome_digest, "permission.outcome_digest")
        {
            return self.reject_without_dispatch(prepared, &error.to_string());
        }
        if !permission.allowed {
            let terminal = OperationRecord {
                phase: OperationPhase::Terminal,
                terminal_status: Some(TerminalStatus::Rejected),
                outcome_digest: Some(permission.outcome_digest),
                ..prepared
            };
            let receipt = terminal.receipt();
            self.journal.upsert(terminal)?;
            return Ok(receipt);
        }

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

        match final_use.with_platform_use(permit, || {
            self.platform
                .invoke_confirmed(&key, &request.payload, &context.resource_digest)
        }) {
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
        self.journal.ensure_healthy()?;
        let pending: Vec<OperationRecord> = self.journal.pending().cloned().collect();
        let mut receipts = Vec::with_capacity(pending.len());
        for record in pending {
            match record.phase {
                OperationPhase::Prepared => {
                    let belongs_to_current = self.session.as_ref().is_some_and(|session| {
                        record.endpoint_id == session.endpoint_id
                            && record.key.session_id == session.session_id
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
                OperationPhase::Terminal | OperationPhase::ObservationClosed => {}
            }
        }
        Ok(receipts)
    }

    pub fn record_startup(
        &self,
        recorder: crate::startup::StartupRecorder,
    ) -> Result<(), ShellError> {
        self.journal.ensure_healthy()?;
        recorder.record(self.require_session()?, self.require_view()?)
    }

    pub fn confirm_update_ready(
        &self,
        updater: &crate::updater::UpdateManager,
        handoff: &crate::update_handoff::UpdateHandoff,
    ) -> Result<(), ShellError> {
        self.journal.ensure_healthy()?;
        updater.confirm_running_process(handoff, self.require_session()?, self.require_view()?)
    }

    pub fn pending_operations(&self) -> Vec<PlatformReceipt> {
        self.journal
            .pending()
            .map(OperationRecord::receipt)
            .collect()
    }

    /// Return one bounded, newest-first page directly from the journal slice.
    /// The UI never clones the complete history. Mutation and history-read lanes
    /// are mutually exclusive, so a displayed page is stable until the next
    /// authoritative mutation publishes a replacement page.
    pub fn operation_history_page(
        &self,
        requested_page: usize,
        page_size: usize,
    ) -> Result<OperationHistoryPage, ShellError> {
        self.journal.ensure_healthy()?;
        if page_size == 0 || page_size > MAX_OPERATION_HISTORY_PAGE_SIZE {
            return Err(ShellError::InvalidInput(format!(
                "operation history page size must be between 1 and {MAX_OPERATION_HISTORY_PAGE_SIZE}"
            )));
        }
        let records = self.journal.all();
        let total = records.len();
        let last_page = total.saturating_sub(1) / page_size;
        let page = requested_page.min(last_page);
        let start = page
            .checked_mul(page_size)
            .ok_or_else(|| ShellError::State("operation history page offset overflow".to_owned()))?;
        let receipts = records
            .iter()
            .rev()
            .skip(start)
            .take(page_size)
            .map(OperationRecord::receipt)
            .collect();
        Ok(OperationHistoryPage {
            page,
            page_size,
            total,
            receipts,
        })
    }

    pub fn close_operation_observation(
        &mut self,
        key: &OperationKey,
    ) -> Result<PlatformReceipt, ShellError> {
        self.journal.close_observation(key)
    }

    pub fn journal_capacity(&self) -> crate::journal::JournalCapacity {
        self.journal.capacity()
    }

    pub fn compact_closed_history(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.journal.compact_closed_history(keep_latest)
    }

    pub fn compact_terminal_history(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.journal.compact_terminal(keep_latest)
    }

    pub fn close(&mut self) -> Result<(), ShellError> {
        // Presentation is invalid even when transport cleanup cannot finish.
        self.view = None;
        self.last_snapshot_generation = None;
        self.displayed_revision = 0;
        self.manifest = None;
        // Even a poisoned journal must not prevent transport cleanup, but it
        // must prevent reporting a clean shutdown to the update handoff.
        let journal_health = self.journal.ensure_healthy();
        if let Some(session) = self.cleanup_pending.as_ref() {
            self.backend.close(session)?;
            self.cleanup_pending = None;
        }
        if let Some(session) = self.session.as_ref() {
            self.backend.close(session)?;
            self.session = None;
        }
        journal_health
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

    fn confirmation_context(
        &self,
        payload: &crate::model::PlatformPayload,
    ) -> Result<PlatformConfirmationContext, ShellError> {
        let view = self.require_view()?;
        let manifest = self.manifest.as_ref().ok_or_else(|| {
            ShellError::State("native endpoint manifest is unavailable".to_owned())
        })?;
        Ok(PlatformConfirmationContext {
            endpoint_manifest_digest: manifest.manifest_digest.clone(),
            view_generation: view.generation,
            view_digest: view.digest.clone(),
            resource_digest: self.platform.confirmation_resource(payload)?,
        })
    }

    fn require_session(&self) -> Result<&SessionIncarnation, ShellError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| ShellError::State("native shell is not connected".to_owned()))?;
        if self.manifest.is_none() {
            return Err(ShellError::State(
                "native session is closing; its identity is retained only for cleanup".to_owned(),
            ));
        }
        Ok(session)
    }

    fn require_view(&self) -> Result<&RuntimeView, ShellError> {
        self.require_session()?;
        self.view.as_ref().ok_or_else(|| {
            ShellError::State("platform request requires a coherent runtime view".to_owned())
        })
    }
}
