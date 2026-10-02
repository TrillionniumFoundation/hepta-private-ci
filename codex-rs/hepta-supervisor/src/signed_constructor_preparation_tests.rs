//! Pure constructor preparation precedes journal normalization and retains
//! independent exact-owner diagnostics even when signed recovery denies replay.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn signed_denial_before_idle_hydration_preserves_matrix_budget_bytes() -> Result<()> {
    for mode in ["prepared", "queued", "recovery_required", "malformed"] {
        for window in ["future", "expired"] {
            let mut s = Scenario::new(Plant::Paired)?;
            let failed = with_qualification_fault(
                "release_transaction.file_write",
                ErrorKind::Other,
                || s.apply(),
            );
            assert!(matches!(
                failed,
                Err(SupervisorError::SignedMutationIndeterminate(_))
            ));
            let record = s.supervisor.record(&s.fleet.first)?;
            let root = record.layout.run_root();
            let tx = s.legacy_unsigned_prepared()?;
            crate::release_transaction::write_release_transaction(root, &tx)?;
            let intent_path = root.join(crate::signed_intent::SIGNED_INTENT_FILE);
            if mode == "malformed" {
                std::fs::write(&intent_path, b"{invalid signed witness}")?;
            } else {
                let status = match mode {
                    "prepared" => SignedIntentStatus::Prepared,
                    "queued" => SignedIntentStatus::Queued,
                    "recovery_required" => SignedIntentStatus::RecoveryRequired,
                    _ => unreachable!("typed fixture mode"),
                };
                let intent = read_intent(root)?
                    .expect("real verified grant intent")
                    .with_status(status)?;
                crate::signed_intent::write_intent(root, &intent)?;
            }
            let wall = crate::restart_journal::unix_millis_now()?;
            let window_started_unix_millis = match window {
                "future" => wall + 600_000,
                "expired" => {
                    wall - u64::try_from(
                        crate::restart_policy::RESTART_RECOVERY_WINDOW.as_millis(),
                    )? - 1_000
                }
                _ => unreachable!("wall clock fixture"),
            };
            let journal = crate::restart_journal::RestartBudgetJournal::new(
                s.fleet.first.clone(),
                ReleaseId::parse("signed-rollback-source")?,
                crate::restart_journal::DurableRestartWindow::empty(),
                crate::restart_journal::DurableRestartWindow {
                    attempts: 1,
                    window_started_unix_millis: Some(window_started_unix_millis),
                },
            )?;
            crate::restart_journal::write_restart_journal(root, &journal)?;
            crate::restart_journal::write_main_restart_budget(
                root,
                &crate::restart_budget::RestartBudgetState {
                    schema_version: 1,
                    window_started_unix_ms: wall,
                    attempts: 2,
                    pending: false,
                    next_eligible_unix_ms: wall,
                },
            )?;
            let budget_path = root.join(crate::restart_journal::RESTART_JOURNAL_FILE);
            let budget_bytes = std::fs::read(&budget_path)?;
            // Both real fake-process observations are terminal. Remove their exact
            // leases so this constructor reaches the idle-hydration branch itself.
            s.control.set_exit(&s.fleet.first);
            s.control.set_matrix_exit(&s.fleet.first);
            let main = crate::lease::read_lease(root)?.expect("main exact lease");
            crate::lease::remove_lease(root, &main)?;
            let matrix = crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?
                .expect("Matrix exact lease");
            crate::lease::remove_matrix_lease(record.layout.matrixd_process_lease(), &matrix)?;
            let spawns = (
                s.control.spawn_count(&s.fleet.first),
                s.control.matrix_spawn_count(&s.fleet.first),
            );
            drop(s.supervisor);
            let (mut recovered, report) = Supervisor::recover(
                s.fleet.registry.clone(),
                s.control.driver(),
                config(),
                s.now,
            )?;
            assert_eq!(
                report.faults.len(),
                usize::from(mode == "malformed"),
                "{mode}: {report:?}"
            );
            assert!(
                recovered.production_recovery_required(&s.fleet.first)?,
                "{mode}"
            );
            let snapshot = recovered
                .snapshot(&s.fleet.first)
                .expect("denied idle slot");
            assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
            assert_eq!(recovered.tick(s.now), TickReport::default(), "{mode}");
            assert_eq!(
                std::fs::read(&budget_path)?,
                budget_bytes,
                "{mode}/{window}"
            );
            assert_eq!(read_release_transaction(root)?, Some(tx), "{mode}");
            assert_eq!(
                (
                    s.control.spawn_count(&s.fleet.first),
                    s.control.matrix_spawn_count(&s.fleet.first)
                ),
                spawns,
                "{mode}"
            );
            assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 0), "{mode}");
            assert_eq!(s.control.matrix_counts(&s.fleet.first), (0, 0, 0), "{mode}");
            assert!(
                !root
                    .join(crate::restart_lineage::RESTART_LINEAGE_FILE)
                    .exists(),
                "{mode}"
            );
            if mode == "malformed" {
                assert_eq!(std::fs::read(&intent_path)?, b"{invalid signed witness}");
            }
        }
    }
    Ok(())
}

