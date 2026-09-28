//! Bounded, single-transaction recovery commitments. Never acquire a second
//! pool connection while collecting a snapshot: WAL readers must see one epoch.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use super::EVIDENCE_DATABASE_LINEAGE;
use super::EvidenceRecoverySnapshotV1;
use crate::EvidenceError;
use crate::qualification::QUALIFICATION_COLUMNS;
use crate::qualification::QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES;
use crate::qualification::authenticated_row_sha256;
use crate::schema_validation::classify_sqlx_error;

const MAX_ROWS: i64 = 1_000_000;
const MAX_REPLAY_ROWS: i64 = 16_384;
const PAGE_ROWS: i64 = 32;
const MAX_SCAN_BYTES: i64 = 512 * 1024 * 1024;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum Domain {
    LegacyEnvelope,
    AuthenticatedAdmission,
}

pub(super) async fn collect(
    pool: &SqlitePool,
    domain: Domain,
) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
    let mut transaction = pool.begin().await.map_err(classify_sqlx_error)?;
    let snapshot = collect_in_transaction(&mut transaction, domain).await?;
    transaction.commit().await.map_err(classify_sqlx_error)?;
    Ok(snapshot)
}

pub(super) async fn collect_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    domain: Domain,
) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
    let migration_rows = sqlx::query(
        "SELECT version, description, checksum FROM _sqlx_migrations
         WHERE success = 1 ORDER BY version LIMIT 1025",
    )
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if migration_rows.len() > 1024 {
        return Err(EvidenceError::Corrupt(
            "migration frontier exceeds capacity".into(),
        ));
    }
    let mut migration_frontier = empty_frontier(b"hepta.evidence.migrations.v1");
    for row in migration_rows {
        let version: i64 = row.try_get("version").map_err(classify_sqlx_error)?;
        let description: String = row.try_get("description").map_err(classify_sqlx_error)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(classify_sqlx_error)?;
        migration_frontier = extend_frontier(
            b"hepta.evidence.migrations.v1",
            &migration_frontier,
            &[&version.to_be_bytes(), description.as_bytes(), &checksum],
        );
    }
    // Inspect lengths in SQLite BEFORE materializing any potentially large JSON.
    let bounds = sqlx::query(
        "SELECT COUNT(*) AS n, COALESCE(MAX(length(CAST(envelope_json AS BLOB))), 0) AS largest,
                COALESCE(SUM(length(CAST(envelope_json AS BLOB))), 0) AS bytes
         FROM qualification_evidence",
    )
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let rows: i64 = bounds.try_get("n").map_err(classify_sqlx_error)?;
    let largest: i64 = bounds.try_get("largest").map_err(classify_sqlx_error)?;
    let bytes: i64 = bounds.try_get("bytes").map_err(classify_sqlx_error)?;
    if rows > MAX_ROWS || bytes > MAX_SCAN_BYTES {
        return Err(EvidenceError::Unavailable(
            "recovery snapshot exceeds row or byte budget".into(),
        ));
    }
    if largest > QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES as i64 {
        return Err(EvidenceError::Corrupt(
            "stored qualification envelope exceeds 256 KiB".into(),
        ));
    }
    let qualification_domain: &[u8] = match domain {
        Domain::LegacyEnvelope => b"hepta.evidence.qualification-frontier.v1",
        Domain::AuthenticatedAdmission => b"hepta.evidence.qualification-frontier.v2",
    };
    let mut qualification_frontier = empty_frontier(qualification_domain);
    if domain == Domain::AuthenticatedAdmission {
        let store_id: Option<String> = sqlx::query_scalar(
            "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
        )
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let store_id = store_id.ok_or_else(|| {
            EvidenceError::InvalidRecord(
                "authenticated recovery requires an enrolled store identity".into(),
            )
        })?;
        StableId::new(store_id.clone())
            .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
        qualification_frontier = extend_frontier(
            qualification_domain,
            &qualification_frontier,
            &[b"store-identity", store_id.as_bytes()],
        );
    }
    let columns = match domain {
        Domain::LegacyEnvelope => "seq, evidence_id, envelope_sha256",
        Domain::AuthenticatedAdmission => QUALIFICATION_COLUMNS,
    };
    let statement = format!(
        "SELECT {columns} FROM qualification_evidence WHERE seq > ? ORDER BY seq ASC LIMIT ?"
    );
    let mut last_seq = 0_i64;
    let mut observed_rows = 0_i64;
    loop {
        let page = sqlx::query(&statement)
            .bind(last_seq)
            .bind(PAGE_ROWS)
            .fetch_all(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if page.is_empty() {
            break;
        }
        for row in page {
            let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
            if seq <= last_seq {
                return Err(EvidenceError::Corrupt(
                    "recovery sequence is not increasing".into(),
                ));
            }
            let evidence_id: String = row.try_get("evidence_id").map_err(classify_sqlx_error)?;
            let digest = match domain {
                Domain::LegacyEnvelope => Sha256Digest::parse(
                    row.try_get::<String, _>("envelope_sha256")
                        .map_err(classify_sqlx_error)?,
                )
                .map_err(EvidenceError::Corrupt)?,
                Domain::AuthenticatedAdmission => authenticated_row_sha256(&row)?,
            };
            qualification_frontier = extend_frontier(
                qualification_domain,
                &qualification_frontier,
                &[
                    &(seq as u64).to_be_bytes(),
                    evidence_id.as_bytes(),
                    digest.as_str().as_bytes(),
                ],
            );
            last_seq = seq;
            observed_rows += 1;
        }
    }
    if observed_rows != rows {
        return Err(EvidenceError::Corrupt(
            "recovery rows include invalid sequence identities".into(),
        ));
    }
    let replay_rows = sqlx::query(
        "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
         FROM authbus_replay_sequences ORDER BY issuer_id, key_epoch, subject_id, scope_digest LIMIT ?",
    ).bind(MAX_REPLAY_ROWS + 1).fetch_all(&mut **transaction).await.map_err(classify_sqlx_error)?;
    if replay_rows.len() > MAX_REPLAY_ROWS as usize {
        return Err(EvidenceError::Unavailable(
            "AuthBus replay frontier exceeds capacity".into(),
        ));
    }
    let mut replay_frontier = empty_frontier(b"hepta.evidence.authbus-replay-frontier.v1");
    for row in replay_rows {
        let issuer_id: String = row.try_get("issuer_id").map_err(classify_sqlx_error)?;
        let key_epoch: Vec<u8> = row.try_get("key_epoch").map_err(classify_sqlx_error)?;
        let subject_id: String = row.try_get("subject_id").map_err(classify_sqlx_error)?;
        let scope_digest: Vec<u8> = row.try_get("scope_digest").map_err(classify_sqlx_error)?;
        let sequence: Vec<u8> = row.try_get("sequence").map_err(classify_sqlx_error)?;
        let envelope_digest: Vec<u8> = row
            .try_get("envelope_digest")
            .map_err(classify_sqlx_error)?;
        if key_epoch.len() != 8
            || scope_digest.len() != 32
            || sequence.len() != 8
            || envelope_digest.len() != 32
        {
            return Err(EvidenceError::Corrupt(
                "AuthBus replay frontier contains invalid widths".into(),
            ));
        }
        replay_frontier = extend_frontier(
            b"hepta.evidence.authbus-replay-frontier.v1",
            &replay_frontier,
            &[
                issuer_id.as_bytes(),
                &key_epoch,
                subject_id.as_bytes(),
                &scope_digest,
                &sequence,
                &envelope_digest,
            ],
        );
    }
    Ok(EvidenceRecoverySnapshotV1 {
        schema_version: match domain {
            Domain::LegacyEnvelope => 1,
            Domain::AuthenticatedAdmission => 2,
        },
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: migration_frontier,
        qualification_max_seq: last_seq as u64,
        qualification_frontier_sha256: qualification_frontier,
        authbus_replay_frontier_sha256: replay_frontier,
    })
}

fn empty_frontier(domain: &[u8]) -> Sha256Digest {
    let mut bytes = domain.to_vec();
    bytes.push(0);
    Sha256Digest::for_bytes(&bytes)
}

fn extend_frontier(domain: &[u8], previous: &Sha256Digest, parts: &[&[u8]]) -> Sha256Digest {
    let mut bytes = domain.to_vec();
    bytes.push(0);
    bytes.extend_from_slice(previous.as_str().as_bytes());
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
}
