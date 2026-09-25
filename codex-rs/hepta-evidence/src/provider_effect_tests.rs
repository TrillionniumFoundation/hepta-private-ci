use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::ProviderEffectStatusObservation;
use codex_hepta_contracts::ProviderEffectUncertainty;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::RequestBindingId;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;
use tokio::sync::Notify;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;

#[derive(Clone)]
struct DurableScriptedAdapter {
    capability: ProviderEffectIdempotencyCapability,
    dispatch_result: ProviderEffectDispatch,
    lookup_result: ProviderEffectLookup,
    dispatches: Arc<AtomicUsize>,
    lookups: Arc<AtomicUsize>,
}

#[derive(Clone)]
struct BlockingLookupAdapter {
    dispatches: Arc<AtomicUsize>,
    lookup_started: Arc<Notify>,
    release_lookup: Arc<Notify>,
}

/// Test-only adapter that models the dangerous provider boundary where the
/// request has been handed to the provider but the local process dies before
/// a response can be observed.  The durable facade must have already written
/// its boundary claim at this point; a reopened store must therefore reconcile
/// by status and never invoke `dispatch` again.
#[derive(Clone)]
struct CrashAfterSendAdapter {
    dispatches: Arc<AtomicUsize>,
    send_started: Arc<Notify>,
    hold_response: Arc<Notify>,
}

impl ProviderEffectAdapter for CrashAfterSendAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        let dispatches = self.dispatches.clone();
        let send_started = self.send_started.clone();
        let hold_response = self.hold_response.clone();
        Box::pin(async move {
            // This increment is the only local witness that the provider
            // boundary was crossed.  Holding the response lets the test abort
            // this task, modelling process death after send and before a
            // response/ACK is durable locally, without poisoning the test
            // process with an intentional panic.
            dispatches.fetch_add(1, Ordering::Relaxed);
            send_started.notify_one();
            hold_response.notified().await;
            ProviderEffectDispatch::Unknown
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }
}

impl ProviderEffectAdapter for BlockingLookupAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.dispatches.fetch_add(1, Ordering::Relaxed);
        Box::pin(async { ProviderEffectDispatch::Unknown })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        let lookup_started = self.lookup_started.clone();
        let release_lookup = self.release_lookup.clone();
        Box::pin(async move {
            lookup_started.notify_one();
            release_lookup.notified().await;
            ProviderEffectLookup::Unknown
        })
    }
}

impl ProviderEffectAdapter for DurableScriptedAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        self.capability
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.dispatches.fetch_add(1, Ordering::Relaxed);
        let result = self.dispatch_result.clone();
        Box::pin(async move { result })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        self.lookups.fetch_add(1, Ordering::Relaxed);
        let result = self.lookup_result.clone();
        Box::pin(async move { result })
    }
}

fn scripted_adapter(
    capability: ProviderEffectIdempotencyCapability,
    dispatch_result: ProviderEffectDispatch,
    lookup_result: ProviderEffectLookup,
) -> DurableScriptedAdapter {
    DurableScriptedAdapter {
        capability,
        dispatch_result,
        lookup_result,
        dispatches: Arc::new(AtomicUsize::new(0)),
        lookups: Arc::new(AtomicUsize::new(0)),
    }
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn request_binding_id() -> RequestBindingId {
    RequestBindingId::for_request(&ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-effect".to_string(),
        turn_id: "turn-effect".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-effect"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-effect-fixture".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"config-effect"),
        model: "effect-model".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/effect"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-effect"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire-effect"),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    })
}

fn effect_intent_for_occurrence(payload: &[u8], occurrence: &str) -> ProviderEffectIntent {
    let key = ProviderEffectKey::for_occurrence(
        "provider-effect-fixture/config-v1",
        occurrence,
        &request_binding_id(),
    )
    .expect("effect key");
    ProviderEffectIntent::new(key, Sha256Digest::for_bytes(payload))
}

fn effect_intent(payload: &[u8]) -> ProviderEffectIntent {
    effect_intent_for_occurrence(payload, "automation:agent-a:occurrence-1")
}

fn completed_ack(intent: &ProviderEffectIntent, operation: &[u8]) -> ProviderEffectAck {
    ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(operation),
        ProviderEffectAckStatus::Completed,
    )
}

#[tokio::test]
async fn effect_journal_quarantines_unknown_and_reconciles_after_restart() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"effect-payload");
    let key = intent.key.clone();

    assert_eq!(
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("intent"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("intent replay"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .reconcile_provider_effect_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            )
            .await
            .expect("unknown is quarantined"),
        ProviderEffectState::Indeterminate
    );
    let quarantined = store
        .get_provider_effect(&key)
        .await
        .expect("read quarantine")
        .expect("effect");
    assert_eq!(quarantined.state(), ProviderEffectState::Indeterminate);
    assert_eq!(quarantined.uncertainties.len(), 1);
    assert!(quarantined.acknowledgements.is_empty());

    assert_eq!(
        store
            .append_provider_effect_ack_from_source(
                &completed_ack(&intent, b"operation-after-unknown"),
                codex_hepta_contracts::ProviderEffectAckSource::StatusLookup,
            )
            .await
            .expect("reconciled completion"),
        AppendDisposition::Inserted
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let completed = reopened
        .get_provider_effect(&key)
        .await
        .expect("read completed")
        .expect("effect");
    assert_eq!(completed.state(), ProviderEffectState::Completed);
    assert_eq!(completed.uncertainties.len(), 1);
    assert_eq!(completed.acknowledgements.len(), 1);
}

#[tokio::test]
async fn late_dispatch_ack_after_quarantine_requires_status_lookup_source() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"source-bound-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .mark_provider_effect_indeterminate(&key, "provider_dispatch_unknown")
        .await
        .expect("quarantine");

    let ack = completed_ack(&intent, b"status-operation");
    let late_dispatch = store
        .append_provider_effect_ack(&ack)
        .await
        .expect_err("a raw dispatch ACK cannot close a quarantined occurrence");
    assert!(matches!(
        late_dispatch,
        EvidenceError::IdempotencyConflict { .. }
    ));

    assert_eq!(
        store
            .append_provider_effect_ack_from_source(&ack, ProviderEffectAckSource::StatusLookup)
            .await
            .expect("status lookup may reconcile the quarantine"),
        AppendDisposition::Inserted
    );
    let stored = store
        .get_provider_effect(&key)
        .await
        .expect("read effect")
        .expect("effect");
    assert_eq!(
        stored.acknowledgements[0].source,
        ProviderEffectAckSource::StatusLookup
    );
}

