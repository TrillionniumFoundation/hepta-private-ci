//! Qualification-only H7 trajectory/evaluation/artifact lifecycle coverage.
//!
//! This file is compiled only for tests. It uses a private SQLite file to
//! exercise durable local state without adding a production H7 runtime API.
//! The state machine is deliberately shadow-only: it never invokes a provider,
//! writes KG or memory state, sends a channel message, or grants authority.

use std::path::Path;

use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use tempfile::TempDir;

const EVALUATION_SCHEMA: &str = "hepta_h7_shadow_evaluation_v1";
const ARTIFACT_SCHEMA: &str = "hepta_h7_shadow_artifact_v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct TrajectoryEvent {
    trajectory_id: String,
    event_seq: u32,
    outcome: String,
    reward_bps: i32,
    safety_ok: bool,
    external_effect_executed: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Evaluation {
    schema: String,
    trajectory_digest: String,
    sample_count: u32,
    candidate_reward_bps: i32,
    safety_floor_met: bool,
    replay_only: bool,
    production_effects: bool,
    evaluation_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Artifact {
    schema: String,
    artifact_id: String,
    trajectory_digest: String,
    evaluation_digest: String,
    generation: u64,
    phase: String,
    authority: String,
    production_authority: bool,
    external_effects: bool,
    body_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RuntimeState {
    runtime_generation: u64,
    active_artifact_id: Option<String>,
    active_artifact_digest: Option<String>,
    active_artifact_generation: u64,
    previous_artifact_digest: Option<String>,
    last_transition: String,
    rollback_from_generation: Option<u64>,
}

#[derive(Debug, thiserror::Error)]
enum LifecycleError {
    #[error("artifact is not approved for qualification reload")]
    UnapprovedArtifact,
    #[error("artifact body digest does not match its stored digest")]
    ArtifactDigestMismatch,
    #[error("evaluation digest does not match its stored digest")]
    EvaluationDigestMismatch,
    #[error("runtime generation fence mismatch")]
    GenerationFence { expected: u64, actual: u64 },
    #[error("artifact generation is not newer than active generation")]
    NonMonotonicReload { artifact: u64, active: u64 },
    #[error("rollback target is not older than active generation")]
    InvalidRollback { target: u64, active: u64 },
    #[error("artifact is missing")]
    MissingArtifact,
    #[error("invalid persisted qualification state: {0}")]
    InvalidState(String),
    #[error("SQLite qualification store failed: {0}")]
    Sqlite(#[from] sqlx::Error),
    #[error("JSON qualification record failed: {0}")]
    Json(#[from] serde_json::Error),
}

impl PartialEq for LifecycleError {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::UnapprovedArtifact, Self::UnapprovedArtifact)
            | (Self::ArtifactDigestMismatch, Self::ArtifactDigestMismatch)
            | (Self::EvaluationDigestMismatch, Self::EvaluationDigestMismatch)
            | (Self::MissingArtifact, Self::MissingArtifact) => true,
            (
                Self::GenerationFence {
                    expected: left_expected,
                    actual: left_actual,
                },
                Self::GenerationFence {
                    expected: right_expected,
                    actual: right_actual,
                },
            ) => left_expected == right_expected && left_actual == right_actual,
            (
                Self::NonMonotonicReload {
                    artifact: left_artifact,
                    active: left_active,
                },
                Self::NonMonotonicReload {
                    artifact: right_artifact,
                    active: right_active,
                },
            ) => left_artifact == right_artifact && left_active == right_active,
            (
                Self::InvalidRollback {
                    target: left_target,
                    active: left_active,
                },
                Self::InvalidRollback {
                    target: right_target,
                    active: right_active,
                },
            ) => left_target == right_target && left_active == right_active,
            (Self::InvalidState(left), Self::InvalidState(right)) => left == right,
            (Self::Sqlite(_), Self::Sqlite(_)) | (Self::Json(_), Self::Json(_)) => false,
            _ => false,
        }
    }
}

impl Eq for LifecycleError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Transition {
    Reload,
    Rollback,
}

impl Transition {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Reload => "reload",
            Self::Rollback => "rollback",
        }
    }
}

fn bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, serde_json::Error> {
    serde_json::to_vec(value)
}

