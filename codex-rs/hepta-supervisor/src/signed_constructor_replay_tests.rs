//! Genuine signed grants and real Fleet/journal files at the old partial
//! authority-publication cut. Process observations are an explicit double.

use super::*;
use crate::durability::with_qualification_fault_after;
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::ReleaseTransactionKind;
use anyhow::Result;
use pretty_assertions::assert_eq;

#[path = "signed_constructor_containment_tests.rs"]
mod containment;

#[derive(Clone, Copy)]
enum Plant {
    Main,
    Paired,
}

struct Scenario {
    fleet: TestFleet,
    control: FakeControl,
    supervisor: Supervisor<FakeDriver>,
    envelope: codex_hepta_memory::H7SignedArtifactEnvelope,
    verifier: crate::H7H89ProductionGrantVerifier,
    grant: crate::H7H89ProductionGrant,
    now: Instant,
}

impl Scenario {
    fn new(plant: Plant) -> Result<Self> {
        let (fleet, control, mut supervisor, now) = match plant {
            Plant::Main => {
                let fleet = TestFleet::new()?;
                let control = FakeControl::default();
                let now = Instant::now();
                let supervisor = start_source(&fleet, &control, now)?;
                (fleet, control, supervisor, now)
            }
            Plant::Paired => ready_paired_supervisor("retry-source")?,
        };
        let source = match plant {
            Plant::Main => admitted_release(&fleet, &fleet.first, "signed-rollback-source")?,
            Plant::Paired => {
                let program = fleet.write_release_source()?;
                let id = ReleaseId::parse("signed-rollback-source")?;
                fleet.registry.install_release_bundle(
                    id.clone(),
                    &program,
                    Vec::new(),
                    Some(&program),
                    Vec::new(),
                )?;
                fleet.registry.allow_release(&fleet.first, &id)?;
                AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?
            }
        };
        supervisor.upgrade(&fleet.first, source, now)?;
        if matches!(plant, Plant::Paired) {
            control.set_matrix_exit(&fleet.first);
            assert_eq!(supervisor.tick(now), TickReport::default());
        }
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        if matches!(plant, Plant::Paired) {
            control.set_matrix_healthy(&fleet.first);
            assert_eq!(supervisor.tick(now), TickReport::default());
            assert_eq!(supervisor.tick(now), TickReport::default());
        }
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(record.lifecycle.lifecycle, AgentLifecycle::Running);
        let (signer, envelope, verifier) = recovery_signing_fixture();
        let grant = signer.sign(
            &fleet.first,
            "signed-rollback-source",
            "retry-source",
            H7H89ProductionTransition::Rollback,
            &envelope,
            supervisor
                .snapshot(&fleet.first)
                .expect("owned source")
                .control_revision,
            record.lifecycle.generation,
            /*authority_epoch*/ 7,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )?;
        Ok(Self {
            fleet,
            control,
            supervisor,
            envelope,
            verifier,
            grant,
            now,
        })
    }

    fn apply(&mut self) -> Result<crate::ProductionMutationReceipt, SupervisorError> {
        self.supervisor.apply_production_grant(
            &self.fleet.first,
            &self.grant,
            &self.envelope,
            &self.verifier,
            /*expected_authority_epoch*/ 7,
            /*now_unix_seconds*/ 150,
            self.now,
        )
    }

    fn legacy_unsigned_prepared(&self) -> Result<DurableReleaseTransaction> {
        let record = self.supervisor.record(&self.fleet.first)?;
        Ok(DurableReleaseTransaction::new(
            self.fleet.first.to_string(),
            ReleaseTransactionKind::ExplicitRollback,
            "signed-rollback-source",
            "retry-source",
            record
                .release_state
                .previous
                .as_ref()
                .map(ToString::to_string),
            Some(self.fleet.registry.resolve_release_binding(
                &self.fleet.first,
                &ReleaseId::parse("signed-rollback-source")?,
            )?),
            Some(
                self.fleet.registry.resolve_release_binding(
                    &self.fleet.first,
                    &ReleaseId::parse("retry-source")?,
                )?,
            ),
            record.release_state.generation,
            record.lifecycle.generation,
        )?)
    }
}

#[test]
fn signed_prepared_release_publication_never_exposes_unsigned_authority() -> Result<()> {
    let mut s = Scenario::new(Plant::Main)?;
    // The first release write is now fully bound Prepared. The second is
    // Draining after actual delivery, rather than a detached authority bind.
    let failed = with_qualification_fault_after(
        "release_transaction.file_write",
        ErrorKind::Other,
        /*successful_occurrences*/ 1,
        || s.apply(),
    );
    assert!(
        matches!(failed, Err(SupervisorError::SignedMutationIndeterminate(ref agent)) if agent == &s.fleet.first)
    );
    let record = s.supervisor.record(&s.fleet.first)?;
    let tx = read_release_transaction(record.layout.run_root())?.expect("bound Prepared");
    assert_eq!(
        (tx.phase, tx.grant_sha256.as_ref(), tx.authority_epoch),
        (
            ReleaseTransactionPhase::Prepared,
            Some(s.grant.digest()),
            Some(7)
        )
    );
    assert_eq!(s.control.counts(&s.fleet.first), (1, 0, 0));
    assert!(s.supervisor.production_recovery_required(&s.fleet.first)?);
    drop(s.supervisor);
    let (recovered, report) = Supervisor::recover(
        s.fleet.registry.clone(),
        s.control.driver(),
        config(),
        s.now,
    )?;
    assert_eq!(report, TickReport::default());
    assert_eq!(s.control.counts(&s.fleet.first), (1, 0, 1));
    assert_eq!(
        read_release_transaction(record.layout.run_root())?
            .expect("bound quarantine")
            .phase,
        ReleaseTransactionPhase::RecoveryRequired
    );
    assert!(recovered.production_recovery_required(&s.fleet.first)?);
    Ok(())
}