#[tokio::test]
async fn duplicate_dispatch_ack_after_quarantine_requires_status_lookup_source() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"duplicate-after-quarantine-payload");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"accepted-before-quarantine"),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("accepted ACK");
    store
        .mark_provider_effect_indeterminate(&intent.key, "late_network_unknown")
        .await
        .expect("quarantine");

    let replay = store
        .append_provider_effect_ack(&accepted)
        .await
        .expect_err("raw duplicate ACK must remain fenced");
    assert!(matches!(replay, EvidenceError::IdempotencyConflict { .. }));
    assert_eq!(
        store
            .append_provider_effect_ack_from_source(
                &accepted,
                ProviderEffectAckSource::StatusLookup
            )
            .await
            .expect("status lookup duplicate is idempotent"),
        AppendDisposition::AlreadyPresent
    );
}

#[tokio::test]
async fn durable_status_observation_binds_payload_and_persists_lookup_provenance() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"status-observation-payload");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted_ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"status-operation"),
        ProviderEffectAckStatus::Accepted,
    );
    let accepted = ProviderEffectStatusObservation::from_ack(&accepted_ack);
    assert_eq!(
        store
            .append_provider_effect_status_observation(&accepted)
            .await
            .expect("status observation"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .append_provider_effect_status_observation(&accepted)
            .await
            .expect("status replay"),
        AppendDisposition::AlreadyPresent
    );

    let mut forged_source = accepted.clone();
    forged_source.source = ProviderEffectAckSource::DispatchResponse;
    assert!(matches!(
        store
            .append_provider_effect_status_observation(&forged_source)
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));

    let mut forged_payload = accepted.clone();
    forged_payload.payload_sha256 = Sha256Digest::for_bytes(b"different-payload");
    assert!(matches!(
        store
            .append_provider_effect_status_observation(&forged_payload)
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));

    let completed = ProviderEffectStatusObservation::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        accepted.provider_operation_id_sha256.clone(),
        ProviderEffectAckStatus::Completed,
    );
    assert_eq!(
        store
            .reconcile_provider_effect_status_observation(&completed)
            .await
            .expect("completed status observation"),
        ProviderEffectState::Completed
    );

    let stored = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read effect")
        .expect("effect");
    assert_eq!(stored.state(), ProviderEffectState::Completed);
    assert_eq!(stored.acknowledgements.len(), 2);
    assert!(
        stored
            .acknowledgements
            .iter()
            .all(|ack| ack.source == ProviderEffectAckSource::StatusLookup)
    );

    // A late raw dispatch response cannot overwrite the provider-owned
    // provenance, even when its ACK payload is an exact replay.
    assert!(matches!(
        store.append_provider_effect_ack(&completed.to_ack()).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));

    // A terminal local state remains authoritative over a late Unknown
    // observation; no uncertainty is appended.
    assert_eq!(
        store
            .reconcile_provider_effect_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &intent.key,
                ProviderEffectLookup::Unknown,
            )
            .await
            .expect("late unknown is ignored after terminal"),
        ProviderEffectState::Completed
    );
    let after_unknown = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read terminal effect")
        .expect("effect");
    assert!(after_unknown.uncertainties.is_empty());

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let persisted = reopened
        .get_provider_effect(&intent.key)
        .await
        .expect("read persisted effect")
        .expect("effect");
    assert!(
        persisted
            .acknowledgements
            .iter()
            .all(|ack| ack.source == ProviderEffectAckSource::StatusLookup)
    );
}

#[tokio::test]
async fn durable_status_accepted_fences_late_dispatch_transition() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"status-accepted-late-dispatch");
    let operation = Sha256Digest::for_bytes(b"status-accepted-operation");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted = ProviderEffectStatusObservation::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        operation.clone(),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_status_observation(&accepted)
        .await
        .expect("status Accepted");

    let late_completed = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        operation,
        ProviderEffectAckStatus::Completed,
    );
    assert!(matches!(
        store.append_provider_effect_ack(&late_completed).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    let stored = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read effect")
        .expect("effect");
    assert_eq!(stored.state(), ProviderEffectState::Accepted);
    assert_eq!(stored.acknowledgements.len(), 1);
    assert_eq!(
        stored.acknowledgements[0].source,
        ProviderEffectAckSource::StatusLookup
    );
}

#[tokio::test]
async fn durable_status_observation_rejects_unknown_intent() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"unknown-status-observation");
    let observation = ProviderEffectStatusObservation::new(
        intent.key,
        intent.payload_sha256,
        Sha256Digest::for_bytes(b"unknown-operation"),
        ProviderEffectAckStatus::Completed,
    );
    assert!(matches!(
        store
            .append_provider_effect_status_observation(&observation)
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));
}

