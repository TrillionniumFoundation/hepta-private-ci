//! Original-owner creation receipts. Inspection never invokes thread/start.
use super::*;
use codex_app_server_protocol::ThreadCreationObserveOutcome;
use codex_app_server_protocol::ThreadCreationObserveParams;
use codex_app_server_protocol::ThreadCreationObserveResponse;
use codex_state::ThreadCreationPhase;
use codex_state::ThreadCreationRecord;
use codex_state::ThreadCreationReservation;
use codex_state::ThreadCreationReserveOutcome;
use sha2::Digest;
use sha2::Sha256;

pub(super) struct IdentifiedCreation {
    pub state: StateDbHandle,
    pub reservation: ThreadCreationReservation,
}

pub(super) enum CreationAdmission {
    Unidentified,
    Reserved(IdentifiedCreation),
    Completed(ThreadStartResponse),
}

impl ThreadRequestProcessor {
    pub(super) async fn admit_identified_creation(
        &self,
        params: &ThreadStartParams,
    ) -> Result<CreationAdmission, JSONRPCErrorError> {
        let Some(key) = &params.idempotency_key else {
            return Ok(CreationAdmission::Unidentified);
        };
        if !self.thread_store.supports_identified_creation() {
            return Err(invalid_request(
                "configured thread store does not support identified creation",
            ));
        }
        if params.ephemeral != Some(false)
            || !self.thread_store.supports_durable_hard_delete_fencing()
        {
            return Err(invalid_request(
                "identified creation requires an original durable thread store and ephemeral:false",
            ));
        }
        let cwd = params
            .cwd
            .as_ref()
            .filter(|cwd| Path::new(cwd).is_absolute())
            .ok_or_else(|| {
                invalid_request("identified creation requires an explicit absolute cwd")
            })?;
        let cwd = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(cwd)
            .map_err(|error| invalid_request(error.to_string()))?;
        let state = self
            .state_db
            .as_ref()
            .ok_or_else(|| invalid_request("identified creation requires original local state"))?;
        let bytes = params
            .canonical_creation_parameters()
            .map_err(|error| invalid_request(error.to_string()))?;
        if bytes.len() > 1024 * 1024 {
            return Err(invalid_request("oversized identified creation parameters"));
        }
        let reservation = ThreadCreationReservation {
            idempotency_key: key.clone(),
            parameters_sha256: format!("{:x}", Sha256::digest(bytes)),
            thread_id: self.thread_manager.reserve_thread_id(),
            project_id: params.project_id.clone(),
            cwd: cwd.to_path_buf(),
            thread_source: serde_json::to_string(
                &params
                    .thread_source
                    .clone()
                    .map(codex_protocol::protocol::ThreadSource::from),
            )
            .map_err(|error| invalid_request(error.to_string()))?,
        };
        match state
            .reserve_thread_creation(&reservation)
            .await
            .map_err(|error| invalid_request(error.to_string()))?
        {
            ThreadCreationReserveOutcome::Reserved => {
                Ok(CreationAdmission::Reserved(IdentifiedCreation {
                    state: state.clone(),
                    reservation,
                }))
            }
            ThreadCreationReserveOutcome::Existing(record) => {
                if record.phase != ThreadCreationPhase::Created {
                    return Err(invalid_request(
                        "original creation is pending or deleted; inspect the same key, never repeat creation",
                    ));
                }
                ensure_creation_not_deleted(state, record.reservation.thread_id).await?;
                verify_creation_index(state, &record).await?;
                let response = creation_receipt(&record)?;
                Ok(CreationAdmission::Completed(response))
            }
        }
    }

    pub(crate) async fn observe_thread_creation(
        &self,
        params: ThreadCreationObserveParams,
    ) -> Result<ThreadCreationObserveResponse, JSONRPCErrorError> {
        let state = self
            .state_db
            .as_ref()
            .ok_or_else(|| invalid_request("local creation observation unavailable"))?;
        let record = read_scoped_creation(state, &params).await?;
        let outcome = match &record {
            None => ThreadCreationObserveOutcome::Missing,
            Some(record) => observe_creation(state, record).await?,
        };
        if read_scoped_creation(state, &params).await? != record {
            return Err(invalid_request(
                "original creation changed during observation",
            ));
        }
        Ok(ThreadCreationObserveResponse {
            idempotency_key: params.idempotency_key,
            parameters_sha256: params.expected_parameters_sha256,
            outcome,
        })
    }

