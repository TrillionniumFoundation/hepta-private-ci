//! Append-only provider-contact evidence for final-use-authorized TaskFlow effects.
//!
//! These rows do not execute effects and grant no authority. The attempt row
//! only records that a verified final-use claim crossed the durable dispatch
//! boundary; the observation row records exactly one provider-owned recovery
//! fact. Keeping both immutable lets recovery repair the TaskFlow step without
//! ever inferring terminality from process-local control flow.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum EffectDispatchObservationKind {
    ProvenAbsent,
    Succeeded,
    Failed,
    Indeterminate,
}

impl EffectDispatchObservationKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::ProvenAbsent => "proven_absent",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "proven_absent" => Ok(Self::ProvenAbsent),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(TaskFlowError::Corrupt(
                "unknown effect dispatch observation".to_string(),
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EffectDispatchObservation {
    pub(crate) kind: EffectDispatchObservationKind,
    pub(crate) evidence_digest: Sha256Digest,
    pub(crate) observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EffectDispatchAttempt {
    pub(crate) run_id: String,
    pub(crate) step_id: String,
    pub(crate) attempt: u32,
    pub(crate) intent_digest: Sha256Digest,
    pub(crate) payload_digest: Sha256Digest,
    pub(crate) binding_digest: Sha256Digest,
    pub(crate) destination_id: String,
    pub(crate) authority_epoch: u64,
    pub(crate) grant_id: String,
    pub(crate) grant_nonce_digest: Sha256Digest,
    pub(crate) record_command_id: String,
    pub(crate) started_at_ms: u64,
    pub(crate) observation: Option<EffectDispatchObservation>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum EffectDispatchStart {
    Inserted(EffectDispatchAttempt),
    Existing(EffectDispatchAttempt),
}

impl AutomationStore {
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn begin_effect_dispatch_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        binding_digest: &Sha256Digest,
        destination_id: &str,
        authority_epoch: u64,
        grant_id: &str,
        grant_nonce_digest: &Sha256Digest,
        record_command_id: &str,
        started_at_ms: u64,
    ) -> Result<EffectDispatchStart, TaskFlowError> {
        let inserted = sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_attempts (
                owner_agent_id, run_id, step_id, attempt, intent_digest,
                payload_digest, binding_digest, destination_id, authority_epoch,
                grant_id, grant_nonce_digest, record_command_id, started_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(intent_digest.as_str())
        .bind(payload_digest.as_str())
        .bind(binding_digest.as_str())
        .bind(destination_id)
        .bind(to_i64(authority_epoch)?)
        .bind(grant_id)
        .bind(grant_nonce_digest.as_str())
        .bind(record_command_id)
        .bind(to_i64(started_at_ms)?)
        .execute(self.taskflow_pool())
        .await;

        match inserted {
            Ok(_) => {
                let attempt = self
                    .effect_dispatch_attempt(run_id, step_id, attempt)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Corrupt(
                            "effect dispatch attempt vanished after insert".to_string(),
                        )
                    })?;
                Ok(EffectDispatchStart::Inserted(attempt))
            }
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .effect_dispatch_attempt(run_id, step_id, attempt)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Conflict(
                            "effect dispatch identity conflicts with durable evidence".to_string(),
                        )
                    })?;
                if existing.intent_digest != *intent_digest
                    || existing.payload_digest != *payload_digest
                    || existing.binding_digest != *binding_digest
                    || existing.destination_id != destination_id
                    || existing.record_command_id != record_command_id
                {
                    return Err(TaskFlowError::Conflict(
                        "effect dispatch attempt is bound to different bytes".to_string(),
                    ));
                }
                Ok(EffectDispatchStart::Existing(existing))
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    pub(crate) async fn effect_dispatch_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<EffectDispatchAttempt>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id
              AND o.run_id = a.run_id
              AND o.step_id = a.step_id
              AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id
              AND r.run_id = a.run_id
              AND r.step_id = a.step_id
              AND r.attempt = a.attempt
             WHERE a.owner_agent_id = ? AND a.run_id = ? AND a.step_id = ?
               AND a.attempt = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(effect_attempt_from_row).transpose()
    }

    pub(crate) async fn pending_effect_dispatch_attempts(
        &self,
        limit: usize,
    ) -> Result<Vec<EffectDispatchAttempt>, TaskFlowError> {
        if limit == 0 || limit > 1_024 {
            return Err(TaskFlowError::Invalid(
                "effect recovery scan limit".to_string(),
            ));
        }
        let rows = sqlx::query(
            "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id
              AND o.run_id = a.run_id
              AND o.step_id = a.step_id
              AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id
              AND r.run_id = a.run_id
              AND r.step_id = a.step_id
              AND r.attempt = a.attempt
             WHERE a.owner_agent_id = ?
               AND r.run_id IS NULL
               AND (o.run_id IS NULL OR o.observation = 'indeterminate')
             ORDER BY a.started_at_ms, a.run_id, a.step_id, a.attempt
             LIMIT ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(
            i64::try_from(limit)
                .map_err(|_| TaskFlowError::Invalid("effect recovery scan limit".to_string()))?,
        )
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        rows.into_iter().map(effect_attempt_from_row).collect()
    }

    pub(crate) async fn record_effect_dispatch_observation(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        kind: EffectDispatchObservationKind,
        evidence_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<EffectDispatchAttempt, TaskFlowError> {
        let current = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("effect dispatch attempt is missing".to_string())
            })?;

        if let Some(observation) = &current.observation {
            if observation.kind == kind && observation.evidence_digest == *evidence_digest {
                return Ok(current);
            }
            if observation.kind != EffectDispatchObservationKind::Indeterminate
                || kind == EffectDispatchObservationKind::Indeterminate
            {
                return Err(TaskFlowError::Conflict(
                    "effect observation is already terminal or bound to different bytes"
                        .to_string(),
                ));
            }

            let inserted = sqlx::query(
                "INSERT INTO taskflow_effect_dispatch_reconciliations (
                    owner_agent_id, run_id, step_id, attempt, observation,
                    evidence_digest, observed_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .bind(kind.as_str())
            .bind(evidence_digest.as_str())
            .bind(to_i64(observed_at_ms)?)
            .execute(self.taskflow_pool())
            .await;

            let refreshed = self
                .effect_dispatch_attempt(run_id, step_id, attempt)
                .await?
                .ok_or_else(|| {
                    TaskFlowError::Corrupt(
                        "effect dispatch attempt vanished during reconciliation".to_string(),
                    )
                })?;
            return match inserted {
                Ok(_) => Ok(refreshed),
                Err(error) if is_constraint(&error) => {
                    let Some(observation) = &refreshed.observation else {
                        return Err(TaskFlowError::Conflict(
                            "effect reconciliation conflicts with durable evidence".to_string(),
                        ));
                    };
                    if observation.kind != kind || observation.evidence_digest != *evidence_digest {
                        return Err(TaskFlowError::Conflict(
                            "effect reconciliation is already bound to different bytes".to_string(),
                        ));
                    }
                    Ok(refreshed)
                }
                Err(_) => Err(TaskFlowError::Unavailable),
            };
        }

        let inserted = sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_observations (
                owner_agent_id, run_id, step_id, attempt, observation,
                evidence_digest, observed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(kind.as_str())
        .bind(evidence_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .execute(self.taskflow_pool())
        .await;

        let refreshed = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Corrupt(
                    "effect dispatch attempt vanished after observation".to_string(),
                )
            })?;
        match inserted {
            Ok(_) => Ok(refreshed),
            Err(error) if is_constraint(&error) => {
                let Some(observation) = &refreshed.observation else {
                    return Err(TaskFlowError::Conflict(
                        "effect observation conflicts with durable evidence".to_string(),
                    ));
                };
                if observation.kind != kind || observation.evidence_digest != *evidence_digest {
                    return Err(TaskFlowError::Conflict(
                        "effect observation is already bound to different bytes".to_string(),
                    ));
                }
                Ok(refreshed)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }
}

fn effect_attempt_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<EffectDispatchAttempt, TaskFlowError> {
    let observation_kind: Option<String> = row
        .try_get("observation")
        .map_err(|_| TaskFlowError::Corrupt("effect observation column".to_string()))?;
    let evidence_digest: Option<String> = row
        .try_get("evidence_digest")
        .map_err(|_| TaskFlowError::Corrupt("effect evidence digest column".to_string()))?;
    let observed_at_ms: Option<i64> = row
        .try_get("observed_at_ms")
        .map_err(|_| TaskFlowError::Corrupt("effect observation timestamp column".to_string()))?;
    let observation = match (observation_kind, evidence_digest, observed_at_ms) {
        (None, None, None) => None,
        (Some(kind), Some(digest), Some(observed_at_ms)) => Some(EffectDispatchObservation {
            kind: EffectDispatchObservationKind::parse(&kind)?,
            evidence_digest: Sha256Digest::parse(digest)
                .map_err(|_| TaskFlowError::Corrupt("effect evidence digest".to_string()))?,
            observed_at_ms: to_u64(observed_at_ms)?,
        }),
        _ => {
            return Err(TaskFlowError::Corrupt(
                "partial effect dispatch observation".to_string(),
            ));
        }
    };
    Ok(EffectDispatchAttempt {
        run_id: row
            .try_get("run_id")
            .map_err(|_| TaskFlowError::Corrupt("effect run id".to_string()))?,
        step_id: row
            .try_get("step_id")
            .map_err(|_| TaskFlowError::Corrupt("effect step id".to_string()))?,
        attempt: u32::try_from(
            row.try_get::<i64, _>("attempt")
                .map_err(|_| TaskFlowError::Corrupt("effect attempt".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect attempt".to_string()))?,
        intent_digest: Sha256Digest::parse(
            row.try_get::<String, _>("intent_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect intent digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect intent digest".to_string()))?,
        payload_digest: Sha256Digest::parse(
            row.try_get::<String, _>("payload_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?,
        binding_digest: Sha256Digest::parse(
            row.try_get::<String, _>("binding_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect binding digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect binding digest".to_string()))?,
        destination_id: row
            .try_get("destination_id")
            .map_err(|_| TaskFlowError::Corrupt("effect destination".to_string()))?,
        authority_epoch: to_u64(
            row.try_get("authority_epoch")
                .map_err(|_| TaskFlowError::Corrupt("effect authority epoch".to_string()))?,
        )?,
        grant_id: row
            .try_get("grant_id")
            .map_err(|_| TaskFlowError::Corrupt("effect grant id".to_string()))?,
        grant_nonce_digest: Sha256Digest::parse(
            row.try_get::<String, _>("grant_nonce_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect grant nonce digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect grant nonce digest".to_string()))?,
        record_command_id: row
            .try_get("record_command_id")
            .map_err(|_| TaskFlowError::Corrupt("effect record command id".to_string()))?,
        started_at_ms: to_u64(
            row.try_get("started_at_ms")
                .map_err(|_| TaskFlowError::Corrupt("effect start timestamp".to_string()))?,
        )?,
        observation,
    })
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| TaskFlowError::Corrupt("negative effect integer".to_string()))
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| TaskFlowError::Invalid("effect integer overflow".to_string()))
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::*;
    use crate::TaskFlowDefinition;
    use crate::TaskFlowEdgeSpec;
    use crate::TaskFlowFence;
    use crate::TaskFlowNodeKind;
    use crate::TaskFlowNodeSpec;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    fn fixture() -> (tempfile::TempDir, codex_hepta_paths::HeptaAgentLayout) {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        (temp, layout)
    }

    async fn prepared_store() -> (
        tempfile::TempDir,
        codex_hepta_paths::HeptaAgentLayout,
        AutomationStore,
        TaskFlowFence,
    ) {
        let (temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("open store");
        let fence = TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            "effect-owner",
            1,
            1,
            "effect-fence-1",
        )
        .expect("fence");
        let definition = TaskFlowDefinition::new(
            "effect-recovery",
            1,
            "work",
            vec![
                TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("work", "success"),
                TaskFlowEdgeSpec::new("work", "failure"),
            ],
            Vec::new(),
            Sha256Digest::for_bytes(b"effect-policy"),
        )
        .expect("definition");
        store
            .register_taskflow_definition(&definition, &fence, 10)
            .await
            .expect("register definition");
        store
            .create_taskflow_run(
                "effect-run",
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "effect-thread",
                10,
            )
            .await
            .expect("create run");
        store
            .claim_taskflow_run("effect-run", &fence, 20, 10_000)
            .await
            .expect("claim run");
        (temp, layout, store, fence)
    }

    #[tokio::test]
    async fn indeterminate_provider_evidence_reconciles_after_reopen_without_redispatch() {
        let (_temp, layout, store, _fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let payload = Sha256Digest::for_bytes(b"effect-payload");
        let binding = Sha256Digest::for_bytes(b"effect-binding");
        let nonce = Sha256Digest::for_bytes(b"effect-nonce");
        let started = store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                1,
                &intent,
                &payload,
                &binding,
                "provider:test",
                7,
                "grant-1",
                &nonce,
                "record-effect",
                21,
            )
            .await
            .expect("begin attempt");
        assert!(matches!(started, EffectDispatchStart::Inserted(_)));

        let unknown = Sha256Digest::for_bytes(b"provider-unknown");
        let first = store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Indeterminate,
                &unknown,
                22,
            )
            .await
            .expect("record indeterminate");
        assert_eq!(
            first.observation.as_ref().map(|value| value.kind),
            Some(EffectDispatchObservationKind::Indeterminate)
        );
        assert_eq!(
            store
                .pending_effect_dispatch_attempts(10)
                .await
                .expect("pending")
                .len(),
            1
        );

        store.close().await;
        let reopened = AutomationStore::open(&layout).await.expect("reopen store");
        let pending = reopened
            .pending_effect_dispatch_attempts(10)
            .await
            .expect("pending after reopen");
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].grant_id, "grant-1");

        let terminal = Sha256Digest::for_bytes(b"provider-terminal");
        let settled = reopened
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                30,
            )
            .await
            .expect("terminal reconciliation");
        assert_eq!(
            settled.observation.as_ref().map(|value| value.kind),
            Some(EffectDispatchObservationKind::Succeeded)
        );
        assert_eq!(
            settled
                .observation
                .as_ref()
                .map(|value| value.evidence_digest.clone()),
            Some(terminal.clone())
        );
        assert!(
            reopened
                .pending_effect_dispatch_attempts(10)
                .await
                .expect("no pending after terminal")
                .is_empty()
        );

        let replay = reopened
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                31,
            )
            .await
            .expect("terminal replay");
        assert_eq!(replay.observation, settled.observation);
        assert!(matches!(
            reopened
                .record_effect_dispatch_observation(
                    "effect-run",
                    "work",
                    1,
                    EffectDispatchObservationKind::Failed,
                    &Sha256Digest::for_bytes(b"different-terminal"),
                    32,
                )
                .await,
            Err(TaskFlowError::Conflict(_))
        ));
        reopened.close().await;
    }
}
