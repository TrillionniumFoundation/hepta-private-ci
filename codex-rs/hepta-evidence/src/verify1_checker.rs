//! Read-only checker for the existing two-field SQLite engineering fixture.
//! The caller pins the trusted goal and state version; imported verdicts are not inputs.
//! A receipt describes one read transaction. It never accepts a task or grants an effect.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Connection;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::Verify1Scope;
use crate::Verify1Verdict;
use crate::Verify1VerificationReceipt;
use crate::verify1_report::python_integer_json;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1FixtureGoal {
    pub task_id: String,
    pub left: i64,
    pub right: i64,
}

impl Verify1FixtureGoal {
    pub fn subject_sha256(&self) -> Result<Sha256Digest, EvidenceError> {
        if self.task_id.is_empty()
            || self.task_id != self.task_id.trim()
            || self.task_id.len() > 1024
            || self.left == i64::MAX
            || self.right == i64::MAX
        {
            return Err(EvidenceError::InvalidRecord(
                "invalid bounded fixture goal".to_string(),
            ));
        }
        python_integer_json(self)
            .map(|raw| Sha256Digest::for_bytes(&raw))
            .map_err(EvidenceError::InvalidRecord)
    }
}

#[derive(Serialize)]
struct Meta {
    epoch: u64,
    tick: u64,
}
#[derive(Serialize)]
struct Intent {
    operation_id: String,
    request: String,
    tick: u64,
    finished: i64,
    ack: i64,
}
#[derive(Serialize)]
struct Readback {
    operation_id: String,
    epoch: u64,
    evidence: String,
}
#[derive(Serialize)]
struct Snapshot {
    goal_json: String,
    meta: Meta,
    resources: BTreeMap<String, i64>,
    intents: Vec<Intent>,
    readbacks: Vec<Readback>,
}