    /// Authenticated explicit repair of only this fixed rollout's index/receipt.
    /// It cannot create, load or resume a Core, or send a user message.
    pub(crate) async fn reconcile_thread_creation(
        &self,
        params: ThreadCreationObserveParams,
    ) -> Result<ThreadCreationObserveResponse, JSONRPCErrorError> {
        let state = self
            .state_db
            .as_ref()
            .ok_or_else(|| invalid_request("local creation reconciliation unavailable"))?;
        if let Some(record) = read_scoped_creation(state, &params).await?
            && record.phase == ThreadCreationPhase::Pending
        {
            ensure_creation_not_deleted(state, record.reservation.thread_id).await?;
            if let Some(items) = creation_rollout_evidence(&record).await? {
                reconcile_creation_index(state, &record, &items, &self.config.model_provider_id)
                    .await?;
                if record.receipt_json.is_some() {
                    creation_receipt(&record)?;
                    state
                        .commit_thread_creation_receipt(&record.reservation)
                        .await
                        .map_err(|error| internal_error(error.to_string()))?;
                }
            }
        }
        self.observe_thread_creation(params).await
    }

    /// Only an explicit action may retire the exact pre-effect reservation.
    /// No file absence, unresolved callback or missing key implies cancellation.
    pub(crate) async fn abandon_thread_creation(
        &self,
        params: ThreadCreationObserveParams,
    ) -> Result<ThreadCreationObserveResponse, JSONRPCErrorError> {
        let state = self
            .state_db
            .as_ref()
            .ok_or_else(|| invalid_request("local creation abandonment unavailable"))?;
        let record = read_scoped_creation(state, &params)
            .await?
            .ok_or_else(|| invalid_request("original creation is unknown; inspect the same key"))?;
        if !state
            .abandon_reserved_thread_creation(&record.reservation)
            .await
            .map_err(|error| internal_error(error.to_string()))?
        {
            return Err(invalid_request(
                "original creation has begun or is unresolved; it cannot be abandoned",
            ));
        }
        self.observe_thread_creation(params).await
    }
}

impl IdentifiedCreation {
    pub(super) async fn finish(
        &self,
        store: &dyn ThreadStore,
        response: &ThreadStartResponse,
    ) -> Result<(), JSONRPCErrorError> {
        if response.thread.id != self.reservation.thread_id.to_string()
            || response.cwd.as_path() != self.reservation.cwd
        {
            return Err(invalid_request(
                "original creation response changed its reserved identity or cwd",
            ));
        }
        let receipt =
            serde_json::to_string(response).map_err(|error| internal_error(error.to_string()))?;
        self.state
            .prepare_thread_creation_receipt(&self.reservation, &receipt)
            .await
            .map_err(|error| internal_error(error.to_string()))?;
        store
            .persist_thread(
                self.reservation.thread_id,
                codex_thread_store::PersistContext::Standard,
            )
            .await
            .map_err(|error| internal_error(format!("persist identified creation: {error}")))?;
        store
            .flush_thread(self.reservation.thread_id)
            .await
            .map_err(|error| internal_error(format!("flush identified creation: {error}")))?;
        let record = self
            .state
            .read_thread_creation(&self.reservation.idempotency_key)
            .await
            .map_err(|error| internal_error(error.to_string()))?
            .ok_or_else(|| internal_error("creation binding disappeared"))?;
        let items = creation_rollout_evidence(&record)
            .await?
            .ok_or_else(|| internal_error("exact creation rollout is not yet durable"))?;
        reconcile_creation_index(&self.state, &record, &items, &response.model_provider).await?;
        self.state
            .commit_thread_creation_receipt(&self.reservation)
            .await
            .map_err(|error| internal_error(error.to_string()))
    }
}