#[test]
fn legacy_unsigned_prepared_with_signed_denial_never_replays_or_dispatches() -> Result<()> {
    for mode in [
        "owned",
        "main_missing",
        "matrix_missing",
        "both_missing",
        "rejected",
    ] {
        let mut s = Scenario::new(Plant::Paired)?;
        // A real verified grant leaves its trusted intent quarantined without
        // publishing a release transaction; install the exact old schema's
        // unsigned Prepared bytes to reproduce the historical bind crash cut.
        let failed =
            with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
                s.apply()
            });
        assert!(
            matches!(failed, Err(SupervisorError::SignedMutationIndeterminate(ref agent)) if agent == &s.fleet.first)
        );
        let record = s.supervisor.record(&s.fleet.first)?;
        let tx = s.legacy_unsigned_prepared()?;
        crate::release_transaction::write_release_transaction(record.layout.run_root(), &tx)?;
        let main_path = record
            .layout
            .run_root()
            .join(crate::lease::PROCESS_LEASE_FILE);
        let main_lease = std::fs::read(&main_path)?;
        let matrix_lease = std::fs::read(record.layout.matrixd_process_lease())?;
        let budget = crate::restart_journal::read_restart_journal(record.layout.run_root())?;
        let spawns = (
            s.control.spawn_count(&s.fleet.first),
            s.control.matrix_spawn_count(&s.fleet.first),
        );
        let main_missing = matches!(mode, "main_missing" | "both_missing");
        let matrix_missing = matches!(mode, "matrix_missing" | "both_missing");
        if main_missing {
            s.control.set_exit(&s.fleet.first);
        }
        if matrix_missing {
            s.control.set_matrix_exit(&s.fleet.first);
        }
        if mode == "rejected" {
            s.control.reject_adoption(s.fleet.first.clone());
        }
        drop(s.supervisor);
        let (recovered, report) = Supervisor::recover(
            s.fleet.registry.clone(),
            s.control.driver(),
            config(),
            s.now,
        )?;
        assert_eq!(report, TickReport::default(), "{mode}");
        assert!(
            recovered.production_recovery_required(&s.fleet.first)?,
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
        assert_eq!(
            s.control.counts(&s.fleet.first),
            (0, 0, usize::from(!main_missing && mode != "rejected")),
            "{mode}"
        );
        assert_eq!(
            s.control.matrix_counts(&s.fleet.first),
            (0, 0, usize::from(!matrix_missing)),
            "{mode}"
        );
        let snapshot = recovered
            .snapshot(&s.fleet.first)
            .expect("quarantined owner projection");
        assert_eq!(
            (snapshot.active, snapshot.matrix.active),
            (!main_missing && mode != "rejected", !matrix_missing),
            "{mode}"
        );
        if snapshot.active {
            assert!(snapshot.runtime_fenced, "{mode}");
        }
        if main_missing {
            assert!(!main_path.exists(), "{mode}");
        } else {
            assert_eq!(std::fs::read(&main_path)?, main_lease, "{mode}");
        }
        if matrix_missing {
            assert!(!record.layout.matrixd_process_lease().exists(), "{mode}");
        } else {
            assert_eq!(
                std::fs::read(record.layout.matrixd_process_lease())?,
                matrix_lease,
                "{mode}"
            );
        }
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(tx),
            "{mode}"
        );
        assert_eq!(
            crate::restart_journal::read_restart_journal(record.layout.run_root())?,
            budget,
            "{mode}"
        );
        assert!(
            !record
                .layout
                .run_root()
                .join(crate::restart_lineage::RESTART_LINEAGE_FILE)
                .exists(),
            "{mode}"
        );
    }
    Ok(())
}

