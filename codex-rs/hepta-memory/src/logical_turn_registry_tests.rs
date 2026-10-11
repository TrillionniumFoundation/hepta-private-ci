use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::LocalLeaseState;
use crate::LogicalTurnAttemptRequest;
use crate::LogicalTurnInspectionDisposition;
use crate::LogicalTurnRegistryError;
use crate::LogicalTurnRequest;
use crate::LogicalTurnReservation;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

async fn opened_store(temp: &TempDir, number: u8) -> CognitiveStore {
    let owner = agent_id(number);
    CognitiveStore::open(&layout(temp, &owner))
        .await
        .expect("cognitive store")
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
}

fn logical_request() -> LogicalTurnRequest {
    LogicalTurnRequest::new(
        "logical-turn:test",
        "scope:test",
        Sha256Digest::for_bytes(b"logical-binding"),
    )
    .expect("logical request")
}

fn attempt(
    suffix: &str,
    lease_suffix: &str,
    generation: u64,
    expiry: u64,
) -> LogicalTurnAttemptRequest {
    attempt_with_owner_epoch(suffix, lease_suffix, 1, generation, expiry)
}

fn attempt_with_owner_epoch(
    suffix: &str,
    lease_suffix: &str,
    owner_epoch: u64,
    generation: u64,
    expiry: u64,
) -> LogicalTurnAttemptRequest {
    LogicalTurnAttemptRequest::new(
        format!("attempt:{suffix}"),
        format!("lease:{lease_suffix}"),
        format!("journal:{suffix}"),
        format!("trajectory:{suffix}"),
        format!("occurrence:{suffix}"),
        1,
        owner_epoch,
        generation,
        format!("fence:{suffix}"),
        expiry,
    )
    .expect("attempt request")
}

#[tokio::test]
async fn reserve_and_exact_replay_are_one_row() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 180).await;
    let request = logical_request();
    let physical = attempt("one", "one", 1, now() + 3_600);
    let first = store
        .reserve_or_replay_logical_turn(request.clone(), physical.clone())
        .await
        .expect("first reservation");
    assert!(matches!(first, LogicalTurnReservation::Acquired { .. }));
    let replay = store
        .reserve_or_replay_logical_turn(request, physical)
        .await
        .expect("exact replay");
    assert!(matches!(replay, LogicalTurnReservation::Replayed { .. }));
    let identity_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turns")
        .fetch_one(&store.pool)
        .await
        .expect("identity count");
    let attempt_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
            .fetch_one(&store.pool)
            .await
            .expect("attempt count");
    assert_eq!(identity_rows, 1);
    assert_eq!(attempt_rows, 1);
}

#[tokio::test]
async fn logical_turn_inspection_missing_is_read_only() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 191).await;
    let request = logical_request();
    let before_identities: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turns")
        .fetch_one(&store.pool)
        .await
        .expect("identity count before");
    let before_attempts: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
            .fetch_one(&store.pool)
            .await
            .expect("attempt count before");
    let inspection = store
        .inspect_logical_turn(request)
        .await
        .expect("missing inspection");
    assert_eq!(
        inspection.disposition,
        LogicalTurnInspectionDisposition::Missing
    );
    assert!(inspection.head.is_none());
    assert!(inspection.lease_head.is_none());
    assert!(inspection.evidence.is_empty());
    let after_identities: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turns")
        .fetch_one(&store.pool)
        .await
        .expect("identity count after");
    let after_attempts: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
            .fetch_one(&store.pool)
            .await
            .expect("attempt count after");
    assert_eq!(before_identities, after_identities);
    assert_eq!(before_attempts, after_attempts);
}

