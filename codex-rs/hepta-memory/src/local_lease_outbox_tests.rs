use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::LOCAL_LEASE_OUTBOX_EXTERNAL_EFFECTS;
use crate::LOCAL_LEASE_OUTBOX_KG_WRITE_AUTHORITY;
use crate::LOCAL_LEASE_OUTBOX_PRODUCTION_CALLER;
use crate::LocalAdmission;
use crate::LocalAdmissionFault;
use crate::LocalLeaseAcquire;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseOutboxCounts;
use crate::LocalLeaseOutboxError;
use crate::LocalLeaseState;
use crate::LocalOutcomeState;
use crate::LocalReconcileOutcome;
use crate::LocalReplayFinalization;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;

async fn opened_store(temp: &TempDir, number: u8) -> CognitiveStore {
    let owner = agent_id(number);
    CognitiveStore::open(&layout(temp, &owner))
        .await
        .expect("cognitive store")
}

fn acquired(value: LocalLeaseAcquire) -> crate::LocalLeaseOutbox {
    match value {
        LocalLeaseAcquire::Acquired(handle) | LocalLeaseAcquire::Replay(handle) => handle,
    }
}

fn unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
}

#[tokio::test]
async fn inspect_local_lease_head_is_read_only_and_classifies_fences() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 100).await;
    let missing = store
        .inspect_local_lease_head("lease:missing")
        .await
        .expect("missing inspection");
    assert_eq!(missing.disposition, LocalLeaseHeadDisposition::Missing);
    assert!(missing.head.is_none());

    let active = acquired(
        store
            .acquire_local_lease("lease:inspect-active", 1, "fence:inspect-active")
            .await
            .expect("active acquire"),
    );
    let before = active
        .snapshot_counts()
        .await
        .expect("counts before inspect");
    let active_read = store
        .inspect_local_lease_head("lease:inspect-active")
        .await
        .expect("active inspection");
    assert_eq!(active_read.disposition, LocalLeaseHeadDisposition::Active);
    let active_head = active_read.head.as_ref().expect("active head witness");
    assert_eq!(active_head.lease_id, "lease:inspect-active");
    assert_eq!(active_head.generation, 1);
    assert_eq!(active_head.fencing_token, "fence:inspect-active");
    assert_eq!(active_head.state, LocalLeaseState::Active);
    assert_eq!(
        active
            .snapshot_counts()
            .await
            .expect("counts after inspect"),
        before,
        "inspection must not append lease/event/outbox rows"
    );
    active.release().await.expect("release active");
    let released = store
        .inspect_local_lease_head("lease:inspect-active")
        .await
        .expect("released inspection");
    assert_eq!(released.disposition, LocalLeaseHeadDisposition::Released);

    let expired = acquired(
        store
            .acquire_host_bound_lease("lease:inspect-expired", 1, 1, 1, "fence:inspect-expired", 1)
            .await
            .expect("expired active acquire"),
    );
    let expired_read = store
        .inspect_local_lease_head("lease:inspect-expired")
        .await
        .expect("expired inspection");
    assert_eq!(
        expired_read.disposition,
        LocalLeaseHeadDisposition::ExpiredActive
    );
    expired
        .expire_lease_at_unix_seconds(2)
        .await
        .expect("expire active");
    let rolled_back = store
        .inspect_local_lease_head("lease:inspect-expired")
        .await
        .expect("rolled back inspection");
    assert_eq!(
        rolled_back.disposition,
        LocalLeaseHeadDisposition::RolledBack
    );
}

#[tokio::test]
async fn acquire_replay_and_atomic_admission_are_idempotent() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 101).await;
    let first = store
        .acquire_local_lease("lease:admission", 1, "fence:1")
        .await
        .expect("acquire");
    assert!(matches!(first, LocalLeaseAcquire::Acquired(_)));
    let replay = store
        .acquire_local_lease("lease:admission", 1, "fence:1")
        .await
        .expect("replay acquire");
    assert!(matches!(replay, LocalLeaseAcquire::Replay(_)));
    let handle = acquired(first);
    let queued = handle
        .admit("occurrence:1", "local.topic", "{\"value\":1}")
        .await
        .expect("admit");
    let replayed = handle
        .admit("occurrence:1", "local.topic", "{\"value\":1}")
        .await
        .expect("replay admit");
    assert!(matches!(queued, LocalAdmission::Queued(_)));
    assert!(matches!(replayed, LocalAdmission::Replay(_)));
    let counts = handle.snapshot_counts().await.expect("counts");
    assert_eq!(counts.lease_rows, 1);
    assert_eq!(counts.event_rows, 1);
    assert_eq!(counts.outbox_rows, 1);
}

#[tokio::test]
async fn generation_cas_release_and_stale_handle_fail_closed() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 102).await;
    let old = acquired(
        store
            .acquire_local_lease("lease:generation", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    assert!(matches!(
        store
            .acquire_local_lease_after("lease:generation", 1, 2, "fence:2")
            .await,
        Err(LocalLeaseOutboxError::CasConflict(message))
            if message.contains("exact lease head")
    ));
    let released = old.release().await.expect("release");
    assert!(
        store
            .acquire_local_lease_after("lease:generation", 1, 2, "fence:1")
            .await
            .is_err()
    );
    assert!(matches!(
        store
            .acquire_local_lease_after("lease:generation", 1, 2, "fence:2")
            .await,
        Err(LocalLeaseOutboxError::CasConflict(message))
            if message.contains("exact lease head")
    ));
    let next = acquired(
        store
            .acquire_local_lease_after_head("lease:generation", released, 2, "fence:2")
            .await
            .expect("next generation"),
    );
    assert!(
        old.admit("occurrence:stale", "topic", "payload")
            .await
            .is_err()
    );
    assert!(
        next.admit("occurrence:current", "topic", "payload")
            .await
            .is_ok()
    );
    assert!(
        store
            .acquire_local_lease_after("lease:generation", 1, 3, "fence:3")
            .await
            .is_err()
    );
}

#[tokio::test]
async fn bound_expiry_is_explicit_timeout_rollback_and_exact_head_reopens_generation() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 113).await;
    let expires_at = unix_seconds() + 3_600;
    let old = acquired(
        store
            .acquire_local_lease_bound(
                "lease:expiry-terminal",
                3,
                8,
                1,
                "fence:expiry-1",
                expires_at,
            )
            .await
            .expect("bound acquire"),
    );
    old.admit("occurrence:before-expiry", "topic", "payload")
        .await
        .expect("admit before expiry");

    assert!(matches!(
        old.expire_lease_at_unix_seconds(expires_at - 1).await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("has not expired")
    ));

    // Deadline expiry makes ordinary host transitions stale; only the
    // explicit timeout operation may close a bound lease.  Use a separate
    // already-expired head so this assertion is independent of wall-clock
    // scheduling while the admitted lease below still exercises its child
    // journals during terminalization.
    let expired_host_transition = acquired(
        store
            .acquire_local_lease_bound(
                "lease:expired-host-transition",
                3,
                8,
                1,
                "fence:expired-host-transition",
                unix_seconds().saturating_sub(1),
            )
            .await
            .expect("already-expired bound acquire"),
    );
    assert!(matches!(
        expired_host_transition.release().await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("has expired")
    ));
    assert!(matches!(
        expired_host_transition.rollback_lease().await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("has expired")
    ));

    let expired = old
        .expire_lease_at_unix_seconds(expires_at)
        .await
        .expect("explicit expiry rollback");
    assert_eq!(expired.state, crate::LocalLeaseState::RolledBack);
    assert_eq!(expired.lease_sequence, 2);
    assert_eq!(expired.generation, 1);
    assert_eq!(expired.fencing_token, "fence:expiry-1");
    assert_eq!(expired.authority_epoch, Some(3));
    assert_eq!(expired.owner_epoch, Some(8));
    assert_eq!(expired.lease_expires_at_unix_seconds, Some(expires_at));

    // A host retry after a committed timeout is a replay, not another
    // terminal append.  The historical event/outbox fence remains valid.
    let replay = old
        .expire_lease_at_unix_seconds(expires_at)
        .await
        .expect("expiry replay");
    assert_eq!(replay, expired);
    assert_eq!(
        old.snapshot_counts()
            .await
            .expect("post-expiry counts")
            .lease_rows,
        2
    );

    // The pre-expiry writer remains fenced after timeout terminalization.
    assert!(matches!(
        old.admit("occurrence:stale-after-expiry", "topic", "payload")
            .await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));

    let next_expires_at = unix_seconds() + 3_600;
    let next = acquired(
        store
            .acquire_local_lease_after_head_bound(
                "lease:expiry-terminal",
                expired.clone(),
                3,
                8,
                2,
                "fence:expiry-2",
                next_expires_at,
            )
            .await
            .expect("exact-head next generation"),
    );
    assert_eq!(next.generation(), 2);
    assert_eq!(next.fencing_token(), "fence:expiry-2");
    assert_eq!(
        next.binding()
            .expect("next bound lease")
            .lease_expires_at_unix_seconds,
        next_expires_at
    );
    assert!(
        next.admit("occurrence:next-generation", "topic", "payload")
            .await
            .is_ok()
    );
}

#[tokio::test]
async fn verify_current_rejects_expired_active_head_but_reopen_allows_explicit_expiry() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 116).await;
    let expires_at = unix_seconds().saturating_sub(1);
    let lease = acquired(
        store
            .acquire_local_lease_bound(
                "lease:verify-expired",
                3,
                8,
                1,
                "fence:verify-expired",
                expires_at,
            )
            .await
            .expect("bound acquire"),
    );

    assert!(matches!(
        lease.verify_current().await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("has expired")
    ));

    // Restart recovery intentionally remains available: a host can reopen
    // the expired active head and make the explicit timeout decision itself.
    let reopened = store
        .reopen_local_lease("lease:verify-expired", 1, "fence:verify-expired")
        .await
        .expect("reopen expired head for explicit expiry");
    let terminal = reopened
        .expire_lease()
        .await
        .expect("explicit expiry after reopen");
    assert_eq!(terminal.state, crate::LocalLeaseState::RolledBack);
    assert_eq!(terminal.lease_sequence, 2);
}

