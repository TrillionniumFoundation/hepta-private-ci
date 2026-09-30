#!/usr/bin/env python3
"""One-shot source materializer for runtime.supervisor six-phase closure.

This script is intentionally exact-marker based. It fails closed when the
reviewed source shape changes instead of silently applying a partial patch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codex-rs" / "hepta-supervisor" / "src"
DOCS = ROOT / "docs" / "modules" / "runtime.supervisor"
WORKFLOWS = ROOT / ".github" / "workflows"
BRANCH = "codex/runtime-supervisor-six-phase-closure-20260930-r4"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(path: Path, old: str, new: str, *, already: str | None = None) -> None:
    text = read(path)
    if already is not None and already in text:
        return
    if old not in text:
        raise SystemExit(f"marker changed in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def replace_block(
    path: Path,
    old: str,
    new: str,
    *,
    already: str | None = None,
) -> None:
    text = read(path)
    if already is not None and already in text:
        return
    old_lines = dedent(old).strip("\n").splitlines()
    new_lines = dedent(new).strip("\n").splitlines()
    source_lines = text.splitlines(keepends=True)
    for start in range(0, len(source_lines) - len(old_lines) + 1):
        first = source_lines[start].rstrip("\n")
        if first.lstrip() != old_lines[0].lstrip():
            continue
        prefix = first[: len(first) - len(first.lstrip())]
        matched = True
        for offset, target in enumerate(old_lines):
            actual = source_lines[start + offset].rstrip("\n")
            expected = prefix + target if target else ""
            if actual != expected:
                matched = False
                break
        if not matched:
            continue
        replacement = [(prefix + line if line else "") + "\n" for line in new_lines]
        source_lines[start : start + len(old_lines)] = replacement
        write(path, "".join(source_lines))
        return
    raise SystemExit(f"block marker changed in {path}: {old_lines[0]!r}")


def insert_after(path: Path, marker: str, addition: str, *, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        return
    if marker not in text:
        raise SystemExit(f"insert marker changed in {path}: {marker!r}")
    write(path, text.replace(marker, marker + addition, 1))


def insert_before(path: Path, marker: str, addition: str, *, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        return
    if marker not in text:
        raise SystemExit(f"insert marker changed in {path}: {marker!r}")
    write(path, text.replace(marker, addition + marker, 1))


def patch_lib() -> None:
    path = SRC / "lib.rs"
    insert_after(
        path,
        "mod model;\n",
        "mod mutation_journal;\nmod process_exit_witness;\nmod recovery_observation;\n",
        sentinel="mod mutation_journal;",
    )
    exports = dedent(
        """
        pub use mutation_journal::DurableMutationPhaseV1;
        pub use mutation_journal::DurableMutationStatusV1;
        pub use mutation_journal::MUTATION_JOURNAL_FILE;
        pub use mutation_journal::MUTATION_JOURNAL_SCHEMA_VERSION;
        pub use mutation_journal::MutationJournalError;
        pub use mutation_journal::commit_mutation;
        pub use mutation_journal::mark_mutation_ambiguous;
        pub use mutation_journal::mark_mutation_effect_started;
        pub use mutation_journal::prepare_mutation;
        pub use mutation_journal::read_mutation_status;
        pub use mutation_journal::require_mutation_operator;
        pub use process_exit_witness::PROCESS_EXIT_WITNESS_FILE;
        pub use process_exit_witness::PROCESS_EXIT_WITNESS_SCHEMA_VERSION;
        pub use process_exit_witness::ProcessExitWitnessError;
        pub use process_exit_witness::ProcessExitWitnessPhaseV1;
        pub use process_exit_witness::ProcessExitWitnessV1;
        pub use process_exit_witness::consume_process_exit_witness;
        pub use process_exit_witness::read_process_exit_witness;
        pub use process_exit_witness::record_process_exit;
        pub use recovery_observation::PRODUCTION_RECOVERY_OBSERVATION_FILE;
        pub use recovery_observation::PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION;
        pub use recovery_observation::ProductionRecoveryObservationV1;
        pub use recovery_observation::RecoveryObservationError;
        pub use recovery_observation::RecoveryReplayDecisionV1;
        pub use recovery_observation::publish_production_recovery_observation;
        pub use recovery_observation::read_production_recovery_observation;
        pub use recovery_observation::replay_production_recovery_observation;
        """
    )
    insert_after(
        path,
        "pub use model::TickReport;\n",
        exports,
        sentinel="pub use mutation_journal::DurableMutationPhaseV1;",
    )


def patch_exit_witness() -> None:
    path = SRC / "process_exit_witness.rs"
    for old, new in [
        ("    fn same_target(\n", "    pub(crate) fn same_target(\n"),
        (
            "    fn compute_witness_id(&self)",
            "    pub(crate) fn compute_witness_id(&self)",
        ),
        (
            "    fn compute_record_digest(&self)",
            "    pub(crate) fn compute_record_digest(&self)",
        ),
    ]:
        text = read(path)
        if new in text:
            continue
        if old not in text:
            raise SystemExit(f"witness marker changed: {old!r}")
        write(path, text.replace(old, new, 1))


def patch_recovery_observation() -> None:
    path = SRC / "recovery_observation.rs"
    insert_after(
        path,
        "use std::fs::OpenOptions;\n",
        "use std::io::ErrorKind;\nuse std::io::Read;\n",
        sentinel="use std::io::ErrorKind;",
    )
    replace_once(
        path,
        "            || self.lifecycle_generation == 0\n",
        "            // A never-started Agent may legitimately remain at lifecycle generation zero.\n",
        already="never-started Agent may legitimately remain",
    )
    read_fn = dedent(
        """
        pub fn read_production_recovery_observation(
            run_root: &Path,
        ) -> Result<Option<ProductionRecoveryObservationV1>, RecoveryObservationError> {
            let path = run_root.join(PRODUCTION_RECOVERY_OBSERVATION_FILE);
            let mut options = OpenOptions::new();
            options.read(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
            }
            let mut file = match options.open(&path) {
                Ok(file) => file,
                Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
                Err(error) => return Err(error.into()),
            };
            let metadata = file.metadata()?;
            if !metadata.file_type().is_file()
                || metadata.file_type().is_symlink()
                || metadata.len() > MAX_RECOVERY_OBSERVATION_BYTES as u64
            {
                return Err(RecoveryObservationError::Invalid(
                    "recovery observation is not a bounded regular file".to_string(),
                ));
            }
            let mut bytes = Vec::new();
            (&mut file)
                .take((MAX_RECOVERY_OBSERVATION_BYTES + 1) as u64)
                .read_to_end(&mut bytes)?;
            if bytes.len() > MAX_RECOVERY_OBSERVATION_BYTES
                || bytes.len() as u64 != metadata.len()
            {
                return Err(RecoveryObservationError::Invalid(
                    "recovery observation changed while being read or exceeds its bound"
                        .to_string(),
                ));
            }
            let observation: ProductionRecoveryObservationV1 = serde_json::from_slice(&bytes)?;
            observation.validate()?;
            Ok(Some(observation))
        }

        """
    )
    insert_before(
        path,
        "fn write_observation(\n",
        read_fn,
        sentinel="pub fn read_production_recovery_observation(",
    )


def patch_tick() -> None:
    path = SRC / "tick.rs"
    insert_after(
        path,
        "use crate::lease::ProcessLeaseRemoval;\n",
        "use crate::process_exit_witness;\n",
        sentinel="use crate::process_exit_witness;",
    )
    witness_code = dedent(
        """
                let exit_witness = process_exit_witness::record_process_exit(
                    record.layout.run_root(),
                    agent_id,
                    runtime.generation,
                    runtime.spawn_generation,
                    &runtime.release_id,
                    &runtime.identity,
                    exit.success,
                    exit.code,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        """
    )
    insert_before(
        path,
        "        let unpublished_launch = slot.exit_lease_removal.as_ref()\n",
        witness_code,
        sentinel="let exit_witness = process_exit_witness::record_process_exit(",
    )
    consume_code = dedent(
        """
                process_exit_witness::consume_process_exit_witness(
                    record.layout.run_root(),
                    &exit_witness.witness_id,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        """
    )
    insert_before(
        path,
        "        slot.exit_lease_removal = None;\n",
        consume_code,
        sentinel="&exit_witness.witness_id",
    )


def patch_recovery() -> None:
    path = SRC / "recovery.rs"
    insert_after(
        path,
        "use crate::control_intent;\n",
        "use crate::process_exit_witness;\nuse crate::ProcessExitWitnessPhaseV1;\n",
        sentinel="use crate::process_exit_witness;",
    )
    insert_before(
        path,
        "        let Some(lease) = read_lease(record.layout.run_root())? else {\n",
        dedent(
            """
                    let pending_exit =
                        process_exit_witness::read_process_exit_witness(record.layout.run_root())
                            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            """
        ),
        sentinel="let pending_exit =\n            process_exit_witness::read_process_exit_witness",
    )
    replace_block(
        path,
        dedent(
            """
                    control_intent::reconcile_absent(
                        record.layout.run_root(),
                        agent_id,
                        terminal_lifecycle,
                    )
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    return Ok(());
            """
        ),
        dedent(
            """
                    control_intent::reconcile_absent(
                        record.layout.run_root(),
                        agent_id,
                        terminal_lifecycle,
                    )
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    if let Some(witness) = pending_exit.as_ref().filter(|witness| {
                        witness.phase == ProcessExitWitnessPhaseV1::Observed
                            && witness.agent_id == *agent_id
                            && witness.lifecycle_generation <= record.lifecycle.generation
                    }) {
                        process_exit_witness::consume_process_exit_witness(
                            record.layout.run_root(),
                            &witness.witness_id,
                        )
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    }
                    return Ok(());
            """
        ),
        already="witness.lifecycle_generation <= record.lifecycle.generation",
    )
    insert_before(
        path,
        "        // Assess the existing durable evidence without propagating a semantic\n",
        dedent(
            """
                    let witnessed_exit = pending_exit.as_ref().filter(|witness| {
                        witness.phase == ProcessExitWitnessPhaseV1::Observed
                            && witness.agent_id == *agent_id
                            && witness.spawn_generation == lease.spawn_generation
                            && witness.release_id == lease.release_id
                            && witness.process_identity == lease.identity
                    });
        """
        ),
        sentinel="let witnessed_exit = pending_exit.as_ref().filter",
    )
    insert_before(
        path,
        "                let admitted = admission.and_then(|admitted| {\n",
        dedent(
            """
                        if witnessed_exit.is_some() {
                            admission::reject_owned(agent_id, slot, now);
                            return Err(SupervisorError::Invalid(format!(
                                "agent {agent_id} was adopted alive after an exact terminal witness; operator reconciliation is required"
                            )));
                        }
        """
        ),
        sentinel="was adopted alive after an exact terminal witness",
    )
    replace_block(
        path,
        dedent(
            """
                        control_intent::reconcile_absent(
                            record.layout.run_root(),
                            agent_id,
                            terminal_lifecycle,
                        )
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                        slot.event(record.lifecycle.generation, SupervisorEventKind::OrphanMissing);
            """
        ),
        dedent(
            """
                        control_intent::reconcile_absent(
                            record.layout.run_root(),
                            agent_id,
                            terminal_lifecycle,
                        )
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                        if let Some(witness) = witnessed_exit {
                            process_exit_witness::consume_process_exit_witness(
                                record.layout.run_root(),
                                &witness.witness_id,
                            )
                            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                        }
                        slot.event(record.lifecycle.generation, SupervisorEventKind::OrphanMissing);
            """
        ),
        already="if let Some(witness) = witnessed_exit",
    )


def patch_mutation_journal() -> None:
    path = SRC / "mutation_journal.rs"
    replace_once(
        path,
        "matches!(self, Self::Prepared | Self::EffectStarted | Self::Ambiguous)",
        "matches!(\n            self,\n            Self::Prepared | Self::EffectStarted | Self::Ambiguous | Self::RequiresOperator\n        )",
        already="Self::Ambiguous | Self::RequiresOperator",
    )
    attempt_fn = dedent(
        """
            fn increment_attempt(&self) -> Result<Self, MutationJournalError> {
                let mut next = self.clone();
                next.attempt_sequence = next.attempt_sequence.checked_add(1).ok_or_else(|| {
                    MutationJournalError::Invalid("mutation attempt sequence overflow".to_string())
                })?;
                next.record_sha256 = next.compute_record_digest()?;
                next.validate()?;
                Ok(next)
            }

        """
    )
    insert_before(
        path,
        "    fn validate(&self) -> Result<(), MutationJournalError> {\n",
        attempt_fn,
        sentinel="fn increment_attempt(&self)",
    )
    replace_block(
        path,
        dedent(
            """
                    if current.request_id == request_id {
                        if current.idempotency_key == next.idempotency_key {
                            return Ok(current);
                        }
                        return Err(MutationJournalError::IdentityConflict);
                    }
            """
        ),
        dedent(
            """
                    if current.request_id == request_id {
                        if current.idempotency_key == next.idempotency_key {
                            let retried = current.increment_attempt()?;
                            write_mutation_status(run_root, &retried)?;
                            return Ok(retried);
                        }
                        return Err(MutationJournalError::IdentityConflict);
                    }
            """
        ),
        already="let retried = current.increment_attempt()?",
    )
    replace_once(
        path,
        "        assert_eq!(first, replay);\n",
        dedent(
            """
                    assert_eq!(replay.idempotency_key, first.idempotency_key);
                    assert_eq!(replay.phase, DurableMutationPhaseV1::Prepared);
                    assert_eq!(replay.attempt_sequence, 2);
            """
        ),
        already="assert_eq!(replay.attempt_sequence, 2);",
    )


def patch_protocol() -> None:
    path = SRC / "daemon_protocol.rs"
    insert_after(
        path,
        "use crate::DurableReleaseTransaction;\n",
        "use crate::DurableMutationStatusV1;\n",
        sentinel="use crate::DurableMutationStatusV1;",
    )
    replace_block(
        path,
        dedent(
            """
                        SupervisordMethod::Health
                        | SupervisordMethod::Snapshot { .. }
                        | SupervisordMethod::ReleaseSelection { .. }
                        | SupervisordMethod::ProductionMutationStatus { .. } => Ok(()),
            """
        ),
        dedent(
            """
                        SupervisordMethod::Health
                        | SupervisordMethod::Snapshot { .. }
                        | SupervisordMethod::ReleaseSelection { .. }
                        | SupervisordMethod::ProductionMutationStatus { .. } => Ok(()),
                        SupervisordMethod::OrdinaryMutationStatus {
                            mutation_request_id,
                            ..
                        } => {
                            if *mutation_request_id == 0 {
                                Err(SupervisordRequestValidationError::InvalidRequest)
                            } else {
                                Ok(())
                            }
                        }
            """
        ),
        already="SupervisordMethod::OrdinaryMutationStatus",
    )
    replace_block(
        path,
        dedent(
            """
                        SupervisordMethod::Start { fence, .. }
                        | SupervisordMethod::Drain { fence }
                        | SupervisordMethod::Stop { fence }
                        | SupervisordMethod::Kill { fence }
                        | SupervisordMethod::Restart { fence }
                        | SupervisordMethod::Upgrade { fence, .. }
                        | SupervisordMethod::Rollback { fence }
                        | SupervisordMethod::SignedUpgrade { fence, .. }
                        | SupervisordMethod::SignedRollback { fence, .. }
                        | SupervisordMethod::ResolveProductionRecovery { fence, .. } => fence.validate(),
            """
        ),
        dedent(
            """
                        SupervisordMethod::Start { fence, .. }
                        | SupervisordMethod::Drain { fence }
                        | SupervisordMethod::Stop { fence }
                        | SupervisordMethod::Kill { fence }
                        | SupervisordMethod::Restart { fence }
                        | SupervisordMethod::Upgrade { fence, .. }
                        | SupervisordMethod::Rollback { fence }
                        | SupervisordMethod::SignedUpgrade { fence, .. }
                        | SupervisordMethod::SignedRollback { fence, .. }
                        | SupervisordMethod::ResolveProductionRecovery { fence, .. } => fence.validate(),
                        SupervisordMethod::ReconcileOrdinaryMutation {
                            fence,
                            mutation_request_id,
                        } => {
                            if *mutation_request_id == 0 {
                                Err(SupervisordRequestValidationError::InvalidRequest)
                            } else {
                                fence.validate()
                            }
                        }
            """
        ),
        already="SupervisordMethod::ReconcileOrdinaryMutation",
    )
    replace_block(
        path,
        """
        ProductionMutationStatus {
            agent_id: AgentId,
        },
        """,
        """
        ProductionMutationStatus {
            agent_id: AgentId,
        },
        /// Query the durable outcome journal for one ordinary lifecycle request.
        OrdinaryMutationStatus {
            agent_id: AgentId,
            mutation_request_id: u64,
        },
        /// Fail-closed reconciliation. It never replays an effect-started request.
        ReconcileOrdinaryMutation {
            fence: SupervisordControlFence,
            mutation_request_id: u64,
        },
        """,
        already="OrdinaryMutationStatus {",
    )
    replace_block(
        path,
        """
        ProductionMutationStatus {
            state: Option<ProductionMutationState>,
        },
        """,
        """
        ProductionMutationStatus {
            state: Option<ProductionMutationState>,
        },
        OrdinaryMutationStatus {
            status: Option<DurableMutationStatusV1>,
        },
        """,
        already="status: Option<DurableMutationStatusV1>",
    )
    test = dedent(
        """
            #[test]
            fn ordinary_mutation_status_and_reconcile_requests_are_validated() {
                let agent_id = AgentId::parse(AGENT_ID).expect("agent");
                let status = SupervisordRequest::new(
                    51,
                    SupervisordMethod::OrdinaryMutationStatus {
                        agent_id: agent_id.clone(),
                        mutation_request_id: 41,
                    },
                );
                assert_eq!(status.validate(), Ok(()));
                let reconcile = SupervisordRequest::new(
                    52,
                    SupervisordMethod::ReconcileOrdinaryMutation {
                        fence: fence(),
                        mutation_request_id: 41,
                    },
                );
                assert_eq!(reconcile.validate(), Ok(()));
                let invalid = SupervisordRequest::new(
                    53,
                    SupervisordMethod::OrdinaryMutationStatus {
                        agent_id,
                        mutation_request_id: 0,
                    },
                );
                assert_eq!(
                    invalid.validate(),
                    Err(SupervisordRequestValidationError::InvalidRequest)
                );
            }

        """
    )
    # Place before the status fixture helper near the end of the test module.
    marker = "    fn status() -> SupervisordAgentStatus {\n"
    insert_before(
        path,
        marker,
        test,
        sentinel="ordinary_mutation_status_and_reconcile_requests_are_validated",
    )


def patch_read_view() -> None:
    path = SRC / "daemon_read_view.rs"
    replace_block(
        path,
        dedent(
            """
                pub(super) fn publish<D: ProcessDriver>(
                    &self,
                    registry: &FleetRegistry,
                    supervisor: &Supervisor<D>,
                    epoch: &SupervisorEpoch,
                ) -> Result<(), SupervisorError> {
            """
        ),
        dedent(
            """
                pub(super) fn publish<D: ProcessDriver>(
                    &self,
                    registry: &FleetRegistry,
                    supervisor: &Supervisor<D>,
                    epoch: &SupervisorEpoch,
                    recovery_observation_blocked: bool,
                ) -> Result<(), SupervisorError> {
            """
        ),
        already="recovery_observation_blocked: bool",
    )
    replace_once(
        path,
        "            ready: ownership_ready && !supervisor.any_production_recovery_required(),\n",
        dedent(
            """
                        ready: ownership_ready
                            && !recovery_observation_blocked
                            && !supervisor.any_production_recovery_required(),
            """
        ),
        already="&& !recovery_observation_blocked",
    )
    replace_once(
        path,
        "            | SupervisordMethod::ProductionMutationStatus { .. }\n",
        dedent(
            """
                        | SupervisordMethod::ProductionMutationStatus { .. }
                        | SupervisordMethod::OrdinaryMutationStatus { .. }
                        | SupervisordMethod::ReconcileOrdinaryMutation { .. }
            """
        ),
        already="| SupervisordMethod::OrdinaryMutationStatus { .. }",
    )


def patch_execution() -> None:
    path = SRC / "daemon_execution.rs"
    old_sig = dedent(
        """
        pub(super) async fn handle(
            state: Arc<DaemonState<UnixProcessDriver>>,
            method: SupervisordMethod,
        ) -> SupervisordPayload {
        """
    )
    new_sig = dedent(
        """
        pub(super) async fn handle(
            state: Arc<DaemonState<UnixProcessDriver>>,
            method: SupervisordMethod,
        ) -> SupervisordPayload {
            handle_with_request_id(state, 1, method).await
        }

        pub(super) async fn handle_with_request_id(
            state: Arc<DaemonState<UnixProcessDriver>>,
            request_id: u64,
            method: SupervisordMethod,
        ) -> SupervisordPayload {
        """
    )
    replace_once(
        path, old_sig, new_sig, already="pub(super) async fn handle_with_request_id("
    )
    replace_once(
        path,
        "        let reply = runtime.block_on(super::handle_request(Arc::clone(state), method));\n",
        dedent(
            """
                    let reply = runtime.block_on(super::handle_request(
                        Arc::clone(state),
                        request_id,
                        method,
                    ));
            """
        ),
        already="request_id,\n            method,",
    )
    replace_block(
        path,
        dedent(
            """
                    .publish(&state.registry, supervisor, &state.supervisor_epoch)
            """
        ),
        dedent(
            """
                    .publish(
                        &state.registry,
                        supervisor,
                        &state.supervisor_epoch,
                        state.any_recovery_observation_blocked(),
                    )
            """
        ),
        already="recovery_observation_blocked",
    )


def patch_daemon() -> None:
    path = SRC / "daemon.rs"
    insert_after(
        path,
        "use std::io::ErrorKind;\n",
        "#[cfg(unix)]\nuse std::collections::BTreeSet;\n",
        sentinel="use std::collections::BTreeSet;",
    )
    insert_after(
        path,
        "    observed_faults: AtomicU64,\n",
        "    recovery_observation_blocked: std::sync::RwLock<BTreeSet<AgentId>>,\n",
        sentinel="recovery_observation_blocked: std::sync::RwLock",
    )
    state_helpers = dedent(
        """
        #[cfg(unix)]
        impl<D: ProcessDriver> DaemonState<D> {
            fn any_recovery_observation_blocked(&self) -> bool {
                self.recovery_observation_blocked
                    .read()
                    .map_or(true, |blocked| !blocked.is_empty())
            }

            fn recovery_observation_blocked_for(&self, agent_id: &AgentId) -> bool {
                self.recovery_observation_blocked
                    .read()
                    .map_or(true, |blocked| blocked.contains(agent_id))
            }

            fn block_recovery_observation(
                &self,
                agent_id: AgentId,
            ) -> Result<(), SupervisorError> {
                self.recovery_observation_blocked
                    .write()
                    .map_err(|_| {
                        SupervisorError::Invalid(
                            "recovery observation block set is unavailable".to_string(),
                        )
                    })?
                    .insert(agent_id);
                Ok(())
            }
        }

        """
    )
    insert_after(
        path,
        "    _instance: SingleInstanceLock,\n}\n",
        state_helpers,
        sentinel="fn any_recovery_observation_blocked(&self)",
    )
    replace_block(
        path,
        dedent(
            """
                let state = Arc::new(DaemonState {
                    registry,
                    supervisor: Mutex::new(supervisor),
                    supervisor_epoch: SupervisorEpoch::new(),
                    production_grant_verifier,
                    observed_faults: AtomicU64::new(recovery.faults.len() as u64),
                    execution: execution::Execution::new(cancellation.clone()),
                    _instance: instance,
                });
                {
                    let supervisor = state.supervisor.lock().await;
                    execution::refresh(&state, &supervisor);
                }
            """
        ),
        dedent(
            """
                let supervisor_epoch = SupervisorEpoch::new();
                let state = Arc::new(DaemonState {
                    registry,
                    supervisor: Mutex::new(supervisor),
                    supervisor_epoch,
                    production_grant_verifier,
                    observed_faults: AtomicU64::new(recovery.faults.len() as u64),
                    recovery_observation_blocked: std::sync::RwLock::new(BTreeSet::new()),
                    execution: execution::Execution::new(cancellation.clone()),
                    _instance: instance,
                });
                {
                    let supervisor = state.supervisor.lock().await;
                    publish_recovery_observations(&state, &supervisor)?;
                    execution::refresh(&state, &supervisor);
                }
            """
        ),
        already="publish_recovery_observations(&state, &supervisor)?;",
    )
    replace_once(
        path,
        "            payload: execution::handle(Arc::clone(&state), request.method).await,\n",
        dedent(
            """
                        payload: execution::handle_with_request_id(
                            Arc::clone(&state),
                            request.request_id,
                            request.method,
                        )
                        .await,
            """
        ),
        already="execution::handle_with_request_id(",
    )
    replace_block(
        path,
        dedent(
            """
        async fn handle_request<D: ProcessDriver>(
            state: Arc<DaemonState<D>>,
            method: SupervisordMethod,
        ) -> SupervisordPayload {
        """
        ),
        dedent(
            """
        async fn handle_request<D: ProcessDriver>(
            state: Arc<DaemonState<D>>,
            request_id: u64,
            method: SupervisordMethod,
        ) -> SupervisordPayload {
        """
        ),
        already="request_id: u64,\n    method: SupervisordMethod",
    )
    replace_once(
        path,
        "                ready: !recovery_required,\n",
        dedent(
            """
                            ready: !recovery_required
                                && !state.any_recovery_observation_blocked(),
            """
        ),
        already="any_recovery_observation_blocked()",
    )

    replace_block(
        path,
        """
        SupervisordMethod::ProductionMutationStatus { agent_id } => {
            let supervisor = state.supervisor.lock().await;
            match supervisor.production_mutation_state(&agent_id) {
                Ok(state) => SupervisordPayload::ProductionMutationStatus { state },
                Err(error) => {
                    safe_rejection(error, /*actual*/ None, /*mutation_started*/ false)
                }
            }
        }
        """,
        """
        SupervisordMethod::ProductionMutationStatus { agent_id } => {
            let supervisor = state.supervisor.lock().await;
            match supervisor.production_mutation_state(&agent_id) {
                Ok(state) => SupervisordPayload::ProductionMutationStatus { state },
                Err(error) => {
                    safe_rejection(error, /*actual*/ None, /*mutation_started*/ false)
                }
            }
        }
        SupervisordMethod::OrdinaryMutationStatus {
            agent_id,
            mutation_request_id,
        } => ordinary_mutation_status(&state, &agent_id, mutation_request_id),
        SupervisordMethod::ReconcileOrdinaryMutation {
            fence,
            mutation_request_id,
        } => reconcile_ordinary_mutation(state, fence, mutation_request_id).await,
        """,
        already="SupervisordMethod::OrdinaryMutationStatus {",
    )

    # Pass the wire request identity to every ordinary lifecycle mutation.
    text = read(path)
    text = text.replace(
        "handle_mutation(state, SupervisordMutation::Start, fence, Some(target)).await",
        "handle_mutation(state, request_id, SupervisordMutation::Start, fence, Some(target)).await",
    )
    text = text.replace(
        "handle_mutation(state, SupervisordMutation::Upgrade, fence, Some(target)).await",
        "handle_mutation(state, request_id, SupervisordMutation::Upgrade, fence, Some(target)).await",
    )
    text = text.replace(
        "handle_mutation(\n                state,\n                SupervisordMutation::",
        "handle_mutation(\n                state,\n                request_id,\n                SupervisordMutation::",
    )
    if "handle_mutation(state, SupervisordMutation::" in text or (
        "handle_mutation(\n                state,\n                SupervisordMutation::"
        in text
    ):
        raise SystemExit(
            "an ordinary mutation call did not receive the wire request identity"
        )
    write(path, text)

    replace_block(
        path,
        """
        async fn handle_mutation<D: ProcessDriver>(
            state: Arc<DaemonState<D>>,
            operation: SupervisordMutation,
            fence: SupervisordControlFence,
            target: Option<AgentRelease>,
        ) -> SupervisordPayload {
            let agent_id = fence.agent_id.clone();
            let accepted_state_digest = fence.state_digest.clone();
            let mut supervisor = state.supervisor.lock().await;
        """,
        """
        async fn handle_mutation<D: ProcessDriver>(
            state: Arc<DaemonState<D>>,
            request_id: u64,
            operation: SupervisordMutation,
            fence: SupervisordControlFence,
            target: Option<AgentRelease>,
        ) -> SupervisordPayload {
            let agent_id = fence.agent_id.clone();
            let accepted_state_digest = fence.state_digest.clone();
            if state.recovery_observation_blocked_for(&agent_id)
                && operation != SupervisordMutation::Kill
            {
                return error_payload(
                    "recovery_observation_required",
                    "this Agent has an owner-bound recovery observation that requires reconciliation; only status, reconciliation, or emergency kill is allowed",
                    /*actual*/ None,
                );
            }
            let mut supervisor = state.supervisor.lock().await;
        """,
        already='"recovery_observation_required"',
    )

    journal_block = dedent(
        """
            let run_root = match agent_run_root(&state, &agent_id) {
                Ok(run_root) => run_root,
                Err(error) => {
                    return safe_rejection(error, Some(actual), /*mutation_started*/ false);
                }
            };
            let durable = match crate::prepare_mutation(
                &run_root,
                request_id,
                &agent_id,
                state.supervisor_epoch.as_str(),
                operation,
                accepted_state_digest.as_str(),
                next_revision,
            ) {
                Ok(status) => status,
                Err(error) => {
                    return error_payload(
                        "mutation_journal_rejected",
                        &format!("ordinary mutation was not admitted: {error}"),
                        Some(actual),
                    );
                }
            };
            match durable.phase {
                crate::DurableMutationPhaseV1::Prepared => {}
                crate::DurableMutationPhaseV1::Committed => {
                    return error_payload(
                        "mutation_already_committed",
                        "this request already committed; query OrdinaryMutationStatus instead of replaying it",
                        Some(actual),
                    );
                }
                crate::DurableMutationPhaseV1::EffectStarted
                | crate::DurableMutationPhaseV1::Ambiguous
                | crate::DurableMutationPhaseV1::RequiresOperator => {
                    return error_payload(
                        "mutation_reconciliation_required",
                        "this request crossed the effect boundary; query or reconcile its durable status instead of replaying it",
                        Some(actual),
                    );
                }
            }
            let durable = match crate::mark_mutation_effect_started(
                &run_root,
                &durable.idempotency_key,
            ) {
                Ok(status) => status,
                Err(error) => {
                    return error_payload(
                        "mutation_journal_rejected",
                        &format!("ordinary mutation effect boundary was not persisted: {error}"),
                        Some(actual),
                    );
                }
            };
        """
    )
    insert_before(
        path,
        "    if let Err(error) = supervisor.set_control_revision(&agent_id, next_revision) {\n",
        journal_block,
        sentinel="let durable = match crate::prepare_mutation(",
    )

    replace_block(
        path,
        dedent(
            """
                if let Err(error) = supervisor.set_control_revision(&agent_id, next_revision) {
                    return safe_rejection(error, Some(actual), /*mutation_started*/ false);
                }
            """
        ),
        dedent(
            """
                if let Err(error) = supervisor.set_control_revision(&agent_id, next_revision) {
                    let observed = agent_status_locked(&state, &supervisor, &agent_id)
                        .ok()
                        .map(|status| status.control_fence.state_digest);
                    let _ = crate::mark_mutation_ambiguous(
                        &run_root,
                        &durable.idempotency_key,
                        observed.as_ref().map(ControlStateDigest::as_str),
                        "control revision persistence failed after the durable effect boundary",
                    );
                    return safe_rejection(error, Some(actual), /*mutation_started*/ true);
                }
            """
        ),
        already="control revision persistence failed after the durable effect boundary",
    )
    replace_block(
        path,
        dedent(
            """
                let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
                if let Err(_error) = mutation {
                    return error_payload(
                        "operation_indeterminate",
                        "operation outcome is indeterminate; refresh before retry",
                        post,
                    );
                }
                let Some(agent) = post else {
                    return error_payload(
                        "operation_indeterminate",
                        "operation outcome is indeterminate; refresh before retry",
                        /*actual*/ None,
                    );
                };
                SupervisordPayload::MutationAccepted {
                    operation,
                    accepted_state_digest,
                    agent,
                    production_receipt: None,
                }
            """
        ),
        dedent(
            """
                let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
                if let Err(error) = mutation {
                    let _ = crate::mark_mutation_ambiguous(
                        &run_root,
                        &durable.idempotency_key,
                        post.as_ref()
                            .map(|status| status.control_fence.state_digest.as_str()),
                        &format!(
                            "driver returned an error after effect_started for request {request_id}: {error}"
                        ),
                    );
                    return error_payload(
                        "operation_indeterminate",
                        "operation crossed the durable effect boundary; query OrdinaryMutationStatus before any retry",
                        post,
                    );
                }
                let Some(agent) = post else {
                    let _ = crate::mark_mutation_ambiguous(
                        &run_root,
                        &durable.idempotency_key,
                        None,
                        "operation completed but the post-state projection was unavailable",
                    );
                    return error_payload(
                        "operation_indeterminate",
                        "operation crossed the durable effect boundary; query OrdinaryMutationStatus before any retry",
                        /*actual*/ None,
                    );
                };
                if let Err(error) = crate::commit_mutation(
                    &run_root,
                    &durable.idempotency_key,
                    next_revision,
                    next_revision,
                    agent.control_fence.state_digest.as_str(),
                ) {
                    let _ = crate::mark_mutation_ambiguous(
                        &run_root,
                        &durable.idempotency_key,
                        Some(agent.control_fence.state_digest.as_str()),
                        &format!(
                            "effect completed but durable commit publication failed for request {request_id}: {error}"
                        ),
                    );
                    return error_payload(
                        "operation_indeterminate",
                        "effect completed but its durable result is ambiguous; query OrdinaryMutationStatus",
                        Some(agent),
                    );
                }
                SupervisordPayload::MutationAccepted {
                    operation,
                    accepted_state_digest,
                    agent,
                    production_receipt: None,
                }
            """
        ),
        already="operation crossed the durable effect boundary; query OrdinaryMutationStatus",
    )

    helper_block = dedent(
        """
        #[cfg(unix)]
        fn agent_run_root<D: ProcessDriver>(
            state: &DaemonState<D>,
            agent_id: &AgentId,
        ) -> Result<PathBuf, SupervisorError> {
            state
                .registry
                .load()?
                .agent(agent_id)
                .map(|record| record.layout.run_root().to_path_buf())
                .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))
        }

        #[cfg(unix)]
        fn ordinary_mutation_status<D: ProcessDriver>(
            state: &DaemonState<D>,
            agent_id: &AgentId,
            mutation_request_id: u64,
        ) -> SupervisordPayload {
            let run_root = match agent_run_root(state, agent_id) {
                Ok(run_root) => run_root,
                Err(error) => {
                    return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
                }
            };
            match crate::read_mutation_status(&run_root) {
                Ok(status) => SupervisordPayload::OrdinaryMutationStatus {
                    status: status.filter(|status| {
                        status.agent_id == *agent_id
                            && status.request_id == mutation_request_id
                    }),
                },
                Err(error) => safe_rejection(
                    SupervisorError::Invalid(error.to_string()),
                    /*actual*/ None,
                    /*mutation_started*/ false,
                ),
            }
        }

        #[cfg(unix)]
        async fn reconcile_ordinary_mutation<D: ProcessDriver>(
            state: Arc<DaemonState<D>>,
            fence: SupervisordControlFence,
            mutation_request_id: u64,
        ) -> SupervisordPayload {
            let agent_id = fence.agent_id.clone();
            let supervisor = state.supervisor.lock().await;
            let actual = match agent_status_locked(&state, &supervisor, &agent_id) {
                Ok(actual) => actual,
                Err(error) => {
                    return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
                }
            };
            if !control_fence_matches(&fence, &actual.control_fence) {
                return error_payload(
                    "stale_control_fence",
                    "selected Agent changed; refresh before reconciliation",
                    Some(actual),
                );
            }
            let run_root = match agent_run_root(&state, &agent_id) {
                Ok(run_root) => run_root,
                Err(error) => {
                    return safe_rejection(error, Some(actual), /*mutation_started*/ false);
                }
            };
            let Some(status) = (match crate::read_mutation_status(&run_root) {
                Ok(status) => status,
                Err(error) => {
                    return safe_rejection(
                        SupervisorError::Invalid(error.to_string()),
                        Some(actual),
                        /*mutation_started*/ false,
                    );
                }
            }) else {
                return SupervisordPayload::OrdinaryMutationStatus { status: None };
            };
            if status.agent_id != agent_id || status.request_id != mutation_request_id {
                return SupervisordPayload::OrdinaryMutationStatus { status: None };
            }
            let reconciled = match status.phase {
                crate::DurableMutationPhaseV1::Prepared
                | crate::DurableMutationPhaseV1::Committed
                | crate::DurableMutationPhaseV1::RequiresOperator => Ok(status),
                crate::DurableMutationPhaseV1::EffectStarted
                | crate::DurableMutationPhaseV1::Ambiguous => {
                    let ambiguous = crate::mark_mutation_ambiguous(
                        &run_root,
                        &status.idempotency_key,
                        Some(actual.control_fence.state_digest.as_str()),
                        "owner reconciliation could not prove whether the effect completed",
                    );
                    ambiguous.and_then(|ambiguous| {
                        crate::require_mutation_operator(
                            &run_root,
                            &ambiguous.idempotency_key,
                            "automatic replay is forbidden after effect_started; inspect the exact process, lineage, exit witness, and recovery observation",
                        )
                    })
                }
            };
            match reconciled {
                Ok(status) => SupervisordPayload::OrdinaryMutationStatus {
                    status: Some(status),
                },
                Err(error) => safe_rejection(
                    SupervisorError::Invalid(error.to_string()),
                    Some(actual),
                    /*mutation_started*/ true,
                ),
            }
        }

        #[cfg(unix)]
        fn publish_recovery_observations<D: ProcessDriver>(
            state: &DaemonState<D>,
            supervisor: &Supervisor<D>,
        ) -> Result<(), SupervisorError> {
            let authority_epoch = state
                .production_grant_verifier
                .as_ref()
                .map(|_| authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str()));
            for (agent_id, record) in state.registry.load()?.agents {
                let snapshot = supervisor
                    .snapshot(&agent_id)
                    .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
                let observation = crate::publish_production_recovery_observation(
                    record.layout.run_root(),
                    &agent_id,
                    state.supervisor_epoch.as_str(),
                    record.lifecycle.lifecycle,
                    record.lifecycle.generation,
                    &snapshot,
                    authority_epoch,
                    None,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                match crate::replay_production_recovery_observation(&observation)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                {
                    crate::RecoveryReplayDecisionV1::Clean
                    | crate::RecoveryReplayDecisionV1::ContinueOwnedProcess => {}
                    crate::RecoveryReplayDecisionV1::FinalizeObservedExit => {
                        return Err(SupervisorError::Invalid(format!(
                            "agent {agent_id} retained an observed exit after recovery finalization"
                        )));
                    }
                    crate::RecoveryReplayDecisionV1::RejectStaleGeneration
                    | crate::RecoveryReplayDecisionV1::RequiresOperator => {
                        state.block_recovery_observation(agent_id.clone())?;
                        state.observed_faults.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            Ok(())
        }

        """
    )
    insert_before(
        path,
        "#[cfg(unix)]\nasync fn resolve_release_outside_lock",
        helper_block,
        sentinel="fn ordinary_mutation_status<D: ProcessDriver>(",
    )


def patch_client() -> None:
    path = SRC / "daemon_client.rs"
    insert_after(
        path,
        "use crate::DurableReleaseTransaction;\n",
        "use crate::DurableMutationStatusV1;\n",
        sentinel="use crate::DurableMutationStatusV1;",
    )
    replace_once(
        path,
        "            next_request_id: AtomicU64::new(1),\n",
        "            next_request_id: AtomicU64::new(random_request_seed()),\n",
        already="AtomicU64::new(random_request_seed())",
    )
    methods = dedent(
        """
            pub fn reserve_request_id(&self) -> u64 {
                loop {
                    let candidate = self.next_request_id.fetch_add(1, Ordering::Relaxed);
                    if candidate != 0 {
                        return candidate;
                    }
                }
            }

            pub async fn execute_mutation_with_request_id(
                &self,
                request_id: u64,
                method: SupervisordMethod,
            ) -> Result<SupervisordMutationAccepted, SupervisorError> {
                if !matches!(
                    &method,
                    SupervisordMethod::Start { .. }
                        | SupervisordMethod::Drain { .. }
                        | SupervisordMethod::Stop { .. }
                        | SupervisordMethod::Kill { .. }
                        | SupervisordMethod::Restart { .. }
                        | SupervisordMethod::Upgrade { .. }
                        | SupervisordMethod::Rollback { .. }
                ) {
                    return Err(SupervisorError::Invalid(
                        "execute_mutation_with_request_id requires an ordinary lifecycle mutation"
                            .to_string(),
                    ));
                }
                self.mutation_with_request_id(request_id, method).await
            }

            pub async fn ordinary_mutation_status(
                &self,
                agent_id: AgentId,
                mutation_request_id: u64,
            ) -> Result<Option<DurableMutationStatusV1>, SupervisorError> {
                match self
                    .send(SupervisordMethod::OrdinaryMutationStatus {
                        agent_id,
                        mutation_request_id,
                    })
                    .await?
                {
                    SupervisordPayload::OrdinaryMutationStatus { status } => Ok(status),
                    payload => unexpected(payload),
                }
            }

            pub async fn reconcile_ordinary_mutation(
                &self,
                fence: SupervisordControlFence,
                mutation_request_id: u64,
            ) -> Result<Option<DurableMutationStatusV1>, SupervisorError> {
                match self
                    .send(SupervisordMethod::ReconcileOrdinaryMutation {
                        fence,
                        mutation_request_id,
                    })
                    .await?
                {
                    SupervisordPayload::OrdinaryMutationStatus { status } => Ok(status),
                    payload => unexpected(payload),
                }
            }

        """
    )
    insert_before(
        path,
        "    pub async fn health(&self) -> Result<SupervisordHealth, SupervisorError> {\n",
        methods,
        sentinel="pub fn reserve_request_id(&self)",
    )
    replace_block(
        path,
        dedent(
            """
                async fn mutation(
                    &self,
                    method: SupervisordMethod,
                ) -> Result<SupervisordMutationAccepted, SupervisorError> {
                    match self.send(method).await? {
            """
        ),
        dedent(
            """
                async fn mutation(
                    &self,
                    method: SupervisordMethod,
                ) -> Result<SupervisordMutationAccepted, SupervisorError> {
                    let request_id = self.reserve_request_id();
                    self.mutation_with_request_id(request_id, method).await
                }

                async fn mutation_with_request_id(
                    &self,
                    request_id: u64,
                    method: SupervisordMethod,
                ) -> Result<SupervisordMutationAccepted, SupervisorError> {
                    match self.send_with_request_id(request_id, method).await? {
            """
        ),
        already="async fn mutation_with_request_id(",
    )
    replace_block(
        path,
        dedent(
            """
                async fn send(&self, method: SupervisordMethod) -> Result<SupervisordPayload, SupervisorError> {
                    let request_id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
                    let request = SupervisordRequest::new(request_id, method);
            """
        ),
        dedent(
            """
                async fn send(&self, method: SupervisordMethod) -> Result<SupervisordPayload, SupervisorError> {
                    let request_id = self.reserve_request_id();
                    self.send_with_request_id(request_id, method).await
                }

                async fn send_with_request_id(
                    &self,
                    request_id: u64,
                    method: SupervisordMethod,
                ) -> Result<SupervisordPayload, SupervisorError> {
                    let request = SupervisordRequest::new(request_id, method);
            """
        ),
        already="async fn send_with_request_id(",
    )
    random_seed = dedent(
        """
        fn random_request_seed() -> u64 {
            let bytes = *uuid::Uuid::new_v4().as_bytes();
            let seed = u64::from_be_bytes(
                bytes[..8]
                    .try_into()
                    .expect("UUID prefix is exactly eight bytes"),
            );
            seed.max(1)
        }

        """
    )
    insert_before(
        path,
        "fn unexpected<T>(payload: SupervisordPayload) -> Result<T, SupervisorError> {\n",
        random_seed,
        sentinel="fn random_request_seed()",
    )


def patch_status_and_docs() -> None:
    path = DOCS / "CAPABILITY_STATUS.json"
    data = json.loads(read(path))
    by_id = {entry["id"]: entry for entry in data["capabilities"]}

    def mark(
        capability_id: str,
        *,
        source_paths: list[str],
        summary: str | None = None,
    ) -> None:
        entry = by_id[capability_id]
        entry.update(
            {
                "source": "implemented",
                "test_source": "present",
                "exact_head": "pending",
                "merge_candidate": "pending",
                "target_host": "not_run",
            }
        )
        entry["source_paths"] = source_paths
        if summary is not None:
            entry["summary"] = summary

    mark(
        "cross_daemon_exit_cleanup_witness",
        source_paths=[
            "codex-rs/hepta-supervisor/src/process_exit_witness.rs",
            "codex-rs/hepta-supervisor/src/tick.rs",
            "codex-rs/hepta-supervisor/src/recovery.rs",
        ],
        summary=(
            "Exact-process terminal evidence is durable before lease/lifecycle finalization "
            "and is consumed only after same-owner cleanup survives daemon restart"
        ),
    )
    mark(
        "predecessor_replacement_lineage",
        source_paths=[
            "codex-rs/hepta-supervisor/src/restart_lineage.rs",
            "codex-rs/hepta-supervisor/src/recovery.rs",
            "docs/modules/runtime.supervisor/RESTART_LINEAGE_REPAIR_20260928.md",
        ],
        summary=(
            "Predecessor and replacement identities are generation-bound and recovery rejects "
            "ambiguous live/terminal combinations"
        ),
    )
    mark(
        "atomic_recovery_observation_envelope",
        source_paths=[
            "codex-rs/hepta-supervisor/src/recovery_observation.rs",
            "codex-rs/hepta-supervisor/src/daemon.rs",
        ],
        summary=(
            "One owner-bound digest-validated observation captures lifecycle, exact process, "
            "lease, exit witness and recovery blockers for deterministic replay"
        ),
    )
    if "durable_ordinary_mutation_protocol" not in by_id:
        entry = {
            "activated": False,
            "exact_head": "pending",
            "id": "durable_ordinary_mutation_protocol",
            "independent_acceptance": "not_obtained",
            "merge_candidate": "pending",
            "source": "implemented",
            "source_paths": [
                "codex-rs/hepta-supervisor/src/mutation_journal.rs",
                "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
                "codex-rs/hepta-supervisor/src/daemon.rs",
                "codex-rs/hepta-supervisor/src/daemon_client.rs",
                "docs/modules/runtime.supervisor/MUTATION_RETRY_PROTOCOL.md",
            ],
            "summary": (
                "Ordinary mutations persist request identity before effect, expose status and "
                "fail-closed reconciliation, and keep attempt/intent/applied/snapshot sequences distinct"
            ),
            "target_host": "not_run",
            "test_source": "present",
        }
        data["capabilities"].append(entry)
    data["current"]["source"] = "implemented"
    data["current"]["claim"] = (
        "source implementation candidate; exact-head, merge, target-host, independent acceptance "
        "and release authorization remain separate fail-closed gates"
    )
    data["current"]["release"] = False
    data["current"]["activated"] = False
    write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    write(
        DOCS / "MUTATION_RETRY_PROTOCOL.md",
        dedent(
            """
            # Ordinary lifecycle mutation retry protocol

            Ordinary `Start`, `Drain`, `Stop`, `Kill`, `Restart`, `Upgrade`, and
            `Rollback` requests use the wire request identity as part of a durable,
            daemon-epoch-bound idempotency key. The journal is persisted in the
            selected Agent run root before the effect boundary.

            ## Required caller sequence

            1. Reserve a non-zero request identity with
               `SupervisordClient::reserve_request_id`.
            2. Submit the mutation with
               `execute_mutation_with_request_id(request_id, method)`.
            3. If connect, write, or response delivery is uncertain, do not allocate a
               new request identity and do not issue a second side effect.
            4. Query `ordinary_mutation_status(agent_id, request_id)`.
            5. Interpret the durable phase:
               - `prepared`: the side effect was not entered; retrying the exact same
                 request identity is allowed.
               - `effect_started`: automatic replay is forbidden.
               - `committed`: the result is durable; no replay is allowed.
               - `ambiguous`: query/reconciliation is required.
               - `requires_operator`: inspect the exact process identity, restart
                 lineage, exit witness, and recovery observation.
            6. `reconcile_ordinary_mutation` never replays an effect-started request.
               When exact completion cannot be proven, it terminalizes the journal as
               `requires_operator`.

            `attempt_sequence`, `intent_sequence`, `applied_state_revision`, and
            `read_snapshot_epoch` are independent fields. Equality of two values in one
            implementation revision does not merge their semantics.

            ## Safety boundary

            A request with an unresolved durable journal blocks a different mutation.
            A PID match is never sufficient evidence. A stale generation, different
            process incarnation, missing containment proof, or contradictory live/exit
            observation remains fail-closed.
            """
        ).lstrip(),
    )
    write(
        DOCS / "SIX_PHASE_CLOSURE.md",
        dedent(
            """
            # runtime.supervisor six-phase closure

            This source revision closes the repository-side implementation portions of
            the six-phase plan without promoting external evidence.

            ## Source closure

            - exact-process exit evidence is persisted before finalization and consumed
              only after lease and lifecycle cleanup;
            - restart lineage remains bound to exact predecessor and replacement
              incarnations;
            - startup publishes one owner-bound recovery observation per Agent and
              deterministically replays it before serving mutations;
            - ordinary lifecycle mutations persist request identity before effect and
              expose durable status and fail-closed reconciliation;
            - attempt, intent, applied-state, and read-snapshot sequences are represented
              separately.

            ## Qualification boundary

            Repository source is not production qualification. The following remain
            false until evidence for one immutable final candidate proves them:

            - `release_eligible`;
            - `production_ready`;
            - `active`.

            Exact-head and deterministic-merge workflows must both pass without skipped
            substantive steps. Target-host receipts must cover Linux x86_64/ext4,
            Linux x86_64/xfs, Linux aarch64, and macOS arm64/APFS, including the
            64/128/256 process and fault matrices. Independent code, security, and
            operations acceptance, key custody, rotation/revocation, takeover/release,
            upgrade/rollback, daemon crash recovery, and release authorization remain
            external gates.

            ## HOL decision

            The current single lifecycle writer is retained until the exact 256-Agent
            target-host evidence breaches the frozen SLO. A per-Agent actor/partition
            rewrite is admissible only from measured evidence; fleet-global authority
            remains limited to generation, ownership transfer, capacity, and authority
            epoch transactions.
            """
        ).lstrip(),
    )


def patch_workflows() -> None:
    # Trigger exact-source rebind after the source-bearing commit.
    path = WORKFLOWS / "runtime-supervisor-source-rebind-materializer.yml"
    text = read(path)
    if f"      - {BRANCH}\n" not in text:
        marker = "      - codex/runtime-supervisor-six-phase-closure-20260930-r3\n"
        if marker not in text:
            raise SystemExit("source-rebind branch marker changed")
        text = text.replace(marker, marker + f"      - {BRANCH}\n", 1)
        write(path, text)

    path = WORKFLOWS / "runtime-supervisor-deep-qualification.yml"
    text = read(path)
    if f"      - {BRANCH}\n" not in text:
        marker = "      - codex/runtime-supervisor-full-qualification-20260930\n"
        if marker not in text:
            raise SystemExit("deep qualification branch marker changed")
        text = text.replace(marker, marker + f"      - {BRANCH}\n", 1)
        write(path, text)

    path = WORKFLOWS / "hepta-supervisor-qualification.yml"
    text = read(path)
    old = "    branches: [main]\n"
    new = f"    branches: [main, {BRANCH}]\n"
    if new not in text:
        if old not in text:
            raise SystemExit("supervisor qualification branch marker changed")
        write(path, text.replace(old, new, 1))


def verify_materialized_source() -> None:
    required = {
        SRC / "lib.rs": [
            "mod mutation_journal;",
            "pub use recovery_observation::read_production_recovery_observation;",
        ],
        SRC / "tick.rs": [
            "record_process_exit(",
            "consume_process_exit_witness(",
        ],
        SRC / "recovery.rs": [
            "let pending_exit =",
            "was adopted alive after an exact terminal witness",
        ],
        SRC / "daemon_protocol.rs": [
            "OrdinaryMutationStatus {",
            "ReconcileOrdinaryMutation {",
        ],
        SRC / "daemon.rs": [
            "handle_with_request_id(",
            "prepare_mutation(",
            "mark_mutation_effect_started(",
            "commit_mutation(",
            "publish_recovery_observations(",
            "recovery_observation_blocked_for",
        ],
        SRC / "daemon_client.rs": [
            "reserve_request_id",
            "execute_mutation_with_request_id",
            "ordinary_mutation_status",
            "reconcile_ordinary_mutation",
            "random_request_seed",
        ],
    }
    for path, markers in required.items():
        materialized = read(path)
        missing = [marker for marker in markers if marker not in materialized]
        if missing:
            raise SystemExit(f"materialized source is missing {missing!r} in {path}")
    daemon = read(SRC / "daemon.rs")
    if "handle_mutation(state, SupervisordMutation::" in daemon:
        raise SystemExit(
            "ordinary mutation call remains detached from request identity"
        )
    status = json.loads(read(DOCS / "CAPABILITY_STATUS.json"))
    if status["current"]["release"] or status["current"]["activated"]:
        raise SystemExit(
            "repository source materialization cannot authorize release or activation"
        )


def main() -> None:
    patch_lib()
    patch_exit_witness()
    patch_recovery_observation()
    patch_tick()
    patch_recovery()
    patch_mutation_journal()
    patch_protocol()
    patch_read_view()
    patch_execution()
    patch_daemon()
    patch_client()
    patch_status_and_docs()
    patch_workflows()
    verify_materialized_source()


if __name__ == "__main__":
    main()