#[test]
fn quarantined_main_and_matrix_exit_admit_no_new_restart_claims() -> Result<()> {
    let mut s = Scenario::new(Plant::Paired)?;
    let failed = with_qualification_fault("signed_intent.directory_sync", ErrorKind::Other, || {
        s.apply()
    });
    assert!(
        matches!(failed, Err(SupervisorError::SignedMutationIndeterminate(ref agent)) if agent == &s.fleet.first)
    );
    let record = s.supervisor.record(&s.fleet.first)?;
    let budget = crate::restart_journal::read_restart_journal(record.layout.run_root())?;
    let spawns = (
        s.control.spawn_count(&s.fleet.first),
        s.control.matrix_spawn_count(&s.fleet.first),
    );
    // Main and Matrix are still the exact healthy source pair: neither the
    // failed Prepared acknowledgment nor quarantine is proof of their exit.
    s.control.set_matrix_exit(&s.fleet.first);
    assert_eq!(s.supervisor.tick(s.now), TickReport::default());
    assert!(!record.layout.matrixd_process_lease().exists());
    assert_eq!(
        crate::restart_journal::read_restart_journal(record.layout.run_root())?,
        budget
    );
    s.control.set_exit(&s.fleet.first);
    assert_eq!(s.supervisor.tick(s.now), TickReport::default());
    assert!(
        !record
            .layout
            .run_root()
            .join(crate::lease::PROCESS_LEASE_FILE)
            .exists()
    );
    assert_eq!(
        crate::restart_journal::read_restart_journal(record.layout.run_root())?,
        budget
    );
    assert!(
        !record
            .layout
            .run_root()
            .join(crate::restart_lineage::RESTART_LINEAGE_FILE)
            .exists()
    );
    let snapshot = s
        .supervisor
        .snapshot(&s.fleet.first)
        .expect("retained quarantine");
    assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
    assert!(!snapshot.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::RestartQueued | SupervisorEventKind::AutomaticRestartQueued { .. }
    )));
    assert!(s.supervisor.production_recovery_required(&s.fleet.first)?);
    assert_eq!(
        (
            s.control.spawn_count(&s.fleet.first),
            s.control.matrix_spawn_count(&s.fleet.first)
        ),
        spawns
    );
    Ok(())
}

#[test]
fn exact_terminal_signed_witness_and_unsigned_history_recover_without_false_denial() -> Result<()> {
    for status in [
        SignedIntentStatus::Queued,
        SignedIntentStatus::RecoveryRequired,
    ] {
        let mut s = Scenario::new(Plant::Main)?;
        s.apply()?;
        finish_release_drain(&mut s.supervisor, &s.control, &s.fleet.first, s.now);
        s.control.set_healthy(&s.fleet.first);
        let failed = with_qualification_fault("signed_intent.file_write", ErrorKind::Other, || {
            s.supervisor.tick(s.now)
        });
        assert_eq!(failed.faults.len(), 1);
        let record = s.supervisor.record(&s.fleet.first)?;
        let intent = read_intent(record.layout.run_root())?
            .expect("signed intent")
            .with_status(status)?;
        write_intent(record.layout.run_root(), &intent)?;
        let lease = std::fs::read(
            record
                .layout
                .run_root()
                .join(crate::lease::PROCESS_LEASE_FILE),
        )?;
        let spawns = s.control.spawn_count(&s.fleet.first);
        drop(s.supervisor);
        let (mut recovered, report) = Supervisor::recover(
            s.fleet.registry.clone(),
            s.control.driver(),
            config(),
            s.now,
        )?;
        assert_eq!(report, TickReport::default(), "{status:?}");
        assert!(
            !recovered.production_recovery_required(&s.fleet.first)?,
            "{status:?}"
        );
        assert!(
            recovered
                .snapshot(&s.fleet.first)
                .expect("target owner")
                .active
        );
        assert!(
            !recovered
                .snapshot(&s.fleet.first)
                .expect("target owner")
                .runtime_fenced
        );
        assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 0), "{status:?}");
        assert_eq!(
            std::fs::read(
                record
                    .layout
                    .run_root()
                    .join(crate::lease::PROCESS_LEASE_FILE)
            )?,
            lease,
            "{status:?}"
        );
        assert_eq!(
            read_intent(record.layout.run_root())?
                .expect("terminal signed intent")
                .status,
            SignedIntentStatus::RolledBack
        );
        assert_eq!(s.control.spawn_count(&s.fleet.first), spawns);

        // A real ordinary transition published Prepared before its directory
        // sync failed. Terminal signed history must not suppress its replay.
        let target = admitted_release(&s.fleet, &s.fleet.first, "unsigned-after-signed-terminal")?;
        let failed = with_qualification_fault(
            "release_transaction.directory_sync",
            ErrorKind::Other,
            || recovered.upgrade(&s.fleet.first, target, s.now),
        );
        assert!(failed.is_err());
        drop(recovered);
        let (recovered, report) = Supervisor::recover(
            s.fleet.registry.clone(),
            s.control.driver(),
            config(),
            s.now,
        )?;
        assert_eq!(report, TickReport::default());
        assert!(!recovered.production_recovery_required(&s.fleet.first)?);
        assert_eq!(s.control.counts(&s.fleet.first), (1, 0, 0));
        assert_eq!(
            recovered.record(&s.fleet.first)?.lifecycle.lifecycle,
            AgentLifecycle::Draining
        );
        assert_eq!(s.control.spawn_count(&s.fleet.first), spawns);
    }
    Ok(())
}
