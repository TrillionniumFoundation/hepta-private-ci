//! Per-Agent durable automation queue and TaskFlow lifecycle.
//!
//! The timer scheduler owns wake-up/materialization. Durable occurrence and
//! TaskFlow records keep Core queue admission separate from terminal execution;
//! downstream effects still require their owning final-use authority and
//! terminal observer.

#![forbid(unsafe_code)]

/// Legacy reference reducer retained only for focused unit tests. Product
/// execution uses the durable TaskFlow ledger/outbox and authorized effect seam.
#[cfg(test)]
mod effect_executor;

mod authorized_effect;
mod automation_taskflow;
mod circuit_admission;
mod circuit_budget;
mod circuit_compute;
mod circuit_history;
mod circuit_join;
mod circuit_journal;
mod circuit_profile;
mod circuit_progress;
mod circuit_runtime;
mod circuit_state;
mod circuit_store;
mod dispatch_recovery;
mod effect_dispatch_ledger;
mod hcsn_job;
mod hcsn_supervisor;
mod hcsn_taskflow;
mod lifecycle;
mod model;
mod neural_circuit;
mod operation_destination;
mod schedule_v2;
mod scheduler;
mod store;
mod taskflow;
mod taskflow_execution_boundary;
#[cfg(feature = "taskflow-structural-qualification")]
mod taskflow_kernel;
mod taskflow_recovery;
mod taskflow_step;
mod timer_lifecycle;

pub use authorized_effect::AsyncAuthorizedEffectDriver;
pub use authorized_effect::AuthorizedEffectDependency;
pub use authorized_effect::AuthorizedEffectDispatchRequest;
pub use authorized_effect::AuthorizedEffectDriver;
pub use authorized_effect::AuthorizedEffectDriverError;
pub use authorized_effect::AuthorizedEffectError;
pub use authorized_effect::AuthorizedEffectFuture;
pub use authorized_effect::AuthorizedEffectIntent;
pub use authorized_effect::AuthorizedEffectOutcome;
pub use authorized_effect::AuthorizedEffectPending;
pub use authorized_effect::AuthorizedEffectProviderReceipt;
pub use authorized_effect::AuthorizedEffectRecovery;
pub use authorized_effect::AuthorizedEffectRecoveryResult;
pub use authorized_effect::AuthorizedEffectRequest;
pub use authorized_effect::AuthorizedProviderEffectLookup;
pub use authorized_effect::AuthorizedProviderEffectRequest;
pub use authorized_effect::ProviderEffectTaskFlowDriver;
pub use automation_taskflow::AutomationTaskFlowDispatch;
pub use automation_taskflow::admission_receipt_digest;
pub use circuit_admission::CircuitComputationAdmissionV2;
pub use circuit_admission::CircuitComputationClaimV2;
pub use circuit_budget::CircuitBudgetV2;
pub use circuit_history::CircuitLeaseClaimV2;
pub use circuit_join::CircuitJoinEnvelopeV2;
pub use circuit_join::circuit_join_output_schema_v2;
pub use circuit_profile::BoundedCircuitDefinitionV2;
pub use circuit_profile::CircuitEdgeV2;
pub use circuit_profile::CircuitExitV2;
pub use circuit_profile::CircuitJoinV2;
pub use circuit_profile::CircuitLimitsV2;
pub use circuit_profile::CircuitNodeKindV2;
pub use circuit_profile::CircuitNodeV2;
pub use circuit_profile::CircuitProfileV2;
pub use circuit_profile::CircuitProgramV2;
pub use circuit_state::CircuitActivationStatusV2;
pub use circuit_state::CircuitActivationV2;
pub use circuit_state::CircuitCommandReceiptV2;
pub use circuit_state::CircuitCommandStatusV2;
pub use circuit_state::CircuitCommandV2;
pub use circuit_state::CircuitCompletionV2;
pub use circuit_state::CircuitDispatchV2;
pub use circuit_state::CircuitEventV2;
pub use circuit_state::CircuitRunV2;
pub use circuit_state::CircuitStartV2;
pub use circuit_state::CircuitStopReasonV2;
pub use hcsn_job::HCSN_MAX_TRAINING_PAYLOAD_BYTES;
pub use hcsn_job::HCSN_SUPERVISOR_SCHEMA_VERSION;
pub use hcsn_job::HcsnJobEvidenceV1;
pub use hcsn_job::HcsnJobIdentityV1;
pub use hcsn_job::HcsnJobObservationV1;
pub use hcsn_job::HcsnJobStateV1;
pub use hcsn_job::HcsnProcessIdentityV1;
pub use hcsn_job::HcsnSupervisor;
pub use hcsn_job::HcsnSupervisorActionV1;
pub use hcsn_job::HcsnSupervisorCommandV1;
pub use hcsn_job::HcsnSupervisorError;
pub use hcsn_supervisor::HcsnProcessSupervisor;
pub use hcsn_supervisor::HcsnProcessSupervisorConfig;
pub use hcsn_taskflow::HcsnTaskFlowActionV1;
pub use hcsn_taskflow::HcsnTaskFlowDriver;
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
pub use neural_circuit::CircuitCompilationReceiptV1;
pub use neural_circuit::CircuitEdgeV1;
pub use neural_circuit::CircuitNodeRoleV1;
pub use neural_circuit::CircuitNodeV1;
pub use neural_circuit::CircuitProgramV1;
pub use neural_circuit::NEURAL_CIRCUIT_SCHEMA_VERSION;
pub use neural_circuit::NeuralCircuitCandidateV1;
pub use neural_circuit::validate_circuit_successor_v1;
pub use operation_destination::AUTOMATION_OPERATION_DESTINATION;
pub use operation_destination::AutomationOperationReceipt;
pub use operation_destination::automation_task_operation_intent;
pub use operation_destination::automation_task_payload_digest;
pub use schedule_v2::AutomationCalendarScheduleV2;
pub use schedule_v2::AutomationDstGapPolicy;
pub use schedule_v2::AutomationDstOverlapPolicy;
pub use schedule_v2::AutomationTimeZoneProfileV1;
pub use schedule_v2::AutomationTimezoneTransitionV1;
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
pub use timer_lifecycle::TimerDrainStatus;
pub use timer_lifecycle::TimerPhase;

pub const AUTOMATION_SCHEMA_VERSION: u32 = 20;

#[cfg(test)]
#[path = "circuit_runtime_tests.rs"]
mod circuit_runtime_tests;

#[cfg(test)]
#[path = "circuit_store_tests.rs"]
mod circuit_store_tests;
