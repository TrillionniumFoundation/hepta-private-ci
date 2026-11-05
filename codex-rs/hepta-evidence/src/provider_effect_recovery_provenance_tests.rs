use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn intent_and_acknowledgements() -> (ProviderEffectIntent, ProviderEffectAck, ProviderEffectAck) {
    let key =
        ProviderEffectKey::for_operation("provider", "run", "step").expect("stable operation key");
    let intent = ProviderEffectIntent::new(key, Sha256Digest::for_bytes(b"immutable payload"));
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original operation"),
        ProviderEffectAckStatus::Accepted,
    );
    let completed = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        accepted.provider_operation_id_sha256.clone(),
        ProviderEffectAckStatus::Completed,
    );
    (intent, accepted, completed)
}

#[tokio::test]
async fn recovery_provenance_rejects_late_dispatch_after_status_without_uncertainty() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let (intent, accepted, completed) = intent_and_acknowledgements();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack_from_source(&accepted, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("provider-owned acceptance");

    // The live append boundary refuses this delayed response even when the
    // key, payload, operation ID and status transition otherwise match.
    assert!(matches!(
        store.append_provider_effect_ack(&completed).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    let before = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read acceptance")
        .expect("stored effect");
    assert_eq!(before.state(), ProviderEffectState::Accepted);
    assert!(before.uncertainties.is_empty());

    // Model an imported database that bypassed only the live append API.
    // Preserve canonical bytes, exact operation binding, schema and strictly
    // increasing timestamps. No uncertainty marker may mask the missing
    // startup provenance check.
    let bytes = crate::canonical::canonical_json(&completed).expect("canonical ACK");
    let digest = Sha256Digest::for_bytes(&bytes);
    let json = String::from_utf8(bytes).expect("ACK JSON");
    let recorded_at_ms = before.acknowledgements[0].recorded_at_ms + 1;
    sqlx::query(
        "INSERT INTO provider_effect_acknowledgements (
            effect_key, payload_sha256, provider_operation_id_sha256,
            status, source, schema_version, payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, 'completed', 'dispatch_response', ?, ?, ?, ?)",
    )
    .bind(completed.key.as_str())
    .bind(completed.payload_sha256.as_str())
    .bind(completed.provider_operation_id_sha256.as_str())
    .bind(i64::from(completed.schema_version))
    .bind(json)
    .bind(digest.as_str())
    .bind(recorded_at_ms)
    .execute(&store.pool)
    .await
    .expect("import delayed dispatch response");
    drop(store);

    assert!(matches!(
        HeptaEvidenceStore::open(&sqlite).await,
        Err(EvidenceError::Corrupt(detail))
            if detail.contains("dispatch ACK follows status lookup")
    ));
}

#[tokio::test]
async fn recovery_provenance_preserves_dispatch_then_authoritative_status() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let (intent, accepted, completed) = intent_and_acknowledgements();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("dispatch acceptance");
    store
        .append_provider_effect_ack_from_source(&completed, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("provider-owned completion");
    let before = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read effect")
        .expect("stored effect");
    assert_eq!(before.state(), ProviderEffectState::Completed);
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen valid history");
    let after = reopened
        .get_provider_effect(&intent.key)
        .await
        .expect("read reopened effect")
        .expect("stored effect");
    assert_eq!(after, before);
}
