//! Per-Agent durable automation queue.
//!
//! This crate stores schedules and leases, then emits a typed request to the
//! owning Agent's normal App Server thread queue. It has no model, tool, or
//! fleet-wide execution authority.

#![forbid(unsafe_code)]

/// Reusable state machine; does not install a second runtime owner.
pub mod effect_executor;

mod model;
mod scheduler;
mod store;
mod taskflow;
mod taskflow_execution_boundary;
#[cfg(feature = "taskflow-structural-qualification")]
mod taskflow_kernel;
#[cfg(feature = "taskflow-structural-qualification")]
mod taskflow_step;

pub use model::AutomationAdmission;
pub use model::AutomationDispatchUncertainty;
pub use model::AutomationError;
pub use model::AutomationLease;
pub use model::AutomationQueueReceipt;
pub use model::AutomationSchedule;
pub use model::AutomationTask;
pub use model::AutomationTaskDraft;
pub use model::AutomationTaskId;
pub use model::AutomationTaskState;
pub use model::AutomationTick;
pub use scheduler::AutomationFuture;
pub use scheduler::AutomationScheduler;
pub use scheduler::AutomationTurnQueue;
pub use store::AutomationStore;
pub use taskflow::TASKFLOW_EXTERNAL_EFFECTS;
pub use taskflow::TASKFLOW_NAMESPACE;
pub use taskflow::TASKFLOW_PRODUCTION_CALLER;
pub use taskflow::TASKFLOW_SCHEDULER_AUTHORITY;
pub use taskflow::TASKFLOW_SCHEMA_VERSION;
pub use taskflow::TaskFlowCommand;
pub use taskflow::TaskFlowCommandResult;
pub use taskflow::TaskFlowCommandStatus;
pub use taskflow::TaskFlowDefinition;
pub use taskflow::TaskFlowDefinitionReceipt;
pub use taskflow::TaskFlowEdgeSpec;
pub use taskflow::TaskFlowError;
pub use taskflow::TaskFlowFence;
pub use taskflow::TaskFlowNodeKind;
pub use taskflow::TaskFlowNodeSpec;
pub use taskflow::TaskFlowReconcileOutcome;
pub use taskflow::TaskFlowRun;
pub use taskflow::TaskFlowRunState;
pub use taskflow::TaskFlowTransition;
pub use taskflow_execution_boundary::LocalTaskFlowBoundaryActionV1;
pub use taskflow_execution_boundary::LocalTaskFlowBoundaryRequestV1;
pub use taskflow_execution_boundary::LocalTaskFlowPredecessorReferenceV1;
pub use taskflow_execution_boundary::LocalTaskFlowTerminalStateV1;
pub use taskflow_execution_boundary::MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES;
pub use taskflow_execution_boundary::MAX_TASKFLOW_BOUNDARY_PREDECESSORS;
pub use taskflow_execution_boundary::TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION;
pub use taskflow_execution_boundary::TaskFlowBoundaryAuthority;
pub use taskflow_execution_boundary::TaskFlowBoundaryError;
pub use taskflow_execution_boundary::TaskFlowBoundaryScope;
pub use taskflow_execution_boundary::TaskFlowBoundaryUnavailableReason;
pub use taskflow_execution_boundary::TaskFlowExecutionUnavailableV1;
pub use taskflow_execution_boundary::assess_local_taskflow_boundary;
pub use taskflow_execution_boundary::assess_local_taskflow_boundary_json;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_EFFECTS;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_PRODUCTION_CALLER;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_QUALIFICATION_ENABLED;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_SCHEDULER_AUTHORITY;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TaskFlowFrontier;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TaskFlowReplayReport;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_kernel::TaskFlowStructuralPreview;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_EFFECTS;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_PRODUCTION_CALLER;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_QUALIFICATION_ENABLED;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_SCHEDULER_AUTHORITY;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TaskFlowStepCommandResult;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TaskFlowStepCommandStatus;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TaskFlowStepObservation;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TaskFlowStepReceipt;
#[cfg(feature = "taskflow-structural-qualification")]
pub use taskflow_step::TaskFlowStepState;

pub const AUTOMATION_SCHEMA_VERSION: u32 = 3;
