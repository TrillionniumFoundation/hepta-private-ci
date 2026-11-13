//! A single late handoff joins the existing delivery actor, never another loop.

use std::os::unix::net::UnixDatagram;
use std::time::Instant;
use codex_arg0::Arg0DispatchPaths;
use crate::{AgentdConfig, AgentdError};

pub(super) struct PendingResidentEnrollment {
    pub(super) socket: UnixDatagram,
    pub(super) end: Instant,
}

pub(super) async fn run_original(
    config: AgentdConfig,
    arg0_paths: Arg0DispatchPaths,
    pending: PendingResidentEnrollment,
) -> Result<(), AgentdError> {
    let identity = config.identity().clone();
    // The old exclusive Config guard still requires the actual Circuit
    // bootstrap/invocation, Objective profile and AuthBus trust before opt-in.
    let (config, enrollment) = config.with_root_resident_learning_enrollment()?;
    let original = crate::run(config, arg0_paths);
    tokio::pin!(original);
    let receive = crate::root_production_handoff::receive_original_resident_enrollment(
        pending.socket, &identity, pending.end,
    );
    tokio::pin!(receive);
    let root = tokio::select! {
        result = &mut original => return result,
        result = &mut receive => result,
    };
    let joined = match root {
        Err(error) => Err(error),
        Ok(root) => {
            // This ACK confirms only the original local outbox/source join.
            // Root's actual Admit remains solely in the original delivery code.
            let join = crate::AgentdRootResidentEnrollmentV3::enroll_original_root(&enrollment, root);
            tokio::pin!(join);
            tokio::select! {
                result = &mut original => {
                    result?;
                    return Err(AgentdError::Protocol(
                        "resident local enrollment ACK unknown at daemon shutdown".into(),
                    ));
                }
                result = &mut join => result.map_err(|error| AgentdError::Protocol(error.to_string())),
            }
        }
    };
    if let Err(error) = &joined {
        tracing::error!(error = %error, "original resident enrollment refused; no retry or replacement claim");
    }
    // Never drop the ordinary daemon future to hide an enrollment failure.
    // Its existing cancellation, worker cleanup and writer shutdown must finish.
    original.await?;
    joined
}