#[tokio::test]
async fn expiry_rejects_legacy_unbound_leases() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 114).await;
    let legacy = acquired(
        store
            .acquire_local_lease("lease:unbound-expiry", 1, "fence:legacy")
            .await
            .expect("legacy acquire"),
    );
    assert!(matches!(
        legacy.expire_lease().await,
        Err(LocalLeaseOutboxError::Invalid(message))
            if message.contains("explicit authority/owner/expiry binding")
    ));
}

#[tokio::test]
async fn host_bound_reopen_requires_exact_head_and_binding() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 141).await;
    let expires_at = unix_seconds() + 3_600;
    let lease = acquired(
        store
            .acquire_host_bound_lease(
                "lease:host-reopen",
                10,
                20,
                1,
                "fence:host-reopen-1",
                expires_at,
            )
            .await
            .expect("host-bound acquire"),
    );
    let head = lease.head_witness().await.expect("active head witness");
    assert_eq!(head.state, crate::LocalLeaseState::Active);
    assert_eq!(head.authority_epoch, Some(10));
    assert_eq!(head.owner_epoch, Some(20));

    let reopened = store
        .reopen_host_bound_lease(head.clone(), 10, 20, expires_at)
        .await
        .expect("exact host-bound reopen");
    assert_eq!(reopened.head_witness().await.expect("reopened head"), head);

    let before = lease
        .snapshot_counts()
        .await
        .expect("counts before rejects");
    assert!(matches!(
        store
            .reopen_host_bound_lease(head.clone(), 10, 21, expires_at)
            .await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("binding")
    ));

    let mut tampered_head = head.clone();
    tampered_head.lease_sha256 = Sha256Digest::for_bytes(b"tampered-host-head");
    assert!(matches!(
        store
            .reopen_host_bound_lease(tampered_head, 10, 20, expires_at)
            .await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("no longer matches")
    ));
    assert_eq!(
        lease.snapshot_counts().await.expect("counts after rejects"),
        before,
        "reopen rejects must never append lease/event/outbox rows"
    );

    let legacy = acquired(
        store
            .acquire_local_lease("lease:host-reopen-legacy", 1, "fence:legacy")
            .await
            .expect("legacy acquire"),
    );
    let legacy_head = legacy.head_witness().await.expect("legacy head witness");
    assert!(matches!(
        store
            .reopen_host_bound_lease(legacy_head, 1, 1, expires_at)
            .await,
        Err(LocalLeaseOutboxError::StaleFence(message))
            if message.contains("binding")
    ));
}

#[tokio::test]
async fn host_bound_successor_cas_requires_lexicographically_newer_epochs() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 142).await;
    let first = acquired(
        store
            .acquire_host_bound_lease(
                "lease:host-epochs",
                4,
                8,
                1,
                "fence:host-epochs-1",
                unix_seconds() + 3_600,
            )
            .await
            .expect("first host-bound acquire"),
    );
    let terminal = first.release().await.expect("terminal head");

    let before = first
        .snapshot_counts()
        .await
        .expect("counts before epoch rejects");
    assert!(matches!(
        store
            .acquire_host_bound_lease_after_head(
                "lease:host-epochs",
                terminal.clone(),
                4,
                8,
                2,
                "fence:host-epochs-replay",
                unix_seconds() + 3_600,
            )
            .await,
        Err(LocalLeaseOutboxError::CasConflict(message))
            if message.contains("epoch must advance")
    ));
    assert!(matches!(
        store
            .acquire_host_bound_lease_after_head(
                "lease:host-epochs",
                terminal.clone(),
                3,
                99,
                2,
                "fence:host-epochs-regressed-authority",
                unix_seconds() + 3_600,
            )
            .await,
        Err(LocalLeaseOutboxError::CasConflict(message))
            if message.contains("epoch must advance")
    ));
    assert_eq!(
        first
            .snapshot_counts()
            .await
            .expect("counts after epoch rejects"),
        before
    );

    let next = acquired(
        store
            .acquire_host_bound_lease_after_head(
                "lease:host-epochs",
                terminal.clone(),
                4,
                9,
                2,
                "fence:host-epochs-2",
                unix_seconds() + 3_600,
            )
            .await
            .expect("strict owner epoch successor"),
    );
    assert_eq!(next.generation(), 2);
    assert_eq!(next.binding().expect("next binding").owner_epoch, 9);
    assert!(
        matches!(
            first.head_witness().await,
            Err(LocalLeaseOutboxError::StaleFence(_))
        ),
        "a stale handle cannot witness a newer generation"
    );

    let stale_counts = next
        .snapshot_counts()
        .await
        .expect("counts before stale CAS");
    let stale_result = store
        .acquire_host_bound_lease_after_head(
            "lease:host-epochs",
            terminal,
            5,
            1,
            2,
            "fence:host-epochs-stale-head",
            unix_seconds() + 3_600,
        )
        .await;
    assert!(
        matches!(
            stale_result,
            Err(LocalLeaseOutboxError::CasConflict(ref message))
                if message.contains("no longer matches")
        ),
        "unexpected stale CAS result: {stale_result:?}"
    );
    assert_eq!(
        next.snapshot_counts()
            .await
            .expect("counts after stale CAS"),
        stale_counts
    );

    let next_terminal = next.release().await.expect("second terminal head");
    let authority_transfer = acquired(
        store
            .acquire_host_bound_lease_after_head(
                "lease:host-epochs",
                next_terminal,
                5,
                1,
                3,
                "fence:host-epochs-3",
                unix_seconds() + 3_600,
            )
            .await
            .expect("higher authority epoch permits explicit owner reset"),
    );
    assert_eq!(
        authority_transfer
            .binding()
            .expect("authority transfer binding")
            .owner_epoch,
        1
    );
}

#[tokio::test]
async fn terminal_or_indeterminate_occurrence_never_replays_as_queued() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 106).await;
    let handle = acquired(
        store
            .acquire_local_lease("lease:terminal-replay", 1, "fence:1")
            .await
            .expect("acquire"),
    );

    for (occurrence, outcome) in [
        ("occurrence:committed", LocalReconcileOutcome::Committed),
        ("occurrence:rejected", LocalReconcileOutcome::Rejected),
    ] {
        handle
            .admit(occurrence, "topic", "payload")
            .await
            .expect("admit");
        handle
            .mark_indeterminate(occurrence, "lost local ack")
            .await
            .expect("mark indeterminate");
        handle
            .reconcile(occurrence, outcome)
            .await
            .expect("reconcile");
        assert!(matches!(
            handle.admit(occurrence, "topic", "payload").await,
            Err(LocalLeaseOutboxError::IllegalTransition(_))
        ));
    }

    handle
        .admit("occurrence:rolled-back", "topic", "payload")
        .await
        .expect("admit");
    handle
        .rollback_occurrence("occurrence:rolled-back", "operator rollback")
        .await
        .expect("rollback");
    assert!(matches!(
        handle
            .admit("occurrence:rolled-back", "topic", "payload")
            .await,
        Err(LocalLeaseOutboxError::IllegalTransition(_))
    ));

    handle
        .admit("occurrence:indeterminate", "topic", "payload")
        .await
        .expect("admit");
    handle
        .mark_indeterminate("occurrence:indeterminate", "lost local ack")
        .await
        .expect("mark indeterminate");
    assert!(matches!(
        handle
            .admit("occurrence:indeterminate", "topic", "payload")
            .await,
        Err(LocalLeaseOutboxError::IllegalTransition(_))
    ));
}

#[tokio::test]
async fn lease_terminalization_rejects_unresolved_outbox_until_occurrence_is_settled() {
    // A queued or indeterminate child intent still needs the exact active
    // generation/fence to append its reconcile decision.  Closing the lease
    // first would make that recovery impossible and could strand an unknown
    // target-side result forever.  Both normal terminal decisions therefore
    // fail closed without appending a lease row until the occurrence is
    // explicitly rolled back (or otherwise reconciled).
    for (index, transition) in ["release", "rollback"].into_iter().enumerate() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp, 108 + index as u8).await;
        let lease = acquired(
            store
                .acquire_local_lease(
                    format!("lease:unresolved-terminal-{transition}"),
                    1,
                    format!("fence:unresolved-terminal-{transition}"),
                )
                .await
                .expect("acquire"),
        );
        lease
            .admit("occurrence:unresolved", "topic", "payload")
            .await
            .expect("admit queued occurrence");

        let before = lease
            .snapshot_counts()
            .await
            .expect("counts before terminal");
        let head_before = lease.head_witness().await.expect("head before terminal");
        let first = match transition {
            "release" => lease.release().await,
            "rollback" => lease.rollback_lease().await,
            _ => unreachable!("test transition"),
        };
        assert!(
            matches!(
                &first,
                Err(LocalLeaseOutboxError::IllegalTransition(message))
                    if message.contains("unresolved local occurrences")
            ),
            "{transition} must reject a queued occurrence: {first:?}"
        );
        assert_eq!(
            lease
                .snapshot_counts()
                .await
                .expect("counts after queued rejection"),
            before,
            "{transition} must not append a terminal lease for a queued occurrence"
        );
        assert_eq!(
            lease
                .head_witness()
                .await
                .expect("head after queued rejection"),
            head_before,
            "{transition} must preserve the active head after a queued rejection"
        );

        lease
            .mark_indeterminate("occurrence:unresolved", "qualification unknown outcome")
            .await
            .expect("mark indeterminate");
        let after_indeterminate = lease
            .snapshot_counts()
            .await
            .expect("counts after indeterminate");
        assert_eq!(after_indeterminate.lease_rows, before.lease_rows);
        assert_eq!(after_indeterminate.event_rows, before.event_rows + 1);
        assert_eq!(after_indeterminate.outbox_rows, before.outbox_rows);

        let second = match transition {
            "release" => lease.release().await,
            "rollback" => lease.rollback_lease().await,
            _ => unreachable!("test transition"),
        };
        assert!(
            matches!(
                &second,
                Err(LocalLeaseOutboxError::IllegalTransition(message))
                    if message.contains("unresolved local occurrences")
            ),
            "{transition} must reject an indeterminate occurrence: {second:?}"
        );
        assert_eq!(
            lease
                .snapshot_counts()
                .await
                .expect("counts after indeterminate rejection"),
            after_indeterminate,
            "{transition} must not append a terminal lease for an indeterminate occurrence"
        );

        lease
            .rollback_occurrence("occurrence:unresolved", "qualification recovery rollback")
            .await
            .expect("settle occurrence");
        let terminal = match transition {
            "release" => lease.release().await,
            "rollback" => lease.rollback_lease().await,
            _ => unreachable!("test transition"),
        }
        .expect("terminalize settled lease");
        let expected_state = if transition == "release" {
            LocalLeaseState::Released
        } else {
            LocalLeaseState::RolledBack
        };
        assert_eq!(terminal.state, expected_state);
        assert_eq!(
            lease
                .snapshot_counts()
                .await
                .expect("counts after settled terminal"),
            LocalLeaseOutboxCounts {
                lease_rows: 2,
                event_rows: 3,
                outbox_rows: 1,
            }
        );
    }
}