fn digest_bytes(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

fn digest<T: Serialize>(value: &T) -> Result<String, serde_json::Error> {
    Ok(digest_bytes(&bytes(value)?))
}

#[expect(
    clippy::disallowed_methods,
    reason = "qualification-only test uses a private SQLite fixture, never production state"
)]
async fn open_store(root: &Path) -> Result<SqlitePool, LifecycleError> {
    let options = SqliteConnectOptions::new()
        .filename(root.join("h7-qualification.sqlite3"))
        .create_if_missing(true);
    Ok(SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await?)
}

async fn create_schema(pool: &SqlitePool) -> Result<(), LifecycleError> {
    for statement in [
        "CREATE TABLE trajectory_events (
            trajectory_id TEXT NOT NULL,
            event_seq INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            PRIMARY KEY (trajectory_id, event_seq)
        )",
        "CREATE TRIGGER trajectory_events_no_update
         BEFORE UPDATE ON trajectory_events
         BEGIN SELECT RAISE(ABORT, 'trajectory is immutable'); END",
        "CREATE TRIGGER trajectory_events_no_delete
         BEFORE DELETE ON trajectory_events
         BEGIN SELECT RAISE(ABORT, 'trajectory is immutable'); END",
        "CREATE TABLE evaluations (
            trajectory_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL
        )",
        "CREATE TABLE artifacts (
            artifact_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            body_digest TEXT NOT NULL
        )",
        "CREATE TABLE artifact_approvals (
            artifact_id TEXT PRIMARY KEY,
            body_digest TEXT NOT NULL,
            approved INTEGER NOT NULL CHECK (approved = 1),
            qualification_only INTEGER NOT NULL CHECK (qualification_only = 1),
            production_authority INTEGER NOT NULL CHECK (production_authority = 0),
            external_effects INTEGER NOT NULL CHECK (external_effects = 0)
        )",
        "CREATE TABLE runtime_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            runtime_generation INTEGER NOT NULL,
            active_artifact_id TEXT,
            active_artifact_digest TEXT,
            active_artifact_generation INTEGER NOT NULL,
            previous_artifact_digest TEXT,
            last_transition TEXT NOT NULL,
            rollback_from_generation INTEGER
        )",
    ] {
        sqlx::query(statement).execute(pool).await?;
    }
    sqlx::query(
        "INSERT INTO runtime_state
         (singleton, runtime_generation, active_artifact_generation, last_transition)
         VALUES (1, 0, 0, 'cold')",
    )
    .execute(pool)
    .await?;
    Ok(())
}

async fn append_trajectory(
    pool: &SqlitePool,
    events: &[TrajectoryEvent],
) -> Result<String, LifecycleError> {
    if events.is_empty() {
        return Err(LifecycleError::InvalidState(
            "trajectory must contain an event".to_string(),
        ));
    }
    let trajectory_id = &events[0].trajectory_id;
    for (index, event) in events.iter().enumerate() {
        let expected_seq = u32::try_from(index + 1)
            .map_err(|_| LifecycleError::InvalidState("sequence overflow".to_string()))?;
        if event.trajectory_id != *trajectory_id
            || event.event_seq != expected_seq
            || event.external_effect_executed
        {
            return Err(LifecycleError::InvalidState(
                "trajectory is not contiguous or contains an external effect".to_string(),
            ));
        }
    }
    for event in events {
        let payload = bytes(event)?;
        let payload = String::from_utf8(payload.clone())
            .map_err(|error| LifecycleError::InvalidState(error.to_string()))?;
        sqlx::query(
            "INSERT INTO trajectory_events
             (trajectory_id, event_seq, payload_json, payload_digest)
             VALUES (?, ?, ?, ?)",
        )
        .bind(&event.trajectory_id)
        .bind(i64::from(event.event_seq))
        .bind(payload.as_str())
        .bind(digest_bytes(payload.as_bytes()))
        .execute(pool)
        .await?;
    }
    let mut snapshot = Vec::new();
    for event in events {
        snapshot.extend(bytes(event)?);
        snapshot.push(b'\n');
    }
    Ok(digest_bytes(&snapshot))
}

