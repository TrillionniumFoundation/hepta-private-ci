//! The publisher and PQ Unix trust services are real component fixtures. The
//! existing process driver records exact spawn/adopt/kill entry calls, while
//! paired_process_product exercises the same owner with real Unix children.

use codex_hepta_fleet::PqReleaseQualification;
use codex_hepta_fleet::QualificationResult;

use super::*;
use pretty_assertions::assert_eq;

#[path = "matrix_binding_io_tests.rs"]
mod matrix_binding_io_tests;

pub(super) fn pq_fleet() -> QualificationResult<(PqReleaseQualification, TestFleet)> {
    let temp = tempfile::Builder::new()
        .prefix("hsup-pq-")
        .tempdir_in("/tmp")?;
    let base = temp.path().canonicalize()?;
    let root = HeptaFleetRoot::parse(base.join("fleet"))?;
    let (publisher, registry) =
        PqReleaseQualification::initialize(&base.join("external"), root.clone())?;
    let first = register_agent(&registry, &root, &base, FIRST_AGENT_ID, "workspace-a")?;
    let second = register_agent(&registry, &root, &base, SECOND_AGENT_ID, "workspace-b")?;
    assert!(!registry.is_release_qualification());
    Ok((
        publisher,
        TestFleet {
            _temp: temp,
            registry,
            first,
            second,
        },
    ))
}

pub(super) fn publish(
    publisher: &mut PqReleaseQualification,
    fleet: &TestFleet,
    name: &str,
    matrix: bool,
) -> QualificationResult<ReleaseId> {
    let source = fleet.write_release_source()?;
    let id = ReleaseId::parse(name)?;
    publisher.install_release_bundle(
        &fleet.registry,
        id.clone(),
        &source,
        Vec::new(),
        matrix.then_some(source.as_path()),
        Vec::new(),
    )?;
    fleet.registry.allow_release(&fleet.first, &id)?;
    if matrix {
        write_matrix_binding(&fleet.registry, &fleet.first, 1)?;
    }
    Ok(id)
}

fn reopen(fleet: &mut TestFleet, publisher: &PqReleaseQualification) -> QualificationResult<()> {
    let root = fleet.registry.layout().fleet_root().clone();
    // All synchronous owner calls have returned and the Supervisor has been
    // dropped. Close the last actual publication owner before ordinary reopen.
    let state_only = FleetRegistry::open_existing(root.clone())?;
    drop(std::mem::replace(&mut fleet.registry, state_only));
    fleet.registry = FleetRegistry::open_existing_with_release_authority(root, publisher.config())?;
    Ok(())
}

#[test]
fn cached_release_cannot_spawn_after_current_publisher_withdrawal() -> QualificationResult<()> {
    let (mut publisher, fleet) = pq_fleet()?;
    let first = publish(&mut publisher, &fleet, "queued-v1", /*matrix*/ false)?;
    let second = publish(&mut publisher, &fleet, "queued-v2", /*matrix*/ false)?;
    let cached = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &first)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    publisher.publish_member_ids(
        &fleet.registry,
        std::slice::from_ref(&second),
        publisher.current_unix_seconds() + 3600,
    )?;
    let frontier = publisher.frontier()?;
    let attempts = publisher.cas_attempts();
    assert!(supervisor.start_release(&fleet.first, cached, now).is_err());
    assert_eq!(control.spawn_count(&fleet.first), 0);
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .expect("agent snapshot")
            .active
    );
    assert_eq!(publisher.frontier()?, frontier);
    assert_eq!(publisher.cas_attempts(), attempts);

    // The currently signed rolling-set member remains usable through this
    // ordinary owner; the negative assertion is not a blanket launch disable.
    let current = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &second)?)?;
    supervisor.start_release(&fleet.first, current, now)?;
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}