#[tokio::test]
async fn reopen_rejects_missing_provider_ack_source_provenance() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"missing-source-payload");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"missing-source-operation"),
        ProviderEffectAckStatus::Accepted,
    );
    let bytes = crate::canonical::canonical_json(&ack).expect("canonical ACK");
    let payload_json = String::from_utf8(bytes.clone()).expect("ACK JSON");
    let record_sha = Sha256Digest::for_bytes(&bytes);
    sqlx::query(
        "INSERT INTO provider_effect_acknowledgements (
            effect_key, payload_sha256, provider_operation_id_sha256,
            status, source, schema_version, payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, 'accepted', NULL, ?, ?, ?, 100)",
    )
    .bind(intent.key.as_str())
    .bind(ack.payload_sha256.as_str())
    .bind(ack.provider_operation_id_sha256.as_str())
    .bind(i64::from(ack.schema_version))
    .bind(&payload_json)
    .bind(record_sha.as_str())
    .execute(&store.pool)
    .await
    .expect("insert legacy-style NULL source row");
    drop(store);

    let reopen = HeptaEvidenceStore::open(&sqlite).await;
    assert!(matches!(reopen, Err(EvidenceError::Corrupt(_))));
}

#[tokio::test]
async fn reopen_rejects_provider_ack_source_check_drift_with_valid_rows() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"source-check-drift-payload");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack(&completed_ack(&intent, b"source-check-drift-operation"))
        .await
        .expect("ACK");

    // Rebuild the ACK table through ordinary DDL, preserving a valid row but
    // removing only the migration-0008 source CHECK.  This models a schema
    // tamper without relying on SQLite's writable_schema escape hatch.
    let mut schema_tx = store.pool.begin().await.expect("begin schema tamper");
    for statement in [
        "DROP TRIGGER provider_effect_acknowledgements_no_update",
        "DROP TRIGGER provider_effect_acknowledgements_no_delete",
        "DROP INDEX provider_effect_acknowledgements_key_seq",
        "CREATE TABLE provider_effect_acknowledgements_replacement (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            effect_key TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL CHECK (
                length(payload_sha256) = 64
                AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            provider_operation_id_sha256 TEXT NOT NULL CHECK (
                length(provider_operation_id_sha256) = 64
                AND provider_operation_id_sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            status TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'rejected')),
            schema_version INTEGER NOT NULL CHECK (schema_version = 1),
            payload_json TEXT NOT NULL,
            record_sha256 TEXT NOT NULL CHECK (
                length(record_sha256) = 64
                AND record_sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            recorded_at_ms INTEGER NOT NULL,
            source TEXT,
            FOREIGN KEY(effect_key)
                REFERENCES provider_effect_intents(effect_key)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            UNIQUE(effect_key, provider_operation_id_sha256, status, payload_sha256)
        )",
        "INSERT INTO provider_effect_acknowledgements_replacement (
            seq, effect_key, payload_sha256, provider_operation_id_sha256,
            status, schema_version, payload_json, record_sha256, recorded_at_ms, source
         )
         SELECT seq, effect_key, payload_sha256, provider_operation_id_sha256,
            status, schema_version, payload_json, record_sha256, recorded_at_ms, source
         FROM provider_effect_acknowledgements",
        "DROP TABLE provider_effect_acknowledgements",
        "ALTER TABLE provider_effect_acknowledgements_replacement
            RENAME TO provider_effect_acknowledgements",
        "CREATE INDEX provider_effect_acknowledgements_key_seq
            ON provider_effect_acknowledgements(effect_key, seq)",
        "CREATE TRIGGER provider_effect_acknowledgements_no_update
         BEFORE UPDATE ON provider_effect_acknowledgements
         BEGIN
             SELECT RAISE(ABORT, 'provider effect acknowledgements are immutable');
         END",
        "CREATE TRIGGER provider_effect_acknowledgements_no_delete
         BEFORE DELETE ON provider_effect_acknowledgements
         BEGIN
             SELECT RAISE(ABORT, 'provider effect acknowledgements are immutable');
         END",
    ] {
        sqlx::query(statement)
            .execute(&mut *schema_tx)
            .await
            .expect("rebuild tampered ACK schema");
    }
    schema_tx
        .commit()
        .await
        .expect("commit tampered ACK schema");

    let preserved: (i64, String) = sqlx::query_as(
        "SELECT COUNT(*), MIN(source)
         FROM provider_effect_acknowledgements",
    )
    .fetch_one(&store.pool)
    .await
    .expect("read preserved ACK");
    assert_eq!(preserved, (1, "dispatch_response".to_string()));
    let table_sql: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema
         WHERE type = 'table' AND name = 'provider_effect_acknowledgements'",
    )
    .fetch_one(&store.pool)
    .await
    .expect("read tampered schema");
    assert!(!table_sql.to_ascii_lowercase().contains("source in"));

    drop(store);
    let reopen = HeptaEvidenceStore::open(&sqlite).await;
    assert!(matches!(reopen, Err(EvidenceError::Corrupt(_))));
}