async fn evaluate_trajectory(
    pool: &SqlitePool,
    trajectory_id: &str,
    trajectory_digest: &str,
) -> Result<Evaluation, LifecycleError> {
    let rows = sqlx::query(
        "SELECT payload_json, payload_digest FROM trajectory_events
         WHERE trajectory_id = ? ORDER BY event_seq",
    )
    .bind(trajectory_id)
    .fetch_all(pool)
    .await?;
    if rows.is_empty() {
        return Err(LifecycleError::InvalidState(
            "cannot evaluate an empty trajectory".to_string(),
        ));
    }
    let mut events = Vec::with_capacity(rows.len());
    for row in rows {
        let payload: String = row.try_get("payload_json")?;
        let stored_digest: String = row.try_get("payload_digest")?;
        if digest_bytes(payload.as_bytes()) != stored_digest {
            return Err(LifecycleError::InvalidState(
                "trajectory event digest mismatch".to_string(),
            ));
        }
        events.push(serde_json::from_str::<TrajectoryEvent>(&payload)?);
    }
    let count = u32::try_from(events.len())
        .map_err(|_| LifecycleError::InvalidState("trajectory too large".to_string()))?;
    let reward_sum: i32 = events.iter().map(|event| event.reward_bps).sum();
    let mut evaluation = Evaluation {
        schema: EVALUATION_SCHEMA.to_string(),
        trajectory_digest: trajectory_digest.to_string(),
        sample_count: count,
        candidate_reward_bps: reward_sum / i32::try_from(count).unwrap_or(1),
        safety_floor_met: events.iter().all(|event| event.safety_ok),
        replay_only: true,
        production_effects: false,
        evaluation_digest: String::new(),
    };
    evaluation.evaluation_digest = digest(&EvaluationForDigest::from(&evaluation))?;
    let payload = String::from_utf8(bytes(&evaluation)?)
        .map_err(|error| LifecycleError::InvalidState(error.to_string()))?;
    sqlx::query(
        "INSERT INTO evaluations (trajectory_id, payload_json, payload_digest)
         VALUES (?, ?, ?)",
    )
    .bind(trajectory_id)
    .bind(payload)
    .bind(&evaluation.evaluation_digest)
    .execute(pool)
    .await?;
    Ok(evaluation)
}

#[derive(Serialize)]
struct EvaluationForDigest<'a> {
    schema: &'a str,
    trajectory_digest: &'a str,
    sample_count: u32,
    candidate_reward_bps: i32,
    safety_floor_met: bool,
    replay_only: bool,
    production_effects: bool,
}

impl<'a> From<&'a Evaluation> for EvaluationForDigest<'a> {
    fn from(value: &'a Evaluation) -> Self {
        Self {
            schema: &value.schema,
            trajectory_digest: &value.trajectory_digest,
            sample_count: value.sample_count,
            candidate_reward_bps: value.candidate_reward_bps,
            safety_floor_met: value.safety_floor_met,
            replay_only: value.replay_only,
            production_effects: value.production_effects,
        }
    }
}

#[derive(Serialize)]
struct ArtifactForDigest<'a> {
    schema: &'a str,
    artifact_id: &'a str,
    trajectory_digest: &'a str,
    evaluation_digest: &'a str,
    generation: u64,
    phase: &'a str,
    authority: &'a str,
    production_authority: bool,
    external_effects: bool,
}

impl<'a> From<&'a Artifact> for ArtifactForDigest<'a> {
    fn from(value: &'a Artifact) -> Self {
        Self {
            schema: &value.schema,
            artifact_id: &value.artifact_id,
            trajectory_digest: &value.trajectory_digest,
            evaluation_digest: &value.evaluation_digest,
            generation: value.generation,
            phase: &value.phase,
            authority: &value.authority,
            production_authority: value.production_authority,
            external_effects: value.external_effects,
        }
    }
}

async fn persist_artifact(
    pool: &SqlitePool,
    artifact_id: &str,
    trajectory_digest: &str,
    evaluation: &Evaluation,
    generation: u64,
) -> Result<Artifact, LifecycleError> {
    if digest(&EvaluationForDigest::from(evaluation))? != evaluation.evaluation_digest {
        return Err(LifecycleError::EvaluationDigestMismatch);
    }
    let mut artifact = Artifact {
        schema: ARTIFACT_SCHEMA.to_string(),
        artifact_id: artifact_id.to_string(),
        trajectory_digest: trajectory_digest.to_string(),
        evaluation_digest: evaluation.evaluation_digest.clone(),
        generation,
        phase: "shadow".to_string(),
        authority: "qualification_only".to_string(),
        production_authority: false,
        external_effects: false,
        body_digest: String::new(),
    };
    artifact.body_digest = digest(&ArtifactForDigest::from(&artifact))?;
    let payload = String::from_utf8(bytes(&artifact)?)
        .map_err(|error| LifecycleError::InvalidState(error.to_string()))?;
    sqlx::query(
        "INSERT INTO artifacts (artifact_id, payload_json, body_digest)
         VALUES (?, ?, ?)",
    )
    .bind(artifact_id)
    .bind(payload)
    .bind(&artifact.body_digest)
    .execute(pool)
    .await?;
    Ok(artifact)
}