#[test]
fn cached_release_cannot_spawn_after_trusted_publication_expiry() -> QualificationResult<()> {
    let (mut publisher, fleet) = pq_fleet()?;
    let id = publish(
        &mut publisher,
        &fleet,
        "queued-expiry",
        /*matrix*/ false,
    )?;
    let expires = publisher.current_unix_seconds() + 5;
    publisher.publish_member_ids(&fleet.registry, std::slice::from_ref(&id), expires)?;
    let cached = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    publisher.advance_clock_to(expires + 1);
    let error = supervisor
        .start_release(&fleet.first, cached, now)
        .expect_err("expired publisher permission");
    assert!(
        error
            .to_string()
            .contains("M15 current publication rejected")
    );
    assert_eq!(control.spawn_count(&fleet.first), 0);
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .expect("agent snapshot")
            .active
    );
    Ok(())
}

#[test]
fn delayed_matrix_spawn_rechecks_current_publication_after_agent_becomes_healthy()
-> QualificationResult<()> {
    let (mut publisher, fleet) = pq_fleet()?;
    let id = publish(
        &mut publisher,
        &fleet,
        "matrix-expiry",
        /*matrix*/ true,
    )?;
    let expires = publisher.current_unix_seconds() + 5;
    publisher.publish_member_ids(&fleet.registry, std::slice::from_ref(&id), expires)?;
    let release = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 0);
    // First commit the primary's CURRENT selection under valid publication.
    // Hold back only the public companion binding, so no Matrix process enters
    // before the independently delayed companion admission below.
    let binding_path = supervisor
        .record(&fleet.first)?
        .layout
        .matrix_public_binding()
        .to_path_buf();
    let held_binding = fleet._temp.path().join("held-matrix-binding.json");
    std::fs::rename(&binding_path, &held_binding)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        supervisor
            .record(&fleet.first)?
            .release_state
            .current
            .as_ref(),
        Some(&id)
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 0);
    let waiting = supervisor
        .snapshot(&fleet.first)
        .expect("primary is healthy before companion admission");
    assert!(waiting.healthy);
    assert!(
        waiting
            .matrix
            .last_error
            .as_ref()
            .is_some_and(|error| error.contains("public binding is absent"))
    );
    let retry_at = supervisor
        .slots
        .get(&fleet.first)
        .and_then(|slot| slot.matrix.retry_at)
        .ok_or("missing original Matrix retry deadline")?;
    std::fs::rename(&held_binding, &binding_path)?;
    publisher.advance_clock_to(expires + 1);
    assert_eq!(supervisor.tick(retry_at), TickReport::default());
    let snapshot = supervisor
        .snapshot(&fleet.first)
        .expect("paired agent snapshot");
    assert!(snapshot.active);
    assert!(snapshot.healthy);
    assert!(!snapshot.matrix.active);
    assert!(snapshot.matrix.degraded);
    assert!(
        snapshot
            .matrix
            .last_error
            .as_ref()
            .is_some_and(|error| error.contains("M15 current publication rejected"))
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 0);
    Ok(())
}

#[test]
fn primary_health_after_publication_expiry_preserves_selection_and_blocks_companion()
-> QualificationResult<()> {
    let (mut publisher, fleet) = pq_fleet()?;
    let id = publish(
        &mut publisher,
        &fleet,
        "primary-health-expiry",
        /*matrix*/ true,
    )?;
    let expires = publisher.current_unix_seconds() + 5;
    publisher.publish_member_ids(&fleet.registry, std::slice::from_ref(&id), expires)?;
    let release = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    let before = supervisor.record(&fleet.first)?.release_state;
    publisher.advance_clock_to(expires + 1);
    control.set_healthy(&fleet.first);
    let report = supervisor.tick(now);
    assert_eq!(report.faults.len(), 1);
    assert_eq!(report.faults[0].agent_id, fleet.first);
    assert!(
        report.faults[0]
            .message
            .contains("M15 current publication rejected")
    );
    assert_eq!(supervisor.record(&fleet.first)?.release_state, before);
    let snapshot = supervisor
        .snapshot(&fleet.first)
        .expect("primary health observation");
    assert!(snapshot.active);
    assert!(snapshot.healthy);
    assert!(!snapshot.matrix.active);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 0);
    Ok(())
}

