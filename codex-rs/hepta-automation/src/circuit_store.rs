//! Circuit V2 uses the existing AutomationStore. No second DB or scheduler.
//! Every mutation holds SQLite's writer reservation across lease/CAS checks and
//! the event append. Public effect authority remains with its existing owner.

use codex_hepta_contracts::Sha256Digest;

use crate::AutomationStore;
use crate::BoundedCircuitDefinitionV2;
use crate::CircuitCommandReceiptV2;
use crate::CircuitCommandStatusV2;
use crate::CircuitCommandV2;
use crate::CircuitLeaseClaimV2;
use crate::CircuitRunV2;
use crate::CircuitStartV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_journal::encode;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

impl AutomationStore {
    /// Register immutable bytes under the new explicit profile. Old versions
    /// remain readable; this does not replace any serving TaskFlow V1 graph.
    pub async fn register_bounded_circuit_definition(
        &self, definition: &BoundedCircuitDefinitionV2, fence: &TaskFlowFence,
    ) -> Result<Sha256Digest, TaskFlowError> {
        self.circuit_fence_identity(fence)?;
        let mut tx = self.taskflow_pool().begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
        circuit_journal::verify_owner(&mut tx, self.owner_agent_id()).await?;
        let digest = circuit_journal::register_definition(&mut tx, self.owner_agent_id(), definition).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(digest)
    }

    /// Commit one bounded run and its frozen definition/inputs atomically.
    pub async fn create_bounded_circuit_run(
        &self, definition: &BoundedCircuitDefinitionV2, start: &CircuitStartV2, fence: &TaskFlowFence,
    ) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        let event = CircuitLedgerEventV2::Created {
            start: start.clone(), fence: self.circuit_fence_identity(fence)?,
        };
        let (run, _) = event.replay(/*previous*/ None, definition, self.owner_agent_id())?;
        let command_digest = hash("hepta.circuit.command.v2", &event)?;
        let mut tx = self.taskflow_pool().begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
        circuit_journal::verify_owner(&mut tx, self.owner_agent_id()).await?;
        circuit_journal::register_definition(&mut tx, self.owner_agent_id(), definition).await?;
        if let Some(history) = circuit_journal::load(&mut tx, self.owner_agent_id(), &start.run_id).await? {
            if history.run.definition_digest != run.definition_digest || history.commands.get("create") != Some(&command_digest) {
                return Err(TaskFlowError::Conflict("circuit run already has different initial bytes".to_string()));
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(CircuitCommandReceiptV2 {
                status: CircuitCommandStatusV2::AlreadyApplied, run: history.run, dispatches: Vec::new(),
            });
        }
        let previous = Sha256Digest::for_bytes(b"hepta.circuit.genesis.v2");
        let last_digest = circuit_journal::event_digest(&run, "create", &command_digest, &previous)?;
        sqlx::query("INSERT INTO circuit_v2_runs VALUES (?, ?, ?, ?, ?, ?, ?)")
            .bind(self.owner_agent_id().as_str()).bind(&run.run_id).bind(run.definition_digest.as_str())
            .bind(0_i64).bind(encode(&run)?).bind(run.state_digest()?.as_str()).bind(last_digest.as_str())
            .execute(&mut *tx).await.map_err(unavailable)?;
        circuit_journal::append(&mut tx, &run, "create", &event, &previous).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(CircuitCommandReceiptV2 { status: CircuitCommandStatusV2::Applied, run, dispatches: Vec::new() })
    }

