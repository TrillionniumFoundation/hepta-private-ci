//! Recovery-only commitment to provider intents, uncertainty and receipts.
//! A digest does not supply freshness; admission still needs an independently
//! retained checkpoint. This never authorizes or dispatches an effect.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::provider_effect_store::verify_record_digest;
use crate::recovery_frontier::empty_frontier;
use crate::recovery_frontier::extend_frontier;
use crate::schema_validation::classify_sqlx_error;

const DOMAIN: &[u8] = b"hepta.evidence.provider-effect-frontier.v1";
const MAX_ROWS: u64 = 1_000_000;
const PAGE_ROWS: i64 = 256;

pub(super) async fn snapshot(
    connection: &mut SqliteConnection,
) -> Result<(u64, Sha256Digest), EvidenceError> {
    // Table identity and sequence are both committed. Independent table
    // sequences do not provide cross-table ordering; recorded_at_ms and ACK
    // source provenance are separate from the canonical record digest.
    let queries = [
        (
            "intent",
            "SELECT seq, effect_key, payload_json, record_sha256, recorded_at_ms, '' AS source
         FROM provider_effect_intents WHERE seq >= ? ORDER BY seq LIMIT ?",
        ),
        (
            "ack",
            "SELECT seq, effect_key, payload_json, record_sha256, recorded_at_ms, source
         FROM provider_effect_acknowledgements WHERE seq >= ? ORDER BY seq LIMIT ?",
        ),
        (
            "uncertainty",
            "SELECT seq, effect_key, payload_json, record_sha256, recorded_at_ms, '' AS source
         FROM provider_effect_uncertainties WHERE seq >= ? ORDER BY seq LIMIT ?",
        ),
    ];
    let mut frontier = empty_frontier(DOMAIN);
    let mut count = 0_u64;
    for (kind, query) in queries {
        // A direct primary-key range keeps later pages from rescanning the
        // prefix. Starting at MIN also refuses corrupt nonpositive sequences.
        let mut next_seq = Some(i64::MIN);
        while let Some(lower_bound) = next_seq {
            let rows = sqlx::query(query)
                .bind(lower_bound)
                .bind(PAGE_ROWS)
                .fetch_all(&mut *connection)
                .await
                .map_err(classify_sqlx_error)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                if count == MAX_ROWS {
                    return Err(EvidenceError::Unavailable(
                        "provider effect recovery frontier exceeds one million rows".into(),
                    ));
                }
                let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
                if seq <= 0 {
                    return Err(EvidenceError::Corrupt(
                        "provider effect recovery contains a nonpositive sequence".into(),
                    ));
                }
                let key: String = row.try_get("effect_key").map_err(classify_sqlx_error)?;
                let payload: String = row.try_get("payload_json").map_err(classify_sqlx_error)?;
                let digest: String = row.try_get("record_sha256").map_err(classify_sqlx_error)?;
                // Open-time row verification predates this SQLite snapshot.
                // Recheck actual bytes here rather than trust a retained label.
                verify_record_digest(&payload, &digest, kind)?;
                let recorded: i64 = row.try_get("recorded_at_ms").map_err(classify_sqlx_error)?;
                let source: Option<String> = row.try_get("source").map_err(classify_sqlx_error)?;
                let source = source.ok_or_else(|| {
                    EvidenceError::Corrupt(
                        "provider effect recovery lacks ACK source provenance".into(),
                    )
                })?;
                frontier = extend_frontier(
                    DOMAIN,
                    &frontier,
                    &[
                        kind.as_bytes(),
                        &seq.to_be_bytes(),
                        key.as_bytes(),
                        digest.as_bytes(),
                        &recorded.to_be_bytes(),
                        source.as_bytes(),
                    ],
                );
                count += 1;
                next_seq = seq.checked_add(1);
            }
        }
    }
    Ok((count, frontier))
}