#[test]
fn signed_denial_preserves_independent_matrix_binding_diagnostics_without_hydration() -> Result<()>
{
    for mode in ["binding_revision", "binding_digest", "other_bundle"] {
        let mut s = Scenario::new(Plant::Paired)?;
        let failed =
            with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
                s.apply()
            });
        assert!(matches!(
            failed,
            Err(SupervisorError::SignedMutationIndeterminate(_))
        ));
        let record = s.supervisor.record(&s.fleet.first)?;
        let root = record.layout.run_root();
        let tx = s.legacy_unsigned_prepared()?;
        crate::release_transaction::write_release_transaction(root, &tx)?;
        let mut matrix = crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?
            .expect("actual owned companion lease");
        let original_matrix = matrix.clone();
        let expected_fault = match mode {
            "binding_revision" => {
                matrix.binding_revision += 1;
                "binding revision is stale"
            }
            "binding_digest" => {
                matrix.binding_digest = Sha256Digest::for_bytes(b"unmatched companion binding");
                "binding digest is stale"
            }
            "other_bundle" => {
                matrix.release_id = ReleaseId::parse("retry-source")?;
                "not the active companion bundle"
            }
            _ => unreachable!("typed fixture mode"),
        };
        // Fixture administrator replaces the exact old lease with a bounded,
        // typed semantic mismatch; process lifetime/identity remains the same.
        crate::lease::remove_matrix_lease(record.layout.matrixd_process_lease(), &original_matrix)?;
        crate::lease::write_matrix_lease(record.layout.matrixd_process_lease(), &matrix)?;
        let main_path = root.join(crate::lease::PROCESS_LEASE_FILE);
        let main_bytes = std::fs::read(&main_path)?;
        let matrix_bytes = std::fs::read(record.layout.matrixd_process_lease())?;
        let budget = crate::restart_journal::read_restart_journal(root)?;
        let spawns = (
            s.control.spawn_count(&s.fleet.first),
            s.control.matrix_spawn_count(&s.fleet.first),
        );
        drop(s.supervisor);
        let (recovered, report) = Supervisor::recover(
            s.fleet.registry.clone(),
            s.control.driver(),
            config(),
            s.now,
        )?;
        assert_eq!(report.faults.len(), 1, "{mode}: {report:?}");
        assert!(
            report.faults[0].message.contains(expected_fault),
            "{mode}: {report:?}"
        );
        let snapshot = recovered
            .snapshot(&s.fleet.first)
            .expect("retained exact pair");
        assert!(snapshot.active && snapshot.matrix.active && snapshot.runtime_fenced);
        assert!(!snapshot.healthy && !snapshot.matrix.healthy);
        assert_eq!(
            snapshot.active_release, None,
            "denial does not admit catalog metadata"
        );
        assert!(recovered.production_recovery_required(&s.fleet.first)?);
        assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 1), "{mode}");
        assert_eq!(s.control.matrix_counts(&s.fleet.first), (0, 0, 1), "{mode}");
        assert_eq!(std::fs::read(&main_path)?, main_bytes, "{mode}");
        assert_eq!(
            std::fs::read(record.layout.matrixd_process_lease())?,
            matrix_bytes,
            "{mode}"
        );
        assert_eq!(
            s.fleet.registry.load_agent(&s.fleet.first)?.lifecycle,
            record.lifecycle,
            "{mode}"
        );
        assert_eq!(read_release_transaction(root)?, Some(tx), "{mode}");
        assert_eq!(
            crate::restart_journal::read_restart_journal(root)?,
            budget,
            "{mode}"
        );
        assert_eq!(
            (
                s.control.spawn_count(&s.fleet.first),
                s.control.matrix_spawn_count(&s.fleet.first)
            ),
            spawns,
            "{mode}"
        );
    }
    Ok(())
}