#[tokio::test]
async fn logical_turn_inspection_classifies_active_and_expired_evidence() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 192).await;
    let request = logical_request();
    let active = attempt("inspect-active", "inspect-active", 1, now() + 3_600);
    store
        .reserve_or_replay_logical_turn(request.clone(), active.clone())
        .await
        .expect("active reservation");
    let active_inspection = store
        .inspect_logical_turn(request.clone())
        .await
        .expect("active inspection");
    assert_eq!(
        active_inspection.disposition,
        LogicalTurnInspectionDisposition::Active
    );
    assert_eq!(
        active_inspection
            .head
            .as_ref()
            .expect("active head")
            .attempt_id,
        active.attempt_id
    );
    assert_eq!(
        active_inspection
            .lease_head
            .as_ref()
            .expect("lease head")
            .state,
        LocalLeaseState::Active
    );
    assert!(active_inspection.evidence.is_empty());

    let temp_expired = TempDir::new().expect("expired temp dir");
    let expired_store = opened_store(&temp_expired, 193).await;
    let expired = attempt("inspect-expired", "inspect-expired", 1, 1);
    expired_store
        .reserve_or_replay_logical_turn(request.clone(), expired.clone())
        .await
        .expect("expired reservation");
    let zero = expired_store
        .inspect_logical_turn(request.clone())
        .await
        .expect("zero-evidence inspection");
    assert_eq!(
        zero.disposition,
        LogicalTurnInspectionDisposition::ExpiredZeroEvidence
    );
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES (?, 1, ?, ?, ?, 1, ?, 'admitted', '{}', ?, ?, ?, 0)",
    )
    .bind(&expired.lease_id)
    .bind("event:inspect-evidence")
    .bind(&expired.occurrence_key)
    .bind(expired_store.owner_agent_id().as_str())
    .bind(&expired.fencing_token)
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .execute(&expired_store.pool)
    .await
    .expect("evidence row");
    let with_evidence = expired_store
        .inspect_logical_turn(request)
        .await
        .expect("evidence inspection");
    assert_eq!(
        with_evidence.disposition,
        LogicalTurnInspectionDisposition::ExpiredWithEvidence
    );
    assert_eq!(with_evidence.evidence.event_rows, 1);
}

#[tokio::test]
async fn logical_turn_inspection_reports_conflict_and_terminal_lease() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 194).await;
    let request = logical_request();
    let physical = attempt("inspect-terminal", "inspect-terminal", 1, now() + 3_600);
    store
        .reserve_or_replay_logical_turn(request.clone(), physical.clone())
        .await
        .expect("reservation");
    let conflicting = LogicalTurnRequest::new(
        request.logical_turn_id.clone(),
        request.scope_key.clone(),
        Sha256Digest::for_bytes(b"different-inspection-binding"),
    )
    .expect("conflicting request");
    let conflict = store
        .inspect_logical_turn(conflicting)
        .await
        .expect("conflict inspection");
    assert_eq!(
        conflict.disposition,
        LogicalTurnInspectionDisposition::Conflict
    );
    assert_eq!(
        conflict.stored_scope_key.as_deref(),
        Some(request.scope_key.as_str())
    );
    assert!(conflict.stored_binding_sha256.is_some());
    assert!(conflict.head.is_none());

    let lease_head = store
        .inspect_local_lease_head(&physical.lease_id)
        .await
        .expect("lease inspection")
        .head
        .expect("lease head");
    let lease = store
        .reopen_host_bound_lease(
            lease_head,
            physical.authority_epoch,
            physical.owner_epoch,
            physical.lease_expires_at_unix_seconds,
        )
        .await
        .expect("reopen lease");
    lease.release().await.expect("release lease");
    let terminal = store
        .inspect_logical_turn(request)
        .await
        .expect("terminal inspection");
    assert_eq!(
        terminal.disposition,
        LogicalTurnInspectionDisposition::TerminalPhysicalLease
    );
    assert_eq!(
        terminal.lease_head.as_ref().expect("terminal lease").state,
        LocalLeaseState::Released
    );

    // Reusing the physical lease id for a later generation must not make the
    // old registry head appear active.  The inspection path must fail closed
    // on this head-digest drift rather than returning the successor lease.
    let terminal_head = terminal.lease_head.expect("terminal head witness");
    let successor = store
        .acquire_host_bound_lease_after_head(
            physical.lease_id.clone(),
            terminal_head,
            physical.authority_epoch,
            physical.owner_epoch + 1,
            physical.generation + 1,
            "inspect-terminal-successor-fence",
            now() + 3_600,
        )
        .await
        .expect("successor lease")
        .into_handle();
    let drift = store.inspect_logical_turn(terminal.request).await;
    assert!(matches!(drift, Err(LogicalTurnRegistryError::Corrupt(_))));
    successor.release().await.expect("release successor lease");
    let terminal_drift = store.inspect_logical_turn(logical_request()).await;
    assert!(matches!(
        terminal_drift,
        Err(LogicalTurnRegistryError::Corrupt(_))
    ));
}

