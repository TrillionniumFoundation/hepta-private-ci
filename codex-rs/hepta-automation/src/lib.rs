//! Per-Agent durable automation queue and TaskFlow lifecycle.
//!
//! The timer scheduler owns wake-up/materialization. Durable occurrence and
//! TaskFlow records keep Core queue admission separate from terminal execution;
//! downstream effects still require their owning final-use authority and
//! terminal observer.

#![forbid(unsafe_code)]

/// Legacy reference reducer retained only for focused unit tests. Product
/// execution uses the durable TaskFlow ledger/outbox and authorized effect seam.
#[cfg(all(test, feature = "runtime"))]
#[cfg(feature = "runtime")]
mod effect_executor;

#[cfg(feature = "runtime")]
mod authorized_effect;
#[cfg(feature = "runtime")]
mod automation_taskflow;
#[cfg(feature = "runtime")]
mod dispatch_recovery;
#[cfg(feature = "runtime")]
mod effect_dispatch_ledger;
#[cfg(feature = "runtime")]
mod lifecycle;
mod model;
#[cfg(feature = "runtime")]
mod neural_circuit;
#[cfg(feature = "runtime")]
mod operation_destination;
#[cfg(feature = "runtime")]
mod schedule_v2;
#[cfg(feature = "runtime")]
mod scheduler;
mod scheduler_admission;
#[cfg(feature = "runtime")]
mod store;
#[cfg(feature = "runtime")]
mod taskflow;
#[cfg(feature = "runtime")]
mod taskflow_execution_boundary;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
mod taskflow_kernel;
#[cfg(feature = "runtime")]
mod taskflow_recovery;
#[cfg(feature = "runtime")]
mod taskflow_step;
#[cfg(feature = "runtime")]
mod timer_lifecycle;
#[cfg(feature = "runtime")]
mod timer_retirement;
mod wire;