#[tokio::test]
async fn successor_terminalization_ignores_unresolved_expired_generation() {
    // Expiry is the explicit quarantine path for an old generation.  Its
    // queued child can no longer be reconciled by a successor because every
    // outcome append is fenced to the original generation/token.  A later
    // generation must therefore be allowed to terminalize when *its own*
    // occurrences are settled, while still rejecting a queued occurrence
    // belonging to that current generation.
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 117).await;
    let now = unix_seconds();
    let old_expires_at = now.saturating_add(3_600);
    let old = acquired(
        store
            .acquire_local_lease_bound(
                "lease:expired-unresolved-successor",
                3,
                8,
                1,
                "fence:expired-unresolved-1",
                old_expires_at,
            )
            .await
            .expect("old bound acquire"),
    );
    old.admit("occurrence:expired-unresolved", "topic", "payload")
        .await
        .expect("old queued admission");
    let expired = old
        .expire_lease_at_unix_seconds(old_expires_at)
        .await
        .expect("explicit expiry quarantine");

    let next = acquired(
        store
            .acquire_local_lease_after_head_bound(
                "lease:expired-unresolved-successor",
                expired,
                3,
                8,
                2,
                "fence:expired-unresolved-2",
                old_expires_at.saturating_add(3_600),
            )
            .await
            .expect("successor acquire"),
    );
    next.admit("occurrence:successor", "topic", "payload")
        .await
        .expect("successor queued admission");
    assert!(matches!(
        next.release().await,
        Err(LocalLeaseOutboxError::IllegalTransition(message))
            if message.contains("occurrence:successor")
    ));
    next.rollback_occurrence("occurrence:successor", "settle successor")
        .await
        .expect("settle successor occurrence");

    // The unresolved old-generation row is intentionally ignored by the
    // normal terminalization guard; no old row is rewritten or deleted.
    let released = next
        .release()
        .await
        .expect("successor release despite quarantined history");
    assert_eq!(released.generation, 2);
    assert_eq!(released.state, LocalLeaseState::Released);
    assert!(matches!(
        old.rollback_occurrence("occurrence:expired-unresolved", "late old rollback")
            .await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert_eq!(
        next.snapshot_counts().await.expect("final counts"),
        LocalLeaseOutboxCounts {
            lease_rows: 4,
            event_rows: 3,
            outbox_rows: 2,
        }
    );
}

#[tokio::test]
async fn new_generation_retry_of_old_occurrence_is_stale_not_corrupt() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 107).await;
    let old = acquired(
        store
            .acquire_local_lease("lease:cross-generation", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    old.admit("occurrence:old", "topic", "payload")
        .await
        .expect("old admission");
    old.rollback_occurrence("occurrence:old", "finish generation before retry")
        .await
        .expect("settle old occurrence");
    let released = old.release().await.expect("release");
    let next = acquired(
        store
            .acquire_local_lease_after_head("lease:cross-generation", released, 2, "fence:2")
            .await
            .expect("next generation"),
    );
    assert!(matches!(
        next.admit("occurrence:old", "topic", "payload").await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert!(matches!(
        next.mark_indeterminate("occurrence:old", "late ack").await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert!(matches!(
        next.rollback_occurrence("occurrence:old", "late rollback")
            .await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert!(matches!(
        next.status("occurrence:old").await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert_eq!(
        next.snapshot_counts()
            .await
            .expect("counts after stale outcomes"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 3,
            event_rows: 2,
            outbox_rows: 1,
        }
    );
}

#[tokio::test]
async fn lease_head_cas_rejects_stale_terminal_head_and_digest_mismatch() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 108).await;
    let first = acquired(
        store
            .acquire_local_lease("lease:head-cas", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let first_terminal = first.release().await.expect("release first");
    let second = acquired(
        store
            .acquire_local_lease_after_head("lease:head-cas", first_terminal.clone(), 2, "fence:2")
            .await
            .expect("acquire second"),
    );
    let second_terminal = second.release().await.expect("release second");

    // The old generation-1 terminal head cannot cross the generation-2
    // terminal transition, even though its generation would otherwise imply
    // the requested next generation.
    assert!(matches!(
        store
            .acquire_local_lease_after_head("lease:head-cas", first_terminal.clone(), 2, "fence:3",)
            .await,
        Err(LocalLeaseOutboxError::CasConflict(_))
    ));

    let mut forged = second_terminal;
    forged.lease_sha256 = Sha256Digest::for_bytes(b"forged head");
    assert!(matches!(
        store
            .acquire_local_lease_after_head("lease:head-cas", forged, 3, "fence:3")
            .await,
        Err(LocalLeaseOutboxError::CasConflict(_))
    ));
}

#[tokio::test]
async fn maximum_length_lease_id_keeps_generated_row_ids_bounded() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 109).await;
    let lease_id = "l".repeat(512);
    let handle = acquired(
        store
            .acquire_local_lease(&lease_id, 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let LocalAdmission::Queued(receipt) = handle
        .admit("occurrence:max-lease-id", "topic", "payload")
        .await
        .expect("admit")
    else {
        panic!("first admission must append");
    };
    assert!(receipt.event_id.len() <= 512);
    assert!(receipt.outbox_id.len() <= 512);
}

#[tokio::test]
async fn event_and_outbox_faults_leave_no_partial_rows() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 103).await;
    let handle = acquired(
        store
            .acquire_local_lease("lease:atomic", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    assert!(
        handle
            .admit_with_fault(
                "occurrence:fault",
                "topic",
                "payload",
                LocalAdmissionFault::AfterEventBeforeOutbox,
            )
            .await
            .is_err()
    );
    assert_eq!(
        handle.snapshot_counts().await.expect("counts after fault"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 1,
            event_rows: 0,
            outbox_rows: 0,
        }
    );
    assert!(
        handle
            .admit_with_fault(
                "occurrence:fault-after-outbox",
                "topic",
                "payload",
                LocalAdmissionFault::AfterOutboxBeforeCommit,
            )
            .await
            .is_err()
    );
    assert_eq!(
        handle
            .snapshot_counts()
            .await
            .expect("counts after outbox fault"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 1,
            event_rows: 0,
            outbox_rows: 0,
        }
    );
    assert!(matches!(
        handle.admit("occurrence:fault", "topic", "payload").await,
        Ok(LocalAdmission::Queued(_))
    ));
}

#[tokio::test]
async fn unknown_reconcile_survives_reopen_and_never_claims_effect() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(104);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let handle = acquired(
        store
            .acquire_local_lease("lease:unknown", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let admission = handle
        .admit("occurrence:unknown", "topic", "payload")
        .await
        .expect("admit");
    let LocalAdmission::Queued(receipt) = admission else {
        panic!("first admission must append");
    };
    assert!(!receipt.external_effect);
    handle
        .mark_indeterminate("occurrence:unknown", "lost-local-ack")
        .await
        .expect("indeterminate");
    assert_eq!(
        handle.status("occurrence:unknown").await.expect("status"),
        LocalOutcomeState::Indeterminate
    );
    store.pool.close().await;
    drop(handle);
    drop(store);

    let reopened_store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen store");
    let reopened = reopened_store
        .reopen_local_lease("lease:unknown", 1, "fence:1")
        .await
        .expect("reopen lease");
    let outcome = reopened
        .reconcile("occurrence:unknown", LocalReconcileOutcome::Committed)
        .await
        .expect("reconcile");
    assert!(!outcome.external_effect);
    assert_eq!(
        reopened.status("occurrence:unknown").await.expect("status"),
        LocalOutcomeState::Committed
    );
}

#[tokio::test]
async fn indeterminate_replay_is_status_aware_and_releases_without_dispatch() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(110);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let first = acquired(
        store
            .acquire_local_lease("lease:replay-recovery", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let LocalAdmission::Queued(receipt) = first
        .admit("occurrence:replay-recovery", "topic", "payload")
        .await
        .expect("admit")
    else {
        panic!("first admission must append");
    };
    assert!(!receipt.external_effect);
    first
        .mark_indeterminate("occurrence:replay-recovery", "simulated-crash-window")
        .await
        .expect("indeterminate");

    // Simulate process death after the durable indeterminate row and before
    // the lease release.  Reopening the same generation must not call admit
    // again or turn the quarantined outbox into a dispatchable receipt.
    drop(first);
    store.pool.close().await;
    drop(store);
    let reopened_store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen store");
    let replay = match reopened_store
        .acquire_local_lease("lease:replay-recovery", 1, "fence:1")
        .await
        .expect("replay acquire")
    {
        LocalLeaseAcquire::Replay(handle) => handle,
        LocalLeaseAcquire::Acquired(_) => panic!("reopen must replay the active lease"),
    };
    let finalized = replay
        .finalize_replayed_occurrence("occurrence:replay-recovery")
        .await
        .expect("status-aware finalization");
    let LocalReplayFinalization::Released {
        outcome,
        external_effect,
        ..
    } = finalized
    else {
        panic!("indeterminate occurrence must be released");
    };
    assert_eq!(outcome, LocalOutcomeState::Indeterminate);
    assert!(!external_effect);
    assert_eq!(
        replay.snapshot_counts().await.expect("counts"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 2,
            event_rows: 2,
            outbox_rows: 1,
        }
    );
    assert!(
        reopened_store
            .acquire_local_lease("lease:replay-recovery", 1, "fence:1")
            .await
            .is_err()
    );
}

#[tokio::test]
async fn replay_finalization_keeps_lease_active_when_another_occurrence_is_unresolved() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 113).await;
    let first = acquired(
        store
            .acquire_local_lease("lease:replay-multiple", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let LocalAdmission::Queued(_) = first
        .admit("occurrence:replay-indeterminate", "topic", "payload-a")
        .await
        .expect("first admission")
    else {
        panic!("first occurrence must append");
    };
    let LocalAdmission::Queued(_) = first
        .admit("occurrence:replay-queued", "topic", "payload-b")
        .await
        .expect("second admission")
    else {
        panic!("second occurrence must append");
    };
    first
        .mark_indeterminate(
            "occurrence:replay-indeterminate",
            "target-may-have-committed",
        )
        .await
        .expect("mark indeterminate");
    drop(first);

    let replay = acquired(
        store
            .acquire_local_lease("lease:replay-multiple", 1, "fence:1")
            .await
            .expect("replay acquire"),
    );
    let error = replay
        .finalize_replayed_occurrence("occurrence:replay-indeterminate")
        .await
        .expect_err("a second unresolved occurrence must block lease release");
    assert!(matches!(
        error,
        LocalLeaseOutboxError::IllegalTransition(ref message)
            if message.contains("occurrence:replay-queued")
    ));
    assert_eq!(
        replay
            .status("occurrence:replay-indeterminate")
            .await
            .expect("indeterminate status"),
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        replay
            .status("occurrence:replay-queued")
            .await
            .expect("queued status"),
        LocalOutcomeState::Queued
    );

    // Once the other occurrence is explicitly settled, the original
    // indeterminate replay may close the lease as before.
    replay
        .rollback_occurrence("occurrence:replay-queued", "operator-revoked")
        .await
        .expect("settle second occurrence");
    let finalized = replay
        .finalize_replayed_occurrence("occurrence:replay-indeterminate")
        .await
        .expect("finalize after all other occurrences settle");
    let LocalReplayFinalization::Released {
        outcome,
        external_effect,
        ..
    } = finalized
    else {
        panic!("indeterminate occurrence must release after peer settles");
    };
    assert_eq!(outcome, LocalOutcomeState::Indeterminate);
    assert!(!external_effect);
    assert!(
        store
            .acquire_local_lease("lease:replay-multiple", 1, "fence:1")
            .await
            .is_err()
    );
}

#[tokio::test]
async fn queued_replay_returns_original_receipt_and_keeps_lease_active() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 111).await;
    let first = acquired(
        store
            .acquire_local_lease("lease:queued-replay", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    let LocalAdmission::Queued(original) = first
        .admit("occurrence:queued-replay", "topic", "payload")
        .await
        .expect("admit")
    else {
        panic!("first admission must append");
    };
    let replay = acquired(
        store
            .acquire_local_lease("lease:queued-replay", 1, "fence:1")
            .await
            .expect("replay"),
    );
    let recovered = replay
        .finalize_replayed_occurrence("occurrence:queued-replay")
        .await
        .expect("queued replay");
    let LocalReplayFinalization::Queued(receipt) = recovered else {
        panic!("queued occurrence must remain active");
    };
    assert_eq!(receipt, original);
    assert!(!receipt.external_effect);
    assert_eq!(
        replay.status("occurrence:queued-replay").await.unwrap(),
        LocalOutcomeState::Queued
    );
}

#[tokio::test]
async fn replay_without_admission_is_explicit_and_keeps_lease_writable() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 112).await;
    let replay = acquired(
        store
            .acquire_local_lease("lease:admit-crash-window", 1, "fence:1")
            .await
            .expect("initial acquire"),
    );

    // The process exits after acquire commits but before admit starts.  The
    // next acquire is a replay, yet there is no occurrence row to finalize.
    let recovered = replay
        .finalize_replayed_occurrence("occurrence:admit-crash-window")
        .await
        .expect("not-admitted replay");
    assert_eq!(recovered, LocalReplayFinalization::NotAdmitted);
    assert_eq!(
        replay.snapshot_counts().await.expect("counts before admit"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 1,
            event_rows: 0,
            outbox_rows: 0,
        }
    );

    let LocalAdmission::Queued(receipt) = replay
        .admit("occurrence:admit-crash-window", "topic", "payload")
        .await
        .expect("retry original admission")
    else {
        panic!("not-admitted replay must permit the first admission");
    };
    assert!(!receipt.external_effect);
    assert_eq!(
        replay.snapshot_counts().await.expect("counts after admit"),
        crate::LocalLeaseOutboxCounts {
            lease_rows: 1,
            event_rows: 1,
            outbox_rows: 1,
        }
    );
}

#[tokio::test]
async fn tampered_event_chain_is_rejected_on_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 105).await;
    let handle = acquired(
        store
            .acquire_local_lease("lease:tamper", 1, "fence:1")
            .await
            .expect("acquire"),
    );
    handle
        .admit("occurrence:tamper", "topic", "payload")
        .await
        .expect("admit");
    sqlx::query("DROP TRIGGER cognitive_local_events_no_update")
        .execute(&store.pool)
        .await
        .expect("drop test trigger");
    sqlx::query(
        "UPDATE cognitive_local_events SET payload_json = 'changed' WHERE lease_id = 'lease:tamper'",
    )
    .execute(&store.pool)
    .await
    .expect("tamper");
    assert!(
        store
            .reopen_local_lease("lease:tamper", 1, "fence:1")
            .await
            .is_err()
    );
}

#[tokio::test]
async fn replay_acquisition_rejects_corrupt_child_chain_before_returning_handle() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp, 106).await;
    let handle = acquired(
        store
            .acquire_local_lease(
                "lease:replay-child-corrupt",
                1,
                "fence:replay-child-corrupt",
            )
            .await
            .expect("acquire"),
    );
    handle
        .admit("occurrence:replay-child-corrupt", "topic", "payload")
        .await
        .expect("admit");

    // Simulate a damaged store discovered on process restart.  The normal
    // reopen API already audits child chains; the acquisition/replay API must
    // enforce the same boundary before returning `LocalLeaseAcquire::Replay`.
    sqlx::query("DROP TRIGGER cognitive_local_events_no_update")
        .execute(&store.pool)
        .await
        .expect("drop test trigger");
    sqlx::query(
        "UPDATE cognitive_local_events
         SET payload_json = 'changed'
         WHERE lease_id = 'lease:replay-child-corrupt'",
    )
    .execute(&store.pool)
    .await
    .expect("tamper event");

    let replay = store
        .acquire_local_lease(
            "lease:replay-child-corrupt",
            1,
            "fence:replay-child-corrupt",
        )
        .await;
    assert!(matches!(
        replay,
        Err(LocalLeaseOutboxError::Corrupt(message))
            if message.contains("event payload digest mismatch")
    ));
    let lease_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_leases
         WHERE lease_id = 'lease:replay-child-corrupt'",
    )
    .fetch_one(&store.pool)
    .await
    .expect("lease row count");
    assert_eq!(lease_rows, 1, "corrupt replay must not append a lease head");
}

#[tokio::test]
async fn tampered_child_chain_cannot_be_terminalized_by_release_or_rollback() {
    // Exercise both host terminal decisions against each append-only child
    // journal.  A corrupt child must fail before the lease terminal row is
    // appended; otherwise a caller could use release/rollback to hide the
    // damaged history from subsequent readers.
    for (index, (transition, child)) in [
        ("release", "event"),
        ("rollback", "event"),
        ("release", "outbox"),
        ("rollback", "outbox"),
    ]
    .into_iter()
    .enumerate()
    {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp, 115 + index as u8).await;
        let lease_id = format!("lease:terminal-tamper-{transition}-{child}");
        let handle = acquired(
            store
                .acquire_local_lease(&lease_id, 1, "fence:tamper")
                .await
                .expect("acquire"),
        );
        handle
            .admit("occurrence:terminal-tamper", "topic", "payload")
            .await
            .expect("admit");

        if child == "event" {
            sqlx::query("DROP TRIGGER cognitive_local_events_no_update")
                .execute(&store.pool)
                .await
                .expect("drop event update trigger");
            sqlx::query("UPDATE cognitive_local_events SET payload_json = ? WHERE lease_id = ?")
                .bind("tampered event payload")
                .bind(&lease_id)
                .execute(&store.pool)
                .await
                .expect("tamper event payload");
        } else {
            sqlx::query("DROP TRIGGER cognitive_local_outbox_no_update")
                .execute(&store.pool)
                .await
                .expect("drop outbox update trigger");
            sqlx::query("UPDATE cognitive_local_outbox SET payload_json = ? WHERE lease_id = ?")
                .bind("tampered outbox payload")
                .bind(&lease_id)
                .execute(&store.pool)
                .await
                .expect("tamper outbox payload");
        }

        let before = handle
            .snapshot_counts()
            .await
            .expect("counts before transition");
        let result = match transition {
            "release" => handle.release().await,
            "rollback" => handle.rollback_lease().await,
            _ => unreachable!("test transition"),
        };
        assert!(
            matches!(result, Err(LocalLeaseOutboxError::Corrupt(_))),
            "{transition} must fail closed for tampered {child} chain: {result:?}"
        );
        assert_eq!(
            handle
                .snapshot_counts()
                .await
                .expect("counts after transition"),
            before,
            "{transition} must not append a terminal lease for tampered {child} chain"
        );
    }
}

#[tokio::test]
async fn terminal_recovery_rejects_missing_event_outbox_pair_without_appending_lease() {
    // The outbox has a foreign key to an event, but no reverse constraint that
    // keeps every admitted event paired.  Simulate an imported/damaged store
    // by bypassing the immutable delete trigger and remove the intent.  A
    // terminal lease mutation must fail closed while the event-only history is
    // still observable for forensic recovery.
    for (index, transition) in ["release", "rollback"].into_iter().enumerate() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp, 119 + index as u8).await;
        let lease = acquired(
            store
                .acquire_local_lease(
                    format!("lease:pairing-{transition}"),
                    1,
                    format!("fence:pairing-{transition}"),
                )
                .await
                .expect("acquire"),
        );
        lease
            .admit("occurrence:pairing", "topic", "payload")
            .await
            .expect("admit");
        sqlx::query("DROP TRIGGER cognitive_local_outbox_no_delete")
            .execute(&store.pool)
            .await
            .expect("drop outbox delete trigger");
        sqlx::query("DELETE FROM cognitive_local_outbox WHERE lease_id = ?")
            .bind(lease.lease_id())
            .execute(&store.pool)
            .await
            .expect("delete damaged outbox intent");

        let before = lease
            .snapshot_counts()
            .await
            .expect("counts before terminal");
        assert_eq!(before.outbox_rows, 0);
        let result = match transition {
            "release" => lease.release().await,
            "rollback" => lease.rollback_lease().await,
            _ => unreachable!("test transition"),
        };
        assert!(
            matches!(result, Err(LocalLeaseOutboxError::Corrupt(ref message)) if message.contains("cardinality mismatch")),
            "{transition} must reject an unpaired admitted event: {result:?}"
        );
        assert_eq!(
            lease
                .snapshot_counts()
                .await
                .expect("counts after terminal"),
            before,
            "{transition} must not append a terminal lease over damaged history"
        );
    }
}

#[tokio::test]
async fn expiry_and_replay_finalization_reject_missing_outbox_pair() {
    // Exercise the two other lease-terminal paths that run in a caller-owned
    // BEGIN IMMEDIATE transaction.  Both must share the same reverse-pair
    // invariant as release/rollback.
    for (index, path) in ["expiry", "replay"].into_iter().enumerate() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp, 121 + index as u8).await;
        let expiry_deadline = unix_seconds() + 3_600;
        let lease = if path == "expiry" {
            acquired(
                store
                    .acquire_host_bound_lease(
                        "lease:pairing-expiry",
                        1,
                        1,
                        1,
                        "fence:pairing-expiry",
                        expiry_deadline,
                    )
                    .await
                    .expect("bound acquire"),
            )
        } else {
            acquired(
                store
                    .acquire_local_lease("lease:pairing-replay", 1, "fence:pairing-replay")
                    .await
                    .expect("acquire"),
            )
        };
        lease
            .admit("occurrence:pairing", "topic", "payload")
            .await
            .expect("admit");
        if path == "replay" {
            lease
                .mark_indeterminate("occurrence:pairing", "qualification crash")
                .await
                .expect("mark indeterminate");
        }
        sqlx::query("DROP TRIGGER cognitive_local_outbox_no_delete")
            .execute(&store.pool)
            .await
            .expect("drop outbox delete trigger");
        sqlx::query("DELETE FROM cognitive_local_outbox WHERE lease_id = ?")
            .bind(lease.lease_id())
            .execute(&store.pool)
            .await
            .expect("delete damaged outbox intent");
        let before = lease
            .snapshot_counts()
            .await
            .expect("counts before recovery");
        let result = if path == "expiry" {
            lease
                .expire_lease_at_unix_seconds(expiry_deadline)
                .await
                .map(|_| ())
        } else {
            lease
                .finalize_replayed_occurrence("occurrence:pairing")
                .await
                .map(|_| ())
        };
        assert!(
            matches!(result, Err(LocalLeaseOutboxError::Corrupt(ref message)) if message.contains("cardinality mismatch")),
            "{path} must reject an unpaired admitted event: {result:?}"
        );
        assert_eq!(
            lease
                .snapshot_counts()
                .await
                .expect("counts after recovery"),
            before,
            "{path} must not append over damaged history"
        );
    }
}