/// Recompute the prefix through `expected_scope.horizon_start` at one snapshot.
/// Step 1 covers only the left target; later prefixes cover both fields. Only
/// frontier 4 is a terminal acceptance candidate, and this checker never accepts.
/// Trusted controller ownership and atomic SQLite reads are explicit assumptions,
/// not isolation against another process with write access to the same database.
pub async fn check_verify1_sqlite(
    path: &Path,
    goal: &Verify1FixtureGoal,
    expected_scope: &Verify1Scope,
) -> Result<Verify1VerificationReceipt, EvidenceError> {
    expected_scope
        .validate()
        .map_err(EvidenceError::InvalidRecord)?;
    let subject = goal.subject_sha256()?;
    if expected_scope.task_id != goal.task_id
        || expected_scope.subject_sha256 != subject.as_str()
        || expected_scope.domain != "sqlite_two_field_engineering_fixture_v1"
        || expected_scope.event != "terminal_goal_value_error"
        || expected_scope.horizon_end != 4
        || !(1..=4).contains(&expected_scope.horizon_start)
    {
        return Err(EvidenceError::InvalidRecord(
            "checker scope does not bind the fixture goal/frontier".to_string(),
        ));
    }
    let parent = path.parent().unwrap_or(Path::new("."));
    let home = parent
        .try_into()
        .map_err(|error: std::io::Error| EvidenceError::InvalidRecord(error.to_string()))?;
    let config = SqliteConfig::from_sqlite_home(home);
    let pool = config
        .open_durable_observation_pool(path)
        .await
        .map_err(|error| EvidenceError::Unavailable(error.to_string()))?;
    let read = async {
        let mut connection = pool.acquire().await.map_err(database_error)?;
        read_snapshot(&mut connection).await
    }
    .await;
    pool.close().await;
    let snapshot = read?;
    let retained: Verify1FixtureGoal = serde_json::from_str(&snapshot.goal_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let expected_raw = python_integer_json(goal).map_err(EvidenceError::InvalidRecord)?;
    if retained != *goal || snapshot.goal_json.as_bytes() != expected_raw {
        return Err(EvidenceError::InvalidRecord(
            "goal differs from the initialized owner journal".to_string(),
        ));
    }
    let (verdict, reason) = evaluate(&snapshot, goal, expected_scope);
    let evidence = python_integer_json(
        &serde_json::json!({"expected_scope":expected_scope,"observation":snapshot}),
    )
    .map_err(EvidenceError::Serialization)?;
    let mut scope = expected_scope.clone();
    scope.state_version = snapshot.meta.epoch;
    let receipt = Verify1VerificationReceipt {
        scope,
        property: "fixture_prefix_goal_and_owner_readback_at_snapshot".to_string(),
        assumptions: vec![
            "controller_goal_is_trusted".to_string(),
            "host_selected_fixture_database_is_trusted".to_string(),
            "sqlite_read_transaction_is_consistent".to_string(),
            "fixture_owner_and_epoch_bound_readbacks_are_trusted".to_string(),
        ],
        checker_id: "verify1.rust.sqlite.goal".to_string(),
        checker_version: "1".to_string(),
        evidence_sha256: Sha256Digest::for_bytes(&evidence).as_str().to_string(),
        checked_step: expected_scope.horizon_start,
        verdict,
        reason: reason.to_string(),
        residual_obligations: if verdict == Verify1Verdict::Proved {
            vec![]
        } else {
            vec![reason.to_string()]
        },
    };
    receipt.validate().map_err(EvidenceError::InvalidRecord)?;
    Ok(receipt)
}

fn evaluate(
    snapshot: &Snapshot,
    goal: &Verify1FixtureGoal,
    scope: &Verify1Scope,
) -> (Verify1Verdict, &'static str) {
    if snapshot.meta.epoch != scope.state_version {
        return (Verify1Verdict::Unknown, "pinned_state_version_mismatch");
    }
    let expected_tick = scope.horizon_start.min(3);
    if snapshot.meta.tick != expected_tick {
        return (Verify1Verdict::Unknown, "state_frontier_mismatch");
    }
    let mut expected = BTreeMap::from([("left".to_string(), goal.left)]);
    if scope.horizon_start >= 2 {
        expected.insert("right".to_string(), goal.right);
    }
    if snapshot.resources != expected {
        return (Verify1Verdict::Refuted, "goal_values_mismatch");
    }
    let required: BTreeSet<_> = (1..=expected_tick)
        .map(|tick| format!("{}/step/{tick}", goal.task_id))
        .collect();
    let actual: BTreeSet<_> = snapshot
        .intents
        .iter()
        .map(|intent| intent.operation_id.clone())
        .collect();
    if actual != required
        || actual.len() != snapshot.intents.len()
        || snapshot.intents.iter().any(|intent| {
            intent.finished != 1
                || intent.operation_id != format!("{}/step/{}", goal.task_id, intent.tick)
        })
    {
        return (Verify1Verdict::Unknown, "incomplete_owner_intents");
    }
    let recovered: BTreeSet<_> = snapshot
        .readbacks
        .iter()
        .filter(|readback| readback.epoch == snapshot.meta.epoch)
        .map(|readback| &readback.operation_id)
        .collect();
    if snapshot
        .readbacks
        .iter()
        .any(|readback| !required.contains(&readback.operation_id))
    {
        return (Verify1Verdict::Unknown, "unbound_owner_readback");
    }
    if snapshot
        .intents
        .iter()
        .any(|intent| intent.ack == 0 && !recovered.contains(&intent.operation_id))
    {
        return (Verify1Verdict::Unknown, "missing_ack_requires_readback");
    }
    (
        Verify1Verdict::Proved,
        "finite_fixture_goal_and_owner_readback",
    )
}

async fn read_snapshot(connection: &mut SqliteConnection) -> Result<Snapshot, EvidenceError> {
    let mut transaction = connection.begin().await.map_err(database_error)?;
    let goals: Vec<(String,)> = sqlx::query_as(
        "SELECT CASE WHEN length(payload)<=32768 THEN payload END FROM journal WHERE kind='goal' LIMIT 2")
        .fetch_all(&mut *transaction).await.map_err(database_error)?;
    let meta: Vec<(i64, i64)> = sqlx::query_as("SELECT epoch,tick FROM meta LIMIT 2")
        .fetch_all(&mut *transaction)
        .await
        .map_err(database_error)?;
    if goals.len() != 1 || meta.len() != 1 {
        return Err(EvidenceError::Corrupt(
            "fixture needs exactly one initialized goal and frontier".to_string(),
        ));
    }
    let resource_rows: Vec<(String, i64)> = sqlx::query_as(
        "SELECT CASE WHEN length(name)<=64 THEN name END,value FROM resources ORDER BY name LIMIT 4")
        .fetch_all(&mut *transaction).await.map_err(database_error)?;
    let intent_rows: Vec<(String,String,i64,i64,i64)> = sqlx::query_as(
        "SELECT CASE WHEN length(operation_id)<=1050 THEN operation_id END, CASE WHEN length(request)=64 THEN request END,tick,finished,ack FROM intents ORDER BY tick,operation_id LIMIT 4")
        .fetch_all(&mut *transaction).await.map_err(database_error)?;
    let readback_rows: Vec<(String,i64,String)> = sqlx::query_as(
        "SELECT CASE WHEN length(operation_id)<=1050 THEN operation_id END,epoch,CASE WHEN length(evidence)=64 THEN evidence END FROM readbacks ORDER BY operation_id LIMIT 4")
        .fetch_all(&mut *transaction).await.map_err(database_error)?;
    if resource_rows.len() > 3 || intent_rows.len() > 3 || readback_rows.len() > 3 {
        return Err(EvidenceError::Corrupt(
            "fixture exceeds bounded state profile".to_string(),
        ));
    }
    let count = resource_rows.len();
    let resources: BTreeMap<_, _> = resource_rows.into_iter().collect();
    if resources.len() != count {
        return Err(EvidenceError::Corrupt(
            "duplicate fixture resource".to_string(),
        ));
    }
    let mut intents = Vec::new();
    for (operation_id, request, tick, finished, ack) in intent_rows {
        Sha256Digest::parse(&request).map_err(EvidenceError::Corrupt)?;
        if !(0..=1).contains(&finished) || !(0..=1).contains(&ack) {
            return Err(EvidenceError::Corrupt(
                "invalid fixture intent flags".to_string(),
            ));
        }
        intents.push(Intent {
            operation_id,
            request,
            tick: nonnegative(tick)?,
            finished,
            ack,
        });
    }
    let mut readbacks = Vec::new();
    for (operation_id, epoch, evidence) in readback_rows {
        Sha256Digest::parse(&evidence).map_err(EvidenceError::Corrupt)?;
        readbacks.push(Readback {
            operation_id,
            epoch: nonnegative(epoch)?,
            evidence,
        });
    }
    let snapshot = Snapshot {
        goal_json: goals[0].0.clone(),
        meta: Meta {
            epoch: nonnegative(meta[0].0)?,
            tick: nonnegative(meta[0].1)?,
        },
        resources,
        intents,
        readbacks,
    };
    transaction.rollback().await.map_err(database_error)?;
    Ok(snapshot)
}

fn nonnegative(value: i64) -> Result<u64, EvidenceError> {
    u64::try_from(value).map_err(|error| EvidenceError::Corrupt(error.to_string()))
}

fn database_error(error: sqlx::Error) -> EvidenceError {
    EvidenceError::Corrupt(error.to_string())
}