#[tokio::test]
async fn qualification_dispatch_ack_is_persisted_with_source_and_reopens() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-dispatch-completed");
    let ack = completed_ack(&intent, b"qualification-dispatch-operation");
    let adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(ack.clone()),
        ProviderEffectLookup::Ack(ack.clone()),
    );

    let receipt = store
        .dispatch_provider_effect_qualification(&adapter, &intent)
        .await
        .expect("dispatch ACK");
    assert_eq!(receipt.state, ProviderEffectState::Completed);
    assert!(receipt.dispatch_claimed);
    assert!(receipt.dispatch_attempted);
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 1);
    let stored = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read dispatched effect")
        .expect("effect");
    assert_eq!(stored.state(), ProviderEffectState::Completed);
    assert_eq!(stored.acknowledgements.len(), 1);
    assert_eq!(
        stored.acknowledgements[0].source,
        ProviderEffectAckSource::DispatchResponse
    );
    assert_eq!(stored.uncertainties.len(), 1);
    assert_eq!(
        stored.uncertainties[0].uncertainty.reason_code,
        "provider_dispatch_boundary_pending"
    );

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen successful dispatch");
    let replay_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(ack.clone()),
        ProviderEffectLookup::Ack(ack.clone()),
    );
    let replay = reopened
        .dispatch_provider_effect_qualification(&replay_adapter, &intent)
        .await
        .expect("terminal replay");
    assert_eq!(replay.state, ProviderEffectState::Completed);
    assert!(!replay.dispatch_attempted);
    assert_eq!(replay_adapter.dispatches.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn qualification_dispatch_claim_survives_reopen_without_redispatch() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-dispatch-claim");
    let key = intent.key.clone();
    let first_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Unknown,
    );
    let first = store
        .dispatch_provider_effect_qualification(&first_adapter, &intent)
        .await
        .expect("qualification dispatch");
    assert_eq!(first.state, ProviderEffectState::Indeterminate);
    assert!(first.dispatch_claimed);
    assert!(first.dispatch_attempted);
    assert_eq!(first_adapter.dispatches.load(Ordering::Relaxed), 1);

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let completion = completed_ack(&intent, b"qualification-operation");
    let replay_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(completion.clone()),
        ProviderEffectLookup::Ack(completion),
    );
    let replay = reopened
        .dispatch_provider_effect_qualification(&replay_adapter, &intent)
        .await
        .expect("replayed qualification dispatch");
    assert_eq!(replay.state, ProviderEffectState::Indeterminate);
    assert!(!replay.dispatch_attempted);
    assert_eq!(replay_adapter.dispatches.load(Ordering::Relaxed), 0);

    assert_eq!(
        reopened
            .reconcile_provider_effect_with_adapter(&replay_adapter, &key)
            .await
            .expect("lookup reconciliation"),
        ProviderEffectState::Completed
    );
    assert_eq!(replay_adapter.dispatches.load(Ordering::Relaxed), 0);
    assert_eq!(replay_adapter.lookups.load(Ordering::Relaxed), 1);
    let effect = reopened
        .get_provider_effect(&key)
        .await
        .expect("read reconciled effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Completed);
    assert_eq!(effect.acknowledgements.len(), 1);
    assert_eq!(effect.uncertainties.len(), 2);
}

#[tokio::test]
async fn qualification_crash_after_send_reopen_reconciles_without_redispatch() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-crash-after-send");
    let key = intent.key.clone();
    let crash_adapter = CrashAfterSendAdapter {
        dispatches: Arc::new(AtomicUsize::new(0)),
        send_started: Arc::new(Notify::new()),
        hold_response: Arc::new(Notify::new()),
    };
    let crash_dispatches = crash_adapter.dispatches.clone();

    // Run the adapter call in a task so the simulated process crash becomes a
    // durable task failure.  The facade has committed its dispatch-boundary
    // claim before crossing into the adapter, so the SQLite journal remains
    // reopenable even though no response was returned.
    let crash_task = tokio::spawn({
        let store = store.clone();
        let adapter = crash_adapter.clone();
        let intent = intent.clone();
        async move {
            store
                .dispatch_provider_effect_qualification(&adapter, &intent)
                .await
        }
    });
    crash_adapter.send_started.notified().await;
    crash_task.abort();
    let crashed = crash_task.await;
    assert!(
        crashed.is_err(),
        "simulated process death must abort the task"
    );
    assert_eq!(crash_dispatches.load(Ordering::Relaxed), 1);

    // Drop/reopen is the crash boundary.  A replay through the dispatch
    // facade must observe the durable uncertainty and must not send again.
    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen after crash-after-send");
    let completion = completed_ack(&intent, b"status-after-crash-operation");
    let status_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(completion.clone()),
        ProviderEffectLookup::Ack(completion),
    );
    let replay = reopened
        .dispatch_provider_effect_qualification(&status_adapter, &intent)
        .await
        .expect("replay must remain quarantined");
    assert_eq!(replay.state, ProviderEffectState::Indeterminate);
    assert!(!replay.dispatch_attempted);
    assert_eq!(status_adapter.dispatches.load(Ordering::Relaxed), 0);

    // Only the provider-owned status path may close the uncertainty.  The
    // resulting durable ACK must retain explicit StatusLookup provenance.
    assert_eq!(
        reopened
            .reconcile_provider_effect_with_adapter(&status_adapter, &key)
            .await
            .expect("status reconciliation"),
        ProviderEffectState::Completed
    );
    assert_eq!(status_adapter.dispatches.load(Ordering::Relaxed), 0);
    assert_eq!(status_adapter.lookups.load(Ordering::Relaxed), 1);
    let effect = reopened
        .get_provider_effect(&key)
        .await
        .expect("read reconciled effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Completed);
    assert_eq!(effect.acknowledgements.len(), 1);
    assert_eq!(
        effect.acknowledgements[0].source,
        ProviderEffectAckSource::StatusLookup
    );
    assert_eq!(effect.uncertainties.len(), 1);
    assert_eq!(
        effect.uncertainties[0].uncertainty.reason_code,
        "provider_dispatch_boundary_pending"
    );
}

