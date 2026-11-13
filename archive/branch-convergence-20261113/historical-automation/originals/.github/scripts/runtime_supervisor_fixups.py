#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-supervisor/src/robrix_protocol.rs",
    '''            SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
''',
    '''            SupervisordPayload::Diagnostics(_)
            | SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    '''use crate::ProductionMutationState;
use crate::ProductionRecoveryDecision;
''',
    '''use crate::ProductionMutationState;
use crate::ProductionMutationStatus;
use crate::ProductionRecoveryDecision;
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    '''    publish::publish_with_context("signed_intent", &temp, &final_path)?;
''',
    '''    crate::durable_publish::publish_with_context("signed_intent", &temp, &final_path)?;
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/recovery_diagnostics.rs",
    '''    if current.is_some_and(|release| {
        release != transaction.source_release && release != transaction.target_release
    }) || transaction.phase != ReleaseTransactionPhase::RecoveryRequired
''',
    '''    if current.is_some_and(|release| {
        release != transaction.source_release.as_str()
            && release != transaction.target_release.as_str()
    }) || transaction.phase != ReleaseTransactionPhase::RecoveryRequired
''',
)

# Hold the authority-distribution read guard across the exact synchronous
# final-use operation. Rotation/revocation therefore linearizes before or after
# admission instead of racing between verifier lookup and durable mutation.
replace_once(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    '''    pub fn resolve_grant(
        &self,
        grant: &H7H89ProductionGrant,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &grant.signer_id,
            grant.signer_epoch,
            Some(&grant.grant_sha256),
        )?;
        Ok(state.verifier.clone())
    }

    pub fn resolve_recovery(
        &self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &decision.signer_id,
            decision.signer_epoch,
            Some(&decision.grant_sha256),
        )?;
        Ok(state.verifier.clone())
    }
