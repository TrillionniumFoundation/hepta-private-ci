//! The existing synchronous run-control cut, shared with private qualification.
use super::*;
use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::AgentdMethod;

pub(super) struct RunControlSnapshot {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    fenced: bool,
}
impl RunControlSnapshot {
    pub(super) fn capture(runtime: &super::super::RuntimeState) -> Self {
        Self {
            current_generation: runtime.current_generation,
            lifecycle: runtime.lifecycle,
            app_server_ready: runtime.app_server_ready,
            fenced: runtime.fenced,
        }
    }
}

enum Envelope {
    Legacy,
    #[cfg(all(test, unix))]
    Qualified(InstanceCommand),
}

#[cfg(all(test, unix))]
use crate::lane_b_runtime::instance::InstanceHandle;
#[cfg(all(test, unix))]
use crate::lane_b_runtime::instance::InstanceKey;
#[cfg(all(test, unix))]
use crate::lane_b_runtime::instance::InstanceMutation;
#[cfg(all(test, unix))]
use crate::lane_b_runtime::instance::InstanceReceipt;

#[cfg(all(test, unix))]
pub(crate) enum InstanceCommand {
    Start { creation_operation: String },
    Mutate(InstanceHandle),
    Reconcile(InstanceKey),
}

struct RunResult {
    payload: AgentdPayload,
    #[cfg(all(test, unix))]
    instance: Option<InstanceReceipt>,
}

impl AgentdState {
    pub(super) fn run_control_response(
        &self,
        method: AgentdMethod,
        snapshot: RunControlSnapshot,
    ) -> Result<AgentdPayload, AgentdError> {
        Ok(self
            .run_control_inner(method, snapshot, Envelope::Legacy)?
            .payload)
    }

    #[cfg(all(test, unix))]
    pub(crate) fn instance_control_response(
        &self,
        spawn_generation: u64,
        method: AgentdMethod,
        command: InstanceCommand,
    ) -> Result<(AgentdPayload, InstanceReceipt), AgentdError> {
        if spawn_generation != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "instance control generation mismatch".into(),
            ));
        }
        self.refresh_generation()?;
        let snapshot = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            RunControlSnapshot::capture(&runtime)
        };
        let result = self.run_control_inner(method, snapshot, Envelope::Qualified(command))?;
        Ok((
            result.payload,
            result
                .instance
                .ok_or_else(|| AgentdError::Protocol("missing instance result".into()))?,
        ))
    }

    fn run_control_inner(
        &self,
        method: AgentdMethod,
        snapshot: RunControlSnapshot,
        envelope: Envelope,
    ) -> Result<RunResult, AgentdError> {
        match &method {
            AgentdMethod::RunStart { snapshot: run } => {
                require_run_admission_ready(
                    snapshot.lifecycle,
                    snapshot.app_server_ready,
                    snapshot.fenced,
                )?;
                require_current_run_identity(
                    &self.identity,
                    snapshot.current_generation,
                    run.generation,
                    &run.fence_digest,
                )?;
            }
            AgentdMethod::RunAttachContext { attachment, .. } => {
                require_run_admission_ready(
                    snapshot.lifecycle,
                    snapshot.app_server_ready,
                    snapshot.fenced,
                )?;
                require_current_run_identity(
                    &self.identity,
                    snapshot.current_generation,
                    attachment.generation,
                    &attachment.fence_digest,
                )?;
            }
            AgentdMethod::RunMarkDispatched { .. } => require_run_admission_ready(
                snapshot.lifecycle,
                snapshot.app_server_ready,
                snapshot.fenced,
            )?,
            AgentdMethod::RunCancel { .. }
            | AgentdMethod::RunObserveTerminal { .. }
            | AgentdMethod::RunStatus { .. }
            | AgentdMethod::RunReleaseClosed { .. } => {
                require_run_reconciliation_ready(snapshot.lifecycle, snapshot.fenced)?
            }
            _ => return Err(AgentdError::Protocol("not a run control method".into())),
        }
        let mut owner = self.runs.lock().map_err(poisoned_state)?;
        // Original status/terminal/release need no clock. Preserve that boundary.
        let now = if matches!(
            &method,
            AgentdMethod::RunStart { .. }
                | AgentdMethod::RunAttachContext { .. }
                | AgentdMethod::RunMarkDispatched { .. }
                | AgentdMethod::RunCancel { .. }
        ) {
            now_ms()?
        } else {
            0
        };
        match envelope {
            Envelope::Legacy => Ok(RunResult {
                payload: execute(&mut owner, method, now).map_err(run_error)?,
                #[cfg(all(test, unix))]
                instance: None,
            }),
            #[cfg(all(test, unix))]
            Envelope::Qualified(command) => {
                let (payload, instance) = match (command, method) {
                    (
                        InstanceCommand::Start { creation_operation },
                        AgentdMethod::RunStart { snapshot },
                    ) => {
                        let result = owner
                            .start_instance(
                                now,
                                &creation_operation,
                                internal_run_snapshot(snapshot),
                            )
                            .map_err(run_error)?;
                        (
                            AgentdPayload::RunReceipt(wire_run_receipt(result.receipt.clone())),
                            result,
                        )
                    }
                    (InstanceCommand::Reconcile(key), AgentdMethod::RunStatus { run_id })
                        if key.run_id == run_id =>
                    {
                        let result = owner.reconcile_instance(&key).map_err(run_error)?;
                        (
                            AgentdPayload::RunStatus {
                                run: Some(wire_run_receipt(result.receipt.clone())),
                            },
                            result,
                        )
                    }
                    (InstanceCommand::Mutate(handle), method) => {
                        let (run_id, revision) = mutation_identity(&method).ok_or_else(|| {
                            AgentdError::Protocol("instance mutation method mismatch".into())
                        })?;
                        if run_id != handle.key.run_id || revision != handle.revision {
                            return Err(run_error(AgentRunError::StaleInstance));
                        }
                        if let AgentdMethod::RunCancel { reason, .. } = method {
                            let ((disposition, receipt), bound) = owner
                                .cancel_instance(&handle, now, &reason)
                                .map_err(run_error)?;
                            (
                                AgentdPayload::RunCancellation(crate::AgentRunCancellation {
                                    disposition: wire_cancellation_disposition(disposition),
                                    receipt: wire_run_receipt(receipt),
                                }),
                                bound,
                            )
                        } else {
                            let mutation = match method {
                                AgentdMethod::RunAttachContext { attachment, .. } => {
                                    InstanceMutation::Attach(Box::new(internal_context_attachment(
                                        attachment,
                                    )))
                                }
                                AgentdMethod::RunMarkDispatched { .. } => {
                                    InstanceMutation::Dispatch
                                }
                                AgentdMethod::RunObserveTerminal {
                                    phase,
                                    terminal_observed,
                                    ..
                                } => InstanceMutation::Observe {
                                    phase: internal_run_phase(phase),
                                    terminal_observed,
                                },
                                AgentdMethod::RunReleaseClosed { .. } => InstanceMutation::Release,
                                _ => return Err(run_error(AgentRunError::InvalidTransition)),
                            };
                            let (receipt, bound) = owner
                                .mutate_instance(&handle, now, mutation)
                                .map_err(run_error)?;
                            (AgentdPayload::RunReceipt(wire_run_receipt(receipt)), bound)
                        }
                    }
                    _ => {
                        return Err(AgentdError::Protocol(
                            "instance command/method mismatch".into(),
                        ));
                    }
                };
                Ok(RunResult {
                    payload,
                    instance: Some(instance),
                })
            }
        }
    }
}

