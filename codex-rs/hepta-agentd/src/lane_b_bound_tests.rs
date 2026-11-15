use super::*;

use crate::ContextAttachment;
use crate::RuntimeComposition;
use pretty_assertions::assert_eq;

#[test]
fn reused_run_ids_cannot_redirect_bound_mutations_or_idempotent_acknowledgements() {
    for phase in [
        RunPhase::ContextAttached,
        RunPhase::Dispatched,
        RunPhase::Cancelling,
        RunPhase::Indeterminate,
        RunPhase::Succeeded,
    ] {
        for field in 0..6 {
            let mut runs = AgentRunCoordinator::compose_runtime(RuntimeComposition {
                agent_id: "agent.bound".to_string(),
                supervisor_generation: 1,
                agentd_generation: 1,
                configuration_digest: "1".repeat(64),
                ports_digest: "2".repeat(64),
                max_active_runs: 1,
            })
            .unwrap();
            let original = RunSnapshot {
                run_id: "reused.run".to_string(),
                request_digest: "3".repeat(64),
                objective_digest: "4".repeat(64),
                body_digest: "5".repeat(64),
                artifact_set_digest: "6".repeat(64),
                authority_epoch: 9,
                generation: 1,
                fence_digest: "7".repeat(64),
                deadline_ms: 10_000,
            };
            let context = "a".repeat(64);
            let envelope = "b".repeat(64);
            let old = admit_at_phase(&mut runs, &original, &context, &envelope, phase);
            let closed = if old.terminal_observed {
                old.clone()
            } else if old.phase == RunPhase::ContextAttached {
                runs.cancel_run(/*now_ms*/ 400, &old.run_id, old.revision, "operator")
                    .unwrap()
                    .1
            } else {
                runs.observe_terminal(
                    &old.run_id,
                    old.revision,
                    RunPhase::Succeeded,
                    /*terminal_observed*/ true,
                )
                .unwrap()
            };
            runs.remove_closed_run(&closed.run_id, closed.revision)
                .unwrap();

            let mut replacement = original.clone();
            let mut replacement_context = context.clone();
            let mut replacement_envelope = envelope.clone();
            match field {
                0 => replacement.request_digest = "c".repeat(64),
                1 => replacement.objective_digest = "c".repeat(64),
                2 => replacement.body_digest = "c".repeat(64),
                3 => replacement.artifact_set_digest = "c".repeat(64),
                4 => replacement_context = "c".repeat(64),
                _ => replacement_envelope = "c".repeat(64),
            }
            let new = admit_at_phase(
                &mut runs,
                &replacement,
                &replacement_context,
                &replacement_envelope,
                phase,
            );
            assert_eq!(new.revision, old.revision);
            if field < 4 {
                // The old RunStatus response cannot distinguish these two runs.
                assert_eq!(new, old);
            }
            let before = runs.run_reconciliation_state(&new.run_id).unwrap();
            let active = runs.active_run_count();
            assert_eq!(
                runs.mark_bound_dispatched(
                    /*now_ms*/ 500,
                    &original,
                    old.revision,
                    &context,
                    &envelope
                ),
                Err(AgentRunError::MixedSnapshot),
            );
            assert_eq!(
                runs.cancel_bound_run(
                    /*now_ms*/ 500,
                    &original,
                    old.revision,
                    &context,
                    &envelope,
                    "operator"
                ),
                Err(AgentRunError::MixedSnapshot),
            );
            for (terminal_phase, terminal_observed) in [
                (RunPhase::Succeeded, true),
                (RunPhase::Indeterminate, false),
            ] {
                assert_eq!(
                    runs.observe_bound_terminal(
                        &original,
                        old.revision,
                        &context,
                        &envelope,
                        terminal_phase,
                        terminal_observed,
                    ),
                    Err(AgentRunError::MixedSnapshot),
                );
            }
            assert_eq!(runs.run_reconciliation_state(&new.run_id), Some(before));
            assert_eq!(runs.active_run_count(), active);
        }
    }
}