async fn read_scoped_creation(
    state: &codex_state::StateRuntime,
    params: &ThreadCreationObserveParams,
) -> Result<Option<ThreadCreationRecord>, JSONRPCErrorError> {
    if params.idempotency_key.is_empty()
        || params.idempotency_key.len() > 256
        || params.idempotency_key.chars().any(char::is_control)
        || params.expected_parameters_sha256.len() != 64
        || !params
            .expected_parameters_sha256
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(invalid_request("invalid original creation observation"));
    }
    let record = state
        .read_thread_creation(&params.idempotency_key)
        .await
        .map_err(|error| internal_error(error.to_string()))?;
    if let Some(record) = &record {
        let source = serde_json::to_string(
            &params
                .expected_thread_source
                .clone()
                .map(codex_protocol::protocol::ThreadSource::from),
        )
        .map_err(|error| invalid_request(error.to_string()))?;
        if record.reservation.parameters_sha256 != params.expected_parameters_sha256
            || record.reservation.project_id != params.expected_project_id
            || record.reservation.cwd != params.expected_cwd.as_path()
            || record.reservation.thread_source != source
        {
            return Err(invalid_request(
                "creation key is outside the exact original parameters and protected scope",
            ));
        }
    }
    Ok(record)
}

async fn observe_creation(
    state: &codex_state::StateRuntime,
    record: &ThreadCreationRecord,
) -> Result<ThreadCreationObserveOutcome, JSONRPCErrorError> {
    let thread_id = record.reservation.thread_id.to_string();
    if record.phase == ThreadCreationPhase::Abandoned {
        return Ok(ThreadCreationObserveOutcome::Abandoned { thread_id });
    }
    if record.phase == ThreadCreationPhase::Deleted
        || state
            .thread_queue()
            .thread_queue_is_sealed_for_deletion(record.reservation.thread_id)
            .await
            .map_err(|error| internal_error(error.to_string()))?
    {
        return Ok(ThreadCreationObserveOutcome::Deleted { thread_id });
    }
    match record.phase {
        ThreadCreationPhase::Created => {
            verify_creation_index(state, record).await?;
            Ok(ThreadCreationObserveOutcome::Created {
                response: Box::new(creation_receipt(record)?),
            })
        }
        ThreadCreationPhase::Pending => match creation_rollout_evidence(record).await {
            Ok(Some(_)) => Ok(ThreadCreationObserveOutcome::Materialized { thread_id }),
            Ok(None) => Ok(ThreadCreationObserveOutcome::Pending { thread_id }),
            Err(_) => Ok(ThreadCreationObserveOutcome::Unknown),
        },
        ThreadCreationPhase::Deleted => Ok(ThreadCreationObserveOutcome::Deleted { thread_id }),
        ThreadCreationPhase::Abandoned => Ok(ThreadCreationObserveOutcome::Abandoned { thread_id }),
    }
}

fn creation_receipt(
    record: &ThreadCreationRecord,
) -> Result<ThreadStartResponse, JSONRPCErrorError> {
    let receipt = record
        .receipt_json
        .as_deref()
        .ok_or_else(|| internal_error("missing original creation receipt"))?;
    let response: ThreadStartResponse =
        serde_json::from_str(receipt).map_err(|error| internal_error(error.to_string()))?;
    if response.thread.id != record.reservation.thread_id.to_string()
        || response.cwd.as_path() != record.reservation.cwd
        || response.thread.project_id != record.reservation.project_id
        || response.thread.cwd.as_path() != record.reservation.cwd
        || response.thread.path.as_ref() != record.rollout_path.as_ref()
        || serde_json::to_string(
            &response
                .thread
                .thread_source
                .clone()
                .map(codex_protocol::protocol::ThreadSource::from),
        )
        .map_err(|error| internal_error(error.to_string()))?
            != record.reservation.thread_source
    {
        return Err(internal_error("substituted original creation receipt"));
    }
    Ok(response)
}

async fn ensure_creation_not_deleted(
    state: &codex_state::StateRuntime,
    thread_id: ThreadId,
) -> Result<(), JSONRPCErrorError> {
    if state
        .thread_queue()
        .thread_queue_is_sealed_for_deletion(thread_id)
        .await
        .map_err(|error| internal_error(error.to_string()))?
    {
        return Err(invalid_request(
            "creation is permanently sealed for deletion",
        ));
    }
    Ok(())
}

