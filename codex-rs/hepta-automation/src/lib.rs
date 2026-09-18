//! Per-Agent durable automation queue and TaskFlow lifecycle.
//!
//! The timer scheduler owns wake-up/materialization. Durable occurrence and
//! TaskFlow records keep Core queue admission separate from terminal execution;
//! downstream effects still require their owning final-use authority and
//! terminal observer.

#![forbid(unsafe_code)]

/// Reusable reference state machine; does not install a second runtime owner.
pub mod effect_executor;

mod authorized_effect;
mod automation_taskflow;
mod dispatch_recovery;
mod lifecycle;
mod model;
mod scheduler;
mod store;
mod taskflow;
mod taskflow_execution_boundary;
#[cfg(feature = "taskflow-structural-qualification")]
mod taskflow_kernel;
mod taskflow_recovery;
mod taskflow_step;

pub use authorized_effect::AuthorizedEffectDriver;
pub use authorized_effect::AuthorizedEffectDriverError;
pub use authorized_effect::AuthorizedEffectError;
pub use authorized_effect::AuthorizedEffectOutcome;
pub use authorized_effect::AuthorizedEffectProviderReceipt;
pub use authorized_effect::AuthorizedEffectRequest;
pub use automation_taskflow::AutomationTaskFlowDispatch;
pub use automation_taskflow::admission_receipt_digest;
pub use lifecycle::AutomationMissedRunPolicy;
pub use lifecycle::AutomationOccurrence;
pub use lifecycle::AutomationOccurrenceState;
pub use lifecycle::AutomationOccurrenceTerminalState;
pub use lifecycle::AutomationOccurrenceWork;
pub use lifecycle::AutomationOverlapPolicy;
pub use lifecycle::AutomationSchedulePolicy;
pub use lifecycle::deterministic_occurrence_id;
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
pub use taskflow::TASKFLOW_COMPOSED_CALLER;
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
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_COMPOSED_CALLER;
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_DURABLE_SCHEMA_ENABLED;
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_EFFECTS;
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_PRODUCTION_CALLER;
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_QUALIFICATION_ENABLED;
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_SCHEDULER_AUTHORITY;
pub use taskflow_step::TaskFlowStepCommandResult;
pub use taskflow_step::TaskFlowStepCommandStatus;
pub use taskflow_step::TaskFlowStepObservation;
pub use taskflow_step::TaskFlowStepReceipt;
pub use taskflow_step::TaskFlowStepState;

pub const AUTOMATION_SCHEMA_VERSION: u32 = 9;
