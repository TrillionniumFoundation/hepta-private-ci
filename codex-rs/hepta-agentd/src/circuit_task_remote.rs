//! Fixed Root Cell/Source lanes for the original daemon task driver. The
//! daemon keeps its only AutomationStore, RunStart ingress and opaque receipts.

use super::CircuitTaskErrorV1 as Error;

#[path = "circuit_task_remote_wire.rs"]
mod wire;
#[path = "circuit_task_remote_data.rs"]
mod data;
#[path = "circuit_task_remote_admission.rs"]
mod admission;
#[path = "circuit_task_remote_loan.rs"]
mod loan;
#[path = "circuit_task_remote_client.rs"]
mod client;
#[path = "circuit_task_remote_invocation.rs"]
mod invocation;
#[path = "circuit_task_remote_service.rs"]
mod service;

pub(crate) use admission::OriginalRemoteAdmission;
pub(crate) use admission::OriginalRemoteCompletion;
pub(crate) use client::DaemonCellPort;
pub(crate) use client::DaemonClient;
pub use client::OriginalRootCircuitTaskDaemonInputsV1;
pub(crate) use loan::OriginalRecordLoan;
pub(crate) use service::OriginalRootTaskStreams;
pub(crate) use service::OriginalRootTaskLane;
pub(crate) use service::serve;