#[tokio::test]
async fn imported_pending_is_quarantined_before_dispatch_and_reconcile_only() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"imported-pending-quarantine");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("imported intent");
    drop(store);

    // Reopen models an intent imported from another local journal or a crash
    // window before the dispatch-boundary claim.  The dispatch facade must
    // quarantine it before touching the adapter; only lookup reconciliation
    // may later close the occurrence.
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let completion = completed_ack(&intent, b"imported-operation");
    let adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(completion.clone()),
        ProviderEffectLookup::Ack(completion),
    );
    let receipt = reopened
        .dispatch_provider_effect_qualification(&adapter, &intent)
        .await
        .expect("imported pending quarantine");
    assert_eq!(receipt.state, ProviderEffectState::Indeterminate);
    assert!(!receipt.dispatch_claimed);
    assert!(!receipt.dispatch_attempted);
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 0);
    let quarantined = reopened
        .get_provider_effect(&intent.key)
        .await
        .expect("read imported quarantine")
        .expect("effect");
    assert_eq!(quarantined.state(), ProviderEffectState::Indeterminate);
    assert_eq!(quarantined.uncertainties.len(), 1);
    assert_eq!(
        quarantined.uncertainties[0].uncertainty.reason_code,
        "provider_imported_pending"
    );

    assert_eq!(
        reopened
            .reconcile_provider_effect_with_adapter(&adapter, &intent.key)
            .await
            .expect("lookup reconciliation"),
        ProviderEffectState::Completed
    );
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 0);
    assert_eq!(adapter.lookups.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn qualification_dispatch_malformed_ack_quarantines_and_replay_does_not_send() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-malformed-ack");
    let malformed = ProviderEffectAck::new(
        intent.key.clone(),
        Sha256Digest::for_bytes(b"wrong-payload"),
        Sha256Digest::for_bytes(b"malformed-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let bad_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(malformed),
        ProviderEffectLookup::Unknown,
    );
    let error = store
        .dispatch_provider_effect_qualification(&bad_adapter, &intent)
        .await
        .expect_err("payload-mismatched adapter ACK must fail closed");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    assert_eq!(bad_adapter.dispatches.load(Ordering::Relaxed), 1);

    let good_ack = completed_ack(&intent, b"reconciled-after-malformed");
    let good_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(good_ack.clone()),
        ProviderEffectLookup::Ack(good_ack),
    );
    let replay = store
        .dispatch_provider_effect_qualification(&good_adapter, &intent)
        .await
        .expect("quarantined replay");
    assert_eq!(replay.state, ProviderEffectState::Indeterminate);
    assert!(!replay.dispatch_attempted);
    assert_eq!(good_adapter.dispatches.load(Ordering::Relaxed), 0);
    assert_eq!(
        store
            .reconcile_provider_effect_with_adapter(&good_adapter, &intent.key)
            .await
            .expect("reconcile malformed ACK quarantine"),
        ProviderEffectState::Completed
    );
    assert_eq!(good_adapter.lookups.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn qualification_reconcile_malformed_ack_quarantines_and_blocks_dispatch() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-reconcile-malformed-ack");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let malformed = ProviderEffectAck::new(
        intent.key.clone(),
        Sha256Digest::for_bytes(b"wrong-lookup-payload"),
        Sha256Digest::for_bytes(b"malformed-lookup-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let bad_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Ack(malformed),
    );
    let error = store
        .reconcile_provider_effect_with_adapter(&bad_adapter, &intent.key)
        .await
        .expect_err("payload-mismatched lookup ACK must fail closed");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    let effect = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read lookup quarantine")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Indeterminate);
    assert_eq!(effect.uncertainties.len(), 1);
    assert_eq!(
        effect.uncertainties[0].uncertainty.reason_code,
        "provider_reconcile_ack_invalid"
    );

    let replay_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(completed_ack(&intent, b"must-not-dispatch")),
        ProviderEffectLookup::Unknown,
    );
    let replay = store
        .dispatch_provider_effect_qualification(&replay_adapter, &intent)
        .await
        .expect("quarantined lookup replay");
    assert_eq!(replay.state, ProviderEffectState::Indeterminate);
    assert!(!replay.dispatch_attempted);
    assert_eq!(replay_adapter.dispatches.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn qualification_dispatch_rejects_cross_key_ack_without_mutating_other_effect() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent_a = effect_intent_for_occurrence(
        b"qualification-cross-key-a",
        "automation:agent-a:cross-key-a",
    );
    let intent_b = effect_intent_for_occurrence(
        b"qualification-cross-key-b",
        "automation:agent-a:cross-key-b",
    );
    store
        .append_provider_effect_intent(&intent_b)
        .await
        .expect("intent B");
    let adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Ack(completed_ack(&intent_b, b"wrong-target-operation")),
        ProviderEffectLookup::Unknown,
    );
    let error = store
        .dispatch_provider_effect_qualification(&adapter, &intent_a)
        .await
        .expect_err("cross-key ACK must fail closed");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 1);

    let effect_a = store
        .get_provider_effect(&intent_a.key)
        .await
        .expect("read A")
        .expect("effect A");
    assert_eq!(effect_a.state(), ProviderEffectState::Indeterminate);
    assert_eq!(effect_a.uncertainties.len(), 2);
    assert_eq!(
        effect_a.uncertainties[1].uncertainty.reason_code,
        "provider_dispatch_ack_invalid"
    );
    let effect_b = store
        .get_provider_effect(&intent_b.key)
        .await
        .expect("read B")
        .expect("effect B");
    assert_eq!(effect_b.state(), ProviderEffectState::Pending);
    assert!(effect_b.acknowledgements.is_empty());
    assert!(effect_b.uncertainties.is_empty());
}