async fn approve_artifact(pool: &SqlitePool, artifact: &Artifact) -> Result<(), LifecycleError> {
    sqlx::query(
        "INSERT INTO artifact_approvals
         (artifact_id, body_digest, approved, qualification_only,
          production_authority, external_effects)
         VALUES (?, ?, 1, 1, 0, 0)",
    )
    .bind(&artifact.artifact_id)
    .bind(&artifact.body_digest)
    .execute(pool)
    .await?;
    Ok(())
}

async fn runtime_state(pool: &SqlitePool) -> Result<RuntimeState, LifecycleError> {
    let row = sqlx::query(
        "SELECT runtime_generation, active_artifact_id, active_artifact_digest,
                active_artifact_generation, previous_artifact_digest,
                last_transition, rollback_from_generation
         FROM runtime_state WHERE singleton = 1",
    )
    .fetch_one(pool)
    .await?;
    decode_runtime(&row)
}

fn decode_runtime(row: &sqlx::sqlite::SqliteRow) -> Result<RuntimeState, LifecycleError> {
    Ok(RuntimeState {
        runtime_generation: to_u64(row.try_get::<i64, _>("runtime_generation")?)?,
        active_artifact_id: row.try_get("active_artifact_id")?,
        active_artifact_digest: row.try_get("active_artifact_digest")?,
        active_artifact_generation: to_u64(row.try_get::<i64, _>("active_artifact_generation")?)?,
        previous_artifact_digest: row.try_get("previous_artifact_digest")?,
        last_transition: row.try_get("last_transition")?,
        rollback_from_generation: row
            .try_get::<Option<i64>, _>("rollback_from_generation")?
            .map(to_u64)
            .transpose()?,
    })
}