async fn verify_creation_index(
    state: &codex_state::StateRuntime,
    record: &ThreadCreationRecord,
) -> Result<(), JSONRPCErrorError> {
    let metadata = state
        .get_thread(record.reservation.thread_id)
        .await
        .map_err(|error| internal_error(error.to_string()))?
        .ok_or_else(|| {
            invalid_request("original creation index is pending; reconcile the same key")
        })?;
    if metadata.cwd != record.reservation.cwd
        || metadata.project_id != record.reservation.project_id
        || serde_json::to_string(&metadata.thread_source)
            .map_err(|error| internal_error(error.to_string()))?
            != record.reservation.thread_source
        || Some(&metadata.rollout_path) != record.rollout_path.as_ref()
    {
        return Err(invalid_request(
            "original creation index changed protected scope or selected rollout",
        ));
    }
    Ok(())
}

async fn creation_rollout_evidence(
    record: &ThreadCreationRecord,
) -> Result<Option<Vec<codex_rollout::RolloutItem>>, JSONRPCErrorError> {
    let Some(path) = &record.rollout_path else {
        return Ok(None);
    };
    let read = async {
        let mut reader =
            match codex_rollout::open_bounded_rollout_line_reader(path, 1024 * 1024).await {
                Ok(reader) => reader,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
                Err(error) => return Err(internal_error(error.to_string())),
            };
        let mut bytes = 0usize;
        let mut selected = Vec::new();
        for index in 0..65536 {
            let Some(line) = reader
                .next_line()
                .await
                .map_err(|error| internal_error(error.to_string()))?
            else {
                return if selected.is_empty() {
                    Err(internal_error("empty creation rollout"))
                } else {
                    Ok(Some(selected))
                };
            };
            bytes = bytes.saturating_add(line.len());
            if bytes > 32 * 1024 * 1024 {
                return Err(internal_error("creation rollout work budget exceeded"));
            }
            let line: codex_rollout::RolloutLine =
                serde_json::from_str(&line).map_err(|error| internal_error(error.to_string()))?;
            if index == 0 {
                let codex_rollout::RolloutItem::SessionMeta(meta) = &line.item else {
                    return Err(internal_error("missing exact creation SessionMeta"));
                };
                if meta.meta.id != record.reservation.thread_id
                    || meta.meta.cwd != record.reservation.cwd
                    || serde_json::to_string(&meta.meta.thread_source)
                        .map_err(|error| internal_error(error.to_string()))?
                        != record.reservation.thread_source
                {
                    return Err(internal_error(
                        "creation rollout has substituted identity or scope",
                    ));
                }
                selected.push(line.item);
            } else if matches!(line.item, codex_rollout::RolloutItem::SessionMeta(_)) {
                return Err(internal_error("duplicate creation SessionMeta"));
            }
        }
        Err(internal_error("creation rollout record budget exceeded"))
    };
    tokio::time::timeout(std::time::Duration::from_secs(4), read)
        .await
        .map_err(|_| internal_error("creation rollout observation timed out"))?
}

async fn reconcile_creation_index(
    state: &codex_state::StateRuntime,
    record: &ThreadCreationRecord,
    items: &[codex_rollout::RolloutItem],
    provider: &str,
) -> Result<(), JSONRPCErrorError> {
    ensure_creation_not_deleted(state, record.reservation.thread_id).await?;
    if state
        .get_thread(record.reservation.thread_id)
        .await
        .map_err(|error| internal_error(error.to_string()))?
        .is_none()
    {
        let builder = codex_rollout::builder_from_items(
            items,
            record
                .rollout_path
                .as_ref()
                .ok_or_else(|| internal_error("missing original rollout path"))?,
        )
        .ok_or_else(|| internal_error("missing exact rollout creation metadata"))?;
        let mut metadata = builder.build(provider);
        for item in items {
            codex_state::apply_rollout_item(&mut metadata, item, provider);
        }
        metadata.project_id = record.reservation.project_id.clone();
        state
            .insert_thread_if_absent(&metadata)
            .await
            .map_err(|error| internal_error(error.to_string()))?;
    }
    verify_creation_index(state, record).await?;
    ensure_creation_not_deleted(state, record.reservation.thread_id).await
}
