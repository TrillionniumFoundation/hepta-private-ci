//! Recovery-only commitment to provider intents, uncertainty and receipts.
//! A digest does not supply freshness; admission still needs an independently
//! retained checkpoint. This never authorizes or dispatches an effect.

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::provider_effect_store::decode_effect_ack_row;
use crate::provider_effect_store::decode_effect_intent_row;
use crate::provider_effect_store::decode_effect_uncertainty_row;
use crate::recovery_frontier::empty_frontier;
use crate::recovery_frontier::extend_frontier;
use crate::schema_validation::classify_sqlx_error;

const DOMAIN: &[u8] = b"hepta.evidence.provider-effect-frontier.v1";
const MAX_ROWS: u64 = 1_000_000;
const PAGE_ROWS: u16 = 256;

pub(super) async fn snapshot(
    connection: &mut SqliteConnection,
) -> Result<(u64, Sha256Digest), EvidenceError> {
    // Table identity and sequence are both committed. Independent table
    // sequences do not provide cross-table ordering; recorded_at_ms and ACK
    // source provenance are separate from the canonical record digest.
    let queries = [
        (
            "intent",
            "SELECT *, '' AS source
             FROM provider_effect_intents WHERE seq >= ? ORDER BY seq LIMIT ?",
        ),
        (
            "ack",
            "SELECT acknowledgements.*, intents.payload_json AS authoritative_intent_payload
             FROM provider_effect_acknowledgements AS acknowledgements
             LEFT JOIN provider_effect_intents AS intents
               ON intents.effect_key = acknowledgements.effect_key
             WHERE acknowledgements.seq >= ? ORDER BY acknowledgements.seq LIMIT ?",
        ),
        (
            "uncertainty",
            "SELECT uncertainties.*, '' AS source,
                    intents.payload_json AS authoritative_intent_payload
             FROM provider_effect_uncertainties AS uncertainties
             LEFT JOIN provider_effect_intents AS intents
               ON intents.effect_key = uncertainties.effect_key
             WHERE uncertainties.seq >= ? ORDER BY uncertainties.seq LIMIT ?",
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
                .bind(i64::from(PAGE_ROWS) + 1)
                .fetch_all(&mut *connection)
                .await
                .map_err(classify_sqlx_error)?;
            if rows.is_empty() {
                break;
            }
            // The extra row makes a repeated sequence at the page boundary
            // visible before advancing the keyset cursor. This also covers a
            // repeated i64::MAX, where there is no representable next cursor.
            for adjacent in rows.windows(2) {
                let previous: i64 = adjacent[0].try_get("seq").map_err(classify_sqlx_error)?;
                let following: i64 = adjacent[1].try_get("seq").map_err(classify_sqlx_error)?;
                if following <= previous {
                    return Err(EvidenceError::Corrupt(
                        "provider effect recovery contains a nonpositive or repeated sequence"
                            .into(),
                    ));
                }
            }
            for row in rows.into_iter().take(usize::from(PAGE_ROWS)) {
                if count == MAX_ROWS {
                    return Err(EvidenceError::Unavailable(
                        "provider effect recovery frontier exceeds one million rows".into(),
                    ));
                }
                let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
                if seq <= 0 || next_seq.is_none_or(|minimum| seq < minimum) {
                    return Err(EvidenceError::Corrupt(
                        "provider effect recovery contains a nonpositive or repeated sequence"
                            .into(),
                    ));
                }
                let key: String = row.try_get("effect_key").map_err(classify_sqlx_error)?;
                // Open-time row verification predates this SQLite snapshot.
                // Validate every projected column and the exact stored intent,
                // not only the retained digest of the canonical JSON bytes.
                if kind == "intent" {
                    decode_effect_intent_row(&row)?;
                } else {
                    // The first pass fully validated each authoritative intent
                    // inside this same SQLite snapshot. A LEFT JOIN also keeps
                    // orphan observations visible so they fail closed here.
                    let authoritative: Option<String> = row
                        .try_get("authoritative_intent_payload")
                        .map_err(classify_sqlx_error)?;
                    let authoritative = authoritative.ok_or_else(|| {
                        EvidenceError::Corrupt(
                            "provider effect observation lacks its authoritative intent".into(),
                        )
                    })?;
                    let intent: ProviderEffectIntent = serde_json::from_str(&authoritative)
                        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
                    if kind == "ack" {
                        decode_effect_ack_row(&row, &intent)?;
                    } else {
                        decode_effect_uncertainty_row(&row, &intent)?;
                    }
                }
                let digest: String = row.try_get("record_sha256").map_err(classify_sqlx_error)?;
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
