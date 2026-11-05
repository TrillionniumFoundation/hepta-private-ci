//! Recovery commitment to the ordinary governance provider invocation history.
//! This covers pending attempts and terminal observations; it does not publish
//! an external checkpoint or make provider dispatch atomic with recovery.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::canonical::canonical_json;
use crate::provider_record::decode_provider_intent_row;
use crate::provider_record::decode_provider_receipt_row;
use crate::recovery_frontier::empty_frontier;
use crate::recovery_frontier::extend_frontier;
use crate::schema_validation::classify_sqlx_error;

const DOMAIN: &[u8] = b"hepta.evidence.provider-invocation-frontier.v1";
const MAX_ROWS: u64 = 1_000_000;
const PAGE_ROWS: i64 = 256;

pub(super) async fn snapshot(
    connection: &mut SqliteConnection,
) -> Result<(u64, Sha256Digest), EvidenceError> {
    crate::recovery_invocation_schema::verify(connection).await?;
    let mut frontier = empty_frontier(DOMAIN);
    let mut count = 0_u64;
    for (kind, query) in [
        (
            "intent",
            "SELECT * FROM provider_invocation_intents WHERE seq >= ? ORDER BY seq LIMIT ?",
        ),
        (
            "terminal",
            "SELECT terminals.*, intents.payload_json AS authoritative_intent_payload
             FROM provider_invocation_terminals AS terminals
             LEFT JOIN provider_invocation_intents AS intents
               ON intents.attempt_id = terminals.attempt_id
              AND intents.request_binding_id = terminals.request_binding_id
             WHERE terminals.seq >= ? ORDER BY terminals.seq LIMIT ?",
        ),
    ] {
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
                        "provider invocation recovery frontier exceeds one million rows".into(),
                    ));
                }
                let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
                if seq <= 0 || next_seq.is_none_or(|minimum| seq < minimum) {
                    return Err(EvidenceError::Corrupt(
                        "provider invocation recovery contains a nonpositive or repeated sequence"
                            .into(),
                    ));
                }
                // Recheck canonical payloads, derived identities and every
                // projected column inside this snapshot, not just at open.
                if kind == "intent" {
                    decode_provider_intent_row(&row)?;
                } else {
                    let receipt = decode_provider_receipt_row(&row)?;
                    // Every intent was fully validated by the first pass in
                    // this same SQLite snapshot. The join checks the actual
                    // stored intent without a separate query for every receipt.
                    let authoritative: Option<String> = row
                        .try_get("authoritative_intent_payload")
                        .map_err(classify_sqlx_error)?;
                    if authoritative.as_deref().map(str::as_bytes)
                        != Some(canonical_json(&receipt.intent)?.as_slice())
                    {
                        return Err(EvidenceError::Corrupt(
                            "provider invocation terminal lacks its exact authoritative intent"
                                .into(),
                        ));
                    }
                }
                let digest: String = row.try_get("payload_sha256").map_err(classify_sqlx_error)?;
                let recorded: i64 = row.try_get("recorded_at_ms").map_err(classify_sqlx_error)?;
                // The verified payload commits every semantic column; table,
                // sequence and local recording time are committed separately.
                frontier = extend_frontier(
                    DOMAIN,
                    &frontier,
                    &[
                        kind.as_bytes(),
                        &seq.to_be_bytes(),
                        digest.as_bytes(),
                        &recorded.to_be_bytes(),
                    ],
                );
                count += 1;
                next_seq = seq.checked_add(1);
            }
        }
    }
    Ok((count, frontier))
}
