use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::ProviderEffectUncertainty;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::AppendDisposition;
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

#[tokio::test]
async fn repeated_status_ack_persists_provenance_and_fences_late_dispatch_after_restart() {
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
    let before = store.recovery_snapshot().await.expect("dispatch snapshot");
    assert_eq!(
        store
            .append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            )
            .await
            .expect("authoritative re-observation"),
        AppendDisposition::Inserted,
        "identical ACK bytes from a new source are a new durable observation"
    );
    let after = store.recovery_snapshot().await.expect("status snapshot");
    assert_ne!(
        after, before,
        "the recovery commitment must retain the provenance boundary"
    );
    assert_eq!(
        store
            .append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            )
            .await
            .expect("identical latest observation replay"),
        AppendDisposition::AlreadyPresent
    );
    assert!(matches!(
        store.append_provider_effect_ack(&completed).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    store.close().await;

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen status history");
    assert_eq!(
        reopened
            .recovery_snapshot()
            .await
            .expect("reopened snapshot"),
        after
    );
    assert!(matches!(
        reopened.append_provider_effect_ack(&completed).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    reopened
        .append_provider_effect_ack_from_source(&completed, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("provider-owned completion remains legal");
    assert_eq!(
        reopened
            .get_provider_effect(&intent.key)
            .await
            .expect("effect read")
            .expect("stored effect")
            .state(),
        ProviderEffectState::Completed
    );
}

#[tokio::test]
async fn repeated_unknown_and_status_observations_survive_recovery_without_erasing_quarantine() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let (intent, accepted, completed) = intent_and_acknowledgements();
    let mut store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack_from_source(&accepted, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("first authoritative acceptance");
    for _ in 0..3 {
        let prior = store.recovery_snapshot().await.expect("prior snapshot");
        assert_eq!(
            store
                .mark_provider_effect_indeterminate(&intent.key, "provider_lookup_unknown")
                .await
                .expect("new unknown observation"),
            AppendDisposition::Inserted
        );
        let quarantined = store
            .get_provider_effect(&intent.key)
            .await
            .expect("read quarantine")
            .expect("stored effect");
        assert_eq!(quarantined.state(), ProviderEffectState::Indeterminate);
        let unknown = store.recovery_snapshot().await.expect("unknown snapshot");
        assert_ne!(unknown, prior);
        assert_eq!(
            store
                .mark_provider_effect_indeterminate(&intent.key, "provider_lookup_unknown")
                .await
                .expect("same latest unknown replay"),
            AppendDisposition::AlreadyPresent
        );
        assert_eq!(
            store
                .recovery_snapshot()
                .await
                .expect("replayed unknown snapshot"),
            unknown
        );
        store.close().await;
        store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("reopen quarantine");
        assert_eq!(
            store
                .get_provider_effect(&intent.key)
                .await
                .expect("read restored quarantine")
                .expect("stored effect"),
            quarantined
        );
        assert_eq!(
            store
                .append_provider_effect_ack_from_source(
                    &accepted,
                    ProviderEffectAckSource::StatusLookup
                )
                .await
                .expect("fresh authoritative acceptance after unknown"),
            AppendDisposition::Inserted
        );
        assert_eq!(
            store
                .get_provider_effect(&intent.key)
                .await
                .expect("read acceptance")
                .expect("stored effect")
                .state(),
            ProviderEffectState::Accepted
        );
    }
    store
        .append_provider_effect_ack_from_source(&completed, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("terminal completion");
    assert!(matches!(
        store
            .mark_provider_effect_indeterminate(&intent.key, "provider_lookup_unknown")
            .await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    store.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen complete history");
    let effect = reopened
        .get_provider_effect(&intent.key)
        .await
        .expect("read complete history")
        .expect("stored effect");
    assert_eq!(effect.state(), ProviderEffectState::Completed);
    assert_eq!(
        (effect.acknowledgements.len(), effect.uncertainties.len()),
        (5, 3)
    );
}

#[tokio::test]
async fn exhausted_observation_clock_refuses_new_events_without_forgetting_exact_retries() {
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
    let bytes = crate::canonical::canonical_json(&accepted).expect("canonical accepted ACK");
    sqlx::query(
        "INSERT INTO provider_effect_acknowledgements (
        effect_key, payload_sha256, provider_operation_id_sha256, status,
        schema_version, payload_json, record_sha256, recorded_at_ms, source
        ) VALUES (?, ?, ?, 'accepted', 1, ?, ?, ?, 'status_lookup')",
    )
    .bind(accepted.key.as_str())
    .bind(accepted.payload_sha256.as_str())
    .bind(accepted.provider_operation_id_sha256.as_str())
    .bind(String::from_utf8(bytes.clone()).expect("ACK JSON"))
    .bind(Sha256Digest::for_bytes(&bytes).as_str())
    .bind(i64::MAX)
    .execute(&store.pool)
    .await
    .expect("import exhausted ordering clock");
    let before = store.recovery_snapshot().await.expect("exhausted snapshot");
    assert!(
        matches!(store.append_provider_effect_ack_from_source(&completed, ProviderEffectAckSource::StatusLookup).await,
        Err(EvidenceError::Corrupt(detail)) if detail.contains("clock is exhausted"))
    );
    assert!(
        matches!(store.mark_provider_effect_indeterminate(&intent.key, "later_unknown").await,
        Err(EvidenceError::Corrupt(detail)) if detail.contains("clock is exhausted"))
    );
    assert_eq!(
        store
            .append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            )
            .await
            .expect("exact latest ACK retry"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .recovery_snapshot()
            .await
            .expect("no ambiguous event was appended"),
        before
    );
}

#[tokio::test]
async fn separate_store_writers_preserve_latest_observation_idempotency() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("first writer");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second writer");
    let (intent, accepted, _) = intent_and_acknowledgements();
    first
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    for round in 0..2 {
        let (a, b) = tokio::join!(
            first.append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            ),
            second.append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            )
        );
        let dispositions = [a.expect("first ACK result"), b.expect("second ACK result")];
        assert_eq!(
            dispositions
                .iter()
                .filter(|value| **value == AppendDisposition::Inserted)
                .count(),
            1
        );
        assert_eq!(
            dispositions
                .iter()
                .filter(|value| **value == AppendDisposition::AlreadyPresent)
                .count(),
            1
        );
        let (a, b) = tokio::join!(
            first.mark_provider_effect_indeterminate(&intent.key, "same_unknown"),
            second.mark_provider_effect_indeterminate(&intent.key, "same_unknown")
        );
        let dispositions = [
            a.expect("first unknown result"),
            b.expect("second unknown result"),
        ];
        assert_eq!(
            dispositions
                .iter()
                .filter(|value| **value == AppendDisposition::Inserted)
                .count(),
            1
        );
        assert_eq!(
            dispositions
                .iter()
                .filter(|value| **value == AppendDisposition::AlreadyPresent)
                .count(),
            1
        );
        let effect = first
            .get_provider_effect(&intent.key)
            .await
            .expect("observed effect")
            .expect("effect");
        assert_eq!(effect.state(), ProviderEffectState::Indeterminate);
        assert_eq!(
            (effect.acknowledgements.len(), effect.uncertainties.len()),
            (round + 1, round + 1)
        );
    }
    assert_eq!(
        first.recovery_snapshot().await.expect("first snapshot"),
        second.recovery_snapshot().await.expect("second snapshot")
    );
}

#[tokio::test]
async fn terminal_status_reobservation_cannot_hide_an_intervening_imported_uncertainty() {
    for status in [
        ProviderEffectAckStatus::Completed,
        ProviderEffectAckStatus::Rejected,
    ] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let (intent, _, mut terminal) = intent_and_acknowledgements();
        terminal.status = status;
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("intent");
        store
            .append_provider_effect_ack(&terminal)
            .await
            .expect("first terminal result");
        assert!(matches!(
            store
                .mark_provider_effect_indeterminate(&intent.key, "late_unknown")
                .await,
            Err(EvidenceError::IdempotencyConflict { .. })
        ));
        let first_terminal_at = store
            .get_provider_effect(&intent.key)
            .await
            .expect("terminal history")
            .expect("stored effect")
            .acknowledgements[0]
            .recorded_at_ms;

        // Preserve canonical bytes, operation identity, schema and ordering.
        // Only the forbidden uncertainty after the first terminal is imported.
        let unknown = ProviderEffectUncertainty::new(
            intent.key.clone(),
            intent.payload_sha256.clone(),
            "late_unknown",
        );
        let bytes = crate::canonical::canonical_json(&unknown).expect("canonical uncertainty");
        sqlx::query(
            "INSERT INTO provider_effect_uncertainties (
            effect_key, payload_sha256, reason_code, schema_version,
            payload_json, record_sha256, recorded_at_ms
            ) VALUES (?, ?, ?, 1, ?, ?, ?)",
        )
        .bind(intent.key.as_str())
        .bind(intent.payload_sha256.as_str())
        .bind(&unknown.reason_code)
        .bind(String::from_utf8(bytes.clone()).expect("unknown JSON"))
        .bind(Sha256Digest::for_bytes(&bytes).as_str())
        .bind(first_terminal_at + 1)
        .execute(&store.pool)
        .await
        .expect("import intervening unknown");
        let bytes = crate::canonical::canonical_json(&terminal).expect("canonical terminal ACK");
        let status_text = match status {
            ProviderEffectAckStatus::Completed => "completed",
            ProviderEffectAckStatus::Rejected => "rejected",
            ProviderEffectAckStatus::Accepted => unreachable!("terminal fixtures only"),
        };
        sqlx::query(
            "INSERT INTO provider_effect_acknowledgements (
            effect_key, payload_sha256, provider_operation_id_sha256, status,
            schema_version, payload_json, record_sha256, recorded_at_ms, source
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'status_lookup')",
        )
        .bind(terminal.key.as_str())
        .bind(terminal.payload_sha256.as_str())
        .bind(terminal.provider_operation_id_sha256.as_str())
        .bind(status_text)
        .bind(String::from_utf8(bytes.clone()).expect("terminal JSON"))
        .bind(Sha256Digest::for_bytes(&bytes).as_str())
        .bind(first_terminal_at + 2)
        .execute(&store.pool)
        .await
        .expect("import later status re-observation");
        store.close().await;
        assert!(matches!(HeptaEvidenceStore::open(&sqlite).await,
            Err(EvidenceError::Corrupt(detail)) if detail.contains("uncertainty follows terminal ACK")));
    }
}
