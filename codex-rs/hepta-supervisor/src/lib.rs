//! Per-agent process lifecycle control for the Hepta workspace fleet.
//!
//! The supervisor does not execute turns or forward messages, models, or tokens.

mod authority_bundle;
#[cfg(any(test, feature = "offline-authority-tools"))]
mod authority_signer;
mod control;
mod control_intent;
mod daemon;
mod daemon_client;
mod daemon_protocol;
mod driver;
mod durability;
#[cfg(all(test, feature = "qualification"))]
mod durability_qualification_tests;
mod durable_publish;
mod error;
#[cfg(unix)]
mod fleet_setup;
mod lease;
mod matrix;
mod model;
mod module_runtime;
mod module_runtime_store;
mod mutation_journal;
mod mutation_journal_slots;
mod process_deadline;
mod process_exit_witness;
#[cfg(feature = "qualification")]
mod qualification_faults;
mod recovery;
mod recovery_diagnostics;
mod recovery_observation;
mod release;
mod release_transaction;
mod restart_budget;
mod restart_journal;
mod restart_lineage;
mod restart_policy;
mod restart_state;
mod result_fence;
mod robrix_projection;
mod robrix_protocol;
mod runtime;
mod signed_authority;
mod signed_intent;
mod supervisor;
mod supervisor_qualification;
mod tick;
mod writer_handoff;

#[cfg(feature = "qualification")]
#[path = "daemon_mutex.rs"]
pub mod qualification_mutex;

#[cfg(unix)]
mod unix;

pub use authority_bundle::PRODUCTION_AUTHORITY_BUNDLE_NAMESPACE;
pub use authority_bundle::PRODUCTION_AUTHORITY_BUNDLE_SCHEMA_VERSION;
pub use authority_bundle::ProductionAuthorityBundle;
pub use authority_bundle::ProductionAuthorityBundleError;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::ExternalSignerError;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::MAX_SIGNING_KEY_INPUT_BYTES;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::MAX_SIGNING_REQUEST_BYTES;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::SignRequest;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::SignResponse;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::load_signing_key_from_fd;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::load_signing_key_from_path;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::read_request;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use authority_signer::sign_request;
pub use daemon::PRODUCTION_AUTHORITY_FEATURE_ENABLED;
pub use daemon::run_supervisord;
pub use daemon::run_supervisord_with_grant_verifier;
pub use daemon_client::SupervisordClient;
pub use daemon_protocol::ControlStateDigest;
pub use daemon_protocol::MAX_SUPERVISORD_ROSTER;
pub use daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
pub use daemon_protocol::SupervisorEpoch;
pub use daemon_protocol::SupervisordAgentStatus;
pub use daemon_protocol::SupervisordControlFence;
pub use daemon_protocol::SupervisordHealth;
pub use daemon_protocol::SupervisordMatrixStatus;
pub use daemon_protocol::SupervisordMethod;
pub use daemon_protocol::SupervisordMutation;
pub use daemon_protocol::SupervisordMutationAccepted;
pub use daemon_protocol::SupervisordPayload;
pub use daemon_protocol::SupervisordRequest;
pub use daemon_protocol::SupervisordRequestValidationError;
pub use daemon_protocol::SupervisordResponse;
pub use driver::AdoptSpec;
pub use driver::Adoption;
pub use driver::ManagedProcess;
pub use driver::MatrixAdoptSpec;
pub use driver::MatrixSpawnSpec;
pub use driver::ProcessDriver;
pub use driver::ProcessObservation;
pub use driver::ProcessState;
pub use driver::SpawnSpec;
pub use driver::SpawnedProcess;
pub use error::ProcessDriverError;
pub use error::SupervisorError;
#[cfg(all(target_os = "linux", feature = "local-host"))]
mod local_fleet_host;
#[cfg(unix)]
pub use fleet_setup::with_offline_fleet_registry;
#[cfg(all(target_os = "linux", feature = "local-host"))]
pub use local_fleet_host::LocalFleetHost;
pub use model::AgentCommand;
pub use model::AgentFault;
pub use model::AgentRelease;
pub use model::AgentSupervisorSnapshot;
pub(crate) use model::ControlReleaseChange;
pub(crate) use model::ControlReleaseChangePhase;
pub(crate) use model::ControlRuntimePhase;
pub use model::MatrixSupervisorSnapshot;
pub use model::ProcessExit;
pub use model::ProcessIdentity;
pub use model::ProcessLog;
pub use model::ProcessStream;
pub use model::SupervisorConfig;
pub use model::SupervisorEvent;
pub use model::SupervisorEventKind;
pub use model::TickReport;