#[cfg(feature = "runtime")]
pub use authorized_effect::AsyncAuthorizedEffectDriver;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectDriver;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectDriverError;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectError;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectFuture;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectOutcome;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectPending;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectProviderReceipt;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectRecovery;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectRecoveryResult;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedEffectRequest;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedProviderEffectLookup;
#[cfg(feature = "runtime")]
pub use authorized_effect::AuthorizedProviderEffectRequest;
#[cfg(feature = "runtime")]
pub use authorized_effect::ProviderEffectTaskFlowDriver;
#[cfg(feature = "runtime")]
pub use automation_taskflow::AutomationTaskFlowDispatch;
#[cfg(feature = "runtime")]
pub use automation_taskflow::admission_receipt_digest;
#[cfg(feature = "runtime")]
pub use lifecycle::AutomationOccurrence;
#[cfg(feature = "runtime")]
pub use lifecycle::AutomationOccurrenceState;
#[cfg(feature = "runtime")]
pub use lifecycle::AutomationOccurrenceTerminalState;
#[cfg(feature = "runtime")]
pub use lifecycle::AutomationOccurrenceWork;
#[cfg(feature = "runtime")]
pub use lifecycle::AutomationSchedulePolicy;
#[cfg(feature = "runtime")]
pub use lifecycle::deterministic_occurrence_id;
pub use model::AutomationAdmission;
pub use model::AutomationDispatchUncertainty;
pub use model::AutomationError;
pub use model::AutomationLease;
pub use model::AutomationQueueReceipt;
pub use model::AutomationSchedule;
pub use model::AutomationTask;
pub use model::AutomationTaskCursorV1;
pub use model::AutomationTaskDraft;
pub use model::AutomationTaskId;
pub use model::AutomationTaskPageV1;
pub use model::AutomationTaskState;
pub use model::AutomationTick;
#[cfg(feature = "runtime")]
pub use neural_circuit::CircuitCompilationReceiptV1;
#[cfg(feature = "runtime")]
pub use neural_circuit::CircuitEdgeV1;
#[cfg(feature = "runtime")]
pub use neural_circuit::CircuitNodeRoleV1;
#[cfg(feature = "runtime")]
pub use neural_circuit::CircuitNodeV1;
#[cfg(feature = "runtime")]
pub use neural_circuit::NEURAL_CIRCUIT_SCHEMA_VERSION;
#[cfg(feature = "runtime")]
pub use neural_circuit::NeuralCircuitCandidateV1;
#[cfg(feature = "runtime")]
pub use neural_circuit::validate_circuit_successor_v1;
#[cfg(feature = "runtime")]
pub use operation_destination::AUTOMATION_OPERATION_DESTINATION;
#[cfg(feature = "runtime")]
pub use operation_destination::AutomationOperationReceipt;
#[cfg(feature = "runtime")]
pub use operation_destination::automation_task_operation_intent;
#[cfg(feature = "runtime")]
pub use operation_destination::automation_task_payload_digest;
#[cfg(feature = "runtime")]
pub use scheduler::AutomationFuture;
#[cfg(feature = "runtime")]
pub use scheduler::AutomationScheduler;
#[cfg(feature = "runtime")]
pub use scheduler::AutomationTurnQueue;
#[cfg(feature = "runtime")]
pub use store::AutomationStore;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_COMPOSED_CALLER;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_EXTERNAL_EFFECTS;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_NAMESPACE;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_PRODUCTION_CALLER;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_SCHEDULER_AUTHORITY;
#[cfg(feature = "runtime")]
pub use taskflow::TASKFLOW_SCHEMA_VERSION;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowCommand;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowCommandResult;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowCommandStatus;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowDefinition;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowDefinitionReceipt;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowEdgeSpec;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowError;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowFence;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowNodeKind;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowNodeSpec;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowReconcileOutcome;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowRun;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowRunState;
#[cfg(feature = "runtime")]
pub use taskflow::TaskFlowTransition;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::LocalTaskFlowBoundaryActionV1;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::LocalTaskFlowBoundaryRequestV1;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::LocalTaskFlowPredecessorReferenceV1;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::LocalTaskFlowTerminalStateV1;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::MAX_TASKFLOW_BOUNDARY_PREDECESSORS;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TaskFlowBoundaryAuthority;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TaskFlowBoundaryError;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TaskFlowBoundaryScope;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TaskFlowBoundaryUnavailableReason;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::TaskFlowExecutionUnavailableV1;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::assess_local_taskflow_boundary;
#[cfg(feature = "runtime")]
pub use taskflow_execution_boundary::assess_local_taskflow_boundary_json;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_EFFECTS;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_PRODUCTION_CALLER;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_QUALIFICATION_ENABLED;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TASKFLOW_STRUCTURAL_SCHEDULER_AUTHORITY;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TaskFlowFrontier;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TaskFlowReplayReport;
#[cfg(feature = "taskflow-structural-qualification")]
#[cfg(feature = "runtime")]
pub use taskflow_kernel::TaskFlowStructuralPreview;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_COMPOSED_CALLER;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_DURABLE_SCHEMA_ENABLED;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_EFFECTS;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_PRODUCTION_CALLER;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_QUALIFICATION_ENABLED;
#[cfg(feature = "runtime")]
pub use taskflow_step::TASKFLOW_STEP_OUTBOX_SCHEDULER_AUTHORITY;
#[cfg(feature = "runtime")]
pub use taskflow_step::TaskFlowStepCommandResult;
#[cfg(feature = "runtime")]
pub use taskflow_step::TaskFlowStepCommandStatus;
#[cfg(feature = "runtime")]
pub use taskflow_step::TaskFlowStepObservation;
#[cfg(feature = "runtime")]
pub use taskflow_step::TaskFlowStepReceipt;
#[cfg(feature = "runtime")]
pub use taskflow_step::TaskFlowStepState;
#[cfg(feature = "runtime")]
pub use timer_lifecycle::TimerDrainStatus;
#[cfg(feature = "runtime")]
pub use timer_lifecycle::TimerPhase;
pub use wire::AuthorizedEffectDependency;
pub use wire::AuthorizedEffectIntent;
pub use wire::AutomationCalendarScheduleV2;
pub use wire::AutomationDstGapPolicy;
pub use wire::AutomationDstOverlapPolicy;
pub use wire::AutomationMissedRunPolicy;
pub use wire::AutomationOverlapPolicy;
pub use wire::AutomationTimeZoneProfileV1;
pub use wire::AutomationTimezoneTransitionV1;

pub const AUTOMATION_SCHEMA_VERSION: u32 = 20;
