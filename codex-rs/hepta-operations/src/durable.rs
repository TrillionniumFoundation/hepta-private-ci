use std::fmt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Acquire;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::OperationError;
use crate::OperationKey;
use crate::OperationRecord;
use crate::OperationState;
use crate::OutboxIntent;
use crate::ReconciliationOutcome;

const OPERATIONS_DB_FILENAME: &str = "hepta_operations_1.sqlite";
const MAX_DURABLE_RECORDS: i64 = 16_384;
const MAX_OUTBOX_LEASE_MS: u64 = 300_000;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Debug)]
pub enum DurableOperationError {
    Operation(OperationError),
    Invalid(String),
    Unavailable(String),
    Corrupt(String),
}

impl fmt::Display for DurableOperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Operation(error) => error.fmt(formatter),
            Self::Invalid(message) => write!(formatter, "invalid durable operation input: {message}"),
            Self::Unavailable(message) => {
                write!(formatter, "durable operation store unavailable: {message}")
            }
            Self::Corrupt(message) => write!(formatter, "durable operation store corrupt: {message}"),
        }
    }
}

impl std::error::Error for DurableOperationError {}

impl From<OperationError> for DurableOperationError {
    fn from(value: OperationError) -> Self {
        Self::Operation(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Pending,
    Claimed {
        owner_id: StableId,
        owner_generation: Generation,
        lease_expires_at_ms: u64,
    },
    Acknowledged {
        owner_id: StableId,
        owner_generation: Generation,
        acknowledgement_digest: Digest32,
    },
}

#[derive(Clone, Debug)]
pub struct DurableOperationStore {
    pool: SqlitePool,
    path: PathBuf,
}

impl DurableOperationStore {
    pub async fn open(root: &Path) -> Result<Self, DurableOperationError> {
        tokio::fs::create_dir_all(root).await.map_err(unavailable)?;
        let home = AbsolutePathBuf::try_from(root.to_path_buf())
            .map_err(|error| DurableOperationError::Invalid(error.to_string()))?;
        let path = root.join(OPERATIONS_DB_FILENAME);
        let pool = SqliteConfig::from_sqlite_home(home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(DurableOperationError::Unavailable(error.to_string()));
        }
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn begin(
        &self,
        key: OperationKey,
        owner_generation: Generation,
    ) -> Result<OperationRecord, DurableOperationError> {
        if key.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation payload").into());
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some(existing) = load_operation_tx(&mut transaction, &key.id).await? {
            if existing.key == key && existing.owner_generation == owner_generation {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(existing);
            }
            return Err(OperationError::Conflict(key.id).into());
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operation_records")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_DURABLE_RECORDS {
            return Err(OperationError::CapacityExceeded {
                resource: "durable operation ledger",
                maximum: MAX_DURABLE_RECORDS as usize,
            }
            .into());
        }
        let record = OperationRecord {
            key,
            owner_generation,
            revision: Revision::new(1).map_err(invalid)?,
            state: OperationState::Pending,
        };
        insert_operation_tx(&mut transaction, &record).await?;
        append_operation_event_tx(&mut transaction, &record).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn record_authorized(
        &self,
        operation_id: &StableId,
        authorization_digest: Digest32,
        authority_generation: Generation,
    ) -> Result<OperationRecord, DurableOperationError> {
        if authorization_digest.is_zero() {
            return Err(OperationError::InvalidDigest("authorization").into());
        }
        self.transition(operation_id, |record| match &record.state {
            OperationState::Pending => Ok(OperationState::Authorized {
                witness_digest: authorization_digest,
                authority_generation,
            }),
            OperationState::Authorized {
                witness_digest,
                authority_generation: existing,
            } if *witness_digest == authorization_digest && *existing == authority_generation => {
                Ok(record.state.clone())
            }
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => Err(OperationError::InvalidTransition {
                from: state.label(),
                to: "authorized",
            }),
        })
        .await
    }

    pub async fn record_dispatch(
        &self,
        operation_id: &StableId,
        dispatch_digest: Digest32,
    ) -> Result<OperationRecord, DurableOperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch").into());
        }
        self.transition(operation_id, |record| match &record.state {
            OperationState::Authorized { .. } => {
                Ok(OperationState::Dispatched { dispatch_digest })
            }
            OperationState::Dispatched {
                dispatch_digest: existing,
            } if *existing == dispatch_digest => Ok(record.state.clone()),
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => Err(OperationError::InvalidTransition {
                from: state.label(),
                to: "dispatched",
            }),
        })
        .await
    }

    pub async fn mark_indeterminate(
        &self,
        operation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<OperationRecord, DurableOperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason").into());
        }
        self.transition(operation_id, |record| match &record.state {
            OperationState::Dispatched { .. } => {
                Ok(OperationState::Indeterminate { reason_digest })
            }
            OperationState::Indeterminate {
                reason_digest: existing,
            } if *existing == reason_digest => Ok(record.state.clone()),
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => Err(OperationError::InvalidTransition {
                from: state.label(),
                to: "indeterminate",
            }),
        })
        .await
    }

    pub async fn observe_terminal(
        &self,
        operation_id: &StableId,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
        observer_generation: Generation,
    ) -> Result<OperationRecord, DurableOperationError> {
        if outcome_digest.is_zero() {
            return Err(OperationError::InvalidDigest("terminal outcome").into());
        }
        self.transition(operation_id, |record| {
            if record.owner_generation != observer_generation {
                return Err(OperationError::StaleGeneration);
            }
            let target = terminal_state(outcome, outcome_digest);
            if record.state == target {
                return Ok(record.state.clone());
            }
            match &record.state {
                OperationState::Dispatched { .. } | OperationState::Indeterminate { .. } => {
                    Ok(target)
                }
                state if state.is_terminal() => Err(OperationError::Terminal),
                state => Err(OperationError::InvalidTransition {
                    from: state.label(),
                    to: "terminal_observation",
                }),
            }
        })
        .await
    }

    pub async fn get(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<OperationRecord>, DurableOperationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let record = load_operation_tx(&mut transaction, operation_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    async fn transition(
        &self,
        operation_id: &StableId,
        next: impl FnOnce(&OperationRecord) -> Result<OperationState, OperationError>,
    ) -> Result<OperationRecord, DurableOperationError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let mut record = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        let state = next(&record)?;
        if state == record.state {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(record);
        }
        record.revision = record
            .revision
            .next()
            .map_err(|_| OperationError::Conflict(operation_id.clone()))?;
        record.state = state;
        update_operation_tx(&mut transaction, &record).await?;
        append_operation_event_tx(&mut transaction, &record).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(record)
    }

    pub async fn enqueue_outbox(
        &self,
        intent: &OutboxIntent,
    ) -> Result<(), DurableOperationError> {
        if intent.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox payload").into());
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some((existing, _)) = load_outbox_tx(&mut transaction, &intent.intent_id).await? {
            if existing == *intent {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(OperationError::Conflict(intent.intent_id.clone()).into());
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operation_outbox")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_DURABLE_RECORDS {
            return Err(OperationError::CapacityExceeded {
                resource: "durable operation outbox",
                maximum: MAX_DURABLE_RECORDS as usize,
            }
            .into());
        }
        sqlx::query(
            "INSERT INTO operation_outbox
             (intent_id, operation_id, destination, payload_digest, state, revision)
             VALUES (?, ?, ?, ?, 'pending', 1)",
        )
        .bind(intent.intent_id.as_str())
        .bind(intent.operation_id.as_str())
        .bind(intent.destination.as_str())
        .bind(intent.payload_digest.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        append_outbox_event_tx(
            &mut transaction,
            intent,
            &DurableOutboxState::Pending,
            1,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(())
    }

    pub async fn claim_outbox(
        &self,
        intent_id: &StableId,
        owner_id: StableId,
        owner_generation: Generation,
        now_ms: u64,
        lease_ms: u64,
    ) -> Result<OutboxIntent, DurableOperationError> {
        if lease_ms == 0 || lease_ms > MAX_OUTBOX_LEASE_MS {
            return Err(DurableOperationError::Invalid(
                "outbox lease must be 1..=300000 ms".to_string(),
            ));
        }
        let expires = now_ms
            .checked_add(lease_ms)
            .ok_or_else(|| DurableOperationError::Invalid("outbox lease overflow".to_string()))?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let (intent, state) = load_outbox_tx(&mut transaction, intent_id)
            .await?
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        match state {
            DurableOutboxState::Acknowledged { .. } => {
                return Err(OperationError::Terminal.into());
            }
            DurableOutboxState::Claimed {
                owner_id: ref existing_owner,
                owner_generation: existing_generation,
                lease_expires_at_ms,
            } if lease_expires_at_ms > now_ms
                && (*existing_owner != owner_id || existing_generation != owner_generation) =>
            {
                return Err(OperationError::StaleGeneration.into());
            }
            _ => {}
        }
        let revision: i64 =
            sqlx::query_scalar("SELECT revision FROM operation_outbox WHERE intent_id = ?")
                .bind(intent_id.as_str())
                .fetch_one(&mut *transaction)
                .await
                .map_err(unavailable)?;
        let next_revision = revision
            .checked_add(1)
            .ok_or_else(|| DurableOperationError::Corrupt("outbox revision overflow".to_string()))?;
        sqlx::query(
            "UPDATE operation_outbox
             SET state='claimed', claim_owner=?, claim_generation=?,
                 lease_expires_at_ms=?, acknowledgement_digest=NULL, revision=?
             WHERE intent_id=?",
        )
        .bind(owner_id.as_str())
        .bind(to_i64(owner_generation.get(), "owner generation")?)
        .bind(to_i64(expires, "lease expiry")?)
        .bind(next_revision)
        .bind(intent_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let next_state = DurableOutboxState::Claimed {
            owner_id,
            owner_generation,
            lease_expires_at_ms: expires,
        };
        append_outbox_event_tx(&mut transaction, &intent, &next_state, next_revision).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(intent)
    }

    pub async fn acknowledge_outbox(
        &self,
        intent_id: &StableId,
        owner_id: &StableId,
        owner_generation: Generation,
        acknowledgement_digest: Digest32,
        now_ms: u64,
    ) -> Result<(), DurableOperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox acknowledgement").into());
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let (intent, state) = load_outbox_tx(&mut transaction, intent_id)
            .await?
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        if let DurableOutboxState::Acknowledged {
            owner_id: existing_owner,
            owner_generation: existing_generation,
            acknowledgement_digest: existing_digest,
        } = &state
        {
            if existing_owner == owner_id
                && *existing_generation == owner_generation
                && *existing_digest == acknowledgement_digest
            {
                transaction.commit().await.map_err(unavailable)?;
                return Ok(());
            }
            return Err(OperationError::Conflict(intent_id.clone()).into());
        }
        match state {
            DurableOutboxState::Claimed {
                owner_id: existing_owner,
                owner_generation: existing_generation,
                lease_expires_at_ms,
            } if existing_owner == *owner_id
                && existing_generation == owner_generation
                && lease_expires_at_ms > now_ms => {}
            DurableOutboxState::Claimed { .. } => {
                return Err(OperationError::StaleGeneration.into());
            }
            DurableOutboxState::Pending => return Err(OperationError::NotClaimed.into()),
            DurableOutboxState::Acknowledged { .. } => unreachable!(),
        }
        let revision: i64 =
            sqlx::query_scalar("SELECT revision FROM operation_outbox WHERE intent_id = ?")
                .bind(intent_id.as_str())
                .fetch_one(&mut *transaction)
                .await
                .map_err(unavailable)?;
        let next_revision = revision
            .checked_add(1)
            .ok_or_else(|| DurableOperationError::Corrupt("outbox revision overflow".to_string()))?;
        sqlx::query(
            "UPDATE operation_outbox
             SET state='acknowledged', acknowledgement_digest=?,
                 lease_expires_at_ms=NULL, revision=?
             WHERE intent_id=?",
        )
        .bind(acknowledgement_digest.to_string())
        .bind(next_revision)
        .bind(intent_id.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let next_state = DurableOutboxState::Acknowledged {
            owner_id: owner_id.clone(),
            owner_generation,
            acknowledgement_digest,
        };
        append_outbox_event_tx(&mut transaction, &intent, &next_state, next_revision).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(())
    }

    pub async fn outbox_state(
        &self,
        intent_id: &StableId,
    ) -> Result<Option<DurableOutboxState>, DurableOperationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let result = load_outbox_tx(&mut transaction, intent_id)
            .await?
            .map(|(_, state)| state);
        transaction.commit().await.map_err(unavailable)?;
        Ok(result)
    }
}

async fn insert_operation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OperationRecord,
) -> Result<(), DurableOperationError> {
    let fields = state_fields(&record.state)?;
    sqlx::query(
        "INSERT INTO operation_records
         (operation_id,payload_digest,owner_generation,revision,state,
          authorization_digest,authority_generation,dispatch_digest,reason_digest,outcome_digest)
         VALUES (?,?,?,?,?,?,?,?,?,?)",
    )
    .bind(record.key.id.as_str())
    .bind(record.key.payload_digest.to_string())
    .bind(to_i64(record.owner_generation.get(), "owner generation")?)
    .bind(to_i64(record.revision.get(), "revision")?)
    .bind(record.state.label())
    .bind(fields.0)
    .bind(fields.1)
    .bind(fields.2)
    .bind(fields.3)
    .bind(fields.4)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn update_operation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OperationRecord,
) -> Result<(), DurableOperationError> {
    let fields = state_fields(&record.state)?;
    let changed = sqlx::query(
        "UPDATE operation_records
         SET revision=?,state=?,authorization_digest=?,authority_generation=?,
             dispatch_digest=?,reason_digest=?,outcome_digest=?
         WHERE operation_id=? AND payload_digest=? AND owner_generation=?",
    )
    .bind(to_i64(record.revision.get(), "revision")?)
    .bind(record.state.label())
    .bind(fields.0)
    .bind(fields.1)
    .bind(fields.2)
    .bind(fields.3)
    .bind(fields.4)
    .bind(record.key.id.as_str())
    .bind(record.key.payload_digest.to_string())
    .bind(to_i64(record.owner_generation.get(), "owner generation")?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if changed.rows_affected() != 1 {
        return Err(DurableOperationError::Corrupt(
            "operation row changed identity while locked".to_string(),
        ));
    }
    Ok(())
}

async fn append_operation_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    record: &OperationRecord,
) -> Result<(), DurableOperationError> {
    let fields = state_fields(&record.state)?;
    sqlx::query(
        "INSERT INTO operation_events
         (operation_id,revision,state,authorization_digest,authority_generation,
          dispatch_digest,reason_digest,outcome_digest)
         VALUES (?,?,?,?,?,?,?,?)",
    )
    .bind(record.key.id.as_str())
    .bind(to_i64(record.revision.get(), "revision")?)
    .bind(record.state.label())
    .bind(fields.0)
    .bind(fields.1)
    .bind(fields.2)
    .bind(fields.3)
    .bind(fields.4)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn state_fields(
    state: &OperationState,
) -> Result<
    (
        Option<String>,
        Option<i64>,
        Option<String>,
        Option<String>,
        Option<String>,
    ),
    DurableOperationError,
> {
    match state {
        OperationState::Pending => Ok((None, None, None, None, None)),
        OperationState::Authorized {
            witness_digest,
            authority_generation,
        } => Ok((
            Some(witness_digest.to_string()),
            Some(to_i64(
                authority_generation.get(),
                "authority generation",
            )?),
            None,
            None,
            None,
        )),
        OperationState::Dispatched { dispatch_digest } => {
            Ok((None, None, Some(dispatch_digest.to_string()), None, None))
        }
        OperationState::Indeterminate { reason_digest } => {
            Ok((None, None, None, Some(reason_digest.to_string()), None))
        }
        OperationState::Applied { outcome_digest }
        | OperationState::NotApplied { outcome_digest } => {
            Ok((None, None, None, None, Some(outcome_digest.to_string())))
        }
        OperationState::Quarantined { reason_digest } => {
            Ok((None, None, None, Some(reason_digest.to_string()), None))
        }
    }
}

async fn load_operation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &StableId,
) -> Result<Option<OperationRecord>, DurableOperationError> {
    let row = sqlx::query(
        "SELECT operation_id,payload_digest,owner_generation,revision,state,
                authorization_digest,authority_generation,dispatch_digest,
                reason_digest,outcome_digest
         FROM operation_records WHERE operation_id=?",
    )
    .bind(operation_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    row.map(decode_operation_row).transpose()
}

fn decode_operation_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<OperationRecord, DurableOperationError> {
    let operation_id =
        StableId::new(row.try_get::<String, _>("operation_id").map_err(unavailable)?)
            .map_err(invalid)?;
    let payload_digest = parse_digest(
        &row.try_get::<String, _>("payload_digest")
            .map_err(unavailable)?,
        "payload",
    )?;
    let owner_generation = generation(
        row.try_get::<i64, _>("owner_generation")
            .map_err(unavailable)?,
        "owner generation",
    )?;
    let revision = revision(
        row.try_get::<i64, _>("revision").map_err(unavailable)?,
    )?;
    let state_name: String = row.try_get("state").map_err(unavailable)?;
    let authorization: Option<String> =
        row.try_get("authorization_digest").map_err(unavailable)?;
    let authority_generation: Option<i64> =
        row.try_get("authority_generation").map_err(unavailable)?;
    let dispatch: Option<String> = row.try_get("dispatch_digest").map_err(unavailable)?;
    let reason: Option<String> = row.try_get("reason_digest").map_err(unavailable)?;
    let outcome: Option<String> = row.try_get("outcome_digest").map_err(unavailable)?;
    let state = match state_name.as_str() {
        "pending" => OperationState::Pending,
        "authorized" => OperationState::Authorized {
            witness_digest: parse_digest(
                authorization
                    .as_deref()
                    .ok_or_else(|| corrupt("authorized row missing digest"))?,
                "authorization",
            )?,
            authority_generation: generation(
                authority_generation
                    .ok_or_else(|| corrupt("authorized row missing generation"))?,
                "authority generation",
            )?,
        },
        "dispatched" => OperationState::Dispatched {
            dispatch_digest: parse_digest(
                dispatch
                    .as_deref()
                    .ok_or_else(|| corrupt("dispatched row missing digest"))?,
                "dispatch",
            )?,
        },
        "indeterminate" => OperationState::Indeterminate {
            reason_digest: parse_digest(
                reason
                    .as_deref()
                    .ok_or_else(|| corrupt("indeterminate row missing reason"))?,
                "reason",
            )?,
        },
        "applied" => OperationState::Applied {
            outcome_digest: parse_digest(
                outcome
                    .as_deref()
                    .ok_or_else(|| corrupt("applied row missing outcome"))?,
                "outcome",
            )?,
        },
        "not_applied" => OperationState::NotApplied {
            outcome_digest: parse_digest(
                outcome
                    .as_deref()
                    .ok_or_else(|| corrupt("not_applied row missing outcome"))?,
                "outcome",
            )?,
        },
        "quarantined" => OperationState::Quarantined {
            reason_digest: parse_digest(
                reason
                    .as_deref()
                    .ok_or_else(|| corrupt("quarantined row missing reason"))?,
                "reason",
            )?,
        },
        _ => return Err(corrupt("unknown operation state")),
    };
    Ok(OperationRecord {
        key: OperationKey {
            id: operation_id,
            payload_digest,
        },
        owner_generation,
        revision,
        state,
    })
}

async fn load_outbox_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    intent_id: &StableId,
) -> Result<Option<(OutboxIntent, DurableOutboxState)>, DurableOperationError> {
    let row = sqlx::query(
        "SELECT intent_id,operation_id,destination,payload_digest,state,
                claim_owner,claim_generation,lease_expires_at_ms,acknowledgement_digest
         FROM operation_outbox WHERE intent_id=?",
    )
    .bind(intent_id.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let intent = OutboxIntent {
        intent_id: StableId::new(row.try_get::<String, _>("intent_id").map_err(unavailable)?)
            .map_err(invalid)?,
        operation_id: StableId::new(
            row.try_get::<String, _>("operation_id")
                .map_err(unavailable)?,
        )
        .map_err(invalid)?,
        destination: StableId::new(
            row.try_get::<String, _>("destination")
                .map_err(unavailable)?,
        )
        .map_err(invalid)?,
        payload_digest: parse_digest(
            &row.try_get::<String, _>("payload_digest")
                .map_err(unavailable)?,
            "outbox payload",
        )?,
    };
    let state_name: String = row.try_get("state").map_err(unavailable)?;
    let owner: Option<String> = row.try_get("claim_owner").map_err(unavailable)?;
    let generation_value: Option<i64> =
        row.try_get("claim_generation").map_err(unavailable)?;
    let expiry: Option<i64> = row.try_get("lease_expires_at_ms").map_err(unavailable)?;
    let acknowledgement: Option<String> =
        row.try_get("acknowledgement_digest").map_err(unavailable)?;
    let state = match state_name.as_str() {
        "pending" => DurableOutboxState::Pending,
        "claimed" => DurableOutboxState::Claimed {
            owner_id: StableId::new(
                owner.ok_or_else(|| corrupt("claimed outbox missing owner"))?,
            )
            .map_err(invalid)?,
            owner_generation: generation(
                generation_value
                    .ok_or_else(|| corrupt("claimed outbox missing generation"))?,
                "claim generation",
            )?,
            lease_expires_at_ms: u64_from_i64(
                expiry.ok_or_else(|| corrupt("claimed outbox missing expiry"))?,
                "claim expiry",
            )?,
        },
        "acknowledged" => DurableOutboxState::Acknowledged {
            owner_id: StableId::new(
                owner.ok_or_else(|| corrupt("acknowledged outbox missing owner"))?,
            )
            .map_err(invalid)?,
            owner_generation: generation(
                generation_value
                    .ok_or_else(|| corrupt("acknowledged outbox missing generation"))?,
                "claim generation",
            )?,
            acknowledgement_digest: parse_digest(
                acknowledgement
                    .as_deref()
                    .ok_or_else(|| corrupt("acknowledged outbox missing digest"))?,
                "acknowledgement",
            )?,
        },
        _ => return Err(corrupt("unknown outbox state")),
    };
    Ok(Some((intent, state)))
}

async fn append_outbox_event_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &OutboxIntent,
    state: &DurableOutboxState,
    revision: i64,
) -> Result<(), DurableOperationError> {
    let (label, owner, generation_value, expiry, acknowledgement) = match state {
        DurableOutboxState::Pending => ("pending", None, None, None, None),
        DurableOutboxState::Claimed {
            owner_id,
            owner_generation,
            lease_expires_at_ms,
        } => (
            "claimed",
            Some(owner_id.as_str().to_string()),
            Some(to_i64(owner_generation.get(), "claim generation")?),
            Some(to_i64(*lease_expires_at_ms, "claim expiry")?),
            None,
        ),
        DurableOutboxState::Acknowledged {
            owner_id,
            owner_generation,
            acknowledgement_digest,
        } => (
            "acknowledged",
            Some(owner_id.as_str().to_string()),
            Some(to_i64(owner_generation.get(), "claim generation")?),
            None,
            Some(acknowledgement_digest.to_string()),
        ),
    };
    sqlx::query(
        "INSERT INTO operation_outbox_events
         (intent_id,revision,state,claim_owner,claim_generation,
          lease_expires_at_ms,acknowledgement_digest)
         VALUES (?,?,?,?,?,?,?)",
    )
    .bind(intent.intent_id.as_str())
    .bind(revision)
    .bind(label)
    .bind(owner)
    .bind(generation_value)
    .bind(expiry)
    .bind(acknowledgement)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn verify_store(pool: &SqlitePool) -> Result<(), DurableOperationError> {
    let quick: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(pool)
        .await
        .map_err(unavailable)?;
    if quick != "ok" {
        return Err(corrupt("SQLite quick_check failed"));
    }
    let foreign_keys: Vec<sqlx::sqlite::SqliteRow> = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if !foreign_keys.is_empty() {
        return Err(corrupt("SQLite foreign_key_check failed"));
    }
    let migrations = sqlx::query(
        "SELECT version,description,success,checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if migrations.len() != MIGRATOR.migrations.len() {
        return Err(corrupt("migration ledger does not match current lineage"));
    }
    for (row, migration) in migrations.iter().zip(MIGRATOR.migrations.iter()) {
        let version: i64 = row.try_get("version").map_err(unavailable)?;
        let description: String = row.try_get("description").map_err(unavailable)?;
        let success: bool = row.try_get("success").map_err(unavailable)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(unavailable)?;
        if version != migration.version
            || description != migration.description.as_ref()
            || !success
            || checksum.as_slice() != migration.checksum.as_ref()
        {
            return Err(corrupt(
                "migration ledger entry differs from current lineage",
            ));
        }
    }
    let bad_operation_projection: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_records AS current
         LEFT JOIN operation_events AS event
           ON event.operation_id = current.operation_id
          AND event.revision = current.revision
          AND event.state = current.state
         WHERE event.seq IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if bad_operation_projection != 0 {
        return Err(corrupt(
            "operation projection is not backed by its immutable event",
        ));
    }
    let bad_outbox_projection: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_outbox AS current
         LEFT JOIN operation_outbox_events AS event
           ON event.intent_id = current.intent_id
          AND event.revision = current.revision
          AND event.state = current.state
         WHERE event.seq IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if bad_outbox_projection != 0 {
        return Err(corrupt(
            "outbox projection is not backed by its immutable event",
        ));
    }
    let bad_operation_history: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_records AS current
         WHERE (SELECT COUNT(*) FROM operation_events AS event
                WHERE event.operation_id = current.operation_id) != current.revision",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if bad_operation_history != 0 {
        return Err(corrupt("operation event history is incomplete"));
    }
    let bad_outbox_history: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM operation_outbox AS current
         WHERE (SELECT COUNT(*) FROM operation_outbox_events AS event
                WHERE event.intent_id = current.intent_id) != current.revision",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if bad_outbox_history != 0 {
        return Err(corrupt("outbox event history is incomplete"));
    }
    let immutable_trigger_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema
         WHERE type='trigger' AND name IN (
           'operation_events_no_update',
           'operation_events_no_delete',
           'operation_outbox_events_no_update',
           'operation_outbox_events_no_delete'
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if immutable_trigger_count != 4 {
        return Err(corrupt("immutable event triggers are missing"));
    }
    Ok(())
}

fn terminal_state(outcome: ReconciliationOutcome, digest: Digest32) -> OperationState {
    match outcome {
        ReconciliationOutcome::Applied => OperationState::Applied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::NotApplied => OperationState::NotApplied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::Quarantined => OperationState::Quarantined {
            reason_digest: digest,
        },
    }
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, DurableOperationError> {
    let digest = Digest32::from_str(value)
        .map_err(|error| corrupt(&format!("invalid {label} digest: {error}")))?;
    if digest.is_zero() {
        return Err(corrupt(&format!("zero {label} digest")));
    }
    Ok(digest)
}

fn generation(value: i64, label: &str) -> Result<Generation, DurableOperationError> {
    Generation::new(u64_from_i64(value, label)?).map_err(invalid)
}

fn revision(value: i64) -> Result<Revision, DurableOperationError> {
    Revision::new(u64_from_i64(value, "revision")?).map_err(invalid)
}

fn u64_from_i64(value: i64, label: &str) -> Result<u64, DurableOperationError> {
    u64::try_from(value).map_err(|_| corrupt(&format!("negative {label}")))
}

fn to_i64(value: u64, label: &str) -> Result<i64, DurableOperationError> {
    i64::try_from(value).map_err(|_| {
        DurableOperationError::Invalid(format!(
            "{label} exceeds SQLite signed integer range"
        ))
    })
}

fn unavailable(error: impl fmt::Display) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

fn invalid(error: impl fmt::Display) -> DurableOperationError {
    DurableOperationError::Invalid(error.to_string())
}

fn corrupt(message: &str) -> DurableOperationError {
    DurableOperationError::Corrupt(message.to_string())
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
