//! A separate durable destination. Faults interrupt real SQLite effects and
//! receipt delivery; neither the goal observer nor the oracle sees `Fault`.

use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::SqlitePool;
use tokio::sync::Notify;

#[derive(Clone, Copy, Debug)]
pub enum Fault {
    None,
    AckLost,
    WaitingInput,
    Partial,
    RejectedPartial,
    RejectBeforeStart,
    ExitZero,
    PauseBeforeCommit,
    PauseAfterCommit,
    CrashAfterCommit,
}

#[derive(Clone, Copy)]
pub enum LookupAvailability {
    Available,
    Unavailable,
    Unsupported,
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct Desired {
    pub rows: Vec<String>,
}

impl Desired {
    pub fn standard() -> Self {
        Self {
            rows: vec!["invoice:42".to_string(), "archive:42".to_string()],
        }
    }
}

#[derive(Deserialize)]
struct Envelope {
    body: Vec<u8>,
}

/// Only destination-owned facts; no injected-fault or expected-result field.
#[derive(Debug, Serialize)]
pub struct JobFacts {
    pub payload: String,
    pub desired: Desired,
    pub phase: String,
    pub exit_code: Option<i64>,
    pub cancel_received: bool,
    pub rows: Vec<String>,
}

#[derive(Clone)]
pub struct Destination {
    pub path: PathBuf,
    pub pool: SqlitePool,
    pub reached: Arc<Notify>,
    pub release: Arc<Notify>,
    fault: Fault,
    lookup: LookupAvailability,
    input_worker: Arc<Mutex<Option<InputWorker>>>,
}

struct InputWorker(Child);

impl Drop for InputWorker {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

pub async fn open_pool(path: &Path) -> SqlitePool {
    sqlite_config(path)
        .open_durable_evidence_pool(path)
        .await
        .expect("open destination SQLite")
}

pub async fn open_observation_pool(path: &Path) -> SqlitePool {
    sqlite_config(path)
        .open_durable_observation_pool(path)
        .await
        .expect("open existing destination for read-only observation")
}

fn sqlite_config(path: &Path) -> SqliteConfig {
    let root = path.parent().expect("destination parent directory");
    let sqlite_home =
        AbsolutePathBuf::try_from(root.to_path_buf()).expect("absolute destination directory");
    SqliteConfig::from_sqlite_home(sqlite_home)
}

impl Destination {
    pub async fn open(root: &Path, fault: Fault) -> Self {
        let path = root.join("destination.sqlite3");
        let pool = open_pool(&path).await;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS jobs (
                effect_key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                body BLOB NOT NULL, phase TEXT NOT NULL,
                exit_code INTEGER, cancel_received INTEGER NOT NULL DEFAULT 0)",
        )
        .execute(&pool)
        .await
        .expect("create jobs");
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS business_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                effect_key TEXT NOT NULL, ordinal INTEGER NOT NULL, value TEXT NOT NULL)",
        )
        .execute(&pool)
        .await
        .expect("create independent business ledger");
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS contacts (
                contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                effect_key TEXT NOT NULL, kind TEXT NOT NULL)",
        )
        .execute(&pool)
        .await
        .expect("create transport history");
        Self {
            path,
            pool,
            reached: Arc::new(Notify::new()),
            release: Arc::new(Notify::new()),
            fault,
            lookup: LookupAvailability::Available,
            input_worker: Arc::new(Mutex::new(None)),
        }
    }

    pub fn with_lookup(mut self, lookup: LookupAvailability) -> Self {
        self.lookup = lookup;
        self
    }

    async fn contact(&self, key: &ProviderEffectKey, kind: &str) {
        sqlx::query("INSERT INTO contacts(effect_key, kind) VALUES (?, ?)")
            .bind(key.as_str())
            .bind(kind)
            .execute(&self.pool)
            .await
            .expect("persist target contact");
    }

    pub async fn contact_count(&self, kind: &str) -> i64 {
        sqlx::query_scalar("SELECT COUNT(*) FROM contacts WHERE kind = ?")
            .bind(kind)
            .fetch_one(&self.pool)
            .await
            .expect("transport contact count")
    }

    pub async fn cancel(&self, key: &ProviderEffectKey) {
        self.contact(key, "cancel").await;
        // Cancellation records a request; it cannot undo committed mutations.
        sqlx::query("UPDATE jobs SET cancel_received = 1 WHERE effect_key = ?")
            .bind(key.as_str())
            .execute(&self.pool)
            .await
            .expect("record cancellation request");
    }

    pub fn input_process_waits(&self) -> bool {
        self.input_worker
            .lock()
            .expect("input worker lock")
            .as_mut()
            .expect("spawned input worker")
            .0
            .try_wait()
            .expect("observe waiting process")
            .is_none()
    }

    pub fn provide_input(&self) {
        let mut worker = self
            .input_worker
            .lock()
            .expect("input worker lock")
            .take()
            .expect("input worker");
        worker
            .0
            .stdin
            .take()
            .expect("input pipe")
            .write_all(b"continue\n")
            .expect("deliver explicit input");
        assert!(worker.0.wait().expect("wait input worker").success());
    }

    pub async fn finish(&self, key: &ProviderEffectKey) {
        self.contact(key, "resume").await;
        self.apply(key, usize::MAX, "completed").await;
    }

    async fn reject(&self, key: &ProviderEffectKey) {
        let mut tx = self.pool.begin().await.expect("begin rejection fence");
        sqlx::query("UPDATE jobs SET phase = phase WHERE effect_key = ?")
            .bind(key.as_str())
            .execute(&mut *tx)
            .await
            .expect("same destination writer fence");
        let effects: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM business_events WHERE effect_key = ?")
                .bind(key.as_str())
                .fetch_one(&mut *tx)
                .await
                .expect("check effects under rejection fence");
        if effects == 0 {
            // The existing primary-key row retains its original payload. All
            // apply paths check this permanent tombstone under the same fence.
            sqlx::query("UPDATE jobs SET phase = 'rejected_tombstone' WHERE effect_key = ?")
                .bind(key.as_str())
                .execute(&mut *tx)
                .await
                .expect("persist rejection tombstone");
        }
        tx.commit()
            .await
            .expect("commit rejection and late-commit exclusion");
    }

    async fn apply(&self, key: &ProviderEffectKey, count: usize, phase: &str) {
        let mut tx = self.pool.begin().await.expect("begin destination effect");
        // This write acquires the same SQLite writer fence used by cancel.
        sqlx::query("UPDATE jobs SET phase = phase WHERE effect_key = ?")
            .bind(key.as_str())
            .execute(&mut *tx)
            .await
            .expect("destination writer fence");
        let job = sqlx::query("SELECT body, phase, cancel_received FROM jobs WHERE effect_key = ?")
            .bind(key.as_str())
            .fetch_one(&mut *tx)
            .await
            .expect("accepted destination job");
        let current: String = job.get("phase");
        if matches!(
            current.as_str(),
            "completed" | "cancelled" | "rejected_tombstone"
        ) {
            tx.commit().await.expect("deduplicated no-op");
            return;
        }
        if job.get::<i64, _>("cancel_received") == 1 {
            sqlx::query("UPDATE jobs SET phase = 'cancelled' WHERE effect_key = ?")
                .bind(key.as_str())
                .execute(&mut *tx)
                .await
                .expect("cancel before mutation");
        } else {
            let desired: Desired = serde_json::from_slice(&job.get::<Vec<u8>, _>("body"))
                .expect("stored domain request");
            for (ordinal, value) in desired.rows.iter().enumerate().take(count) {
                let present: i64 = sqlx::query_scalar(
                    "SELECT COUNT(*) FROM business_events WHERE effect_key = ? AND ordinal = ?",
                )
                .bind(key.as_str())
                .bind(i64::try_from(ordinal).expect("small ordinal"))
                .fetch_one(&mut *tx)
                .await
                .expect("destination dedupe read");
                if present == 0 {
                    sqlx::query(
                        "INSERT INTO business_events(effect_key, ordinal, value) VALUES (?, ?, ?)",
                    )
                    .bind(key.as_str())
                    .bind(i64::try_from(ordinal).expect("small ordinal"))
                    .bind(value)
                    .execute(&mut *tx)
                    .await
                    .expect("actual domain mutation");
                }
            }
            sqlx::query("UPDATE jobs SET phase = ?, exit_code = 0 WHERE effect_key = ?")
                .bind(phase)
                .bind(key.as_str())
                .execute(&mut *tx)
                .await
                .expect("worker process completion");
        }
        tx.commit().await.expect("commit destination-owned facts");
    }

    async fn receive(&self, intent: &ProviderEffectIntent, wire: &[u8]) -> ProviderEffectDispatch {
        self.contact(&intent.key, "dispatch").await;
        if intent.payload_sha256 != Sha256Digest::for_bytes(wire) {
            return ProviderEffectDispatch::NotDispatched {
                reason_code: "payload_mismatch".to_string(),
            };
        }
        let envelope: Envelope = serde_json::from_slice(wire).expect("validated skill envelope");
        let _: Desired = serde_json::from_slice(&envelope.body).expect("domain request");
        let inserted = sqlx::query(
            "INSERT OR IGNORE INTO jobs(effect_key, payload, body, phase) VALUES (?, ?, ?, 'accepted')",
        )
        .bind(intent.key.as_str())
        .bind(intent.payload_sha256.as_str())
        .bind(envelope.body)
        .execute(&self.pool)
        .await
        .expect("durable destination admission")
        .rows_affected();
        let accepted_facts = facts(&self.pool, &intent.key)
            .await
            .expect("accepted facts");
        if accepted_facts.payload != intent.payload_sha256.as_str() {
            return ProviderEffectDispatch::Unknown;
        }
        if inserted == 0 {
            return ProviderEffectDispatch::Ack(ack(intent, &accepted_facts.phase));
        }
        if matches!(self.fault, Fault::PauseBeforeCommit) {
            self.reached.notify_one();
            self.release.notified().await;
        }
        match self.fault {
            Fault::WaitingInput => {
                sqlx::query("UPDATE jobs SET phase = 'waiting_input' WHERE effect_key = ?")
                    .bind(intent.key.as_str())
                    .execute(&self.pool)
                    .await
                    .expect("worker waits for input");
                let child = Command::new(std::env::current_exe().expect("test executable"))
                    .args([
                        "--ignored",
                        "--exact",
                        "action_skill_input_worker",
                        "--nocapture",
                    ])
                    .env(
                        super::ROOT_ENV,
                        self.path.parent().expect("destination directory"),
                    )
                    .env(super::KEY_ENV, intent.key.as_str())
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .spawn()
                    .expect("spawn real process awaiting input");
                *self.input_worker.lock().expect("input worker lock") = Some(InputWorker(child));
            }
            Fault::Partial => self.apply(&intent.key, 1, "partial").await,
            Fault::RejectedPartial => self.apply(&intent.key, 1, "rejected_partial").await,
            Fault::RejectBeforeStart => {
                self.reject(&intent.key).await;
                self.reached.notify_one();
                self.release.notified().await;
            }
            Fault::ExitZero => self.apply(&intent.key, 0, "exited").await,
            Fault::None
            | Fault::AckLost
            | Fault::PauseBeforeCommit
            | Fault::PauseAfterCommit
            | Fault::CrashAfterCommit => {
                self.apply(&intent.key, usize::MAX, "completed").await;
            }
        }
        if matches!(self.fault, Fault::CrashAfterCommit) {
            let marker = self.path.with_extension("committed");
            std::fs::write(marker, b"destination transaction committed").expect("kill barrier");
            std::future::pending::<()>().await;
        }
        if matches!(self.fault, Fault::PauseAfterCommit) {
            self.reached.notify_one();
            self.release.notified().await;
        }
        if matches!(self.fault, Fault::AckLost) {
            return ProviderEffectDispatch::Unknown;
        }
        let final_facts = facts(&self.pool, &intent.key)
            .await
            .expect("final destination facts");
        ProviderEffectDispatch::Ack(ack(intent, &final_facts.phase))
    }
}