#[tokio::test]
async fn logical_turn_inspection_observes_fresh_head_after_takeover() {
    let temp = TempDir::new().expect("temp dir");
    let left = opened_store(&temp, 195).await;
    let right = opened_store(&temp, 195).await;
    let request = logical_request();
    let old = attempt("inspect-old", "inspect-old", 1, 1);
    left.reserve_or_replay_logical_turn(request.clone(), old.clone())
        .await
        .expect("old reservation");
    let before = right
        .inspect_logical_turn(request.clone())
        .await
        .expect("old inspection");
    assert_eq!(
        before.disposition,
        LogicalTurnInspectionDisposition::ExpiredZeroEvidence
    );
    let successor = attempt_with_owner_epoch("inspect-new", "inspect-new", 1, 1, now() + 3_600);
    left.reserve_or_replay_logical_turn(request.clone(), successor.clone())
        .await
        .expect("takeover");
    // The prior read witness is intentionally stale; a fresh read sees the
    // new physical attempt and never authorizes the old handle.
    let after = right
        .inspect_logical_turn(request)
        .await
        .expect("new inspection");
    assert_eq!(after.disposition, LogicalTurnInspectionDisposition::Active);
    assert_eq!(
        after.head.expect("new head").attempt_id,
        successor.attempt_id
    );
    assert_eq!(before.head.expect("old head").attempt_id, old.attempt_id);
}

#[tokio::test]
async fn live_different_attempt_is_existing_in_flight_without_side_effects() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 181).await;
    let request = logical_request();
    let first = attempt("live-a", "live-a", 1, now() + 3_600);
    store
        .reserve_or_replay_logical_turn(request.clone(), first)
        .await
        .expect("first reservation");
    let second = attempt("live-b", "live-b", 1, now() + 3_600);
    let result = store
        .reserve_or_replay_logical_turn(request, second)
        .await
        .expect("in-flight result");
    assert!(matches!(
        result,
        LogicalTurnReservation::ExistingInFlight { .. }
    ));
    let lease_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases")
        .fetch_one(&store.pool)
        .await
        .expect("lease count");
    assert_eq!(lease_rows, 1, "losing observation must not append a lease");
}

#[tokio::test]
async fn physical_attempt_identity_cannot_alias_another_logical_turn() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 189).await;
    let first_request = logical_request();
    let first_attempt = attempt("alias-first", "alias-shared", 1, now() + 3_600);
    store
        .reserve_or_replay_logical_turn(first_request, first_attempt)
        .await
        .expect("first reservation");

    let second_request = LogicalTurnRequest::new(
        "logical-turn:other",
        "scope:test",
        Sha256Digest::for_bytes(b"other-binding"),
    )
    .expect("second logical request");
    let result = store
        .reserve_or_replay_logical_turn(
            second_request,
            attempt("alias-second", "alias-shared", 1, now() + 3_600),
        )
        .await
        .expect("alias result");
    assert!(matches!(result, LogicalTurnReservation::Conflict { .. }));
    let identity_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turns")
        .fetch_one(&store.pool)
        .await
        .expect("identity rows");
    let attempt_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
            .fetch_one(&store.pool)
            .await
            .expect("attempt rows");
    assert_eq!(identity_rows, 1);
    assert_eq!(attempt_rows, 1);
}

