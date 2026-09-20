use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

pub const EVIDENCE_DATABASE_LINEAGE: &str = "hepta_evidence_2.sqlite";
const MAX_QUALIFICATION_FRONTIER_ROWS: usize = 1_000_000;
const MAX_AUTHBUS_REPLAY_FRONTIER_ROWS: usize = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoverySnapshotV1 {
    pub schema_version: u32,
    pub database_lineage: String,
    pub migration_set_sha256: Sha256Digest,
    pub qualification_max_seq: u64,
    pub qualification_frontier_sha256: Sha256Digest,
    pub authbus_replay_frontier_sha256: Sha256Digest,
}

impl HeptaEvidenceStore {
    pub async fn recovery_snapshot(&self) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
        let migration_rows = sqlx::query(
            "SELECT version, description, checksum
             FROM _sqlx_migrations
             WHERE success = 1
             ORDER BY version",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let mut migration_frontier = empty_frontier(b"hepta.evidence.migrations.v1");
        for row in migration_rows {
            let version: i64 = row.try_get("version").map_err(classify_sqlx_error)?;
            let description: String =
                row.try_get("description").map_err(classify_sqlx_error)?;
            let checksum: Vec<u8> = row.try_get("checksum").map_err(classify_sqlx_error)?;
            migration_frontier = extend_frontier(
                b"hepta.evidence.migrations.v1",
                &migration_frontier,
                &[
                    &version.to_be_bytes(),
                    description.as_bytes(),
                    checksum.as_slice(),
                ],
            );
        }

        let qualification_rows = sqlx::query(
            "SELECT seq, evidence_id, envelope_sha256
             FROM qualification_evidence
             ORDER BY seq ASC
             LIMIT ?",
        )
        .bind(i64::try_from(MAX_QUALIFICATION_FRONTIER_ROWS + 1).map_err(|_| {
            EvidenceError::InvalidRecord("qualification recovery bound overflow".into())
        })?)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if qualification_rows.len() > MAX_QUALIFICATION_FRONTIER_ROWS {
            return Err(EvidenceError::Unavailable(
                "qualification recovery frontier exceeds one million rows".to_string(),
            ));
        }
        let mut qualification_frontier =
            empty_frontier(b"hepta.evidence.qualification-frontier.v1");
        let mut qualification_max_seq = 0_u64;
        for row in qualification_rows {
            let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
            let seq = u64::try_from(seq)
                .map_err(|_| EvidenceError::Corrupt("negative qualification sequence".into()))?;
            let evidence_id: String =
                row.try_get("evidence_id").map_err(classify_sqlx_error)?;
            let envelope_sha256: String =
                row.try_get("envelope_sha256").map_err(classify_sqlx_error)?;
            qualification_frontier = extend_frontier(
                b"hepta.evidence.qualification-frontier.v1",
                &qualification_frontier,
                &[
                    &seq.to_be_bytes(),
                    evidence_id.as_bytes(),
                    envelope_sha256.as_bytes(),
                ],
            );
            qualification_max_seq = seq;
        }

        let replay_rows = sqlx::query(
            "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
             FROM authbus_replay_sequences
             ORDER BY issuer_id, key_epoch, subject_id, scope_digest
             LIMIT ?",
        )
        .bind(i64::try_from(MAX_AUTHBUS_REPLAY_FRONTIER_ROWS + 1).map_err(|_| {
            EvidenceError::InvalidRecord("AuthBus recovery bound overflow".into())
        })?)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if replay_rows.len() > MAX_AUTHBUS_REPLAY_FRONTIER_ROWS {
            return Err(EvidenceError::Unavailable(
                "AuthBus replay recovery frontier exceeds registered capacity".to_string(),
            ));
        }
        let mut replay_frontier = empty_frontier(b"hepta.evidence.authbus-replay-frontier.v1");
        for row in replay_rows {
            let issuer_id: String =
                row.try_get("issuer_id").map_err(classify_sqlx_error)?;
            let key_epoch: Vec<u8> =
                row.try_get("key_epoch").map_err(classify_sqlx_error)?;
            let subject_id: String =
                row.try_get("subject_id").map_err(classify_sqlx_error)?;
            let scope_digest: Vec<u8> =
                row.try_get("scope_digest").map_err(classify_sqlx_error)?;
            let sequence: Vec<u8> =
                row.try_get("sequence").map_err(classify_sqlx_error)?;
            let envelope_digest: Vec<u8> =
                row.try_get("envelope_digest").map_err(classify_sqlx_error)?;
            if key_epoch.len() != 8
                || scope_digest.len() != 32
                || sequence.len() != 8
                || envelope_digest.len() != 32
            {
                return Err(EvidenceError::Corrupt(
                    "AuthBus replay frontier contains invalid fixed-width fields".to_string(),
                ));
            }
            replay_frontier = extend_frontier(
                b"hepta.evidence.authbus-replay-frontier.v1",
                &replay_frontier,
                &[
                    issuer_id.as_bytes(),
                    key_epoch.as_slice(),
                    subject_id.as_bytes(),
                    scope_digest.as_slice(),
                    sequence.as_slice(),
                    envelope_digest.as_slice(),
                ],
            );
        }

        Ok(EvidenceRecoverySnapshotV1 {
            schema_version: 1,
            database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
            migration_set_sha256: migration_frontier,
            qualification_max_seq,
            qualification_frontier_sha256: qualification_frontier,
            authbus_replay_frontier_sha256: replay_frontier,
        })
    }
}

fn empty_frontier(domain: &[u8]) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(domain.len() + 1);
    bytes.extend_from_slice(domain);
    bytes.push(0);
    Sha256Digest::for_bytes(&bytes)
}

fn extend_frontier(
    domain: &[u8],
    previous: &Sha256Digest,
    parts: &[&[u8]],
) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(
        domain.len()
            + previous.as_str().len()
            + parts.iter().map(|part| part.len() + 8).sum::<usize>()
            + 2,
    );
    bytes.extend_from_slice(domain);
    bytes.push(0);
    bytes.extend_from_slice(previous.as_str().as_bytes());
    for part in parts {
        bytes.extend_from_slice(
            &u64::try_from(part.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
}
