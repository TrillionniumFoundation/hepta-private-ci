use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistryError;

use crate::AgentRelease;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::ReleaseTransactionKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::runtime::AgentSlot;
use crate::runtime::ReleaseChange;
use crate::runtime::ReleaseChangePhase;

impl<D: ProcessDriver> Supervisor<D> {
    /// Re-admit a release at the final-use boundary. Product/catalog releases
    /// must still exist, remain allowed, and not be revoked. Direct in-process
    /// qualification fixtures historically use unregistered AgentRelease
    /// values; only UnknownRelease falls back to that local value.
    pub(crate) fn refresh_release_for_transition(
        &self,
        agent_id: &AgentId,
        release: &AgentRelease,
    ) -> Result<AgentRelease, SupervisorError> {
        match self
            .registry
            .resolve_release(agent_id, release.release_id())
        {
            Ok(current) => AgentRelease::try_from(current),
            Err(FleetRegistryError::UnknownRelease(_)) => Ok(release.clone()),
            Err(error) => Err(error.into()),
        }
    }

    fn release_binding_for_transition(
        &self,
        agent_id: &AgentId,
        release: &AgentRelease,
    ) -> Result<Option<codex_hepta_fleet::ReleaseBinding>, SupervisorError> {
        match self
            .registry
            .resolve_release_binding(agent_id, release.release_id())
        {
            Ok(binding) => Ok(Some(binding)),
            Err(FleetRegistryError::UnknownRelease(_)) => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    fn verify_release_binding_against_transaction(
        &self,
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
        release: &AgentRelease,
        target: bool,
    ) -> Result<(), SupervisorError> {
        let Some(transaction) = slot.release_transaction.as_ref() else {
            return Ok(());
        };
        let expected = if target {
            transaction.target_binding.as_ref()
        } else {
            transaction.source_binding.as_ref()
        };
        let Some(expected) = expected else {
            // Qualification-only unregistered fixtures intentionally carry no
            // catalog binding and never acquire production authority.
            return Ok(());
        };
        let actual = self
            .registry
            .resolve_release_binding(agent_id, release.release_id())?;
        if expected.release_id != actual.release_id.to_string()
            || expected.manifest_sha256.as_str() != actual.manifest_sha256.as_str()
            || expected.agentd_program_sha256.as_str() != actual.agentd_program_sha256.as_str()
            || expected.matrixd_program_sha256.as_deref()
                != actual.matrixd_program_sha256.as_deref()
            || expected.admission_frontier_sha256.as_str()
                != actual.admission_frontier_sha256.as_str()
        {
            return Err(SupervisorError::ProductionAuthority(
                "release admission binding changed after durable transaction preparation"
                    .to_string(),
            ));
        }
        Ok(())
    }

    fn prepare_release_transaction(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        source: &AgentRelease,
        target: &AgentRelease,
        explicit_rollback: bool,
        lifecycle_generation: u64,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let kind = if explicit_rollback {
            ReleaseTransactionKind::ExplicitRollback
        } else {
            ReleaseTransactionKind::Upgrade
        };
        let transaction = DurableReleaseTransaction::new(
            agent_id.to_string(),
            kind,
            source.identity(),
            target.identity(),
            slot.previous_release
                .as_ref()
                .map(|release| release.identity().to_string()),
            self.release_binding_for_transition(agent_id, source)?,
            self.release_binding_for_transition(agent_id, target)?,
            record.release_state.generation,
            lifecycle_generation,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        write_release_transaction(record.layout.run_root(), &transaction)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.release_transaction = Some(transaction);
        Ok(())
    }

    pub(crate) fn bind_release_transaction_authority(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        grant_sha256: codex_hepta_contracts::Sha256Digest,
        authority_epoch: u64,
    ) -> Result<(), SupervisorError> {
        let transaction = slot.release_transaction.clone().ok_or_else(|| {
            SupervisorError::Invalid("release transaction is not prepared".to_string())
        })?;
        let transaction = transaction
            .with_authority(grant_sha256, authority_epoch)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let record = self.record(agent_id)?;
        write_release_transaction(record.layout.run_root(), &transaction)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.release_transaction = Some(transaction);
        Ok(())
    }

    pub(crate) fn advance_release_transaction(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        phase: ReleaseTransactionPhase,
    ) -> Result<(), SupervisorError> {
        let Some(transaction) = slot.release_transaction.clone() else {
            return Ok(());
        };
        let transaction = transaction
            .with_phase(phase)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let record = self.record(agent_id)?;
        write_release_transaction(record.layout.run_root(), &transaction)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.release_transaction = Some(transaction);
        Ok(())
    }

    fn reconcile_unsigned_release_outcome(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        allow_source_abort: bool,
    ) -> Result<bool, SupervisorError> {
        let Some(transaction) = slot.release_transaction.clone() else {
            return Ok(false);
        };
        if transaction.grant_sha256.is_some() {
            return Ok(false);
        }
        let record = self.record(agent_id)?;
        let current = record
            .release_state
            .current
            .as_ref()
            .map(codex_hepta_fleet::ReleaseId::as_str);
        let previous = record
            .release_state
            .previous
            .as_ref()
            .map(codex_hepta_fleet::ReleaseId::as_str);
        let next_generation = transaction
            .expected_release_state_generation
            .checked_add(1)
            .ok_or_else(|| {
                SupervisorError::Invalid("release-state generation overflow".to_string())
            })?;

        let terminal = if current == Some(transaction.target_release.as_str())
            && previous == Some(transaction.source_release.as_str())
            && record.release_state.generation == next_generation
        {
            Some(match transaction.kind {
                ReleaseTransactionKind::Upgrade => ReleaseTransactionPhase::Committed,
                ReleaseTransactionKind::ExplicitRollback => ReleaseTransactionPhase::RolledBack,
            })
        } else if allow_source_abort
            && current == Some(transaction.source_release.as_str())
            && record.release_state.generation == transaction.expected_release_state_generation
            && slot.runtime.as_ref().is_none_or(|runtime| {
                runtime.fenced || runtime.release_id.as_str() == transaction.source_release
            })
        {
            Some(ReleaseTransactionPhase::Aborted)
        } else {
            None
        };

        let Some(terminal) = terminal else {
            return Ok(false);
        };
        let terminal_transaction = transaction
            .with_phase(terminal)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        write_release_transaction(record.layout.run_root(), &terminal_transaction)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.release_transaction = Some(terminal_transaction);
        slot.release_change = None;
        Ok(true)
    }

    fn enter_unsigned_release_recovery(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<bool, SupervisorError> {
        self.advance_release_transaction(
            agent_id,
            slot,
            ReleaseTransactionPhase::RecoveryRequired,
        )?;
        self.reconcile_unsigned_release_outcome(agent_id, slot, /*allow_source_abort*/ true)
    }

    pub(crate) fn upgrade_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        target: AgentRelease,
        now: Instant,
        explicit_rollback: bool,
        authority: Option<(codex_hepta_contracts::Sha256Digest, u64)>,
    ) -> Result<(), SupervisorError> {
        if slot.release_change.is_some()
            || slot.restart_pending
            || slot
                .release_transaction
                .as_ref()
                .is_some_and(|transaction| !transaction.phase.terminal())
        {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        let target = self.refresh_release_for_transition(agent_id, &target)?;
        let current = slot.active_release.clone().ok_or_else(|| {
            SupervisorError::Invalid(format!(
                "agent {agent_id} has no explicit active release identity"
            ))
        })?;
        if current.identity() == target.identity()
            || (current.command() == target.command()
                && current.matrixd_command() == target.matrixd_command())
        {
            return Err(SupervisorError::TargetReleaseUnchanged(agent_id.clone()));
        }
        let lifecycle = self.record(agent_id)?.lifecycle;
        if lifecycle.lifecycle != AgentLifecycle::Running {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot change release from {:?}",
                lifecycle.lifecycle
            )));
        }
        let prior_previous = slot.previous_release.clone();
        self.prepare_release_transaction(
            agent_id,
            slot,
            &current,
            &target,
            explicit_rollback,
            lifecycle.generation,
        )?;
        if let Some((grant_sha256, authority_epoch)) = authority {
            self.bind_release_transaction_authority(agent_id, slot, grant_sha256, authority_epoch)?;
        }
        slot.release_change = Some(ReleaseChange {
            origin: current.clone(),
            target: target.clone(),
            prior_previous,
            phase: ReleaseChangePhase::WaitingForTargetExit,
            explicit_rollback,
        });
        if let Err(error) = self.drain_slot_preserving_restart(agent_id, slot, now) {
            let _ = self.enter_unsigned_release_recovery(agent_id, slot);
            slot.release_change = None;
            return Err(error);
        }
        self.advance_release_transaction(agent_id, slot, ReleaseTransactionPhase::Draining)?;
        let generation = slot
            .runtime
            .as_ref()
            .map(|runtime| runtime.generation)
            .unwrap_or(lifecycle.generation);
        let kind = if explicit_rollback {
            SupervisorEventKind::ExplicitRollbackQueued {
                previous: current.identity().to_string(),
                target: target.identity().to_string(),
            }
        } else {
            SupervisorEventKind::UpgradeQueued {
                previous: current.identity().to_string(),
                target: target.identity().to_string(),
            }
        };
        slot.event(generation, kind);
        Ok(())
    }

    pub(crate) fn release_became_healthy(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
    ) -> Result<(), SupervisorError> {
        let mut terminal_transaction_phase = None;
        if let Some(change) = slot.release_change.take() {
            match change.phase {
                ReleaseChangePhase::TargetStarting => {
                    slot.previous_release = Some(change.origin.clone());
                    terminal_transaction_phase = Some(if change.explicit_rollback {
                        ReleaseTransactionPhase::RolledBack
                    } else {
                        ReleaseTransactionPhase::Committed
                    });
                    let kind = if change.explicit_rollback {
                        SupervisorEventKind::ExplicitRollbackCommitted {
                            previous: change.origin.identity().to_string(),
                            target: change.target.identity().to_string(),
                        }
                    } else {
                        SupervisorEventKind::UpgradeCommitted {
                            previous: change.origin.identity().to_string(),
                            target: change.target.identity().to_string(),
                        }
                    };
                    slot.event(generation, kind);
                }
                ReleaseChangePhase::AutomaticRollbackStarting => {
                    slot.previous_release = change.prior_previous;
                    terminal_transaction_phase = Some(ReleaseTransactionPhase::RolledBack);
                    slot.event(
                        generation,
                        SupervisorEventKind::AutomaticRollbackCommitted {
                            failed: change.target.identity().to_string(),
                            restored: change.origin.identity().to_string(),
                        },
                    );
                }
                ReleaseChangePhase::WaitingForTargetExit => {
                    slot.release_change = Some(change);
                }
            }
        }
        self.persist_release_state(agent_id, slot)?;
        if let Some(phase) = terminal_transaction_phase {
            self.advance_release_transaction(agent_id, slot, phase)?;
        }
        self.commit_signed_intent_if_target(agent_id, slot)
    }

    pub(crate) fn persist_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let current = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone());
        let previous = slot
            .previous_release
            .as_ref()
            .map(|release| release.release_id().clone());
        if current
            .as_ref()
            .is_some_and(|release| release.as_str() == "unversioned")
        {
            return Ok(());
        }
        let actual = self.record(agent_id)?.release_state;
        slot.release_state_generation = actual.generation;
        if actual.current == current && actual.previous == previous {
            return Ok(());
        }
        let next = self.registry.compare_and_set_release_state(
            agent_id,
            actual.generation,
            current,
            previous,
        )?;
        slot.release_state_generation = next.generation;
        Ok(())
    }

    pub(crate) fn continue_release_change_after_exit(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let Some(mut change) = slot.release_change.take() else {
            return Ok(false);
        };
        match change.phase {
            ReleaseChangePhase::WaitingForTargetExit => {
                let target = match self.refresh_release_for_transition(agent_id, &change.target) {
                    Ok(target) => target,
                    Err(_) => {
                        slot.release_change = Some(change);
                        return self.start_automatic_rollback(agent_id, slot, now);
                    }
                };
                if self
                    .verify_release_binding_against_transaction(
                        agent_id, slot, &target, /*target*/ true,
                    )
                    .is_err()
                {
                    slot.release_change = Some(change);
                    return self.start_automatic_rollback(agent_id, slot, now);
                }
                change.target = target.clone();
                self.advance_release_transaction(
                    agent_id,
                    slot,
                    ReleaseTransactionPhase::TargetStarting,
                )?;
                change.phase = ReleaseChangePhase::TargetStarting;
                slot.release_change = Some(change);
                slot.active_release = None;
                match self.start_release_slot(agent_id, slot, target, now) {
                    Ok(()) => Ok(true),
                    Err(_) => self.start_automatic_rollback(agent_id, slot, now),
                }
            }
            ReleaseChangePhase::TargetStarting => {
                slot.release_change = Some(change);
                self.start_automatic_rollback(agent_id, slot, now)
            }
            ReleaseChangePhase::AutomaticRollbackStarting => {
                let generation = self.record(agent_id)?.lifecycle.generation;
                slot.active_release = None;
                slot.event(
                    generation,
                    SupervisorEventKind::AutomaticRollbackFailed {
                        failed: change.target.identity().to_string(),
                        rollback: change.origin.identity().to_string(),
                    },
                );
                Ok(true)
            }
        }
    }

    pub(crate) fn recover_release_transaction(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let Some(mut transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            return Ok(());
        };
        if transaction.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "release transaction agent binding mismatch".to_string(),
            ));
        }
        slot.release_transaction = Some(transaction.clone());
        if transaction.phase.terminal() {
            return Ok(());
        }

        // Externally-authorized transitions bind the daemon authority epoch.
        // A restart creates a new epoch, so they never continue automatically;
        // the signed-intent recovery ceremony resolves them explicitly.
        if transaction.grant_sha256.is_some() {
            if transaction.phase != ReleaseTransactionPhase::RecoveryRequired {
                transaction = transaction
                    .with_phase(ReleaseTransactionPhase::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                write_release_transaction(record.layout.run_root(), &transaction)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.release_transaction = Some(transaction);
            }
            return Ok(());
        }

        // A release-state CAS can prove an unsigned transition terminal even
        // when the daemon crashed before publishing the matching transaction
        // phase. Target publication advances exactly one release-state
        // generation; an unchanged source generation only closes an explicitly
        // recovery-required transition as Aborted.
        if self.reconcile_unsigned_release_outcome(
            agent_id,
            slot,
            transaction.phase == ReleaseTransactionPhase::RecoveryRequired,
        )? {
            return Ok(());
        }
        if transaction.phase == ReleaseTransactionPhase::RecoveryRequired {
            return Ok(());
        }

        let source_id = codex_hepta_fleet::ReleaseId::parse(transaction.source_release.clone())?;
        let target_id = codex_hepta_fleet::ReleaseId::parse(transaction.target_release.clone())?;
        let source = match self.registry.resolve_release(agent_id, &source_id) {
            Ok(release) => AgentRelease::try_from(release)?,
            Err(error) => {
                if self.enter_unsigned_release_recovery(agent_id, slot)? {
                    return Ok(());
                }
                return Err(error.into());
            }
        };
        if let Err(error) = self.verify_release_binding_against_transaction(
            agent_id, slot, &source, /*target*/ false,
        ) {
            if self.enter_unsigned_release_recovery(agent_id, slot)? {
                return Ok(());
            }
            return Err(error);
        }
        let target = match self.registry.resolve_release(agent_id, &target_id) {
            Ok(release) => AgentRelease::try_from(release)?,
            Err(error) => {
                if self.enter_unsigned_release_recovery(agent_id, slot)? {
                    return Ok(());
                }
                return Err(error.into());
            }
        };
        if let Err(error) = self.verify_release_binding_against_transaction(
            agent_id, slot, &target, /*target*/ true,
        ) {
            if self.enter_unsigned_release_recovery(agent_id, slot)? {
                return Ok(());
            }
            return Err(error);
        }
        let prior_previous = transaction
            .rollback_predecessor
            .as_ref()
            .map(|value| codex_hepta_fleet::ReleaseId::parse(value.clone()))
            .transpose()?
            .map(|release_id| self.registry.resolve_release(agent_id, &release_id))
            .transpose()?
            .map(AgentRelease::try_from)
            .transpose()?;
        let explicit_rollback = transaction.kind == ReleaseTransactionKind::ExplicitRollback;

        match transaction.phase {
            ReleaseTransactionPhase::Prepared | ReleaseTransactionPhase::Draining => {
                slot.release_change = Some(ReleaseChange {
                    origin: source,
                    target,
                    prior_previous,
                    phase: ReleaseChangePhase::WaitingForTargetExit,
                    explicit_rollback,
                });
                match record.lifecycle.lifecycle {
                    AgentLifecycle::Running => {
                        self.drain_slot_preserving_restart(agent_id, slot, now)?;
                        self.advance_release_transaction(
                            agent_id,
                            slot,
                            ReleaseTransactionPhase::Draining,
                        )?;
                    }
                    AgentLifecycle::Draining => {}
                    AgentLifecycle::Stopped | AgentLifecycle::Failed if slot.runtime.is_none() => {
                        let _ = self.continue_release_change_after_exit(agent_id, slot, now)?;
                    }
                    _ => {}
                }
            }
            ReleaseTransactionPhase::TargetStarting => {
                slot.release_change = Some(ReleaseChange {
                    origin: source,
                    target,
                    prior_previous,
                    phase: ReleaseChangePhase::TargetStarting,
                    explicit_rollback,
                });
                if slot.runtime.is_none() {
                    let _ = self.start_automatic_rollback(agent_id, slot, now)?;
                }
            }
            ReleaseTransactionPhase::AutomaticRollbackStarting => {
                slot.release_change = Some(ReleaseChange {
                    origin: source.clone(),
                    target,
                    prior_previous,
                    phase: ReleaseChangePhase::AutomaticRollbackStarting,
                    explicit_rollback,
                });
                if slot.runtime.is_none()
                    && matches!(
                        record.lifecycle.lifecycle,
                        AgentLifecycle::Stopped | AgentLifecycle::Failed
                    )
                {
                    slot.active_release = None;
                    self.start_release_slot(agent_id, slot, source, now)?;
                }
            }
            ReleaseTransactionPhase::Committed
            | ReleaseTransactionPhase::RolledBack
            | ReleaseTransactionPhase::Aborted
            | ReleaseTransactionPhase::RecoveryRequired => {}
        }
        Ok(())
    }

    fn start_automatic_rollback(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let Some(mut change) = slot.release_change.take() else {
            return Ok(false);
        };
        let generation = self.record(agent_id)?.lifecycle.generation;
        slot.event(
            generation,
            SupervisorEventKind::AutomaticRollbackQueued {
                failed: change.target.identity().to_string(),
                target: change.origin.identity().to_string(),
            },
        );
        let rollback = match self.refresh_release_for_transition(agent_id, &change.origin) {
            Ok(rollback) => rollback,
            Err(error) => {
                slot.release_change = Some(change);
                let _ = self.enter_unsigned_release_recovery(agent_id, slot);
                return Err(error);
            }
        };
        if let Err(error) = self.verify_release_binding_against_transaction(
            agent_id, slot, &rollback, /*target*/ false,
        ) {
            slot.release_change = Some(change);
            let _ = self.enter_unsigned_release_recovery(agent_id, slot);
            return Err(error);
        }
        change.origin = rollback.clone();
        self.advance_release_transaction(
            agent_id,
            slot,
            ReleaseTransactionPhase::AutomaticRollbackStarting,
        )?;
        change.phase = ReleaseChangePhase::AutomaticRollbackStarting;
        slot.release_change = Some(change);
        slot.active_release = None;
        if let Err(error) = self.start_release_slot(agent_id, slot, rollback, now) {
            let failed_generation = self.record(agent_id)?.lifecycle.generation;
            if let Some(change) = slot.release_change.take() {
                slot.event(
                    failed_generation,
                    SupervisorEventKind::AutomaticRollbackFailed {
                        failed: change.target.identity().to_string(),
                        rollback: change.origin.identity().to_string(),
                    },
                );
            }
            let _ = self.advance_release_transaction(
                agent_id,
                slot,
                ReleaseTransactionPhase::RecoveryRequired,
            );
            return Err(error);
        }
        Ok(true)
    }
}