#[test]
fn exact_bound_transitions_compare_revision_before_any_idempotent_return() {
    let mut runs = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.bound".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 1,
    })
    .unwrap();
    let snapshot = RunSnapshot {
        run_id: "run.bound".to_string(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 9,
        generation: 1,
        fence_digest: "7".repeat(64),
        deadline_ms: 10_000,
    };
    let context = "a".repeat(64);
    let envelope = "b".repeat(64);
    let attached = admit_at_phase(
        &mut runs,
        &snapshot,
        &context,
        &envelope,
        RunPhase::ContextAttached,
    );
    assert_eq!(
        runs.mark_bound_dispatched(
            snapshot.deadline_ms,
            &snapshot,
            attached.revision,
            &context,
            &envelope
        ),
        Err(AgentRunError::DeadlineElapsed),
    );
    assert_eq!(runs.run(&snapshot.run_id), Some(attached.clone()));
    let dispatched = runs
        .mark_bound_dispatched(
            /*now_ms*/ 300,
            &snapshot,
            attached.revision,
            &context,
            &envelope,
        )
        .unwrap();
    assert_eq!(
        runs.mark_bound_dispatched(
            /*now_ms*/ 300,
            &snapshot,
            attached.revision,
            &context,
            &envelope
        ),
        Err(AgentRunError::StaleRevision),
    );
    // Expiration prevents a new dispatch, but still allows cancellation and
    // publication of an already-observed physical terminal.
    let cancelled = runs
        .cancel_bound_run(
            /*now_ms*/ 11_000,
            &snapshot,
            dispatched.revision,
            &context,
            &envelope,
            "operator",
        )
        .unwrap()
        .1;
    let terminal = runs
        .observe_bound_terminal(
            &snapshot,
            cancelled.revision,
            &context,
            &envelope,
            RunPhase::Cancelled,
            /*terminal_observed*/ true,
        )
        .unwrap();
    assert_eq!(
        runs.observe_bound_terminal(
            &snapshot,
            cancelled.revision,
            &context,
            &envelope,
            RunPhase::Cancelled,
            /*terminal_observed*/ true
        ),
        Err(AgentRunError::StaleRevision),
    );
    assert!(
        runs.observe_bound_terminal(
            &snapshot,
            terminal.revision,
            &context,
            &envelope,
            RunPhase::Cancelled,
            /*terminal_observed*/ true
        )
        .unwrap()
        .idempotent
    );
    assert_eq!(runs.run(&snapshot.run_id), Some(terminal));
}

fn admit_at_phase(
    runs: &mut AgentRunCoordinator,
    snapshot: &RunSnapshot,
    context: &str,
    envelope: &str,
    phase: RunPhase,
) -> RunReceipt {
    let admitted = runs.start_run(/*now_ms*/ 100, snapshot.clone()).unwrap();
    let attached = runs
        .attach_context(
            /*now_ms*/ 200,
            admitted.revision,
            ContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest.clone(),
                objective_digest: snapshot.objective_digest.clone(),
                body_digest: snapshot.body_digest.clone(),
                artifact_set_digest: snapshot.artifact_set_digest.clone(),
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest.clone(),
                deadline_ms: snapshot.deadline_ms,
                context_digest: context.to_string(),
                compilation_receipt_digest: envelope.to_string(),
            },
        )
        .unwrap();
    if phase == RunPhase::ContextAttached {
        return attached;
    }
    let dispatched = runs
        .mark_dispatched(/*now_ms*/ 300, &snapshot.run_id, attached.revision)
        .unwrap();
    match phase {
        RunPhase::Dispatched => dispatched,
        RunPhase::Cancelling => {
            runs.cancel_run(
                /*now_ms*/ 400,
                &snapshot.run_id,
                dispatched.revision,
                "operator",
            )
            .unwrap()
            .1
        }
        RunPhase::Indeterminate => runs
            .observe_terminal(
                &snapshot.run_id,
                dispatched.revision,
                phase,
                /*terminal_observed*/ false,
            )
            .unwrap(),
        RunPhase::Succeeded => runs
            .observe_terminal(
                &snapshot.run_id,
                dispatched.revision,
                phase,
                /*terminal_observed*/ true,
            )
            .unwrap(),
        _ => panic!("unsupported fixture phase"),
    }
}