#[cfg(all(test, unix))]
fn mutation_identity(method: &AgentdMethod) -> Option<(&str, u64)> {
    match method {
        AgentdMethod::RunAttachContext {
            expected_revision,
            attachment,
        } => Some((&attachment.run_id, *expected_revision)),
        AgentdMethod::RunMarkDispatched {
            run_id,
            expected_revision,
        }
        | AgentdMethod::RunCancel {
            run_id,
            expected_revision,
            ..
        }
        | AgentdMethod::RunObserveTerminal {
            run_id,
            expected_revision,
            ..
        }
        | AgentdMethod::RunReleaseClosed {
            run_id,
            expected_revision,
        } => Some((run_id, *expected_revision)),
        _ => None,
    }
}

fn execute(
    owner: &mut AgentRunCoordinator,
    method: AgentdMethod,
    now: u64,
) -> Result<AgentdPayload, AgentRunError> {
    Ok(match method {
        AgentdMethod::RunStart { snapshot } => AgentdPayload::RunReceipt(wire_run_receipt(
            owner.start_run(now, internal_run_snapshot(snapshot))?,
        )),
        AgentdMethod::RunAttachContext {
            expected_revision,
            attachment,
        } => AgentdPayload::RunReceipt(wire_run_receipt(owner.attach_context(
            now,
            expected_revision,
            internal_context_attachment(attachment),
        )?)),
        AgentdMethod::RunMarkDispatched {
            run_id,
            expected_revision,
        } => AgentdPayload::RunReceipt(wire_run_receipt(owner.mark_dispatched(
            now,
            &run_id,
            expected_revision,
        )?)),
        AgentdMethod::RunCancel {
            run_id,
            expected_revision,
            reason,
        } => {
            let (disposition, receipt) =
                owner.cancel_run(now, &run_id, expected_revision, &reason)?;
            AgentdPayload::RunCancellation(crate::AgentRunCancellation {
                disposition: wire_cancellation_disposition(disposition),
                receipt: wire_run_receipt(receipt),
            })
        }
        AgentdMethod::RunObserveTerminal {
            run_id,
            expected_revision,
            phase,
            terminal_observed,
        } => AgentdPayload::RunReceipt(wire_run_receipt(owner.observe_terminal(
            &run_id,
            expected_revision,
            internal_run_phase(phase),
            terminal_observed,
        )?)),
        AgentdMethod::RunStatus { run_id } => AgentdPayload::RunStatus {
            run: owner.run(&run_id).map(wire_run_receipt),
        },
        AgentdMethod::RunReleaseClosed {
            run_id,
            expected_revision,
        } => AgentdPayload::RunReceipt(wire_run_receipt(
            owner.remove_closed_run(&run_id, expected_revision)?,
        )),
        _ => return Err(AgentRunError::InvalidTransition),
    })
}