#[tokio::test]
async fn reopen_rejects_late_reconcile_after_terminal_outcome() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(117);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let handle = acquired(
        store
            .acquire_local_lease("lease:late-reconcile", 1, "fence:late-reconcile")
            .await
            .expect("acquire"),
    );
    handle
        .admit("occurrence:late-reconcile", "topic", "payload")
        .await
        .expect("admit");
    handle
        .mark_indeterminate("occurrence:late-reconcile", "lost local ack")
        .await
        .expect("mark indeterminate");
    handle
        .reconcile(
            "occurrence:late-reconcile",
            LocalReconcileOutcome::Committed,
        )
        .await
        .expect("terminal reconcile");

    // Model an imported/damaged store that bypassed the public transition
    // guard. A distinct transition kind is still accepted by the schema, so
    // the append-only verifier must reject it rather than allowing
    // `current_outcome` to downgrade the committed result to indeterminate.
    let previous_sha256: String = sqlx::query_scalar(
        "SELECT event_sha256 FROM cognitive_local_events
         WHERE lease_id = ? ORDER BY event_sequence DESC LIMIT 1",
    )
    .bind("lease:late-reconcile")
    .fetch_one(&store.pool)
    .await
    .expect("event head");
    let payload = "late quarantine";
    let payload_sha256 = Sha256Digest::for_bytes(payload.as_bytes());
    let event_sequence = 4_u64;
    let event_id = "event:late-reconcile";
    let kind = "reconcile_still_indeterminate";
    let event_sha256 = test_event_digest(
        "lease:late-reconcile",
        event_sequence,
        event_id,
        "occurrence:late-reconcile",
        &owner,
        handle.generation(),
        handle.fencing_token(),
        kind,
        &payload_sha256,
        &Sha256Digest::parse(previous_sha256.clone()).expect("event head digest"),
    );
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind("lease:late-reconcile")
    .bind(i64::try_from(event_sequence).expect("event sequence"))
    .bind(event_id)
    .bind("occurrence:late-reconcile")
    .bind(owner.as_str())
    .bind(i64::try_from(handle.generation()).expect("generation"))
    .bind(handle.fencing_token())
    .bind(kind)
    .bind(payload)
    .bind(payload_sha256.as_str())
    .bind(&previous_sha256)
    .bind(event_sha256.as_str())
    .bind(0_i64)
    .execute(&store.pool)
    .await
    .expect("insert late transition");

    assert!(matches!(
        handle.status("occurrence:late-reconcile").await,
        Err(LocalLeaseOutboxError::Corrupt(message))
            if message.contains("invalid reconcile_still_indeterminate transition")
    ));
    drop(handle);
    store.pool.close().await;
    drop(store);

    let reopened = CognitiveStore::open(&layout(&temp, &owner)).await;
    assert!(matches!(
        reopened,
        Err(crate::CognitiveStoreError::Corrupt(message))
            if message.contains("invalid reconcile_still_indeterminate transition")
    ));
}