async fn transition_artifact(
    pool: &SqlitePool,
    artifact_id: &str,
    expected_runtime_generation: u64,
    transition: Transition,
) -> Result<RuntimeState, LifecycleError> {
    let current = runtime_state(pool).await?;
    if current.runtime_generation != expected_runtime_generation {
        return Err(LifecycleError::GenerationFence {
            expected: expected_runtime_generation,
            actual: current.runtime_generation,
        });
    }
    let row = sqlx::query("SELECT payload_json, body_digest FROM artifacts WHERE artifact_id = ?")
        .bind(artifact_id)
        .fetch_optional(pool)
        .await?
        .ok_or(LifecycleError::MissingArtifact)?;
    let payload: String = row.try_get("payload_json")?;
    let stored_digest: String = row.try_get("body_digest")?;
    let artifact: Artifact = serde_json::from_str(&payload)?;
    if artifact.body_digest != stored_digest
        || digest(&ArtifactForDigest::from(&artifact))? != artifact.body_digest
    {
        return Err(LifecycleError::ArtifactDigestMismatch);
    }
    let approval = sqlx::query(
        "SELECT body_digest, approved, qualification_only,
                production_authority, external_effects
         FROM artifact_approvals WHERE artifact_id = ?",
    )
    .bind(artifact_id)
    .fetch_optional(pool)
    .await?;
    let Some(approval) = approval else {
        return Err(LifecycleError::UnapprovedArtifact);
    };
    let approved: i64 = approval.try_get("approved")?;
    let qualification_only: i64 = approval.try_get("qualification_only")?;
    let production_authority: i64 = approval.try_get("production_authority")?;
    let external_effects: i64 = approval.try_get("external_effects")?;
    if approval.try_get::<String, _>("body_digest")? != artifact.body_digest
        || approved != 1
        || qualification_only != 1
        || production_authority != 0
        || external_effects != 0
    {
        return Err(LifecycleError::UnapprovedArtifact);
    }
    match transition {
        Transition::Reload if artifact.generation <= current.active_artifact_generation => {
            return Err(LifecycleError::NonMonotonicReload {
                artifact: artifact.generation,
                active: current.active_artifact_generation,
            });
        }
        Transition::Rollback if artifact.generation >= current.active_artifact_generation => {
            return Err(LifecycleError::InvalidRollback {
                target: artifact.generation,
                active: current.active_artifact_generation,
            });
        }
        Transition::Reload | Transition::Rollback => {}
    }
    let next_generation = current.runtime_generation.saturating_add(1);
    let changed = sqlx::query(
        "UPDATE runtime_state SET
            runtime_generation = ?, active_artifact_id = ?,
            active_artifact_digest = ?, active_artifact_generation = ?,
            previous_artifact_digest = ?, last_transition = ?,
            rollback_from_generation = ?
         WHERE singleton = 1 AND runtime_generation = ?",
    )
    .bind(
        i64::try_from(next_generation)
            .map_err(|_| LifecycleError::InvalidState("runtime generation overflow".to_string()))?,
    )
    .bind(&artifact.artifact_id)
    .bind(&artifact.body_digest)
    .bind(
        i64::try_from(artifact.generation).map_err(|_| {
            LifecycleError::InvalidState("artifact generation overflow".to_string())
        })?,
    )
    .bind(current.active_artifact_digest)
    .bind(transition.as_str())
    .bind(match transition {
        Transition::Reload => None,
        Transition::Rollback => Some(i64::try_from(current.active_artifact_generation).map_err(
            |_| LifecycleError::InvalidState("rollback generation overflow".to_string()),
        )?),
    })
    .bind(
        i64::try_from(expected_runtime_generation).map_err(|_| {
            LifecycleError::InvalidState("expected generation overflow".to_string())
        })?,
    )
    .execute(pool)
    .await?;
    if changed.rows_affected() != 1 {
        let actual = runtime_state(pool).await?.runtime_generation;
        return Err(LifecycleError::GenerationFence {
            expected: expected_runtime_generation,
            actual,
        });
    }
    runtime_state(pool).await
}

fn to_u64(value: i64) -> Result<u64, LifecycleError> {
    u64::try_from(value)
        .map_err(|_| LifecycleError::InvalidState("negative persisted generation".to_string()))
}

