//! Native durable writes around the budget/lineage crash boundaries.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn legacy_started_replacement_requires_exact_absence_and_replays_the_next_charged_claim() {
    let directory = tempfile::tempdir().expect("directory");
    let agent = AgentId::parse(uuid::Uuid::new_v4().to_string()).expect("agent");
    let predecessor = RestartProcessWitness::new(
        /*spawn_generation*/ 5,
        ProcessIdentity::new(/*system_id*/ 41, "original-predecessor").expect("identity"),
        ReleaseId::parse("release-a").expect("release"),
    )
    .expect("witness");
    let replacement = RestartProcessWitness::new(
        /*spawn_generation*/ 8,
        ProcessIdentity::new(/*system_id*/ 52, "original-replacement").expect("identity"),
        predecessor.release_id.clone(),
    )
    .expect("witness");
    let claim = crate::restart_budget::claim_restart(
        directory.path(),
        /*maximum_attempts*/ 3,
        std::time::Duration::from_millis(1),
        std::time::Duration::from_millis(250),
    )
    .expect("claim");
    begin(
        directory.path(),
        &agent,
        claim.window_started_unix_ms,
        claim.attempt,
        Some(predecessor),
    )
    .expect("begin");
    let predecessor = read(directory.path())
        .expect("read")
        .expect("lineage")
        .predecessor
        .expect("predecessor");
    mark_predecessor_exited(directory.path(), &agent, &predecessor).expect("exact exit");
    bind_replacement(
        directory.path(),
        &agent,
        claim.window_started_unix_ms,
        claim.attempt,
        replacement.clone(),
    )
    .expect("bind");
    // Recover exactly the legacy schema and checksum, not a fabricated v2
    // fixture that cannot expose failures reading installed old owner state.
    let mut legacy = read(directory.path()).expect("read").expect("lineage");
    legacy.schema_version = 1;
    legacy.record_sha256 = legacy.compute_digest().expect("legacy checksum");
    write(directory.path(), &legacy).expect("legacy write");
    let path = directory.path().join(RESTART_LINEAGE_FILE);
    let original_bytes = std::fs::read(&path).expect("bytes");
    assert!(
        reconcile_pending(
            directory.path(),
            &agent,
            claim.window_started_unix_ms,
            claim.attempt,
            /*current*/ None,
            /*process_lease_present*/ false
        )
        .is_err()
    );
    let mut foreign = replacement.clone();
    foreign.identity =
        ProcessIdentity::new(/*system_id*/ 52, "different-incarnation").expect("identity");
    assert!(mark_process_absent(directory.path(), &agent, &foreign).is_err());
    assert_eq!(
        std::fs::read(&path).expect("unchanged bytes"),
        original_bytes
    );
    mark_process_absent(directory.path(), &agent, &replacement).expect("original absence");
    let expected_exit = ExitedRestart {
        window_started_unix_ms: claim.window_started_unix_ms,
        attempt: claim.attempt,
        replacement: replacement.clone(),
    };
    assert_eq!(
        exited_restart(directory.path(), &agent).expect("exit witness"),
        Some(expected_exit.clone())
    );
    let exited_bytes = std::fs::read(&path).expect("exited bytes");
    let foreign_agent = AgentId::parse(uuid::Uuid::new_v4().to_string()).expect("foreign agent");
    assert!(
        reconcile_pending(
            directory.path(),
            &foreign_agent,
            claim.window_started_unix_ms,
            claim.attempt + 1,
            /*current*/ None,
            /*process_lease_present*/ false
        )
        .is_err()
    );
    assert!(
        begin_absent(
            directory.path(),
            &foreign_agent,
            claim.window_started_unix_ms,
            claim.attempt + 1,
            replacement.clone()
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&path).expect("owned bytes"), exited_bytes);
    assert_eq!(
        reconcile_pending(
            directory.path(),
            &agent,
            claim.window_started_unix_ms,
            claim.attempt,
            /*current*/ None,
            /*process_lease_present*/ false
        )
        .expect("reconcile"),
        RestartRecoveryRole::ReplacementExited
    );
    // Crash boundary: ending the failed pending bit preserves the operation's
    // paid attempt and exact original witness until the next claim is written.
    crate::restart_budget::cancel_restart(directory.path()).expect("end failed pending bit");
    assert!(
        crate::restart_budget::pending_restart(directory.path(), /*maximum_attempts*/ 3)
            .expect("budget")
            .is_none()
    );
    assert_eq!(
        exited_restart(directory.path(), &agent).expect("reopened witness"),
        Some(expected_exit)
    );
    let next = crate::restart_budget::continue_failed_restart(
        directory.path(),
        /*maximum_attempts*/ 3,
        std::time::Duration::from_millis(250),
        claim.window_started_unix_ms,
        claim.attempt,
    )
    .expect("next claim");
    assert_eq!(
        (next.window_started_unix_ms, next.attempt),
        (claim.window_started_unix_ms, 2)
    );
    // Second boundary: a committed claim and old exited lineage replay without
    // silently claiming a third attempt or losing the prior replacement.
    for _ in 0..2 {
        assert_eq!(
            reconcile_pending(
                directory.path(),
                &agent,
                next.window_started_unix_ms,
                next.attempt,
                /*current*/ None,
                /*process_lease_present*/ false
            )
            .expect("next recovery"),
            RestartRecoveryRole::ReplacementPending
        );
        assert_eq!(
            read(directory.path())
                .expect("read")
                .expect("lineage")
                .predecessor,
            Some(replacement.clone())
        );
        let pending =
            crate::restart_budget::pending_restart(directory.path(), /*maximum_attempts*/ 3)
                .expect("budget")
                .expect("pending");
        assert_eq!(
            (pending.window_started_unix_ms, pending.attempt),
            (next.window_started_unix_ms, next.attempt)
        );
    }
}