#[tokio::test]
async fn verifier_accepts_direct_queued_apply_and_reject_after_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(118);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let handle = acquired(
        store
            .acquire_local_lease("lease:direct-terminal", 1, "fence:direct-terminal")
            .await
            .expect("acquire"),
    );

    // `apply` and `reject` are the higher-level saga names for these two
    // direct queued terminal events.  This H4 lane predates those wrappers,
    // so insert their exact immutable event representation as a test-only
    // imported chain and exercise the same reopen verifier they use.
    handle
        .admit("occurrence:direct-apply", "topic", "apply-payload")
        .await
        .expect("apply admission");
    handle
        .admit("occurrence:direct-reject", "topic", "reject-payload")
        .await
        .expect("reject admission");
    insert_test_transition(
        &store,
        "lease:direct-terminal",
        "occurrence:direct-apply",
        &owner,
        handle.generation(),
        handle.fencing_token(),
        "event:direct-apply",
        "reconcile_committed",
        "target already committed",
    )
    .await;
    insert_test_transition(
        &store,
        "lease:direct-terminal",
        "occurrence:direct-reject",
        &owner,
        handle.generation(),
        handle.fencing_token(),
        "event:direct-reject",
        "reconcile_rejected",
        "target rejected",
    )
    .await;

    assert_eq!(
        handle
            .status("occurrence:direct-apply")
            .await
            .expect("direct apply status"),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        handle
            .status("occurrence:direct-reject")
            .await
            .expect("direct reject status"),
        LocalOutcomeState::Rejected
    );

    // A terminal direct result is one-shot.  Neither an indeterminate marker
    // nor a rollback may be appended after it, even though both are valid
    // transitions from Queued in the ordinary recovery path.  The public
    // writer rejects these before inserting a row.
    let late_marker = handle
        .mark_indeterminate("occurrence:direct-apply", "late marker")
        .await;
    assert!(matches!(
        late_marker,
        Err(LocalLeaseOutboxError::IllegalTransition(message))
            if message.contains("already in committed state")
    ));
    assert!(matches!(
        handle
            .rollback_occurrence("occurrence:direct-reject", "late rollback")
            .await,
        Err(LocalLeaseOutboxError::IllegalTransition(message))
            if message.contains("already in rejected state")
    ));

    drop(handle);
    store.pool.close().await;
    drop(store);

    let reopened_store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen store");
    let reopened = acquired(
        reopened_store
            .acquire_local_lease("lease:direct-terminal", 1, "fence:direct-terminal")
            .await
            .expect("replay lease"),
    );
    assert_eq!(
        reopened
            .status("occurrence:direct-apply")
            .await
            .expect("reopened direct apply status"),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        reopened
            .status("occurrence:direct-reject")
            .await
            .expect("reopened direct reject status"),
        LocalOutcomeState::Rejected
    );

    // A validly hashed imported row can bypass the public guard.  The
    // reopen/status verifier must still fail closed when that row attempts a
    // late rollback after the direct Rejected terminal result.
    insert_test_transition(
        &reopened_store,
        "lease:direct-terminal",
        "occurrence:direct-reject",
        &owner,
        reopened.generation(),
        reopened.fencing_token(),
        "event:late-direct-rollback",
        "rolled_back",
        "late imported rollback",
    )
    .await;
    assert!(matches!(
        reopened
            .status("occurrence:direct-reject")
            .await,
        Err(LocalLeaseOutboxError::Corrupt(message))
            if message.contains("invalid rolled_back transition from rejected")
    ));
}

