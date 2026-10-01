//! Only the independently authenticated external consumer publishes these ACKs.

use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;

use super::ConsumerPortError;
use super::consumer_wire::ConsumerAcknowledgement;
use super::consumer_wire::ConsumerIntent;
use super::consumer_wire::MAX_CONSUMER_OPERATIONS;
use super::consumer_wire::MAX_FRAME_BYTES;
use super::consumer_wire::SignedConsumerAcknowledgement;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./consumer_migrations");

pub(super) struct CredentialConsumerOwner {
    pool: SqlitePool,
    public_key: [u8; 32],
    fenced: AtomicBool,
}

struct UncertainCommit<'a> {
    owner: &'a CredentialConsumerOwner,
    armed: bool,
}
impl Drop for UncertainCommit<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.owner.fence_writer();
        }
    }
}

impl CredentialConsumerOwner {
    pub async fn open(path: &Path, public_key: [u8; 32]) -> Result<Self, ConsumerPortError> {
        crate::sqlite_owner::prepare_private_storage(path).map_err(unavailable)?;
        let home = AbsolutePathBuf::try_from(
            path.parent()
                .ok_or(ConsumerPortError::Invalid)?
                .to_path_buf(),
        )
        .map_err(unavailable)?;
        let pool = SqliteConfig::from_sqlite_home(home)
            .open_durable_evidence_pool(path)
            .await
            .map_err(unavailable)?;
        let result = async {
            let check: String = sqlx::query_scalar("PRAGMA quick_check")
                .fetch_one(&pool)
                .await
                .map_err(unavailable)?;
            if check != "ok" {
                return Err(ConsumerPortError::Unavailable);
            }
            MIGRATOR.run(&pool).await.map_err(unavailable)?;
            crate::sqlite_owner::secure_database_file(path).map_err(unavailable)?;
            verify_schema(&pool).await
        }
        .await;
        if let Err(error) = result {
            pool.close().await;
            return Err(error);
        }
        Ok(Self {
            pool,
            public_key,
            fenced: AtomicBool::new(false),
        })
    }

    pub async fn authenticate(
        &self,
        intent: &ConsumerIntent,
        credential: &[u8],
        proof: &[u8; 32],
        signing_key: &SigningKey,
    ) -> Result<SignedConsumerAcknowledgement, ConsumerPortError> {
        intent.verify_proof(credential, proof)?;
        if signing_key.verifying_key().to_bytes() != self.public_key {
            return Err(ConsumerPortError::Unavailable);
        }
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        // A cancelled SQLite future can already have submitted work to its
        // worker. Arm before BEGIN and never infer rollback from cancellation.
        let mut uncertainty = UncertainCommit {
            owner: self,
            armed: true,
        };
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        let existing = sqlx::query(
            "SELECT operation_id,consumer_id,semantic_sha256,durable_revision,acknowledgement_json FROM credential_consumer_ack WHERE operation_id = ?",
        ).bind(&intent.operation_id).fetch_optional(&mut *transaction)
            .await.map_err(unavailable)?;
        if let Some(row) = existing {
            let receipt = decode_row(&row, intent, &self.public_key)?;
            transaction.commit().await.map_err(unavailable)?;
            uncertainty.armed = false;
            return Ok(receipt);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM credential_consumer_ack")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_CONSUMER_OPERATIONS {
            return Err(ConsumerPortError::Capacity);
        }
        let revision: i64 = sqlx::query_scalar(
            "SELECT next_revision FROM credential_consumer_meta WHERE singleton = 1",
        )
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let next = revision.checked_add(1).ok_or(ConsumerPortError::Capacity)?;
        let acknowledgement = ConsumerAcknowledgement {
            intent: intent.clone(),
            durable_revision: u64::try_from(revision).map_err(unavailable)?,
        };
        let signature = signing_key
            .sign(&acknowledgement.signing_bytes()?)
            .to_bytes()
            .to_vec();
        let receipt = SignedConsumerAcknowledgement {
            acknowledgement,
            signature,
        };
        let encoding = serde_json::to_vec(&receipt).map_err(unavailable)?;
        if encoding.len() > MAX_FRAME_BYTES {
            return Err(ConsumerPortError::Invalid);
        }
        sqlx::query(
            "INSERT INTO credential_consumer_ack(operation_id,consumer_id,semantic_sha256,durable_revision,acknowledgement_json) VALUES(?,?,?,?,?)",
        ).bind(&intent.operation_id).bind(&intent.consumer_id).bind(intent.semantic_sha256.as_slice())
            .bind(revision).bind(encoding).execute(&mut *transaction).await.map_err(unavailable)?;
        let updated = sqlx::query("UPDATE credential_consumer_meta SET next_revision = ? WHERE singleton = 1 AND next_revision = ?")
            .bind(next).bind(revision).execute(&mut *transaction).await.map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(ConsumerPortError::Unavailable);
        }
        // No signed ACK escapes before the FULL transaction has committed.
        // If this await is cancelled or fails, the caller retains Unknown and
        // reads the same operation through Status; it never retries delivery.
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        transaction.commit().await.map_err(unavailable)?;
        uncertainty.armed = false;
        Ok(receipt)
    }

    pub async fn status(
        &self,
        intent: &ConsumerIntent,
    ) -> Result<Option<SignedConsumerAcknowledgement>, ConsumerPortError> {
        intent.validate()?;
        let row = sqlx::query(
            "SELECT operation_id,consumer_id,semantic_sha256,durable_revision,acknowledgement_json FROM credential_consumer_ack WHERE operation_id = ?",
        ).bind(&intent.operation_id).fetch_optional(&self.pool).await.map_err(unavailable)?;
        match row {
            Some(row) => Ok(Some(decode_row(&row, intent, &self.public_key)?)),
            None => Ok(None),
        }
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }
    pub fn fence_writer(&self) {
        self.fenced.store(true, Ordering::Release);
    }
}