#[tokio::test]
async fn qualification_h7_trajectory_eval_approved_artifact_reload_and_rollback_fence() {
    let temp = tempfile::tempdir().expect("temporary qualification root");
    let pool = open_store(temp.path()).await.expect("open SQLite store");
    create_schema(&pool).await.expect("create schema");
    let trajectory = vec![
        TrajectoryEvent {
            trajectory_id: "trajectory:h7:001".to_string(),
            event_seq: 1,
            outcome: "abstain".to_string(),
            reward_bps: 4_000,
            safety_ok: true,
            external_effect_executed: false,
        },
        TrajectoryEvent {
            trajectory_id: "trajectory:h7:001".to_string(),
            event_seq: 2,
            outcome: "proposal".to_string(),
            reward_bps: 8_000,
            safety_ok: true,
            external_effect_executed: false,
        },
    ];
    let trajectory_digest = append_trajectory(&pool, &trajectory)
        .await
        .expect("persist trajectory");
    let evaluation = evaluate_trajectory(&pool, "trajectory:h7:001", &trajectory_digest)
        .await
        .expect("evaluate trajectory");
    assert_eq!(evaluation.schema, EVALUATION_SCHEMA);
    assert_eq!(evaluation.candidate_reward_bps, 6_000);
    assert!(evaluation.safety_floor_met);
    assert!(evaluation.replay_only);
    assert!(!evaluation.production_effects);

    let artifact_v1 =
        persist_artifact(&pool, "artifact:h7:001", &trajectory_digest, &evaluation, 1)
            .await
            .expect("persist artifact v1");
    assert_eq!(
        artifact_v1.body_digest,
        digest(&ArtifactForDigest::from(&artifact_v1)).expect("artifact digest")
    );
    assert_eq!(artifact_v1.phase, "shadow");
    assert_eq!(artifact_v1.authority, "qualification_only");
    assert!(!artifact_v1.production_authority);
    assert!(!artifact_v1.external_effects);
    assert_eq!(
        transition_artifact(&pool, &artifact_v1.artifact_id, 0, Transition::Reload)
            .await
            .expect_err("unapproved artifact must be rejected"),
        LifecycleError::UnapprovedArtifact
    );
    approve_artifact(&pool, &artifact_v1)
        .await
        .expect("approve artifact v1");
    let state_v1 = transition_artifact(&pool, &artifact_v1.artifact_id, 0, Transition::Reload)
        .await
        .expect("reload approved v1");
    assert_eq!(state_v1.runtime_generation, 1);
    assert_eq!(
        state_v1.active_artifact_id.as_deref(),
        Some("artifact:h7:001")
    );
    assert_eq!(state_v1.active_artifact_generation, 1);
    assert_eq!(state_v1.last_transition, "reload");

    pool.close().await;
    let pool = open_store(temp.path()).await.expect("reopen SQLite store");
    assert_eq!(
        runtime_state(&pool).await.expect("read durable state"),
        state_v1
    );

    let artifact_v2 =
        persist_artifact(&pool, "artifact:h7:002", &trajectory_digest, &evaluation, 2)
            .await
            .expect("persist artifact v2");
    approve_artifact(&pool, &artifact_v2)
        .await
        .expect("approve artifact v2");
    let state_v2 = transition_artifact(&pool, &artifact_v2.artifact_id, 1, Transition::Reload)
        .await
        .expect("reload approved v2");
    assert_eq!(state_v2.runtime_generation, 2);
    assert_eq!(state_v2.active_artifact_generation, 2);
    assert_eq!(
        state_v2.previous_artifact_digest,
        state_v1.active_artifact_digest
    );

    for transition in [Transition::Reload, Transition::Rollback] {
        assert_eq!(
            transition_artifact(&pool, &artifact_v1.artifact_id, 1, transition)
                .await
                .expect_err("stale fence must reject"),
            LifecycleError::GenerationFence {
                expected: 1,
                actual: 2,
            }
        );
    }
    let rollback = transition_artifact(&pool, &artifact_v1.artifact_id, 2, Transition::Rollback)
        .await
        .expect("rollback approved v1");
    assert_eq!(rollback.runtime_generation, 3);
    assert_eq!(rollback.active_artifact_generation, 1);
    assert_eq!(rollback.last_transition, "rollback");
    assert_eq!(rollback.rollback_from_generation, Some(2));
    assert_eq!(
        rollback.previous_artifact_digest,
        state_v2.active_artifact_digest
    );
    assert_eq!(
        transition_artifact(&pool, &artifact_v1.artifact_id, 3, Transition::Reload)
            .await
            .expect_err("active artifact reload must remain fenced"),
        LifecycleError::NonMonotonicReload {
            artifact: 1,
            active: 1,
        }
    );
}

#[tokio::test]
async fn qualification_h7_artifact_digest_tamper_is_rejected_before_reload() {
    let temp = TempDir::new().expect("temporary qualification root");
    let pool = open_store(temp.path()).await.expect("open SQLite store");
    create_schema(&pool).await.expect("create schema");
    let event = TrajectoryEvent {
        trajectory_id: "trajectory:h7:tamper".to_string(),
        event_seq: 1,
        outcome: "abstain".to_string(),
        reward_bps: 2_000,
        safety_ok: true,
        external_effect_executed: false,
    };
    let trajectory_digest = append_trajectory(&pool, &[event])
        .await
        .expect("persist trajectory");
    let evaluation = evaluate_trajectory(&pool, "trajectory:h7:tamper", &trajectory_digest)
        .await
        .expect("evaluate trajectory");
    let artifact = persist_artifact(
        &pool,
        "artifact:h7:tamper",
        &trajectory_digest,
        &evaluation,
        1,
    )
    .await
    .expect("persist artifact");
    approve_artifact(&pool, &artifact)
        .await
        .expect("approve artifact");
    sqlx::query(
        "UPDATE artifacts SET payload_json = REPLACE(payload_json, 'shadow', 'tampered')
         WHERE artifact_id = ?",
    )
    .bind(&artifact.artifact_id)
    .execute(&pool)
    .await
    .expect("tamper test fixture");
    assert_eq!(
        transition_artifact(&pool, &artifact.artifact_id, 0, Transition::Reload)
            .await
            .expect_err("tampered artifact must fail closed"),
        LifecycleError::ArtifactDigestMismatch
    );
}