/// Insert one validly hashed event after a normal admission.  This models a
/// higher-level apply/reject writer that shares the append-only event table
/// but is not present in this qualification-only branch.
async fn insert_test_transition(
    store: &CognitiveStore,
    lease_id: &str,
    occurrence_key: &str,
    owner: &codex_hepta_contracts::AgentId,
    generation: u64,
    fencing_token: &str,
    event_id: &str,
    kind: &str,
    payload: &str,
) {
    let previous_sha256: String = sqlx::query_scalar(
        "SELECT event_sha256 FROM cognitive_local_events
         WHERE lease_id = ? ORDER BY event_sequence DESC LIMIT 1",
    )
    .bind(lease_id)
    .fetch_one(&store.pool)
    .await
    .expect("event head");
    let event_sequence: i64 = sqlx::query_scalar(
        "SELECT COALESCE(MAX(event_sequence), 0) + 1
         FROM cognitive_local_events WHERE lease_id = ?",
    )
    .bind(lease_id)
    .fetch_one(&store.pool)
    .await
    .expect("next event sequence");
    let event_sequence = u64::try_from(event_sequence).expect("event sequence fits");
    let payload_sha256 = Sha256Digest::for_bytes(payload.as_bytes());
    let event_sha256 = test_event_digest(
        lease_id,
        event_sequence,
        event_id,
        occurrence_key,
        owner,
        generation,
        fencing_token,
        kind,
        &payload_sha256,
        &Sha256Digest::parse(previous_sha256.clone()).expect("event head digest"),
    );
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(lease_id)
    .bind(i64::try_from(event_sequence).expect("event sequence"))
    .bind(event_id)
    .bind(occurrence_key)
    .bind(owner.as_str())
    .bind(i64::try_from(generation).expect("generation"))
    .bind(fencing_token)
    .bind(kind)
    .bind(payload)
    .bind(payload_sha256.as_str())
    .bind(previous_sha256)
    .bind(event_sha256.as_str())
    .bind(0_i64)
    .execute(&store.pool)
    .await
    .expect("insert direct terminal transition");
}