fn decode_row(
    row: &SqliteRow,
    intent: &ConsumerIntent,
    public_key: &[u8; 32],
) -> Result<SignedConsumerAcknowledgement, ConsumerPortError> {
    let operation: String = row.try_get("operation_id").map_err(unavailable)?;
    let consumer: String = row.try_get("consumer_id").map_err(unavailable)?;
    let semantic: Vec<u8> = row.try_get("semantic_sha256").map_err(unavailable)?;
    let revision: i64 = row.try_get("durable_revision").map_err(unavailable)?;
    let receipt = decode_receipt(row.try_get("acknowledgement_json").map_err(unavailable)?)?;
    let projected = &receipt.acknowledgement;
    if operation != projected.intent.operation_id
        || consumer != projected.intent.consumer_id
        || semantic != projected.intent.semantic_sha256
        || revision <= 0
        || u64::try_from(revision).map_err(unavailable)? != projected.durable_revision
    {
        return Err(ConsumerPortError::Unavailable);
    }
    receipt.verify(intent, public_key)?;
    Ok(receipt)
}

fn decode_receipt(bytes: Vec<u8>) -> Result<SignedConsumerAcknowledgement, ConsumerPortError> {
    if bytes.is_empty() || bytes.len() > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Unavailable);
    }
    serde_json::from_slice(&bytes).map_err(unavailable)
}

async fn verify_schema(pool: &SqlitePool) -> Result<(), ConsumerPortError> {
    let home = AbsolutePathBuf::try_from(std::env::temp_dir()).map_err(unavailable)?;
    let reference = SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(Path::new(":memory:"))
        .await
        .map_err(unavailable)?;
    let result = async {
        let mut connection = reference.acquire().await.map_err(unavailable)?;
        MIGRATOR.run(&mut *connection).await.map_err(unavailable)?;
        let query = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL ORDER BY type,name";
        let expected = sqlx::query_as::<_, (String,String,String,String)>(query)
            .fetch_all(&mut *connection).await.map_err(unavailable)?;
        let actual = sqlx::query_as::<_, (String,String,String,String)>(query)
            .fetch_all(pool).await.map_err(unavailable)?;
        if actual != expected { return Err(ConsumerPortError::Unavailable); }
        Ok(())
    }.await;
    reference.close().await;
    result
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