#[test]
fn ownerless_signed_denial_reports_corrupt_persisted_catalog_without_budget_normalization()
-> Result<()> {
    for which in ["current", "previous"] {
        let mut s = Scenario::new(Plant::Main)?;
        let failed =
            with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
                s.apply()
            });
        assert!(matches!(
            failed,
            Err(SupervisorError::SignedMutationIndeterminate(_))
        ));
        let record = s.supervisor.record(&s.fleet.first)?;
        let root = record.layout.run_root();
        let tx = s.legacy_unsigned_prepared()?;
        crate::release_transaction::write_release_transaction(root, &tx)?;
        let journal = crate::restart_journal::RestartBudgetJournal::new(
            s.fleet.first.clone(),
            ReleaseId::parse("signed-rollback-source")?,
            crate::restart_journal::DurableRestartWindow::empty(),
            crate::restart_journal::DurableRestartWindow {
                attempts: 1,
                window_started_unix_millis: Some(
                    crate::restart_journal::unix_millis_now()? + 600_000,
                ),
            },
        )?;
        crate::restart_journal::write_restart_journal(root, &journal)?;
        let budget_path = root.join(crate::restart_journal::RESTART_JOURNAL_FILE);
        let budget_bytes = std::fs::read(&budget_path)?;
        s.control.set_exit(&s.fleet.first);
        let lease = crate::lease::read_lease(root)?.expect("exact observed terminal main");
        crate::lease::remove_lease(root, &lease)?;
        assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
        let release_id = match which {
            "current" => record.release_state.current.as_ref(),
            "previous" => record.release_state.previous.as_ref(),
            _ => unreachable!("persisted release fixture"),
        }
        .expect("persisted catalog selection");
        let allowance = record
            .layout
            .releases_root()
            .join(format!("allow-{release_id}.json"));
        // A corrupt existing admission record is a catalog error, rather than
        // the compatible revoked/not-allowed projection that returns None.
        std::fs::remove_file(&allowance)?;
        std::fs::write(&allowance, b"{invalid existing catalog allowance}")?;
        let spawns = s.control.spawn_count(&s.fleet.first);
        drop(s.supervisor);
        let (recovered, report) = Supervisor::recover(
            s.fleet.registry.clone(),
            s.control.driver(),
            config(),
            s.now,
        )?;
        assert_eq!(report.faults.len(), 1, "{which}: {report:?}");
        assert_eq!(report.faults[0].agent_id, s.fleet.first);
        assert!(recovered.production_recovery_required(&s.fleet.first)?);
        let snapshot = recovered
            .snapshot(&s.fleet.first)
            .expect("denied ownerless slot");
        assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
        assert_eq!(snapshot.active_release, None);
        assert_eq!(std::fs::read(&budget_path)?, budget_bytes, "{which}");
        assert_eq!(read_release_transaction(root)?, Some(tx), "{which}");
        assert_eq!(s.control.spawn_count(&s.fleet.first), spawns, "{which}");
        assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 0), "{which}");
        assert_eq!(
            std::fs::read(&allowance)?,
            b"{invalid existing catalog allowance}"
        );
    }
    Ok(())
}