fn test_event_digest(
    lease_id: &str,
    sequence: u64,
    event_id: &str,
    occurrence_key: &str,
    owner: &codex_hepta_contracts::AgentId,
    generation: u64,
    fencing_token: &str,
    kind: &str,
    payload_sha256: &Sha256Digest,
    previous: &Sha256Digest,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_test_part(&mut hasher, b"hepta-memory:local-event:v1");
    frame_test_part(&mut hasher, lease_id.as_bytes());
    frame_test_part(&mut hasher, &sequence.to_be_bytes());
    frame_test_part(&mut hasher, event_id.as_bytes());
    frame_test_part(&mut hasher, occurrence_key.as_bytes());
    frame_test_part(&mut hasher, owner.as_str().as_bytes());
    frame_test_part(&mut hasher, &generation.to_be_bytes());
    frame_test_part(&mut hasher, fencing_token.as_bytes());
    frame_test_part(&mut hasher, kind.as_bytes());
    frame_test_part(&mut hasher, payload_sha256.as_str().as_bytes());
    frame_test_part(&mut hasher, previous.as_str().as_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn frame_test_part(hasher: &mut Sha256, part: &[u8]) {
    hasher.update((part.len() as u64).to_be_bytes());
    hasher.update(part);
}

#[test]
fn local_lease_outbox_has_no_production_authority() {
    assert!(!LOCAL_LEASE_OUTBOX_EXTERNAL_EFFECTS);
    assert!(!LOCAL_LEASE_OUTBOX_KG_WRITE_AUTHORITY);
    assert!(!LOCAL_LEASE_OUTBOX_PRODUCTION_CALLER);
}

// H4 qualification probe constants. These are test-only and deliberately
// use the same Agent-local SQLite lease/event/outbox tables as the explicit
// qualification writer; no production path reads these environment values.
const H4_PROBE_MODE_ENV: &str = "HEPTA_MEMORY_H4_CRASH_PROBE_MODE";
const H4_PROBE_FLEET_ROOT_ENV: &str = "HEPTA_MEMORY_H4_CRASH_PROBE_FLEET_ROOT";
const H4_PROBE_MARKER_DIR_ENV: &str = "HEPTA_MEMORY_H4_CRASH_PROBE_MARKER_DIR";
const H4_PROBE_HELPER_TEST: &str =
    "local_lease_outbox_tests::qualification_durable_writer_crash_helper";
const H4_PROBE_OWNER_NUMBER: u8 = 240;
const H4_PROBE_LEASE_ID: &str = "lease:h4-crash-probe";
const H4_PROBE_OCCURRENCE_KEY: &str = "occurrence:h4-crash-probe";
const H4_PROBE_TOPIC: &str = "qualification.h4.crash.v1";
const H4_PROBE_PAYLOAD: &str = r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false,"production_caller":false}"#;
const H4_PROBE_AUTHORITY_EPOCH: u64 = 7;
const H4_PROBE_INITIAL_OWNER_EPOCH: u64 = 11;
const H4_PROBE_SUCCESSOR_OWNER_EPOCH: u64 = 12;
const H4_PROBE_INITIAL_GENERATION: u64 = 1;
const H4_PROBE_SUCCESSOR_GENERATION: u64 = 2;
const H4_PROBE_INITIAL_TOKEN: &str = "h4-crash-probe:fence:1";
const H4_PROBE_SUCCESSOR_TOKEN: &str = "h4-crash-probe:fence:2";
const H4_PROBE_LEASE_TTL_SECONDS: u64 = 3_600;
const H4_PROBE_SCHEMA_VERSION: u32 = 1;
const H4_PROBE_NAMESPACE: &str = "local_development_only";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct H4ProbeChildMarker {
    phase: String,
    lease_rows: u64,
    event_rows: u64,
    outbox_rows: u64,
    lease_state: String,
    lease_expires_at_unix_seconds: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LocalLeaseOutboxCountsReceipt {
    lease_rows: u64,
    event_rows: u64,
    outbox_rows: u64,
}

impl From<LocalLeaseOutboxCounts> for LocalLeaseOutboxCountsReceipt {
    fn from(counts: LocalLeaseOutboxCounts) -> Self {
        Self {
            lease_rows: counts.lease_rows,
            event_rows: counts.event_rows,
            outbox_rows: counts.outbox_rows,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct H4CrashReopenReceipt {
    schema_version: u32,
    namespace: String,
    journal_mode: String,
    synchronous: i64,
    rollback: H4ProbeChildMarker,
    crash: H4ProbeChildMarker,
    counts_after_reopen: LocalLeaseOutboxCountsReceipt,
    counts_after_retry: LocalLeaseOutboxCountsReceipt,
    counts_after_terminal: LocalLeaseOutboxCountsReceipt,
    retry_disposition: String,
    terminal_transition: String,
    final_lease_state: String,
    external_effect: bool,
    kg_write_authority: bool,
    production_caller: bool,
    physical_power_loss_claim: bool,
}

impl H4CrashReopenReceipt {
    fn validate(&self) -> Result<(), String> {
        if self.schema_version != H4_PROBE_SCHEMA_VERSION || self.namespace != H4_PROBE_NAMESPACE {
            return Err("unsupported H4 receipt schema or namespace".to_string());
        }
        if !self.journal_mode.eq_ignore_ascii_case("wal") || self.synchronous != 2 {
            return Err(format!(
                "H4 receipt did not observe WAL/FULL (journal_mode={}, synchronous={})",
                self.journal_mode, self.synchronous
            ));
        }
        if self.rollback.phase != "rollback"
            || self.rollback.event_rows != 0
            || self.rollback.outbox_rows != 0
            || self.rollback.lease_rows != 2
            || self.rollback.lease_state != "rolled_back"
        {
            return Err("rollback child did not leave only the terminal lease witness".to_string());
        }
        if self.crash.phase != "crash_after_admission"
            || self.crash.event_rows != 1
            || self.crash.outbox_rows != 1
            || self.crash.lease_rows != 3
            || self.crash.lease_state != "active"
        {
            return Err(
                "crash child marker does not describe one admitted active attempt".to_string(),
            );
        }
        if self.counts_after_reopen.lease_rows != 3
            || self.counts_after_reopen.event_rows != 1
            || self.counts_after_reopen.outbox_rows != 1
            || self.counts_after_retry.lease_rows != 3
            || self.counts_after_retry.event_rows != 1
            || self.counts_after_retry.outbox_rows != 1
            || self.counts_after_terminal.lease_rows != 4
            || self.counts_after_terminal.event_rows != 3
            || self.counts_after_terminal.outbox_rows != 1
        {
            return Err("H4 reopen/retry/terminal counts are inconsistent".to_string());
        }
        if self.retry_disposition != "replay"
            || self.terminal_transition
                != "mark_indeterminate_then_rollback_occurrence_then_release"
            || self.final_lease_state != "released"
        {
            return Err("H4 retry/rollback transition receipt is incomplete".to_string());
        }
        if self.external_effect || self.kg_write_authority || self.production_caller {
            return Err("H4 receipt crossed the qualification-only authority boundary".to_string());
        }
        if self.physical_power_loss_claim {
            return Err("H4 child kill must not claim physical power-loss durability".to_string());
        }
        Ok(())
    }
}

fn h4_publish_synced(path: &Path, bytes: &[u8]) {
    let parent = path.parent().expect("H4 marker parent");
    fs::create_dir_all(parent).expect("create H4 marker parent");
    let name = path
        .file_name()
        .expect("H4 marker filename")
        .to_string_lossy();
    let temporary = parent.join(format!(".{name}.tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .expect("create H4 marker temporary");
    file.write_all(bytes).expect("write H4 marker");
    file.sync_all().expect("sync H4 marker");
    drop(file);
    fs::rename(&temporary, path).expect("publish H4 marker");
}

fn h4_publish_marker(path: &Path, marker: &H4ProbeChildMarker) {
    h4_publish_synced(
        path,
        serde_json::to_string(marker)
            .expect("serialize H4 child marker")
            .as_bytes(),
    );
}

async fn h4_open_store(fleet_root: &Path) -> CognitiveStore {
    let canonical_root = fleet_root.canonicalize().expect("H4 canonical fleet root");
    let fleet = HeptaFleetRoot::parse(canonical_root).expect("H4 fleet root");
    let owner = agent_id(H4_PROBE_OWNER_NUMBER);
    CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("H4 cognitive store")
}

async fn h4_counts(store: &CognitiveStore) -> LocalLeaseOutboxCounts {
    let lease_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases WHERE lease_id = ?")
            .bind(H4_PROBE_LEASE_ID)
            .fetch_one(&store.pool)
            .await
            .expect("H4 lease row count");
    let event_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE lease_id = ?")
            .bind(H4_PROBE_LEASE_ID)
            .fetch_one(&store.pool)
            .await
            .expect("H4 event row count");
    let outbox_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox WHERE lease_id = ?")
            .bind(H4_PROBE_LEASE_ID)
            .fetch_one(&store.pool)
            .await
            .expect("H4 outbox row count");
    LocalLeaseOutboxCounts {
        lease_rows: u64::try_from(lease_rows).expect("non-negative H4 lease count"),
        event_rows: u64::try_from(event_rows).expect("non-negative H4 event count"),
        outbox_rows: u64::try_from(outbox_rows).expect("non-negative H4 outbox count"),
    }
}

async fn h4_pragma_durability(store: &CognitiveStore) -> (String, i64) {
    let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&store.pool)
        .await
        .expect("H4 journal mode");
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
        .fetch_one(&store.pool)
        .await
        .expect("H4 synchronous mode");
    (journal_mode, synchronous)
}

fn h4_initial_expiry() -> u64 {
    unix_seconds()
        .checked_add(H4_PROBE_LEASE_TTL_SECONDS)
        .expect("H4 expiry overflow")
}

fn h4_probe_command(
    executable: &Path,
    mode: &str,
    fleet_root: &Path,
    marker_dir: &Path,
) -> Command {
    let mut command = Command::new(executable);
    command
        .arg("--exact")
        .arg(H4_PROBE_HELPER_TEST)
        .arg("--nocapture")
        .env(H4_PROBE_MODE_ENV, mode)
        .env(H4_PROBE_FLEET_ROOT_ENV, fleet_root)
        .env(H4_PROBE_MARKER_DIR_ENV, marker_dir)
        .env("RUST_BACKTRACE", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
}

struct H4ProbeChild {
    child: Option<Child>,
}

impl H4ProbeChild {
    fn spawn(mut command: Command) -> Self {
        Self {
            child: Some(command.spawn().expect("spawn H4 probe child")),
        }
    }

    fn wait_for_marker(&mut self, marker: &Path, timeout: Duration) {
        let deadline = Instant::now() + timeout;
        loop {
            if marker.is_file() {
                return;
            }
            if let Some(status) = self
                .child
                .as_mut()
                .expect("H4 probe child handle")
                .try_wait()
                .expect("poll H4 probe child")
            {
                panic!(
                    "H4 probe child exited before marker {}: {status}",
                    marker.display()
                );
            }
            assert!(
                Instant::now() < deadline,
                "H4 probe child did not publish marker {} within {:?}",
                marker.display(),
                timeout
            );
            thread::sleep(Duration::from_millis(5));
        }
    }

    fn wait(&mut self, timeout: Duration) -> ExitStatus {
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(status) = self
                .child
                .as_mut()
                .expect("H4 probe child handle")
                .try_wait()
                .expect("poll H4 probe child")
            {
                self.child.take();
                return status;
            }
            if Instant::now() >= deadline {
                let _ = self.child.as_mut().expect("H4 probe child handle").kill();
                let status = self
                    .child
                    .as_mut()
                    .expect("H4 probe child handle")
                    .wait()
                    .expect("wait timed-out H4 probe child");
                self.child.take();
                panic!("H4 probe child timed out after {timeout:?}: {status}");
            }
            thread::sleep(Duration::from_millis(5));
        }
    }

    fn kill_and_wait(&mut self) -> ExitStatus {
        let _ = self.child.as_mut().expect("H4 probe child handle").kill();
        let status = self
            .child
            .as_mut()
            .expect("H4 probe child handle")
            .wait()
            .expect("wait killed H4 probe child");
        self.child.take();
        status
    }
}

impl Drop for H4ProbeChild {
    fn drop(&mut self) {
        let Some(mut child) = self.child.take() else {
            return;
        };
        if child.try_wait().ok().flatten().is_none() {
            let _ = child.kill();
        }
        let _ = child.wait();
    }
}

/// Child entrypoint for [`qualification_durable_writer_crash_reopen_probe`].
/// It is inert during ordinary test runs and is activated only by the
/// parent-side ignored qualification harness below.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn qualification_durable_writer_crash_helper() {
    let Some(mode) = env::var(H4_PROBE_MODE_ENV).ok() else {
        return;
    };
    let fleet_root =
        PathBuf::from(env::var(H4_PROBE_FLEET_ROOT_ENV).expect("H4 fleet root environment"));
    let marker_dir =
        PathBuf::from(env::var(H4_PROBE_MARKER_DIR_ENV).expect("H4 marker directory environment"));
    let store = h4_open_store(&fleet_root).await;
    match mode.as_str() {
        "rollback" => {
            let lease = acquired(
                store
                    .acquire_host_bound_lease(
                        H4_PROBE_LEASE_ID,
                        H4_PROBE_AUTHORITY_EPOCH,
                        H4_PROBE_INITIAL_OWNER_EPOCH,
                        H4_PROBE_INITIAL_GENERATION,
                        H4_PROBE_INITIAL_TOKEN,
                        h4_initial_expiry(),
                    )
                    .await
                    .expect("H4 initial host-bound lease"),
            );
            assert!(matches!(
                lease
                    .admit_with_fault(
                        H4_PROBE_OCCURRENCE_KEY,
                        H4_PROBE_TOPIC,
                        H4_PROBE_PAYLOAD,
                        LocalAdmissionFault::AfterOutboxBeforeCommit,
                    )
                    .await,
                Err(LocalLeaseOutboxError::TransactionAborted(_))
            ));
            let after_fault = lease.snapshot_counts().await.expect("H4 rollback counts");
            assert_eq!(
                after_fault,
                LocalLeaseOutboxCounts {
                    lease_rows: 1,
                    event_rows: 0,
                    outbox_rows: 0,
                }
            );
            let terminal = lease.rollback_lease().await.expect("H4 rollback lease");
            assert_eq!(terminal.state, LocalLeaseState::RolledBack);
            let counts = lease
                .snapshot_counts()
                .await
                .expect("H4 rollback terminal counts");
            h4_publish_marker(
                &marker_dir.join("rollback-complete"),
                &H4ProbeChildMarker {
                    phase: "rollback".to_string(),
                    lease_rows: counts.lease_rows,
                    event_rows: counts.event_rows,
                    outbox_rows: counts.outbox_rows,
                    lease_state: "rolled_back".to_string(),
                    lease_expires_at_unix_seconds: terminal.lease_expires_at_unix_seconds,
                },
            );
        }
        "crash" => {
            let inspection = store
                .inspect_local_lease_head(H4_PROBE_LEASE_ID)
                .await
                .expect("H4 rollback head inspection");
            assert_eq!(
                inspection.disposition,
                LocalLeaseHeadDisposition::RolledBack
            );
            let previous = inspection.head.expect("H4 rollback head");
            let lease = acquired(
                store
                    .acquire_host_bound_lease_after_head(
                        H4_PROBE_LEASE_ID,
                        previous,
                        H4_PROBE_AUTHORITY_EPOCH,
                        H4_PROBE_SUCCESSOR_OWNER_EPOCH,
                        H4_PROBE_SUCCESSOR_GENERATION,
                        H4_PROBE_SUCCESSOR_TOKEN,
                        h4_initial_expiry(),
                    )
                    .await
                    .expect("H4 successor host-bound lease"),
            );
            let LocalAdmission::Queued(receipt) = lease
                .admit(H4_PROBE_OCCURRENCE_KEY, H4_PROBE_TOPIC, H4_PROBE_PAYLOAD)
                .await
                .expect("H4 crash admission")
            else {
                panic!("H4 crash child admission unexpectedly replayed");
            };
            assert!(!receipt.external_effect);
            let counts = lease.snapshot_counts().await.expect("H4 crash counts");
            let head = lease.head_witness().await.expect("H4 crash active head");
            h4_publish_marker(
                &marker_dir.join("crash-after-admission"),
                &H4ProbeChildMarker {
                    phase: "crash_after_admission".to_string(),
                    lease_rows: counts.lease_rows,
                    event_rows: counts.event_rows,
                    outbox_rows: counts.outbox_rows,
                    lease_state: "active".to_string(),
                    lease_expires_at_unix_seconds: head.lease_expires_at_unix_seconds,
                },
            );
            // The parent sends an OS-level kill after the fsync'd marker. A
            // pending future keeps this a real child-process crash boundary
            // rather than an ordinary clean shutdown.
            std::future::pending::<()>().await;
        }
        other => panic!("unknown H4 probe mode {other}"),
    }
    store.pool.close().await;
}

/// Qualification-only child crash/reopen probe for H4's durable writer and
/// local outbox. The rollback child injects a failure before COMMIT and
/// proves that event+outbox rows are absent; the crash child commits an
/// admission, publishes an fsync'd marker, and is then terminated by the
/// parent. A fresh process reopens the WAL/FULL database, verifies the exact
/// lease head and immutable chains, replays without a second outbox row, then
/// marks the unknown outcome, rolls the occurrence back, and releases the
/// lease. The emitted receipt is local qualification evidence only: the
/// child kill is not an interruption inside a SQLite syscall and makes no
/// physical host/VM power-loss durability claim.
#[test]
#[ignore = "qualification: child-process crash/reopen probe"]
fn qualification_durable_writer_crash_reopen_probe() {
    let temp = TempDir::new().expect("H4 qualification temp dir");
    let fleet_root = temp.path().join("fleet");
    let marker_dir = temp.path().join("markers");
    fs::create_dir_all(&fleet_root).expect("H4 fleet root");
    fs::create_dir_all(&marker_dir).expect("H4 marker root");
    let executable = env::current_exe().expect("H4 qualification test executable");
    let timeout = Duration::from_secs(30);
    let runtime = tokio::runtime::Runtime::new().expect("H4 qualification runtime");

    let mut rollback = H4ProbeChild::spawn(h4_probe_command(
        &executable,
        "rollback",
        &fleet_root,
        &marker_dir,
    ));
    let rollback_status = rollback.wait(timeout);
    assert!(
        rollback_status.success(),
        "H4 rollback child failed: {rollback_status}"
    );
    let rollback_marker: H4ProbeChildMarker = serde_json::from_slice(
        &fs::read(marker_dir.join("rollback-complete")).expect("H4 rollback marker"),
    )
    .expect("decode H4 rollback marker");
    assert_eq!(rollback_marker.phase, "rollback");
    assert_eq!(rollback_marker.lease_rows, 2);
    assert_eq!(rollback_marker.event_rows, 0);
    assert_eq!(rollback_marker.outbox_rows, 0);
    assert_eq!(rollback_marker.lease_state, "rolled_back");

    let (journal_mode, synchronous) = runtime.block_on(async {
        let store = h4_open_store(&fleet_root).await;
        let pragma = h4_pragma_durability(&store).await;
        assert_eq!(
            h4_counts(&store).await,
            LocalLeaseOutboxCounts {
                lease_rows: 2,
                event_rows: 0,
                outbox_rows: 0,
            }
        );
        store.pool.close().await;
        pragma
    });
    assert_eq!(journal_mode.to_ascii_lowercase(), "wal");
    assert_eq!(
        synchronous, 2,
        "qualification evidence requires SQLite FULL"
    );

    let mut crash = H4ProbeChild::spawn(h4_probe_command(
        &executable,
        "crash",
        &fleet_root,
        &marker_dir,
    ));
    crash.wait_for_marker(&marker_dir.join("crash-after-admission"), timeout);
    let crash_status = crash.kill_and_wait();
    assert!(
        !crash_status.success(),
        "H4 crash child unexpectedly exited cleanly: {crash_status}"
    );
    let crash_marker: H4ProbeChildMarker = serde_json::from_slice(
        &fs::read(marker_dir.join("crash-after-admission")).expect("H4 crash marker"),
    )
    .expect("decode H4 crash marker");
    assert_eq!(crash_marker.phase, "crash_after_admission");
    assert_eq!(crash_marker.lease_rows, 3);
    assert_eq!(crash_marker.event_rows, 1);
    assert_eq!(crash_marker.outbox_rows, 1);
    assert_eq!(crash_marker.lease_state, "active");

    let (receipt, reopened_counts) = runtime.block_on(async {
        let store = h4_open_store(&fleet_root).await;
        let (reopened_journal_mode, reopened_synchronous) = h4_pragma_durability(&store).await;
        assert_eq!(reopened_journal_mode.to_ascii_lowercase(), "wal");
        assert_eq!(reopened_synchronous, 2);
        let inspection = store
            .inspect_local_lease_head(H4_PROBE_LEASE_ID)
            .await
            .expect("H4 crash active head inspection");
        assert_eq!(inspection.disposition, LocalLeaseHeadDisposition::Active);
        let head = inspection.head.expect("H4 crash active head");
        let expiry = head
            .lease_expires_at_unix_seconds
            .expect("H4 crash expiry binding");
        let lease = store
            .reopen_host_bound_lease(
                head,
                H4_PROBE_AUTHORITY_EPOCH,
                H4_PROBE_SUCCESSOR_OWNER_EPOCH,
                expiry,
            )
            .await
            .expect("H4 exact host-bound reopen");
        let counts_after_reopen = lease.snapshot_counts().await.expect("H4 reopen counts");
        assert_eq!(
            counts_after_reopen,
            LocalLeaseOutboxCounts {
                lease_rows: 3,
                event_rows: 1,
                outbox_rows: 1,
            }
        );
        let replay = lease
            .admit(H4_PROBE_OCCURRENCE_KEY, H4_PROBE_TOPIC, H4_PROBE_PAYLOAD)
            .await
            .expect("H4 admission replay");
        assert!(matches!(replay, LocalAdmission::Replay(_)));
        let counts_after_retry = lease.snapshot_counts().await.expect("H4 retry counts");
        assert_eq!(counts_after_retry, counts_after_reopen);
        lease
            .mark_indeterminate(H4_PROBE_OCCURRENCE_KEY, "child_process_killed_after_commit")
            .await
            .expect("H4 indeterminate marker");
        lease
            .rollback_occurrence(H4_PROBE_OCCURRENCE_KEY, "qualification_recovery_rollback")
            .await
            .expect("H4 occurrence rollback");
        let terminal = lease.release().await.expect("H4 release after rollback");
        assert_eq!(terminal.state, LocalLeaseState::Released);
        let counts_after_terminal = lease.snapshot_counts().await.expect("H4 terminal counts");
        assert_eq!(
            counts_after_terminal,
            LocalLeaseOutboxCounts {
                lease_rows: 4,
                event_rows: 3,
                outbox_rows: 1,
            }
        );
        store.pool.close().await;
        drop(lease);
        drop(store);
        // A second fresh open makes the reopen-time chain verifier part of the
        // probe rather than relying only on the active handle's counts.
        let final_store = h4_open_store(&fleet_root).await;
        let final_counts = h4_counts(&final_store).await;
        assert_eq!(final_counts, counts_after_terminal);
        final_store.pool.close().await;
        let receipt = H4CrashReopenReceipt {
            schema_version: H4_PROBE_SCHEMA_VERSION,
            namespace: H4_PROBE_NAMESPACE.to_string(),
            journal_mode: reopened_journal_mode,
            synchronous: reopened_synchronous,
            rollback: rollback_marker.clone(),
            crash: crash_marker.clone(),
            counts_after_reopen: counts_after_reopen.into(),
            counts_after_retry: counts_after_retry.into(),
            counts_after_terminal: counts_after_terminal.into(),
            retry_disposition: "replay".to_string(),
            terminal_transition: "mark_indeterminate_then_rollback_occurrence_then_release"
                .to_string(),
            final_lease_state: "released".to_string(),
            external_effect: false,
            kg_write_authority: false,
            production_caller: false,
            physical_power_loss_claim: false,
        };
        (receipt, final_counts)
    });
    receipt.validate().expect("self-validating H4 receipt");
    assert_eq!(reopened_counts.lease_rows, 4);
    assert_eq!(reopened_counts.event_rows, 3);
    assert_eq!(reopened_counts.outbox_rows, 1);
    let receipt_path = marker_dir.join("h4-durable-writer-crash-reopen-receipt.json");
    h4_publish_synced(
        &receipt_path,
        &serde_json::to_vec_pretty(&receipt).expect("serialize H4 receipt"),
    );
    let decoded: H4CrashReopenReceipt =
        serde_json::from_slice(&fs::read(&receipt_path).expect("read H4 receipt"))
            .expect("decode H4 receipt");
    decoded.validate().expect("persisted H4 receipt validation");
    eprintln!(
        "H4 qualification durable writer crash/reopen receipt: {}",
        serde_json::to_string(&decoded).expect("render H4 receipt")
    );
}