#[tokio::test]
async fn qualification_boundary_lock_serializes_lookup_against_dispatch() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-boundary-lock");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let adapter = BlockingLookupAdapter {
        dispatches: Arc::new(AtomicUsize::new(0)),
        lookup_started: Arc::new(Notify::new()),
        release_lookup: Arc::new(Notify::new()),
    };
    let reconcile_store = store.clone();
    let reconcile_adapter = adapter.clone();
    let key = intent.key.clone();
    let reconcile_task = tokio::spawn(async move {
        reconcile_store
            .reconcile_provider_effect_with_adapter(&reconcile_adapter, &key)
            .await
    });
    adapter.lookup_started.notified().await;

    let dispatch_store = store.clone();
    let dispatch_adapter = adapter.clone();
    let dispatch_intent = intent.clone();
    let dispatch_task = tokio::spawn(async move {
        dispatch_store
            .dispatch_provider_effect_qualification(&dispatch_adapter, &dispatch_intent)
            .await
    });
    tokio::task::yield_now().await;
    assert_eq!(
        adapter.dispatches.load(Ordering::Relaxed),
        0,
        "dispatch must wait while lookup owns the opened-store boundary"
    );
    adapter.release_lookup.notify_one();
    assert_eq!(
        reconcile_task
            .await
            .expect("reconcile task")
            .expect("reconcile result"),
        ProviderEffectState::Indeterminate
    );
    let dispatch = dispatch_task
        .await
        .expect("dispatch task")
        .expect("dispatch result");
    assert!(!dispatch.dispatch_attempted);
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn qualification_dispatch_claim_has_one_concurrent_winner() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-concurrent-claim");
    let first_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Unknown,
    );
    let second_adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Unknown,
    );
    let (first, second) = tokio::join!(
        store.dispatch_provider_effect_qualification(&first_adapter, &intent),
        store.dispatch_provider_effect_qualification(&second_adapter, &intent),
    );
    let first = first.expect("first concurrent qualification call");
    let second = second.expect("second concurrent qualification call");
    assert_eq!(
        first.dispatch_attempted as u8 + second.dispatch_attempted as u8,
        1,
        "only one caller may cross the adapter boundary"
    );
    assert_eq!(
        first_adapter.dispatches.load(Ordering::Relaxed)
            + second_adapter.dispatches.load(Ordering::Relaxed),
        1
    );
    let effect = store
        .get_provider_effect(&intent.key)
        .await
        .expect("read concurrent claim")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Indeterminate);
}

#[tokio::test]
async fn qualification_dispatch_unsupported_capability_never_invokes_adapter() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"qualification-unsupported");
    let adapter = scripted_adapter(
        ProviderEffectIdempotencyCapability::Unsupported,
        ProviderEffectDispatch::Ack(completed_ack(&intent, b"must-not-send")),
        ProviderEffectLookup::Unknown,
    );
    let receipt = store
        .dispatch_provider_effect_qualification(&adapter, &intent)
        .await
        .expect("unsupported capability quarantine");
    assert_eq!(receipt.state, ProviderEffectState::Indeterminate);
    assert!(receipt.dispatch_claimed);
    assert!(!receipt.dispatch_attempted);
    assert_eq!(adapter.dispatches.load(Ordering::Relaxed), 0);
    let reconcile_error = store
        .reconcile_provider_effect_with_adapter(&adapter, &intent.key)
        .await
        .expect_err("unsupported lookup must remain fail-closed");
    assert!(matches!(reconcile_error, EvidenceError::InvalidRecord(_)));
    assert_eq!(adapter.lookups.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn accepted_effect_stays_indeterminate_when_reconcile_reports_rejected() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"accepted-then-rejected");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-accepted"),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("accepted");
    assert_eq!(
        store
            .reconcile_provider_effect_lookup(
                ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                &key,
                ProviderEffectLookup::Unknown,
            )
            .await
            .expect("unknown quarantine"),
        ProviderEffectState::Indeterminate
    );
    let rejected = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-authoritative"),
        ProviderEffectAckStatus::Rejected,
    );
    let error = store
        .append_provider_effect_ack(&rejected)
        .await
        .expect_err("accepted -> rejected must remain fail-closed");
    assert!(matches!(error, EvidenceError::IdempotencyConflict { .. }));
    let effect = store
        .get_provider_effect(&key)
        .await
        .expect("read effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Indeterminate);
    assert_eq!(effect.acknowledgements.len(), 1);
    assert_eq!(effect.uncertainties.len(), 1);
}

#[tokio::test]
async fn unsupported_provider_capability_is_durable_indeterminate() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"unsupported-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");

    let error = store
        .reconcile_provider_effect_lookup(
            ProviderEffectIdempotencyCapability::Unsupported,
            &key,
            ProviderEffectLookup::Unknown,
        )
        .await
        .expect_err("unsupported lookup must fail closed");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    let effect = store
        .get_provider_effect(&key)
        .await
        .expect("read effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Indeterminate);
    assert_eq!(
        effect.uncertainties[0].uncertainty.reason_code,
        "provider_capability_unsupported"
    );
}

#[tokio::test]
async fn terminal_effect_cannot_be_quarantined_or_replaced() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"terminal-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let completion = completed_ack(&intent, b"terminal-operation");
    store
        .append_provider_effect_ack(&completion)
        .await
        .expect("completion");

    let quarantine = store
        .mark_provider_effect_indeterminate(&key, "late_network_unknown")
        .await
        .expect_err("terminal cannot be quarantined");
    assert!(matches!(
        quarantine,
        EvidenceError::IdempotencyConflict { .. }
    ));
    let replacement = ProviderEffectAck::new(
        key,
        intent.payload_sha256,
        Sha256Digest::for_bytes(b"other-operation"),
        ProviderEffectAckStatus::Rejected,
    );
    let error = store
        .append_provider_effect_ack(&replacement)
        .await
        .expect_err("terminal cannot be replaced");
    assert!(matches!(error, EvidenceError::IdempotencyConflict { .. }));
}

#[tokio::test]
async fn terminal_lookup_replay_is_idempotent_without_late_uncertainty() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"terminal-lookup-replay");
    let key = intent.key.clone();
    let completion = completed_ack(&intent, b"terminal-lookup-operation");
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack(&completion)
        .await
        .expect("completion");

    for lookup in [
        ProviderEffectLookup::Unknown,
        ProviderEffectLookup::NotFound,
        ProviderEffectLookup::Conflict {
            observed_payload_sha256: None,
        },
    ] {
        assert_eq!(
            store
                .reconcile_provider_effect_lookup(
                    ProviderEffectIdempotencyCapability::Unsupported,
                    &key,
                    lookup,
                )
                .await
                .expect("terminal state must short-circuit late lookup"),
            ProviderEffectState::Completed
        );
    }

    assert_eq!(
        store
            .reconcile_provider_effect_lookup(
                ProviderEffectIdempotencyCapability::Unsupported,
                &key,
                ProviderEffectLookup::Ack(completion.clone()),
            )
            .await
            .expect("exact terminal ACK replay"),
        ProviderEffectState::Completed
    );

    let conflicting_ack = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"conflicting-terminal-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let conflict = store
        .reconcile_provider_effect_lookup(
            ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            &key,
            ProviderEffectLookup::Ack(conflicting_ack),
        )
        .await
        .expect_err("conflicting terminal ACK must remain fail-closed");
    assert!(matches!(
        conflict,
        EvidenceError::IdempotencyConflict { .. }
    ));

    let effect = store
        .get_provider_effect(&key)
        .await
        .expect("read terminal effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Completed);
    assert_eq!(effect.acknowledgements.len(), 1);
    assert!(effect.uncertainties.is_empty());
}