#[tokio::test]
async fn expired_attempt_without_evidence_has_one_takeover_winner() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 182).await;
    let request = logical_request();
    let expired = attempt("old", "old", 1, 1);
    store
        .reserve_or_replay_logical_turn(request.clone(), expired)
        .await
        .expect("expired reservation");
    // Equal owner epochs are permitted for a same-generation, zero-evidence
    // retry; only a regressing epoch is rejected below.
    let successor = attempt_with_owner_epoch("new", "new", 1, 1, now() + 3_600);
    let result = store
        .reserve_or_replay_logical_turn(request, successor)
        .await
        .expect("takeover");
    let LogicalTurnReservation::Takeover {
        superseded,
        attempt,
    } = result
    else {
        panic!("expected takeover");
    };
    assert_eq!(
        superseded.transition,
        crate::LogicalTurnAttemptTransition::Superseded
    );
    assert_eq!(superseded.registry_sequence, 2);
    assert_eq!(
        attempt.transition,
        crate::LogicalTurnAttemptTransition::Active
    );
    assert_eq!(attempt.registry_sequence, 3);
    assert_eq!(attempt.attempt_no, 2);
}

#[tokio::test]
async fn expired_takeover_rejects_regressing_owner_epoch() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 190).await;
    let request = logical_request();
    store
        .reserve_or_replay_logical_turn(
            request.clone(),
            attempt_with_owner_epoch("epoch-old", "epoch-old", 2, 1, 1),
        )
        .await
        .expect("expired reservation");
    let result = store
        .reserve_or_replay_logical_turn(
            request,
            attempt_with_owner_epoch("epoch-new", "epoch-new", 1, 1, now() + 3_600),
        )
        .await
        .expect("epoch conflict");
    assert!(matches!(result, LogicalTurnReservation::Conflict { .. }));
    let attempts: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
        .fetch_one(&store.pool)
        .await
        .expect("attempt count");
    assert_eq!(attempts, 1);
}

#[tokio::test]
async fn takeover_reopens_with_historical_witness_and_fences_old_handle() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 185).await;
    let request = logical_request();
    let expired = attempt("reopen-old", "reopen-old", 1, 1);
    store
        .reserve_or_replay_logical_turn(request.clone(), expired.clone())
        .await
        .expect("expired reservation");
    let successor = attempt_with_owner_epoch("reopen-new", "reopen-new", 2, 1, now() + 3_600);
    let takeover = store
        .reserve_or_replay_logical_turn(request.clone(), successor.clone())
        .await
        .expect("takeover");
    assert!(matches!(takeover, LogicalTurnReservation::Takeover { .. }));
    let old_state: String = sqlx::query_scalar(
        "SELECT state FROM cognitive_local_leases
         WHERE lease_id = ? ORDER BY lease_sequence DESC LIMIT 1",
    )
    .bind(&expired.lease_id)
    .fetch_one(&store.pool)
    .await
    .expect("old lease state");
    assert_eq!(old_state, "rolled_back");

    store.pool.close().await;
    let reopened = opened_store(&temp, 185).await;
    let replay = reopened
        .reserve_or_replay_logical_turn(request, successor)
        .await
        .expect("replay after reopen");
    assert!(matches!(replay, LogicalTurnReservation::Replayed { .. }));
    assert!(
        reopened
            .reopen_local_lease(
                &expired.lease_id,
                expired.generation,
                &expired.fencing_token
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn identity_payload_mismatch_is_a_conflict_without_new_attempt() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 186).await;
    let original = logical_request();
    store
        .reserve_or_replay_logical_turn(
            original.clone(),
            attempt("identity", "identity", 1, now() + 3_600),
        )
        .await
        .expect("first reservation");
    let scope_mismatch = LogicalTurnRequest::new(
        original.logical_turn_id.clone(),
        "scope:changed",
        original.logical_binding_sha256.clone(),
    )
    .expect("scope mismatch request");
    let result = store
        .reserve_or_replay_logical_turn(
            scope_mismatch,
            attempt("identity-scope", "identity-scope", 1, now() + 3_600),
        )
        .await
        .expect("scope conflict result");
    assert!(matches!(result, LogicalTurnReservation::Conflict { .. }));

    let binding_mismatch = LogicalTurnRequest::new(
        original.logical_turn_id,
        original.scope_key,
        Sha256Digest::for_bytes(b"changed-binding"),
    )
    .expect("binding mismatch request");
    let result = store
        .reserve_or_replay_logical_turn(
            binding_mismatch,
            attempt("identity-binding", "identity-binding", 1, now() + 3_600),
        )
        .await
        .expect("binding conflict result");
    assert!(matches!(result, LogicalTurnReservation::Conflict { .. }));
    let attempts: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
        .fetch_one(&store.pool)
        .await
        .expect("attempt count");
    assert_eq!(attempts, 1);
}