pub use module_runtime::RuntimeModuleInitializationWitnessV1;
pub use module_runtime::RuntimeModulePendingPromotionCheckpointV1;
pub use module_runtime::RuntimeModuleRetirementCheckpointV1;
pub use module_runtime::RuntimeModuleRetirementWitnessV1;
pub use module_runtime::RuntimeModuleSelectionCheckpointV1;
pub use module_runtime::RuntimeModuleSupervisorCheckpointV1;
pub use module_runtime::RuntimeModuleSupervisorErrorV1;
pub use module_runtime::RuntimeModuleSupervisorV1;
pub use module_runtime_store::DurableRuntimeModuleSupervisorErrorV1;
pub use module_runtime_store::DurableRuntimeModuleSupervisorV1;
pub use mutation_journal::DurableMutationPhaseV1;
pub use mutation_journal::DurableMutationStatusV1;
pub use mutation_journal::MUTATION_JOURNAL_FILE;
pub use mutation_journal::MUTATION_JOURNAL_SCHEMA_VERSION;
pub use mutation_journal::MutationJournalError;
pub use mutation_journal::commit_mutation;
pub use mutation_journal::mark_mutation_ambiguous;
pub use mutation_journal::mark_mutation_effect_started;
pub use mutation_journal::prepare_mutation;
pub use mutation_journal::read_mutation_status;
pub use mutation_journal::require_mutation_operator;
pub use process_deadline::ProcessDeadlineOutcomeV1;
pub use process_deadline::ProcessDeadlinePolicyErrorV1;
pub use process_deadline::ProcessDeadlinePolicyV1;
pub use process_deadline::ProcessTerminationOutcomeV1;
pub use process_deadline::enforce_process_deadline_v1;
pub use process_deadline::enforce_process_termination_deadline_v1;
pub use process_exit_witness::PROCESS_EXIT_WITNESS_FILE;
pub use process_exit_witness::PROCESS_EXIT_WITNESS_SCHEMA_VERSION;
pub use process_exit_witness::ProcessExitWitnessError;
pub use process_exit_witness::ProcessExitWitnessPhaseV1;
pub use process_exit_witness::ProcessExitWitnessV1;
pub use process_exit_witness::consume_process_exit_witness;
pub use process_exit_witness::read_process_exit_witness;
pub use process_exit_witness::record_process_exit;
#[cfg(feature = "qualification")]
pub use qualification_faults::QualificationCrashProbeError;
#[cfg(feature = "qualification")]
pub use qualification_faults::QualificationCrashProbeReceipt;
#[cfg(feature = "qualification")]
pub use qualification_faults::inspect_qualification_crash_probe;
#[cfg(feature = "qualification")]
pub use qualification_faults::publish_qualification_crash_probe;
pub use recovery_diagnostics::RecoveryBlockerDiagnostic;
pub use recovery_diagnostics::RecoveryBlockerKind;
pub use recovery_diagnostics::RecoveryDiagnostic;
pub use recovery_diagnostics::RecoveryDiagnosticContext;
pub use recovery_diagnostics::RecoveryOperatorAction;
pub use recovery_diagnostics::diagnose_recovery;
pub use recovery_observation::PRODUCTION_RECOVERY_OBSERVATION_FILE;
pub use recovery_observation::PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION;
pub use recovery_observation::ProductionRecoveryObservationV1;
pub use recovery_observation::RecoveryObservationError;
pub use recovery_observation::RecoveryReplayDecisionV1;
pub use recovery_observation::publish_production_recovery_observation;
pub use recovery_observation::read_production_recovery_observation;
pub use recovery_observation::replay_production_recovery_observation;
pub use release_transaction::DurableReleaseTransaction;
pub use release_transaction::ReleaseTransactionKind;
pub use release_transaction::ReleaseTransactionPhase;
pub use result_fence::WriterResultFenceErrorV1;
pub use result_fence::WriterResultFenceV1;
pub use robrix_projection::CORPUS_FILE;
pub use robrix_projection::GENERATED_CONSTANTS_FILE;
pub use robrix_projection::MANIFEST_FILE;
pub use robrix_projection::MATRIXD_SCHEMA_FILE;
pub use robrix_projection::ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION;
pub use robrix_projection::SUPERVISORD_SCHEMA_FILE;
pub use robrix_projection::generated_robrix_control_artifacts;
pub use robrix_projection::verify_robrix_control_corpus;
pub use robrix_projection::write_robrix_control_projection;
pub use robrix_protocol::ROBRIX_SUPERVISORD_ALLOWED_METHODS;
pub use robrix_protocol::RobrixProtocolError;
pub use robrix_protocol::RobrixSupervisordMethod;
pub use robrix_protocol::RobrixSupervisordPayload;
pub use robrix_protocol::RobrixSupervisordRequest;
pub use robrix_protocol::RobrixSupervisordResponse;
pub use signed_authority::H7H89ProductionGrant;
#[cfg(any(test, feature = "offline-authority-tools"))]
pub use signed_authority::H7H89ProductionGrantSigner;
pub use signed_authority::H7H89ProductionGrantVerifier;
pub use signed_authority::H7H89ProductionTransition;
pub use signed_authority::PRODUCTION_RECOVERY_NAMESPACE;
pub use signed_authority::PRODUCTION_RECOVERY_SCHEMA_VERSION;
pub use signed_authority::ProductionAuthorityError;
pub use signed_authority::ProductionMutationReceipt;
pub use signed_authority::ProductionMutationState;
pub use signed_authority::ProductionMutationStatus;
pub use signed_authority::ProductionRecoveryDecision;
pub use signed_authority::ProductionRecoveryOutcome;
pub use signed_authority::SIGNED_AUTHORITY_NAMESPACE;
pub use signed_authority::SIGNED_AUTHORITY_SCHEMA_VERSION;
pub use signed_authority::authority_epoch_for_supervisor_epoch;
pub use signed_intent::SIGNED_INTENT_FILE;
pub use signed_intent::SIGNED_INTENT_RECOVERY_FILE;
pub use signed_intent::SignedIntentError;
pub use signed_intent::SignedIntentRecoveryAction;
pub use signed_intent::SignedIntentRecoveryDirective;
pub use signed_intent::SignedIntentStatus;
pub use signed_intent::SignedSupervisorIntent;
pub use signed_intent::read_intent as read_signed_intent;
pub use signed_intent::read_recovery_directive as read_signed_intent_recovery_directive;
pub use signed_intent::write_recovery_directive as write_signed_intent_recovery_directive;
pub use supervisor::Supervisor;
pub use supervisor_qualification::H8_H9_SHADOW_EFFECT_AUTHORITY;
pub use supervisor_qualification::H8_H9_SHADOW_EXECUTE_ALLOWED;
pub use supervisor_qualification::H8_H9_SHADOW_EXTERNAL_EFFECTS;
pub use supervisor_qualification::H8_H9_SHADOW_G5_ALLOWED;
pub use supervisor_qualification::H8_H9_SHADOW_GOVERNANCE_BYPASS;
pub use supervisor_qualification::H8_H9_SHADOW_NAMESPACE;
pub use supervisor_qualification::H8_H9_SHADOW_OPERATOR_ACCEPTANCE;
pub use supervisor_qualification::H8_H9_SHADOW_PRODUCTION_AUTHORITY;
pub use supervisor_qualification::H8_H9_SHADOW_PRODUCTION_CALLER;
pub use supervisor_qualification::H8_H9_SHADOW_PRODUCTION_WRITER;
pub use supervisor_qualification::H8_H9_SHADOW_PROMOTION;
pub use supervisor_qualification::H8_H9_SHADOW_PROMOTION_ELIGIBLE;
pub use supervisor_qualification::H8_H9_SHADOW_SCHEMA_VERSION;
pub use supervisor_qualification::H8H9PendingRollback;
pub use supervisor_qualification::H8H9RecoveryOutcome;
pub use supervisor_qualification::H8H9RollbackPhase;
pub use supervisor_qualification::H8H9ShadowSupervisor;
pub use supervisor_qualification::H8H9SupervisorError;
pub use supervisor_qualification::H8H9SupervisorState;
pub use supervisor_qualification::H8ShadowSupervisor;
pub use supervisor_qualification::H9ShadowRollbackMachine;
pub use supervisor_qualification::QualificationSupervisor;
pub use writer_handoff::DurableWriterHandoffJournalV1;
pub use writer_handoff::WriterHandoffAdvanceV1;
pub use writer_handoff::WriterHandoffCheckpointV1;
pub use writer_handoff::WriterHandoffErrorV1;
pub use writer_handoff::WriterHandoffPhaseV1;
pub use writer_handoff::WriterHandoffPlanV1;

#[cfg(unix)]
pub use unix::UnixManagedProcess;
#[cfg(unix)]
pub use unix::UnixProcessDriver;


#[cfg(all(target_os = "linux", feature = "local-host"))]
pub use daemon::run_supervisord_with_local_host;
