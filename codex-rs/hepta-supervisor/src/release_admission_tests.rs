//! Final-use catalog admission across cached descriptors and automatic restarts.

use super::*;

use pretty_assertions::assert_eq;

#[test]
fn cached_catalog_start_is_readmitted_before_any_lifecycle_or_process_effect()
-> Result<(), SupervisorError> {
    for denied in ["revoked", "not_allowed", "removed"] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        let cached = admitted_release(&fleet, &fleet.first, "cached-admission")?;
        let record = supervisor.record(&fleet.first)?;
        match denied {
            "revoked" => fleet
                .registry
                .revoke_release(&fleet.first, cached.release_id())?,
            "not_allowed" => std::fs::remove_file(
                record
                    .layout
                    .releases_root()
                    .join("allow-cached-admission.json"),
            )?,
            "removed" => {
                // A previously resolved descriptor cannot turn into a direct
                // plant merely because its catalog and allowance disappear.
                std::fs::rename(
                    fleet
                        .registry
                        .layout()
                        .releases_root()
                        .join(cached.identity()),
                    // Keep the same parent so the immutable directory's
                    // parent link does not need to change.
                    fleet
                        .registry
                        .layout()
                        .releases_root()
                        .join(".removed-catalog-entry"),
                )?;
                std::fs::remove_file(
                    record
                        .layout
                        .releases_root()
                        .join("allow-cached-admission.json"),
                )?;
                assert!(
                    !fleet
                        .registry
                        .layout()
                        .releases_root()
                        .join(cached.identity())
                        .exists()
                );
            }
            _ => unreachable!(),
        }
        assert!(
            supervisor.start_release(&fleet.first, cached, now).is_err(),
            "{denied}"
        );
        let after = supervisor.record(&fleet.first)?;
        assert_eq!(after.lifecycle, record.lifecycle, "{denied}");
        assert_eq!(after.release_state, record.release_state, "{denied}");
        assert!(crate::lease::read_lease(after.layout.run_root())?.is_none());
        assert_eq!(control.spawn_count(&fleet.first), 0, "{denied}");
    }
    Ok(())
}

#[test]
fn revoked_running_release_cannot_spawn_its_automatic_replacement() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    fleet
        .registry
        .revoke_release(&fleet.first, &ReleaseId::parse("retry-source")?)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let exited = supervisor.record(&fleet.first)?;
    assert_eq!(exited.lifecycle.lifecycle, AgentLifecycle::Failed);
    let failed = supervisor.tick(now + config().restart_backoff_base);
    assert_eq!(failed.faults.len(), 1);
    assert!(failed.faults[0].message.contains("revoked"));
    assert_eq!(supervisor.record(&fleet.first)?.lifecycle, exited.lifecycle);
    assert!(crate::lease::read_lease(exited.layout.run_root())?.is_none());
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}

#[test]
fn registered_start_descriptor_uses_current_canonical_commands() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let canonical = admitted_release(&fleet, &fleet.first, "canonical-dispatch")?;
    let wrong = AgentCommand::new(fake_program("uncanonical-dispatch"), Vec::new())?;
    control.reject_spawn_program(wrong.program.clone());
    supervisor.start_release(
        &fleet.first,
        AgentRelease::new("canonical-dispatch", wrong)?,
        now,
    )?;
    supervisor.with_slot(&fleet.first, |_supervisor, slot| {
        assert_eq!(
            slot.active_release
                .as_ref()
                .expect("admitted selection")
                .command(),
            canonical.command()
        );
        Ok(())
    })?;
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}