#[tokio::test]
async fn takeover_fault_rolls_back_lease_and_registry_rows() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 187).await;
    let request = logical_request();
    let expired = attempt("fault-old", "fault-old", 1, 1);
    store
        .reserve_or_replay_logical_turn(request.clone(), expired.clone())
        .await
        .expect("expired reservation");
    sqlx::query(
        "CREATE TRIGGER logical_turn_registry_fault
         BEFORE INSERT ON cognitive_logical_turn_attempts
         WHEN NEW.transition = 'active'
         BEGIN SELECT RAISE(ABORT, 'injected logical registry fault'); END",
    )
    .execute(&store.pool)
    .await
    .expect("fault trigger");
    let failed = store
        .reserve_or_replay_logical_turn(
            request.clone(),
            attempt_with_owner_epoch("fault-new", "fault-new", 2, 1, now() + 3_600),
        )
        .await;
    assert!(failed.is_err());
    sqlx::query("DROP TRIGGER logical_turn_registry_fault")
        .execute(&store.pool)
        .await
        .expect("drop fault trigger");
    let attempts: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_logical_turn_attempts")
        .fetch_one(&store.pool)
        .await
        .expect("attempt count after rollback");
    let leases: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases")
        .fetch_one(&store.pool)
        .await
        .expect("lease count after rollback");
    assert_eq!(attempts, 1, "registry rows must roll back together");
    assert_eq!(
        leases, 1,
        "new and terminal lease rows must roll back together"
    );
    let state: String = sqlx::query_scalar(
        "SELECT state FROM cognitive_local_leases
         WHERE lease_id = ? ORDER BY lease_sequence DESC LIMIT 1",
    )
    .bind(&expired.lease_id)
    .fetch_one(&store.pool)
    .await
    .expect("old lease state after rollback");
    assert_eq!(state, "active");

    let takeover = store
        .reserve_or_replay_logical_turn(
            request,
            attempt_with_owner_epoch("fault-new", "fault-new", 2, 1, now() + 3_600),
        )
        .await
        .expect("retry takeover");
    assert!(matches!(takeover, LogicalTurnReservation::Takeover { .. }));
}

#[tokio::test]
async fn tampered_registry_digest_is_rejected_on_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 188).await;
    store
        .reserve_or_replay_logical_turn(
            logical_request(),
            attempt("tamper", "tamper", 1, now() + 3_600),
        )
        .await
        .expect("reservation");
    sqlx::query("DROP TRIGGER cognitive_logical_turn_attempts_no_update")
        .execute(&store.pool)
        .await
        .expect("drop immutable trigger");
    sqlx::query(
        "UPDATE cognitive_logical_turn_attempts
         SET attempt_sha256 = ?",
    )
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .execute(&store.pool)
    .await
    .expect("tamper digest");
    assert!(
        crate::logical_turn_registry::verify_logical_turn_registry(
            &store.pool,
            store.owner_agent_id(),
        )
        .await
        .is_err()
    );
    store.pool.close().await;
    assert!(
        CognitiveStore::open(&layout(&temp, &agent_id(188)))
            .await
            .is_err()
    );
}

