//! Same Fleet/spawn generation only. The private state cut is not wire V2.
use super::super::control::InstanceCommand;
use super::*;
use crate::RunPhase;
use crate::lane_b_runtime::instance::InstanceReceipt;

fn construct_instance(
    identity: AgentdIdentity,
    registry: FleetRegistry,
    capacity: usize,
    path: &Path,
    mode: JournalOpenMode,
) -> Result<AgentdState, AgentdError> {
    AgentdState::new_with_run_owner(identity, registry, capacity, |composition| {
        AgentRunCoordinator::open_instance_journaled(composition, path, mode)
    })
}
fn create_instance(state: &AgentdState, operation: &str) -> anyhow::Result<InstanceReceipt> {
    let (_, result) = state.instance_control_response(
        state.identity.spawn_generation,
        AgentdMethod::RunStart {
            snapshot: snapshot(state),
        },
        InstanceCommand::Start {
            creation_operation: operation.into(),
        },
    )?;
    Ok(result)
}
fn cancel_instance(
    state: &AgentdState,
    value: &InstanceReceipt,
) -> anyhow::Result<InstanceReceipt> {
    Ok(state
        .instance_control_response(
            state.identity.spawn_generation,
            AgentdMethod::RunCancel {
                run_id: value.handle.key.run_id.clone(),
                expected_revision: value.handle.revision,
                reason: "stop".into(),
            },
            InstanceCommand::Mutate(value.handle.clone()),
        )?
        .1)
}

#[tokio::test]
async fn actual_state_recreate_rejects_old_identity_and_legacy_mutations() -> anyhow::Result<()> {
    let fixture = Fixture::using(construct_instance)?;
    let state = fixture.state()?;
    let first = create_instance(state, "create.1")?;
    let cancelled = cancel_instance(state, &first)?;
    let (_, released) = state.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunReleaseClosed {
            run_id: first.handle.key.run_id.clone(),
            expected_revision: cancelled.handle.revision,
        },
        InstanceCommand::Mutate(cancelled.handle),
    )?;
    assert!(released.released);
    let replacement = create_instance(state, "create.2")?;
    assert_eq!(first.handle.revision, replacement.handle.revision);
    assert_ne!(first.handle.key, replacement.handle.key);
    assert!(cancel_instance(state, &first).is_err());
    let replay = create_instance(state, "create.1")?;
    assert!(replay.released && replay.receipt.idempotent);
    assert_eq!(replay.handle.key, first.handle.key);
    assert!(
        call(
            state,
            AgentdMethod::RunCancel {
                run_id: replacement.handle.key.run_id.clone(),
                expected_revision: replacement.handle.revision,
                reason: "legacy".into()
            }
        )
        .await
        .is_err()
    );
    assert!(
        call(
            state,
            AgentdMethod::RunStart {
                snapshot: snapshot(state)
            }
        )
        .await
        .is_err()
    );
    let (_, current) = state.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunStatus {
            run_id: replacement.handle.key.run_id.clone(),
        },
        InstanceCommand::Reconcile(replacement.handle.key.clone()),
    )?;
    assert_eq!(current, replacement);
    Ok(())
}

#[test]
fn actual_state_same_fleet_reopen_rotates_owner_activation() -> anyhow::Result<()> {
    let mut fixture = Fixture::using(construct_instance)?;
    let first = create_instance(fixture.state()?, "create.1")?;
    fixture.recompose_same_activation()?; // Same Fleet activation, new coordinator activation.
    let state = fixture.state()?;
    assert!(cancel_instance(state, &first).is_err());
    let (_, current) = state.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunStatus {
            run_id: first.handle.key.run_id.clone(),
        },
        InstanceCommand::Reconcile(first.handle.key.clone()),
    )?;
    assert_eq!(current.handle.key, first.handle.key);
    assert_eq!(current.receipt, first.receipt);
    assert_eq!(current.handle.activation, first.handle.activation + 1);
    assert_eq!(
        cancel_instance(state, &current)?.receipt.phase,
        RunPhase::Cancelled
    );
    Ok(())
}