fn recover_after_publication_retirement(expire: bool) -> QualificationResult<()> {
    let (mut publisher, mut fleet) = pq_fleet()?;
    let first = publish(&mut publisher, &fleet, "recover-v1", /*matrix*/ false)?;
    let second = publish(&mut publisher, &fleet, "recover-v2", /*matrix*/ false)?;
    let expires = publisher.current_unix_seconds() + 5;
    publisher.publish_member_ids(&fleet.registry, &[first.clone(), second.clone()], expires)?;
    let release = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &first)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);
    if expire {
        publisher.advance_clock_to(expires + 1);
    } else {
        publisher.publish_member_ids(&fleet.registry, &[second], expires)?;
    }
    reopen(&mut fleet, &publisher)?;
    let frontier = publisher.frontier()?;
    let attempts = publisher.cas_attempts();
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert!(!report.faults.is_empty());
    assert!(
        report
            .faults
            .iter()
            .all(|fault| fault.agent_id == fleet.first)
    );
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("retained fenced child");
    assert!(snapshot.active);
    assert!(snapshot.runtime_fenced);
    assert!(!snapshot.healthy);
    assert_eq!(snapshot.active_release, None);
    // Adoption here establishes exact existing identity for containment. It
    // must never become a fresh healthy owner or another process dispatch.
    assert_eq!(
        control.world.lock().expect("fake world").adoption_requests,
        1
    );
    assert_eq!(control.counts(&fleet.first).2, 1);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(publisher.frontier()?, frontier);
    assert_eq!(publisher.cas_attempts(), attempts);
    control.set_exit(&fleet.first);
    let _ = recovered.tick(now);
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("observed exit")
            .active
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}

#[test]
fn ordinary_recovery_fences_withdrawn_publisher_release_before_adoption() -> QualificationResult<()>
{
    recover_after_publication_retirement(/*expire*/ false)
}

#[test]
fn ordinary_recovery_fences_expired_publisher_release_and_still_recovers_owned_identity()
-> QualificationResult<()> {
    recover_after_publication_retirement(/*expire*/ true)
}

#[test]
fn expired_primary_publication_does_not_skip_independent_matrix_identity_containment()
-> QualificationResult<()> {
    let (mut publisher, mut fleet) = pq_fleet()?;
    let id = publish(
        &mut publisher,
        &fleet,
        "recover-pair-expiry",
        /*matrix*/ true,
    )?;
    let expires = publisher.current_unix_seconds() + 5;
    publisher.publish_member_ids(&fleet.registry, std::slice::from_ref(&id), expires)?;
    let release = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_matrix_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("paired owner")
            .matrix
            .healthy
    );
    drop(supervisor);
    publisher.advance_clock_to(expires + 1);
    reopen(&mut fleet, &publisher)?;
    let retained = (publisher.frontier()?, publisher.cas_attempts());
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert!(!report.faults.is_empty());
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("both retained identities");
    assert!(snapshot.active);
    assert!(snapshot.runtime_fenced);
    assert!(!snapshot.healthy);
    assert!(snapshot.matrix.active);
    assert!(!snapshot.matrix.healthy);
    assert!(snapshot.matrix.degraded);
    assert_eq!(
        control.world.lock().expect("fake world").adoption_requests,
        2
    );
    assert_eq!(control.counts(&fleet.first).2, 1);
    assert_eq!(control.matrix_counts(&fleet.first).2, 1);
    assert_eq!(
        (
            control.spawn_count(&fleet.first),
            control.matrix_spawn_count(&fleet.first)
        ),
        (1, 1)
    );
    assert_eq!((publisher.frontier()?, publisher.cas_attempts()), retained);
    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);
    let _ = recovered.tick(now);
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("both observed exits");
    assert!(!snapshot.active);
    assert!(!snapshot.matrix.active);
    assert_eq!(
        (
            control.spawn_count(&fleet.first),
            control.matrix_spawn_count(&fleet.first)
        ),
        (1, 1)
    );
    Ok(())
}