#[tokio::test]
async fn evidence_blocks_expired_takeover() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 183).await;
    let request = logical_request();
    let expired = attempt("evidence-old", "evidence-old", 1, 1);
    store
        .reserve_or_replay_logical_turn(request.clone(), expired.clone())
        .await
        .expect("expired reservation");
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES (?, 1, ?, ?, ?, 1, ?, 'admitted', '{}', ?, ?, ?, 0)",
    )
    .bind(&expired.lease_id)
    .bind("event:evidence")
    .bind(&expired.occurrence_key)
    .bind(store.owner_agent_id().as_str())
    .bind(&expired.fencing_token)
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .execute(&store.pool)
    .await
    .expect("evidence row");
    let result = store
        .reserve_or_replay_logical_turn(
            request,
            attempt("evidence-new", "evidence-new", 1, now() + 3_600),
        )
        .await
        .expect("blocked result");
    let LogicalTurnReservation::BlockedByEvidence { evidence, .. } = result else {
        panic!("expected evidence block");
    };
    assert_eq!(evidence.event_rows, 1);
    assert!(!evidence.is_empty());
}

#[tokio::test]
async fn concurrent_reservations_have_one_acquired_and_one_existing() {
    let temp = TempDir::new().expect("temp dir");
    // Separate pools model two independent spawn/process handles against the
    // same Agent-local database; BEGIN IMMEDIATE must still leave one winner.
    let left_store = opened_store(&temp, 184).await;
    let right_store = opened_store(&temp, 184).await;
    let request = logical_request();
    let left = attempt("concurrent-left", "concurrent-left", 1, now() + 3_600);
    let right = attempt("concurrent-right", "concurrent-right", 1, now() + 3_600);
    let (first, second) = tokio::join!(
        left_store.reserve_or_replay_logical_turn(request.clone(), left),
        right_store.reserve_or_replay_logical_turn(request, right),
    );
    let first = first.expect("first concurrent result");
    let second = second.expect("second concurrent result");
    let acquired = usize::from(matches!(first, LogicalTurnReservation::Acquired { .. }))
        + usize::from(matches!(second, LogicalTurnReservation::Acquired { .. }));
    let existing = usize::from(matches!(
        first,
        LogicalTurnReservation::ExistingInFlight { .. }
    )) + usize::from(matches!(
        second,
        LogicalTurnReservation::ExistingInFlight { .. }
    ));
    assert_eq!(acquired, 1);
    assert_eq!(existing, 1);
}

#[test]
fn request_validation_rejects_zero_fences_and_bad_digests() {
    let bad = LogicalTurnRequest {
        logical_turn_id: "turn".to_string(),
        scope_key: "scope".to_string(),
        logical_binding_sha256: Sha256Digest::parse("bad")
            .unwrap_or_else(|_| Sha256Digest::for_bytes(b"placeholder")),
    };
    assert!(
        bad.validate().is_ok(),
        "parsed digest is structurally valid"
    );
    let invalid = LogicalTurnAttemptRequest {
        attempt_id: "attempt".to_string(),
        lease_id: "lease".to_string(),
        journal_id: "journal".to_string(),
        trajectory_id: "trajectory".to_string(),
        occurrence_key: "occurrence".to_string(),
        authority_epoch: 0,
        owner_epoch: 1,
        generation: 1,
        fencing_token: "fence".to_string(),
        lease_expires_at_unix_seconds: 1,
    };
    assert!(matches!(
        invalid.validate(),
        Err(LogicalTurnRegistryError::Invalid(_))
    ));
}

#[test]
fn registry_policy_is_explicitly_local_only() {
    assert_eq!(
        crate::LOGICAL_TURN_REGISTRY_NAMESPACE,
        "local_qualification_only"
    );
    const {
        assert!(!crate::LOGICAL_TURN_REGISTRY_EXTERNAL_EFFECTS);
        assert!(!crate::LOGICAL_TURN_REGISTRY_KG_WRITE_AUTHORITY);
        assert!(!crate::LOGICAL_TURN_REGISTRY_PRODUCTION_CALLER);
    }
}