#[tokio::test]
async fn rejected_terminal_lookup_replay_is_idempotent_without_late_uncertainty() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"rejected-terminal-lookup-replay");
    let key = intent.key.clone();
    let rejection = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"rejected-terminal-operation"),
        ProviderEffectAckStatus::Rejected,
    );
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack(&rejection)
        .await
        .expect("rejection");

    for lookup in [
        ProviderEffectLookup::Unknown,
        ProviderEffectLookup::NotFound,
        ProviderEffectLookup::Conflict {
            observed_payload_sha256: None,
        },
    ] {
        assert_eq!(
            store
                .reconcile_provider_effect_lookup(
                    ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
                    &key,
                    lookup,
                )
                .await
                .expect("terminal rejection must short-circuit late lookup"),
            ProviderEffectState::Rejected
        );
    }

    let effect = store
        .get_provider_effect(&key)
        .await
        .expect("read rejected effect")
        .expect("effect");
    assert_eq!(effect.state(), ProviderEffectState::Rejected);
    assert_eq!(effect.acknowledgements.len(), 1);
    assert!(effect.uncertainties.is_empty());
}

#[tokio::test]
async fn reopen_rejects_late_uncertainty_after_terminal_ack() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"late-uncertainty-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .append_provider_effect_ack(&completed_ack(&intent, b"terminal-operation"))
        .await
        .expect("terminal ACK");

    // Model a damaged/imported store that bypassed the public append guard.
    // A late quarantine row must not downgrade a terminal result to
    // Indeterminate when the evidence store is reopened.
    let uncertainty = ProviderEffectUncertainty::new(
        key.clone(),
        intent.payload_sha256.clone(),
        "late_network_unknown",
    );
    let uncertainty_bytes =
        crate::canonical::canonical_json(&uncertainty).expect("canonical uncertainty");
    let uncertainty_json = String::from_utf8(uncertainty_bytes.clone()).expect("uncertainty JSON");
    let uncertainty_record_sha = Sha256Digest::for_bytes(&uncertainty_bytes);
    sqlx::query(
        "INSERT INTO provider_effect_uncertainties (
            effect_key, payload_sha256, reason_code, schema_version,
            payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(key.as_str())
    .bind(uncertainty.payload_sha256.as_str())
    .bind(&uncertainty.reason_code)
    .bind(i64::from(uncertainty.schema_version))
    .bind(&uncertainty_json)
    .bind(uncertainty_record_sha.as_str())
    .bind(i64::MAX)
    .execute(&store.pool)
    .await
    .expect("insert damaged late uncertainty");
    drop(store);

    let reopen = HeptaEvidenceStore::open(&sqlite).await;
    assert!(matches!(
        reopen,
        Err(EvidenceError::Corrupt(detail))
            if detail.contains("uncertainty follows terminal ACK")
    ));
}

#[tokio::test]
async fn reopen_rejects_ack_uncertainty_timestamp_tie() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"timestamp-tie-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"timestamp-tie-operation"),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("accepted ACK");
    let ack_recorded_at_ms: i64 = sqlx::query_scalar(
        "SELECT recorded_at_ms FROM provider_effect_acknowledgements
         WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .fetch_one(&store.pool)
    .await
    .expect("read ACK timestamp");
    let uncertainty = ProviderEffectUncertainty::new(
        key.clone(),
        intent.payload_sha256.clone(),
        "imported_timestamp_tie",
    );
    let uncertainty_bytes = crate::canonical::canonical_json(&uncertainty).expect("canonical");
    let uncertainty_json = String::from_utf8(uncertainty_bytes.clone()).expect("JSON");
    let uncertainty_record_sha = Sha256Digest::for_bytes(&uncertainty_bytes);
    sqlx::query(
        "INSERT INTO provider_effect_uncertainties (
            effect_key, payload_sha256, reason_code, schema_version,
            payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(key.as_str())
    .bind(uncertainty.payload_sha256.as_str())
    .bind(&uncertainty.reason_code)
    .bind(i64::from(uncertainty.schema_version))
    .bind(&uncertainty_json)
    .bind(uncertainty_record_sha.as_str())
    .bind(ack_recorded_at_ms)
    .execute(&store.pool)
    .await
    .expect("insert tied uncertainty");
    drop(store);

    let reopen = HeptaEvidenceStore::open(&sqlite).await;
    assert!(matches!(
        reopen,
        Err(EvidenceError::Corrupt(detail))
            if detail.contains("ambiguous timestamp")
    ));
}

#[tokio::test]
async fn reopen_orders_ack_and_uncertainty_by_per_key_time_not_cross_table_seq() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let target = effect_intent(b"cross-table-seq-target");
    store
        .append_provider_effect_intent(&target)
        .await
        .expect("target intent");

    // Skew the global uncertainty AUTOINCREMENT sequence with unrelated
    // effects.  A target uncertainty may then have seq 100+ while its target
    // ACK still has acknowledgement seq 1; those values are not comparable.
    for index in 0..4 {
        let other = effect_intent_for_occurrence(
            format!("cross-table-seq-other-{index}").as_bytes(),
            &format!("automation:agent-a:cross-table-other-{index}"),
        );
        store
            .append_provider_effect_intent(&other)
            .await
            .expect("other intent");
        store
            .mark_provider_effect_indeterminate(&other.key, "provider_lookup_unknown")
            .await
            .expect("other uncertainty");
    }
    store
        .reconcile_provider_effect_lookup(
            ProviderEffectIdempotencyCapability::KeyAndStatusLookup,
            &target.key,
            ProviderEffectLookup::Unknown,
        )
        .await
        .expect("target uncertainty");
    store
        .append_provider_effect_ack_from_source(
            &completed_ack(&target, b"cross-table-seq-operation"),
            codex_hepta_contracts::ProviderEffectAckSource::StatusLookup,
        )
        .await
        .expect("target terminal ACK");
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let effect = reopened
        .get_provider_effect(&target.key)
        .await
        .expect("read target")
        .expect("target effect");
    assert_eq!(effect.state(), ProviderEffectState::Completed);
    assert_eq!(effect.uncertainties.len(), 1);
    assert_eq!(effect.acknowledgements.len(), 1);
}