''',
    '''    pub fn with_grant_verifier<R>(
        &self,
        grant: &H7H89ProductionGrant,
        operation: impl FnOnce(&H7H89ProductionGrantVerifier) -> R,
    ) -> Result<R, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &grant.signer_id,
            grant.signer_epoch,
            Some(&grant.grant_sha256),
        )?;
        Ok(operation(&state.verifier))
    }

    pub fn resolve_grant(
        &self,
        grant: &H7H89ProductionGrant,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        self.with_grant_verifier(grant, |verifier| verifier.clone())
    }

    pub fn with_recovery_verifier<R>(
        &self,
        decision: &ProductionRecoveryDecision,
        operation: impl FnOnce(&H7H89ProductionGrantVerifier) -> R,
    ) -> Result<R, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &decision.signer_id,
            decision.signer_epoch,
            Some(&decision.grant_sha256),
        )?;
        Ok(operation(&state.verifier))
    }

    pub fn resolve_recovery(
        &self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        self.with_recovery_verifier(decision, |verifier| verifier.clone())
    }
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    '''mod tests {
    use codex_hepta_contracts::Sha256Digest;
''',
    '''mod tests {
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    use codex_hepta_contracts::Sha256Digest;
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    '''        assert!(matches!(
            reader.resolve_grant(&wrong),
            Err(ProductionAuthorityDistributionError::UnknownSigner)
        ));
    }
}
''',
    '''        assert!(matches!(
            reader.resolve_grant(&wrong),
            Err(ProductionAuthorityDistributionError::UnknownSigner)
        ));
    }

    #[test]
    fn rotation_waits_until_final_use_releases_the_reader_guard() {
        let (publisher, reader) =
            production_authority_distribution(verifier("release-policy", 1, 1))
                .expect("distribution");
        let current = grant(
            "release-policy",
            1,
            Sha256Digest::for_bytes(b"linearized-grant"),
        );
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let reader_thread = thread::spawn(move || {
            reader
                .with_grant_verifier(&current, |_| {
                    entered_tx.send(()).expect("announce final use");
                    release_rx.recv().expect("release final use");
                })
                .expect("current verifier");
        });
        entered_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("reader entered final use");

        let (attempt_tx, attempt_rx) = mpsc::channel();
        let (rotated_tx, rotated_rx) = mpsc::channel();
        let publisher_thread = thread::spawn(move || {
            attempt_tx.send(()).expect("announce rotate attempt");
            let result = publisher.rotate(1, verifier("release-policy", 2, 2));
            rotated_tx.send(result).expect("publish rotate result");
        });
        attempt_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("rotation attempted");
        assert!(
            rotated_rx
                .recv_timeout(Duration::from_millis(100))
                .is_err(),
            "rotation crossed an active final-use read guard"
        );

        release_tx.send(()).expect("release reader");
        reader_thread.join().expect("reader thread");
        let rotated = rotated_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("rotation completed")
            .expect("rotation accepted");
        assert_eq!(rotated.generation, 2);
        publisher_thread.join().expect("publisher thread");
    }
}
''',
)

# The daemon has already acquired the single-writer supervisor lock when it
# enters these closures. No await occurs while the authority read guard is held.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let verifier = match authority.resolve_recovery(&decision) {
        Ok(verifier) => verifier,
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
''',
    '''''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    if let Err(error) = supervisor.resolve_production_recovery(
        &agent_id,
        &decision,
        &verifier,
        authority_epoch,
        unix_seconds_now(),
    ) {
        let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
        return safe_rejection(
            error,
            post.or(Some(actual)),
            /*mutation_started*/ false,
        );
    }
''',
    '''    let recovery = match authority.with_recovery_verifier(&decision, |verifier| {
        supervisor.resolve_production_recovery(
            &agent_id,
            &decision,
            verifier,
            authority_epoch,
            unix_seconds_now(),
        )
    }) {
        Ok(recovery) => recovery,
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
    if let Err(error) = recovery {
        let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
        return safe_rejection(
            error,
            post.or(Some(actual)),
            /*mutation_started*/ false,
        );
    }
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let verifier = match authority.resolve_grant(&grant) {
        Ok(verifier) => verifier,
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
''',
    '''''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let receipt = match supervisor.apply_production_grant(
        &agent_id,
        &grant,
        &h7_envelope,
        &verifier,
        authority_epoch,
        unix_seconds_now(),
        Instant::now(),
    ) {
        Ok(receipt) => receipt,
        Err(error) => {
            let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
            return safe_rejection(
                error,
                post.or(Some(actual)),
                /*mutation_started*/ false,
            );
        }
    };
''',
    '''    let receipt = match authority.with_grant_verifier(&grant, |verifier| {
        supervisor.apply_production_grant(
            &agent_id,
            &grant,
            &h7_envelope,
            verifier,
            authority_epoch,
            unix_seconds_now(),
            Instant::now(),
        )
    }) {
        Ok(Ok(receipt)) => receipt,
        Ok(Err(error)) => {
            let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
            return safe_rejection(
                error,
                post.or(Some(actual)),
                /*mutation_started*/ false,
            );
        }
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
''',
)

# Use one monotonic observation cut for the whole periodic plan while still
# yielding the writer lock between Agents.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''                    for agent_id in agent_ids {
                        let faults = {
                            let mut supervisor = tick_state
                                .supervisor
                                .lock(SupervisordLockOperation::TickAgent)
                                .await;
                            supervisor.tick_agent(&agent_id, Instant::now()).faults
''',
    '''                    let cycle_now = Instant::now();
                    for agent_id in agent_ids {
                        let faults = {
                            let mut supervisor = tick_state
                                .supervisor
                                .lock(SupervisordLockOperation::TickAgent)
                                .await;
                            supervisor.tick_agent(&agent_id, cycle_now).faults
''',
)

# Exercise the restart journal at the same real post-publication SIGKILL cut as
# the lease, signed intent and release transaction.
replace_once(
    "codex-rs/hepta-supervisor/src/crash_qualification.rs",
    '''        for (kind, point) in [
            ("lease", "lease.after_publish=kill"),
            ("intent", "signed_intent.after_publish=kill"),
            ("release", "release_transaction.after_publish=kill"),
        ] {
''',
    '''        for (kind, point) in [
            ("lease", "lease.after_publish=kill"),
            ("restart", "restart_journal.after_publish=kill"),
            ("intent", "signed_intent.after_publish=kill"),
            ("release", "release_transaction.after_publish=kill"),
        ] {
''',
)

print("runtime.supervisor compile and final-use fixups applied")
