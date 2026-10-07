//! Child of taskflow_step: uses its actual validators/core/event readers.
//! No caller can supply an independent transaction or native command digest.
use sqlx::Row;
use tokio::sync::Barrier;

use super::*;
use crate::retrieval_choice_qualification::FixtureError;
use crate::retrieval_choice_qualification::FixtureRootCapability;
use crate::retrieval_choice_qualification::budget;
use crate::retrieval_choice_qualification::check_connection;
use crate::retrieval_choice_qualification::check_root;
use crate::retrieval_choice_qualification::records::FreshClaim;
use crate::retrieval_choice_qualification::records::PhaseCommand;
use crate::retrieval_choice_qualification::records::PhaseFault;
use crate::retrieval_choice_qualification::records::PhaseOperation;
use crate::retrieval_choice_qualification::records::PhaseOutcome;
use crate::retrieval_choice_qualification::records::PhaseReceipt;

impl AutomationStore {
    pub(crate) async fn retrieval_phase_command(
        &self,
        capability: &FixtureRootCapability,
        command: &PhaseCommand,
        fault: PhaseFault,
        before_write: Option<(&Barrier, Option<&Barrier>)>,
    ) -> Result<PhaseOutcome, FixtureError> {
        command.validate(capability)?;
        validate_common(
            &command.run_id,
            &command.node,
            /*attempt*/ 1,
            &command.command_id,
            &command.intent_digest,
            &command.payload_digest,
        )?;
        validate_fence(self, &command.fence)?;
        check_root(capability.root(), self.owner_agent_id(), Some(capability))?;
        if self.path().parent() != Some(capability.root()) {
            return Err(FixtureError::Invalid);
        }
        // These four objects already exist after normal schema19 migration.
        // Reject missing objects rather than repair schema on a historical/expired call.
        let native_objects: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE
            (type = 'table' AND name = 'taskflow_step_outbox') OR
            (type = 'trigger' AND name IN ('taskflow_step_outbox_no_update','taskflow_step_outbox_no_delete')) OR
            (type = 'index' AND name = 'taskflow_step_outbox_lookup')")
            .fetch_one(self.taskflow_pool()).await?;
        if native_objects != 4 {
            return Err(FixtureError::Invalid);
        }
        // Fixed claim signature carries no receipt/observation/reconcile outcome.
        // These are the same pre-transaction checks as the ordinary wrapper.
        ensure_step_schema(self).await?;
        let (bytes, digest) = command.canonical()?;
        let mut tx = self.begin_step_tx().await?;
        check_connection(&mut tx, self.owner_agent_id(), Some(capability)).await?;
        let run = load_run(&mut tx, self, &command.run_id).await?;
        // load_run already verifies the complete run event chain. Registry
        // integrity and node validity also precede all historical returns.
        let definition = load_definition(&mut tx, self, &run).await?;
        validate_step_node(&definition, &command.node)?;
        if definition.definition_digest() != &run.definition_digest
            || run.definition_digest != command.definition_digest
        {
            return Err(FixtureError::Invalid);
        }
        let events = load_step_events(
            &mut tx,
            self,
            &command.run_id,
            &command.node,
            /*attempt*/ 1,
        )
        .await?;
        let choice = sqlx::query(
            "SELECT * FROM qualification_retrieval_choices WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(&command.run_id)
        .fetch_optional(&mut *tx)
        .await?;
        let claim = sqlx::query(
            "SELECT * FROM qualification_retrieval_claims WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(&command.run_id)
        .fetch_optional(&mut *tx)
        .await?;
        if let Some(row) = choice.as_ref() {
            let saved: Vec<u8> = row.try_get("command_bytes")?;
            let prepared: PhaseCommand =
                serde_json::from_slice(&saved).map_err(|_| FixtureError::Invalid)?;
            prepared.validate(capability)?;
            let (canonical, prepared_digest) = prepared.canonical()?;
            let native_prepared_digest = operation_digest(
                "prepare",
                self.owner_agent_id(),
                &prepared.run_id,
                &prepared.node,
                /*attempt*/ 1,
                &prepared.command_id,
                prepared.intent_digest.as_str(),
                prepared.payload_digest.as_str(),
                &prepared.fence,
                /*receipt_digest*/ None,
                /*observation*/ None,
                /*final_outcome*/ None,
                prepared.now_ms,
            )?;
            let prepared_event = existing_command(
                &events,
                &prepared.command_id,
                native_prepared_digest.as_str(),
            )?
            .ok_or(FixtureError::Invalid)?;
            if saved != canonical
                || prepared.operation != PhaseOperation::Prepare
                || row.try_get::<String, _>("command_id")? != prepared.command_id
                || row.try_get::<String, _>("activation_id")? != prepared.activation_id
                || row.try_get::<String, _>("command_digest")? != prepared_digest.as_str()
                || row.try_get::<String, _>("native_command_digest")?
                    != native_prepared_digest.as_str()
                || row.try_get::<String, _>("definition_digest")?
                    != prepared.definition_digest.as_str()
                || row.try_get::<String, _>("step_id")? != prepared.node
                || row.try_get::<i64, _>("attempt")? != 1
                || u64::try_from(row.try_get::<i64, _>("event_seq")?)
                    .map_err(|_| FixtureError::Invalid)?
                    != prepared_event.event_seq
                || u64::try_from(row.try_get::<i64, _>("frozen_revision")?)
                    .map_err(|_| FixtureError::Invalid)?
                    != prepared.revision
                || u64::try_from(row.try_get::<i64, _>("bootstrap_event_seq")?)
                    .map_err(|_| FixtureError::Invalid)?
                    != command.bootstrap_event_seq
                || (command.operation == PhaseOperation::Claim
                    && command.prepare_digest.as_ref() != Some(&prepared_digest))
            {
                return Err(FixtureError::Invalid);
            }
        }
        let operation = match command.operation {
            PhaseOperation::Prepare => "prepare",
            PhaseOperation::Claim => "claim",
        };
        let native_digest = operation_digest(
            operation,
            self.owner_agent_id(),
            &command.run_id,
            &command.node,
            /*attempt*/ 1,
            &command.command_id,
            command.intent_digest.as_str(),
            command.payload_digest.as_str(),
            &command.fence,
            /*receipt_digest*/ None,
            /*observation*/ None,
            /*final_outcome*/ None,
            command.now_ms,
        )?;
        let existing = match command.operation {
            PhaseOperation::Prepare => choice.as_ref(),
            PhaseOperation::Claim => claim.as_ref(),
        };
        if let Some(row) = existing {
            if row.try_get::<String, _>("command_id")? != command.command_id
                || row.try_get::<Vec<u8>, _>("command_bytes")? != bytes
                || row.try_get::<String, _>("command_digest")? != digest.as_str()
                || row.try_get::<String, _>("activation_id")? != command.activation_id
                || row.try_get::<String, _>("native_command_digest")? != native_digest.as_str()
                || row.try_get::<String, _>("step_id")? != command.node
                || row.try_get::<i64, _>("attempt")? != 1
            {
                return Err(FixtureError::Invalid);
            }
            let seq = u64::try_from(row.try_get::<i64, _>("event_seq")?)
                .map_err(|_| FixtureError::Invalid)?;
            let event = existing_command(&events, &command.command_id, native_digest.as_str())?
                .ok_or(FixtureError::Invalid)?;
            if event.event_seq != seq {
                return Err(FixtureError::Invalid);
            }
            let historical: Vec<_> = events
                .iter()
                .take_while(|e| e.event_seq <= seq)
                .cloned()
                .collect();
            let native = reconstruct_step(
                self.owner_agent_id(),
                &command.run_id,
                &command.node,
                /*attempt*/ 1,
                &historical,
            )?;
            let choice_row = choice.as_ref().ok_or(FixtureError::Invalid)?;
            let floor = choice_row.try_get("bootstrap_event_seq")?;
            let retained_bytes = budget::retained_bytes(&mut tx, command, floor).await?;
            tx.commit().await?;
            return Ok(PhaseOutcome::Historical(PhaseReceipt {
                native,
                command_digest: digest,
                retained_bytes,
            }));
        }
        if run.state != crate::TaskFlowRunState::Running
            || run.cancel_requested
            || run.revision != command.revision
            || run.current_node != command.node
            || run.definition_digest != command.definition_digest
        {
            return Err(FixtureError::Invalid);
        }
        check_active_run_fence(&run, &command.fence, capability.now_ms())?;
        let floor = if let Some(row) = choice.as_ref() {
            let prepare_bytes: Vec<u8> = row.try_get("command_bytes")?;
            let prepare: PhaseCommand =
                serde_json::from_slice(&prepare_bytes).map_err(|_| FixtureError::Invalid)?;
            prepare.validate(capability)?;
            let (canonical, prepared_digest) = prepare.canonical()?;
            if canonical != prepare_bytes
                || row.try_get::<String, _>("command_digest")? != prepared_digest.as_str()
                || command.prepare_digest.as_ref() != Some(&prepared_digest)
                || command.activation_id != prepare.activation_id
                || prepare.operation != PhaseOperation::Prepare
            {
                return Err(FixtureError::Invalid);
            }
            row.try_get::<i64, _>("bootstrap_event_seq")?
        } else {
            if command.operation != PhaseOperation::Prepare || !events.is_empty() || claim.is_some()
            {
                return Err(FixtureError::Invalid);
            }
            sqlx::query_scalar::<_, i64>("SELECT MAX(event_seq) FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ?")
                .bind(self.owner_agent_id().as_str()).bind(&command.run_id).fetch_one(&mut *tx).await?
        };
        if u64::try_from(floor).map_err(|_| FixtureError::Invalid)? != command.bootstrap_event_seq {
            return Err(FixtureError::Invalid);
        }
        budget::reserve(command)?;
        budget::retained_bytes(&mut tx, command, floor).await?;
        // No write lock has been acquired. Never put a two-writer barrier later.
        if let Some((snapshot_ready, release)) = before_write {
            snapshot_ready.wait().await;
            if let Some(release) = release {
                release.wait().await;
            }
        }
        check_active_run_fence(&run, &command.fence, capability.now_ms())?;
        let pending = match command.operation {
            PhaseOperation::Prepare => {
                self.prepare_taskflow_step_tx(
                    &mut tx,
                    &command.run_id,
                    &command.node,
                    /*attempt*/ 1,
                    &command.fence,
                    &command.intent_digest,
                    &command.payload_digest,
                    &command.command_id,
                    command.now_ms,
                )
                .await?
            }
            PhaseOperation::Claim => {
                self.append_taskflow_step_operation_tx(
                    &mut tx,
                    "claim",
                    &command.run_id,
                    &command.node,
                    /*attempt*/ 1,
                    &command.fence,
                    &command.intent_digest,
                    &command.payload_digest,
                    &command.command_id,
                    /*receipt_digest*/ None,
                    /*observation*/ None,
                    /*final_outcome*/ None,
                    command.now_ms,
                )
                .await?
            }
        };
        // Combined fixture transactions reconstruct before their own commit;
        // the unchanged ordinary wrappers still reconstruct fresh after commit.
        let native_result = pending.into_result(
            self.owner_agent_id(),
            &command.run_id,
            &command.node,
            /*attempt*/ 1,
        )?;
        if native_result.status != TaskFlowStepCommandStatus::Applied {
            return Err(FixtureError::Invalid);
        }
        if fault == PhaseFault::AfterNativeAppend {
            return Err(FixtureError::Injected);
        }
        let seq =
            i64::try_from(native_result.receipt.event_seq).map_err(|_| FixtureError::Invalid)?;
        match command.operation {
            PhaseOperation::Prepare => {
                sqlx::query("INSERT INTO qualification_retrieval_choices
                    (owner_agent_id,run_id,activation_id,definition_digest,command_id,command_digest,command_bytes,native_command_digest,step_id,attempt,event_seq,frozen_revision,bootstrap_event_seq)
                    VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?)")
                    .bind(self.owner_agent_id().as_str()).bind(&command.run_id).bind(&command.activation_id)
                    .bind(command.definition_digest.as_str()).bind(&command.command_id).bind(digest.as_str())
                    .bind(&bytes).bind(native_digest.as_str()).bind(&command.node).bind(seq)
                    .bind(i64::try_from(command.revision).map_err(|_| FixtureError::Invalid)?).bind(floor)
                    .execute(&mut *tx).await?;
            }
            PhaseOperation::Claim => {
                sqlx::query("INSERT INTO qualification_retrieval_claims
                    (owner_agent_id,run_id,activation_id,command_id,command_digest,command_bytes,native_command_digest,step_id,attempt,event_seq)
                    VALUES (?,?,?,?,?,?,?,?,1,?)")
                    .bind(self.owner_agent_id().as_str()).bind(&command.run_id).bind(&command.activation_id)
                    .bind(&command.command_id).bind(digest.as_str()).bind(&bytes).bind(native_digest.as_str())
                    .bind(&command.node).bind(seq).execute(&mut *tx).await?;
            }
        }
        if fault == PhaseFault::AfterCorrelationInsert {
            return Err(FixtureError::Injected);
        }
        let retained_bytes = budget::retained_bytes(&mut tx, command, floor).await?;
        check_active_run_fence(&run, &command.fence, capability.now_ms())?;
        if fault == PhaseFault::BeforeCommit {
            return Err(FixtureError::Injected);
        }
        tx.commit().await?;
        if fault == PhaseFault::AfterCommitAckLoss {
            return Err(FixtureError::Injected);
        }
        let receipt = PhaseReceipt {
            native: native_result.receipt,
            command_digest: digest,
            retained_bytes,
        };
        Ok(match command.operation {
            PhaseOperation::Prepare => PhaseOutcome::Applied(receipt),
            PhaseOperation::Claim => PhaseOutcome::Fresh(FreshClaim { receipt }),
        })
    }
}