#[test]
fn private_identity_entry_keeps_actual_generation_and_admission_gates() -> anyhow::Result<()> {
    let fixture = Fixture::using(construct_instance)?;
    let state = fixture.state()?;
    assert!(
        state
            .instance_control_response(
                /*spawn_generation*/ 99,
                AgentdMethod::RunStart {
                    snapshot: snapshot(state)
                },
                InstanceCommand::Start {
                    creation_operation: "create.1".into()
                }
            )
            .is_err()
    );
    state.mark_fenced();
    assert!(create_instance(state, "create.1").is_err());
    assert!(
        state
            .runs
            .lock()
            .unwrap()
            .run("run.journal.control")
            .is_none()
    );
    Ok(())
}

#[test]
fn actual_state_possible_dispatch_reopens_same_instance_without_send_permission()
-> anyhow::Result<()> {
    let mut fixture = Fixture::using(construct_instance)?;
    let started = create_instance(fixture.state()?, "create.1")?;
    let s = snapshot(fixture.state()?);
    let (_, attached) = fixture.state()?.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunAttachContext {
            expected_revision: started.handle.revision,
            attachment: crate::AgentContextAttachment {
                run_id: s.run_id,
                request_digest: s.request_digest,
                objective_digest: s.objective_digest,
                body_digest: s.body_digest,
                artifact_set_digest: s.artifact_set_digest,
                authority_epoch: s.authority_epoch,
                generation: s.generation,
                fence_digest: s.fence_digest,
                deadline_ms: s.deadline_ms,
                context_digest: "5".repeat(64),
                compilation_receipt_digest: "6".repeat(64),
            },
        },
        InstanceCommand::Mutate(started.handle),
    )?;
    let (_, dispatched) = fixture.state()?.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunMarkDispatched {
            run_id: attached.handle.key.run_id.clone(),
            expected_revision: attached.handle.revision,
        },
        InstanceCommand::Mutate(attached.handle),
    )?;
    fixture.recompose_same_activation()?;
    let state = fixture.state()?;
    let (_, current) = state.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunStatus {
            run_id: dispatched.handle.key.run_id.clone(),
        },
        InstanceCommand::Reconcile(dispatched.handle.key.clone()),
    )?;
    assert_eq!(current.handle.key, dispatched.handle.key);
    assert_eq!(current.receipt.phase, RunPhase::Indeterminate);
    assert_eq!(current.handle.revision, dispatched.handle.revision + 1);
    assert!(
        state
            .instance_control_response(
                /*spawn_generation*/ 1,
                AgentdMethod::RunMarkDispatched {
                    run_id: current.handle.key.run_id.clone(),
                    expected_revision: current.handle.revision
                },
                InstanceCommand::Mutate(current.handle)
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn actual_create_replay_needs_explicit_current_activation_reconciliation() -> anyhow::Result<()> {
    let mut fixture = Fixture::using(construct_instance)?;
    let first = create_instance(fixture.state()?, "create.1")?;
    fixture.recompose_same_activation()?;
    let state = fixture.state()?;
    let replay = create_instance(state, "create.1")?;
    assert!(replay.receipt.idempotent);
    assert_eq!(replay.handle.key, first.handle.key);
    assert_eq!(replay.handle.activation, first.handle.activation);
    assert!(cancel_instance(state, &replay).is_err());
    let (_, current) = state.instance_control_response(
        /*spawn_generation*/ 1,
        AgentdMethod::RunStatus {
            run_id: replay.handle.key.run_id.clone(),
        },
        InstanceCommand::Reconcile(replay.handle.key),
    )?;
    assert_eq!(current.handle.activation, replay.handle.activation + 1);
    assert_eq!(current.receipt.phase, replay.receipt.phase);
    assert_eq!(
        cancel_instance(state, &current)?.receipt.phase,
        RunPhase::Cancelled
    );
    Ok(())
}
