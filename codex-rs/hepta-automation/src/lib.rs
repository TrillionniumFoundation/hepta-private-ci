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
mod cross_host_controller;
mod cross_host_recovery;
mod dispatch_recovery;
#[allow(
    dead_code,
    reason = "immutable activation-intent fields remain persisted recovery evidence"
)]
mod durable_neural_circuit;
mod durable_neural_circuit_recovery;
mod effect_dispatch_ledger;
mod external_host_fence;
#[path = "lifecycle_bounded.rs"]
mod lifecycle;
mod model;
mod neural_circuit;
mod neural_circuit_runtime;
mod operation_destination;
mod recovery_sweeps;
mod runtime_metrics;
mod runtime_policy;
mod schedule_v2;
mod scheduler;
mod store;
#[path = "taskflow_bounded.rs"]
mod taskflow;
mod taskflow_execution_boundary;
#[cfg(feature = "taskflow-structural-qualification")]
mod taskflow_kernel;
mod taskflow_recovery;
mod taskflow_step;
mod timer_lifecycle;

pub use authorized_effect::AsyncAuthorizedEffectDriver;
pub use authorized_effect::AuthorizedEffectDependency;
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
pub use cross_host_recovery::AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION;
pub use cross_host_recovery::AutomationCrossHostRecoveryManifestV1;
pub use durable_neural_circuit::CircuitRuntimeRecoveredOutcomeV1;
pub use durable_neural_circuit::CircuitRuntimeRecoveryObserverV1;
pub use durable_neural_circuit::CircuitRuntimeRecoveryRequestV1;
pub use durable_neural_circuit::DurableCircuitCommitStatusV1;
pub use durable_neural_circuit::DurableCircuitExecutionReceiptV1;
pub use durable_neural_circuit::DurableCircuitRunStateV1;
pub use durable_neural_circuit::DurableCircuitSnapshotV1;
pub use durable_neural_circuit::DurableNeuralCircuitError;
pub use external_host_fence::AUTOMATION_HOST_FENCE_SCHEMA_VERSION;
pub use external_host_fence::AutomationHostFenceClaimsV1;
pub use external_host_fence::AutomationHostFenceTrustV1;
pub use external_host_fence::SignedAutomationHostFenceV1;
pub use external_host_fence::VerifiedAutomationHostFenceV1;
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
pub use neural_circuit::NEURAL_CIRCUIT_SCHEMA_VERSION;
pub use neural_circuit::NeuralCircuitCandidateV1;
pub use neural_circuit::validate_circuit_successor_v1;
pub use neural_circuit_runtime::CircuitCancellationV1;
pub use neural_circuit_runtime::CircuitChoiceKindV1;
pub use neural_circuit_runtime::CircuitDecisionCellV1;
pub use neural_circuit_runtime::CircuitDecisionRequestV1;
pub use neural_circuit_runtime::CircuitDecisionV1;
pub use neural_circuit_runtime::CircuitEffectBoundaryV1;
pub use neural_circuit_runtime::CircuitEffectResolutionStateV1;
pub use neural_circuit_runtime::CircuitEffectResolutionV1;
pub use neural_circuit_runtime::CircuitEventIngressV1;
pub use neural_circuit_runtime::CircuitOrganPortV1;
pub use neural_circuit_runtime::CircuitOrganReceiptV1;
pub use neural_circuit_runtime::CircuitOrganRequestV1;
pub use neural_circuit_runtime::CircuitRecordedChoiceV1;
pub use neural_circuit_runtime::CircuitRuntimeCheckpointV1;
pub use neural_circuit_runtime::CircuitRuntimeOutcomeV1;
pub use neural_circuit_runtime::CircuitRuntimeProfileV1;
pub use neural_circuit_runtime::CircuitRuntimeTraceV1;
pub use neural_circuit_runtime::CircuitTerminalReceiptV1;
pub use neural_circuit_runtime::CircuitTerminalStateV1;
pub use neural_circuit_runtime::CircuitWaitBoundaryV1;
pub use neural_circuit_runtime::CircuitWaitJoinPortV1;
pub use neural_circuit_runtime::CircuitWaitReceiptV1;
pub use neural_circuit_runtime::CircuitWaitRequestV1;
pub use neural_circuit_runtime::CircuitWaitStateV1;
pub use neural_circuit_runtime::NEURAL_CIRCUIT_RUNTIME_SCHEMA_VERSION;
pub use neural_circuit_runtime::NeuralCircuitRuntimeError;
pub use neural_circuit_runtime::NeverCancelled;
pub use neural_circuit_runtime::checkpoint_for_circuit_outcome_v1;
pub use neural_circuit_runtime::circuit_runtime_outcome_digest_v1;
pub use neural_circuit_runtime::resume_neural_circuit_after_effect_v1;
pub use neural_circuit_runtime::resume_neural_circuit_v1;
pub use neural_circuit_runtime::run_neural_circuit_v1;
pub use neural_circuit_runtime::runtime_profile_digest_v1;
pub use neural_circuit_runtime::validate_circuit_runtime_outcome_v1;
pub use operation_destination::AUTOMATION_OPERATION_DESTINATION;
pub use operation_destination::AutomationOperationReceipt;
pub use operation_destination::automation_task_operation_intent;
pub use operation_destination::automation_task_payload_digest;
pub use recovery_sweeps::AutomationRecoverySelection;
pub use runtime_metrics::AUTOMATION_CIRCUIT_RECOVERY_REQUIRED_TOTAL;
pub use runtime_metrics::AUTOMATION_CIRCUIT_RESERVED_COST_UNITS;
pub use runtime_metrics::AUTOMATION_CIRCUIT_RESUME_LATENCY_SECONDS;
pub use runtime_metrics::AUTOMATION_DESTINATION_DEDUPE_CONFLICT_TOTAL;
pub use runtime_metrics::AUTOMATION_OCCURRENCE_PARKED_SECONDS;
pub use runtime_metrics::AUTOMATION_RECOVERY_BUDGET_SATURATION_TOTAL;
pub use runtime_metrics::AUTOMATION_RECOVERY_SWEEP_LAG;
pub use runtime_metrics::AUTOMATION_TIMER_DRAIN_BLOCKED_TOTAL;
pub use runtime_metrics::AUTOMATION_TIMER_WRITER_EPOCH;
pub use runtime_metrics::AUTOMATION_UNKNOWN_EFFECT_AGE_SECONDS;
pub use runtime_metrics::AutomationRuntimeMetricsV1;
pub use runtime_metrics::record_automation_circuit_recovery_required;
pub use runtime_metrics::record_automation_destination_dedupe_conflict;
pub use runtime_metrics::record_automation_recovery_budget_saturation;
pub use runtime_metrics::record_automation_timer_drain_blocked;
pub use runtime_policy::AUTOMATION_RUNTIME_POLICY_SCHEMA_VERSION;
pub use runtime_policy::AutomationFailureDisposition;
pub use runtime_policy::AutomationRuntimePolicyV1;
pub use runtime_policy::AutomationRuntimeSloV1;
pub use runtime_policy::classify_automation_error;
pub use schedule_v2::AutomationCalendarScheduleV2;
pub use schedule_v2::AutomationDstGapPolicy;
pub use schedule_v2::AutomationDstOverlapPolicy;
pub use schedule_v2::AutomationTimeZoneProfileV1;
pub use schedule_v2::AutomationTimezoneTransitionV1;
pub use scheduler::AutomationBatchReport;
pub use scheduler::AutomationBatchStopReason;
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

pub const AUTOMATION_SCHEMA_VERSION: u32 = 22;