#[tokio::test]
async fn same_key_payload_conflict_and_ack_binding_fail_closed() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"authoritative-payload");
    let key = intent.key.clone();
    assert_eq!(
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("intent"),
        AppendDisposition::Inserted
    );

    // A provider/client retry may replay the exact occurrence, but it must
    // not reuse the durable key for a different payload.
    let conflicting_intent = effect_intent(b"different-payload");
    let conflict = store
        .append_provider_effect_intent(&conflicting_intent)
        .await
        .expect_err("same-key/different-payload must be rejected");
    assert!(matches!(
        conflict,
        EvidenceError::IdempotencyConflict { .. }
    ));

    // An ACK is independently bound to both the occurrence key and the
    // exact payload digest; a provider response for another payload cannot
    // close this intent even when the occurrence key matches.
    let mismatched_ack = ProviderEffectAck::new(
        key.clone(),
        Sha256Digest::for_bytes(b"different-payload"),
        Sha256Digest::for_bytes(b"provider-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let binding_error = store
        .append_provider_effect_ack(&mismatched_ack)
        .await
        .expect_err("payload-mismatched ACK must be rejected");
    assert!(matches!(binding_error, EvidenceError::InvalidRecord(_)));

    let valid_ack = completed_ack(&intent, b"provider-operation");
    assert_eq!(
        store
            .append_provider_effect_ack(&valid_ack)
            .await
            .expect("valid ACK"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .append_provider_effect_ack(&valid_ack)
            .await
            .expect("exact ACK replay"),
        AppendDisposition::AlreadyPresent
    );
}

#[tokio::test]
async fn effect_tables_are_append_only() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let intent = effect_intent(b"immutable-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .mark_provider_effect_indeterminate(&key, "network_unknown")
        .await
        .expect("quarantine");

    let update = sqlx::query(
        "UPDATE provider_effect_uncertainties SET reason_code = 'tampered' WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .execute(&store.pool)
    .await;
    assert!(update.is_err());
    let delete = sqlx::query("DELETE FROM provider_effect_uncertainties WHERE effect_key = ?")
        .bind(key.as_str())
        .execute(&store.pool)
        .await;
    assert!(delete.is_err());
}

#[tokio::test]
async fn reopen_rejects_illegal_ack_even_when_late_uncertainty_exists() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let intent = effect_intent(b"corrupt-transition-payload");
    let key = intent.key.clone();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    let accepted = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-one"),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("accepted");

    // Bypass the public transition guard to model a damaged/imported store.
    // The reopen verifier must reject it rather than allowing a later
    // uncertainty row to retroactively legalize the operation-id change.
    let illegal = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-two"),
        ProviderEffectAckStatus::Completed,
    );
    let illegal_bytes = crate::canonical::canonical_json(&illegal).expect("canonical ACK");
    let illegal_json = String::from_utf8(illegal_bytes.clone()).expect("ACK JSON");
    let illegal_record_sha = Sha256Digest::for_bytes(&illegal_bytes);
    sqlx::query(
        "INSERT INTO provider_effect_acknowledgements (
            effect_key, payload_sha256, provider_operation_id_sha256,
            status, source, schema_version, payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, 'completed', 'dispatch_response', ?, ?, ?, 200)",
    )
    .bind(key.as_str())
    .bind(illegal.payload_sha256.as_str())
    .bind(illegal.provider_operation_id_sha256.as_str())
    .bind(i64::from(illegal.schema_version))
    .bind(&illegal_json)
    .bind(illegal_record_sha.as_str())
    .execute(&store.pool)
    .await
    .expect("insert damaged ACK");

    let uncertainty = ProviderEffectUncertainty::new(
        key.clone(),
        intent.payload_sha256.clone(),
        "late_uncertainty",
    );
    let uncertainty_bytes =
        crate::canonical::canonical_json(&uncertainty).expect("canonical uncertainty");
    let uncertainty_json = String::from_utf8(uncertainty_bytes.clone()).expect("uncertainty JSON");
    let uncertainty_record_sha = Sha256Digest::for_bytes(&uncertainty_bytes);
    sqlx::query(
        "INSERT INTO provider_effect_uncertainties (
            effect_key, payload_sha256, reason_code, schema_version,
            payload_json, record_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, 300)",
    )
    .bind(key.as_str())
    .bind(uncertainty.payload_sha256.as_str())
    .bind(&uncertainty.reason_code)
    .bind(i64::from(uncertainty.schema_version))
    .bind(&uncertainty_json)
    .bind(uncertainty_record_sha.as_str())
    .execute(&store.pool)
    .await
    .expect("insert late uncertainty");
    drop(store);

    let reopen = HeptaEvidenceStore::open(&sqlite).await;
    assert!(matches!(reopen, Err(EvidenceError::Corrupt(_))));
}