    /// Persist a scheduling quantum or a receipt. A duplicate command returns
    /// its verified current run and no new dispatch, even after acknowledgement
    /// loss. Changed bytes under the same command ID are rejected.
    pub async fn apply_bounded_circuit_command(&self, command: &CircuitCommandV2) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        let event = CircuitLedgerEventV2::Applied {
            fence: self.circuit_fence_identity(&command.fence)?,
            expected_revision: command.expected_revision, now_ms: command.now_ms, event: command.event.clone(),
        };
        self.apply_circuit_ledger(&command.run_id, &command.command_id, &event).await
    }

    /// Lease renewal/takeover is journaled. Expired in-flight computations become
    /// indeterminate under the successor; original invocation identity and full
    /// reservations survive. They must reconcile, never dispatch again.
    pub async fn claim_bounded_circuit_run(&self, claim: &CircuitLeaseClaimV2) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        let event = CircuitLedgerEventV2::Claimed {
            fence: self.circuit_fence_identity(&claim.fence)?,
            expected_revision: claim.expected_revision, now_ms: claim.now_ms,
            lease_duration_ms: claim.lease_duration_ms,
        };
        self.apply_circuit_ledger(&claim.run_id, &claim.command_id, &event).await
    }

    /// Recover from canonical events in one consistent read transaction. A
    /// projection is compared against replay; it is never deserialized as trusted
    /// runtime state. This observation alone cannot reissue computation/effects.
    pub async fn bounded_circuit_run(&self, run_id: &str) -> Result<Option<CircuitRunV2>, TaskFlowError> {
        text(run_id)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(history.map(|history| history.run))
    }

    fn circuit_fence_identity(&self, fence: &TaskFlowFence) -> Result<CircuitFenceIdentityV2, TaskFlowError> {
        if fence.owner_agent_id != *self.owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        CircuitFenceIdentityV2::from_fence(fence)
    }

    async fn apply_circuit_ledger(
        &self, run_id: &str, command_id: &str, event: &CircuitLedgerEventV2,
    ) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        text(run_id)?;
        text(command_id)?;
        if encode(event)?.len() > 131_072 {
            return Err(invalid("circuit command exceeds byte bound"));
        }
        let command_digest = hash("hepta.circuit.command.v2", event)?;
        let mut tx = self.taskflow_pool().begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id).await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".to_string()))?;
        if let Some(existing) = history.commands.get(command_id) {
            if existing != &command_digest {
                return Err(TaskFlowError::Conflict("circuit command ID has different bytes".to_string()));
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(CircuitCommandReceiptV2 {
                status: CircuitCommandStatusV2::AlreadyApplied, run: history.run, dispatches: Vec::new(),
            });
        }
        // Keep a bounded reconciliation allowance after the normal event budget.
        // Each unresolved computation can be marked and resolved once; another
        // 64 lease records remain available. No limit silently grants new work.
        let maximum = u64::from(history.definition.limits.max_events)
            + 2 * u64::from(history.definition.limits.max_activations) + 64;
        if history.run.revision >= maximum {
            return Err(invalid("circuit recovery history bound reached"));
        }
        let (run, dispatches) = event.replay(Some(&history.run), &history.definition, self.owner_agent_id())?;
        let state_json = encode(&run)?;
        if state_json.len() > 8_388_608 {
            return Err(invalid("circuit state exceeds byte bound"));
        }
        let last_digest = circuit_journal::event_digest(&run, command_id, &command_digest, &history.last_digest)?;
        let changed = sqlx::query("UPDATE circuit_v2_runs
             SET revision = ?, state_json = ?, state_digest = ?, last_event_digest = ?
             WHERE owner_agent_id = ? AND run_id = ? AND revision = ? AND state_digest = ?")
            .bind(i64::try_from(run.revision).map_err(|_| invalid("revision overflow"))?)
            .bind(state_json).bind(run.state_digest()?.as_str()).bind(last_digest.as_str())
            .bind(self.owner_agent_id().as_str()).bind(run_id)
            .bind(i64::try_from(history.run.revision).map_err(|_| invalid("revision overflow"))?)
            .bind(history.run.state_digest()?.as_str()).execute(&mut *tx).await.map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(TaskFlowError::StaleFence);
        }
        circuit_journal::append(&mut tx, &run, command_id, event, &history.last_digest).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(CircuitCommandReceiptV2 { status: CircuitCommandStatusV2::Applied, run, dispatches })
    }
}