pub async fn facts(pool: &SqlitePool, key: &ProviderEffectKey) -> Option<JobFacts> {
    let job = sqlx::query(
        "SELECT payload, body, phase, exit_code, cancel_received FROM jobs WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .fetch_optional(pool)
    .await
    .expect("read independent target facts")?;
    let rows = sqlx::query_scalar(
        "SELECT value FROM business_events WHERE effect_key = ? ORDER BY ordinal, event_id",
    )
    .bind(key.as_str())
    .fetch_all(pool)
    .await
    .expect("read actual business effects");
    Some(JobFacts {
        payload: job.get("payload"),
        desired: serde_json::from_slice(&job.get::<Vec<u8>, _>("body")).expect("desired state"),
        phase: job.get("phase"),
        exit_code: job.get("exit_code"),
        cancel_received: job.get::<i64, _>("cancel_received") == 1,
        rows,
    })
}

fn ack(intent: &ProviderEffectIntent, phase: &str) -> ProviderEffectAck {
    // The destination acknowledges job execution. Goal verification is separate.
    let status = match phase {
        "completed" | "partial" | "exited" => ProviderEffectAckStatus::Completed,
        "rejected_partial" | "rejected_tombstone" => ProviderEffectAckStatus::Rejected,
        _ => ProviderEffectAckStatus::Accepted,
    };
    ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(intent.key.as_str().as_bytes()),
        status,
    )
}

impl ProviderEffectAdapter for Destination {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        match self.lookup {
            LookupAvailability::Available | LookupAvailability::Unavailable => {
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup
            }
            LookupAvailability::Unsupported => ProviderEffectIdempotencyCapability::Unsupported,
        }
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "exact_payload_required".to_string(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(self.receive(intent, wire))
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }

    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async move {
            self.contact(&intent.key, "lookup").await;
            if !matches!(self.lookup, LookupAvailability::Available) {
                return ProviderEffectLookup::Unknown;
            }
            match facts(&self.pool, &intent.key).await {
                Some(facts) if facts.payload == intent.payload_sha256.as_str() => {
                    ProviderEffectLookup::Ack(ack(intent, &facts.phase))
                }
                Some(_) | None => ProviderEffectLookup::Unknown,
            }
        })
    }
}
