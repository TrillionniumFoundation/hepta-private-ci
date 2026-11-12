//! One-process-per-workspace Hepta agent host.
//!
//! `agentd` binds exactly one fleet `AgentId`, embeds the existing Codex App
//! Server execution path, and exposes a small local lifecycle/control socket.
//! It does not implement a second runtime kernel or a fleet-wide message bus.

mod app_runtime;
#[cfg(test)]
#[path = "native_g2_entry/command_runtime.rs"]
mod native_g2_command_runtime;
#[cfg(all(test, target_os = "linux"))]
#[path = "native_g2_entry/socket_publication.rs"]
mod native_g2_socket_publication;
#[cfg(target_os = "linux")]
mod native_hos2_owner;
#[cfg(target_os = "linux")]
pub use native_hos2_owner::AgentdG2NativeImage;
#[cfg(target_os = "linux")]
pub use native_hos2_owner::AgentdG2NativeOperationHost;
#[cfg(target_os = "linux")]
pub use native_hos2_owner::attach_g2_native_cpu_policy_host;
#[cfg(target_os = "linux")]
pub use native_hos2_owner::attach_g2_native_operation_host;
#[cfg(target_os = "linux")]
mod root_bound_socket;
#[cfg(target_os = "linux")]
pub use root_bound_socket::bind_root_agentd_socket;
#[cfg(target_os = "linux")]
pub use root_bound_socket::listen_root_bound_socket;
#[cfg(target_os = "linux")]
mod authority_host_consumer_frontier;
#[cfg(target_os = "linux")]
pub use authority_host_consumer_frontier::HostConsumerFrontier;
#[cfg(target_os = "linux")]
mod authority_host_checkpoint;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::HostCognitiveCheckpoint;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::HostCognitiveCheckpointRegistration;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::HostPhysicalCurrentObservation;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::RetainedCheckpointPublisher;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::RetiredCheckpointPublisher;
#[cfg(target_os = "linux")]
mod authority_host_wire;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HOST_AUTHORITY_OBSERVATION_V2;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HOST_WRITER_AUTHORIZATION_V1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostAuthorityObservationRequestV2;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostAuthorityObservationResponseV2;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostAuthorityWriterObservationV2;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostConsumerFrontierRequestV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostConsumerFrontierResponseV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostConsumerFrontierStatusV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostSignedWriterAuthorizationV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostWriterAuthorizationClaimsV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostWriterAuthorizationReadRequestV1;
#[cfg(target_os = "linux")]
pub use authority_host_wire::HostWriterAuthorizationReadResponseV1;

#[cfg(target_os = "linux")]
mod authority_host_bootstrap;
#[cfg(target_os = "linux")]
mod authority_host_bootstrap_seal;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap_seal::seal_host_authority_bootstrap;
#[cfg(target_os = "linux")]
mod authority_host_config;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HOST_AUTHORITY_BOOTSTRAP_BOUND;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HOST_AUTHORITY_BOOTSTRAP_V1;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HostAuthorityFiveLanePathsV1;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HostAuthorityPublicBootstrapV1;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HostAuthorityPublicConsumerV1;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HostAuthorityPublicConsumersV1;
#[cfg(target_os = "linux")]
pub use authority_host_bootstrap::HostAuthorityPublicIssuerKeyV1;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityBindIdentity;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityConsumerConfig;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityConsumersConfig;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityRegisteredIdentity;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityRegistration;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityServiceConfig;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthoritySocketPaths;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostIssuerRecordProfile;
#[cfg(target_os = "linux")]
mod authority_host_native_launch;
#[cfg(target_os = "linux")]
mod authority_host_runtime;
#[cfg(target_os = "linux")]
pub use authority_host_native_launch::HostAuthorityNativeProfile;
#[cfg(target_os = "linux")]
pub use authority_host_native_launch::NativeLaunchDiagnostic;
#[cfg(target_os = "linux")]
pub use authority_host_native_launch::diagnose_native_launch;
#[cfg(target_os = "linux")]
pub use authority_host_native_launch::launch_host_authority_native_session;
#[cfg(target_os = "linux")]
mod authority_host_admin;
#[cfg(target_os = "linux")]
mod authority_host_service;
#[cfg(target_os = "linux")]
pub use authority_host_admin::ROOT_ADMIN_FRAME_BOUND;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminAction;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminCapability;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminConsumerSynchronization;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminInstance;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminObservation;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminRequest;
#[cfg(target_os = "linux")]
pub use authority_host_admin::RootAdminResponse;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::HostAuthorityBootstrap;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::HostAuthorityInitialized;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::HostIssuerLeaseRenewalPlan;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::PreparedHostAuthoritySession;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::RootNotesPolicyPredecessor;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::commit_host_issuer_lease_renewal;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::initialize_host_authority;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::prepare_host_issuer_lease_renewal;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::recover_host_resident_learning_v3;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::register_host_learning_checkpoint;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::register_host_resident_learning_v3;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::register_host_writer_authorization;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::rotate_host_writer_authorization;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::serve_host_authority_session;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::serve_host_authority_session_with_text;
#[cfg(target_os = "linux")]
pub use authority_host_service::FreshHostCognitiveState;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityLane;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityLearningRegistrationV1;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityService;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityTextUiRegistration;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::AgentdRootResidentLearningClientV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::ROOT_RESIDENT_LEARNING_EXECUTE_V3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::ROOT_RESIDENT_LEARNING_READBACK_V3;
#[cfg(target_os = "linux")]
pub(crate) use authority_host_service::resident::RootResidentLearningEffectGateV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningHandleV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningObservationV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningProfileV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningReadbackAuthorizationV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningRegistrationV3;
#[cfg(target_os = "linux")]
pub use authority_host_service::resident::RootResidentLearningRuntimeV3;
#[cfg(target_os = "linux")]
pub(crate) use circuit_learning_delivery::AgentdRootResidentDeliveryV3;
#[cfg(target_os = "linux")]
pub use circuit_learning_delivery::AgentdRootResidentEnrollmentV3;
#[cfg(target_os = "linux")]
mod root_authority_session;
#[cfg(target_os = "linux")]
mod root_production_inputs;
#[cfg(target_os = "linux")]
mod root_production_learning_inputs;
#[cfg(target_os = "linux")]
pub use root_production_inputs::AgentdRootProductionInputs;
#[cfg(target_os = "linux")]
pub use root_production_inputs::receive_root_production_inputs;
#[cfg(target_os = "linux")]
pub use root_production_learning_inputs::AgentdRootLearningInputsV1;
#[cfg(target_os = "linux")]
mod root_production_handoff;
#[cfg(target_os = "linux")]
pub use config::PreparedRootAgentdConfig;
#[cfg(target_os = "linux")]
pub use config::drop_root_native_owner_credentials;
#[cfg(target_os = "linux")]
pub use root_production_handoff::RootLearningHandoffV1;
#[cfg(target_os = "linux")]
pub use root_production_handoff::RootProductionWriterDescriptor;
#[cfg(target_os = "linux")]
pub use root_production_handoff::receive_root_learning_handoff;
#[cfg(target_os = "linux")]
pub use root_production_handoff::receive_root_production_handoff;
#[cfg(target_os = "linux")]
pub use root_production_handoff::receive_root_production_writer_handoff;
#[cfg(target_os = "linux")]
pub use root_production_handoff::send_root_learning_handoff;
#[cfg(target_os = "linux")]
pub use root_production_handoff::send_root_production_handoff;
#[cfg(target_os = "linux")]
pub use root_production_handoff::send_root_production_writer_handoff;
#[cfg(target_os = "linux")]
mod root_observation_cache;
#[cfg(target_os = "linux")]
mod root_observation_stream;
#[cfg(target_os = "linux")]
pub use root_authority_session::AgentdRootAuthoritySession;
#[cfg(target_os = "linux")]
mod root_writer_proof;
#[cfg(target_os = "linux")]
pub use root_observation_stream::AgentdRootAuthorityPeer;
#[cfg(target_os = "linux")]
pub use root_writer_proof::AgentdRootAuthorityError;
#[cfg(target_os = "linux")]
pub use root_writer_proof::AgentdRootWriterTrust;
mod authbus_checkpoint;
mod authbus_dispatch;
mod authbus_ingress;
mod authbus_trust;
mod automation;
mod automation_effect_host;
mod automation_effect_payload;
mod automation_recovery;
mod browser_servo;
mod client;
#[cfg(target_os = "linux")]
mod cognitive_checkpoint_unix;
mod cognitive_context;
mod cognitive_ranker;
mod cognitive_retrieval_context;
mod cognitive_retrieval_learning;
mod config;
mod control;
#[cfg(target_os = "linux")]
mod deployment_frontier;
#[cfg(target_os = "linux")]
pub use deployment_frontier::DeploymentFrontierStore;
#[cfg(target_os = "linux")]
mod deployment_issuer;
#[cfg(target_os = "linux")]
pub use deployment_issuer::DeploymentFinalUseIssuer;
#[cfg(target_os = "linux")]
pub use deployment_issuer::DeploymentGrantPolicy;
#[cfg(target_os = "linux")]
pub use deployment_issuer::DeploymentIssuerObserver;
#[cfg(target_os = "linux")]
pub use deployment_issuer::HostAuthorityWriterRegistration;
#[cfg(target_os = "linux")]
pub use deployment_issuer::RootDesktopPolicy;
#[cfg(target_os = "linux")]
pub use deployment_issuer::RootIssuedNotesGrantObservation;
#[cfg(target_os = "linux")]
pub use deployment_issuer::RootIssuedNotesGrantSelection;
#[cfg(target_os = "linux")]
pub use deployment_issuer::RootNotesGrantAdmission;
mod android_runtime;
#[cfg(target_os = "linux")]
mod calculator_bootstrap;
#[cfg(target_os = "linux")]
mod calculator_channel;
#[cfg(target_os = "linux")]
mod calculator_deadline;
#[cfg(target_os = "linux")]
mod calculator_observer;
#[cfg(target_os = "linux")]
mod calculator_recovery_process;
#[cfg(target_os = "linux")]
mod calculator_recovery_selection;
mod cell_composed_q24;
mod cell_q24_backend;
mod cell_q24_dataset;
mod cell_temporal_q24;
mod circuit_cell;
mod circuit_cell_binding;
mod circuit_cell_causal;
mod circuit_cell_dispatch;
mod circuit_cell_output;
mod circuit_cell_ports;
mod circuit_cell_representation_encoder;
mod circuit_credit;
#[cfg(target_os = "linux")]
mod circuit_feature_current;
mod circuit_learning_delivery;
#[cfg(target_os = "linux")]
mod circuit_original_evaluation_provider;
#[cfg(target_os = "linux")]
mod circuit_on_policy_evaluation;
#[cfg(target_os = "linux")]
mod circuit_q24_task_profile;
mod circuit_task;
#[cfg(target_os = "linux")]
mod cpu_policy;
#[cfg(target_os = "linux")]
mod cpu_policy_consumer;
#[cfg(target_os = "linux")]
mod desktop_launch;
#[cfg(target_os = "linux")]
pub(crate) mod desktop_previous_recovery;
#[cfg(target_os = "linux")]
mod desktop_root_composition;
#[cfg(target_os = "linux")]
mod desktop_startup;
#[cfg(target_os = "linux")]
mod desktop_thread_catalog;
#[cfg(target_os = "linux")]
mod desktop_thread_execution;
#[cfg(target_os = "linux")]
mod desktop_thread_seed;
#[cfg(target_os = "linux")]
mod desktop_thread_tool;
mod error;
mod event_buffer;
mod evidence_frontier;
mod evidence_host;
mod evidence_trust;
#[cfg(target_os = "linux")]
mod final_use_issuer;
mod grant_provider_worker;
#[cfg(target_os = "linux")]
mod hos2_device;
mod intelligence_ingress;
mod intelligence_product;
mod intuition_policy;
mod lane_b_runtime;
mod learning_iteration;
#[cfg(target_os = "linux")]
mod learning_iteration_evidence_client;
#[cfg(target_os = "linux")]
mod learning_iteration_generation_evidence;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::AuthenticatedCellLearningEvaluationV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::CellLearningEvaluationReadbackErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::CellLearningEvaluationReadbackRequestV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::LearningIterationEvidenceClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::LearningIterationEvidencePeerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24CandidateReadbackClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24CandidateReadbackErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24CandidateStageOwnersV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24CandidateStageStreamsV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24DatasetCommandReadbackV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialEvidenceErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialEvidenceOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialEvidenceRoleV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialSourceConnectionV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24MaterialSourceErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24ModelCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24ModelCommandConnectionV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24ModelCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24ModelCommandHostV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24ModelCommandReceiptV1;
pub(crate) use learning_iteration_evidence_client::OriginalCellQ24ModelReadV1;
pub(crate) use learning_iteration_evidence_client::OriginalCellQ24ModelReadCompletionV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24NoUpdatePeerStreamV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24NoUpdateStageOwnersV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24NoUpdateStageStreamsV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24NoUpdateTaskStreamV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24RemoteMaterialClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingBootstrapConfigV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingBootstrapCustodyV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingBootstrapErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingBootstrapOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandConnectionErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandConnectionV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandContextV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCellQ24TrainingReadbackConnectionV1;

#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionCommandContextV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitSelectionReadbackConnectionV1;

#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitNextUseCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitNextUseCommandContextV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitNextUseCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitNextUseCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitNextUseCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::read_cell_learning_evaluation_v1;
#[cfg(target_os = "linux")]
pub use learning_iteration_generation_evidence::AuthenticatedGenerationLearningStageV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_generation_evidence::GenerationLearningStageReadV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_generation_evidence::GenerationLearningStageReadbackErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_generation_evidence::GenerationLearningStageReadbackRequestV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_generation_evidence::read_generation_learning_stage_v1;

#[cfg(target_os = "linux")]
mod artifact_original_head;
mod cell_q24_material_receipt_owner;
mod cell_q24_model_material;
mod cell_q24_model_proposal;
mod cell_q24_training_receipt_owner;
mod cell_q24_training_snapshot_readback;
#[cfg(target_os = "linux")]
mod cell_q24_training_source;
#[cfg(target_os = "linux")]
mod circuit_model_selection_receipt_owner;
#[cfg(target_os = "linux")]
mod circuit_next_use_receipt_owner;
#[cfg(target_os = "linux")]
mod circuit_selection_receipt_owner;
mod learning_iteration_auth;
#[cfg(unix)]
mod learning_iteration_checkpoint;
mod learning_iteration_ports;
mod learning_iteration_proposal;
#[cfg(all(test, unix))]
mod learning_iteration_research_external;
#[cfg(all(test, unix))]
mod learning_iteration_research_external_material;
#[cfg(target_os = "linux")]
mod learning_owner_command_channel;
mod learning_owner_evidence;
mod learning_owner_journal;
mod neuron_cell_evaluation;
mod neuron_cell_evaluation_execution_store;
mod neuron_cell_evaluation_owner;
#[cfg(target_os = "linux")]
mod neuron_cell_evaluation_qualification_owner;
#[cfg(target_os = "linux")]
mod neuron_cell_evaluation_receipt_owner;
mod neuron_cell_learning_evaluation;
pub use cell_composed_q24::CellQ24FeatureEncoderV1;
pub use cell_composed_q24::CellQ24FeatureWorkerV1;
pub use cell_composed_q24::CellQ24GenerationWorkerV1;
pub use cell_composed_q24::CellQ24ModelFilesV1;
pub use cell_composed_q24::CellQ24PrivateHeadV1;
pub use cell_composed_q24::CellQ24SgdRuleV1;
pub use cell_composed_q24::CellQ24SingleHeadTrainingPlanV1;
pub use cell_composed_q24::CellQ24TrainedCandidateV1;
pub use cell_composed_q24::CellQ24TrainingBatchV1;
pub use cell_composed_q24::CellQ24TrainingErrorV1;
pub use cell_composed_q24::CellQ24TrainingMetricsV1;
pub use cell_composed_q24::CellQ24TrainingObservationV2;
pub use cell_composed_q24::CellQ24TrainingOutcomeV1;
pub use cell_composed_q24::CellQ24TrainingOwnerErrorV1;
pub use cell_composed_q24::CellQ24TrainingOwnerV1;
pub use cell_composed_q24::CellQ24TrainingPlanErrorV1;
pub use cell_composed_q24::CellQ24TrainingSampleV1;
pub use cell_composed_q24::LoadedCellQ24ModelV1;
#[cfg(target_os = "linux")]
pub use cell_composed_q24::OriginalCellQ24CandidateMaterialErrorV1;
#[cfg(target_os = "linux")]
pub use cell_composed_q24::OriginalCellQ24CandidateMaterialV1;
pub use cell_composed_q24::cell_q24_single_head_update_rule_v1;
pub use cell_q24_backend::CellQ24BackendFilesV1;
pub use cell_q24_backend::load_cell_q24_backend_v1;
pub use cell_q24_dataset::CellQ24DatasetErrorV1;
pub use cell_q24_dataset::CellQ24DatasetReaderV1;
pub use cell_q24_dataset::CellQ24DatasetRuleV1;
pub use cell_q24_dataset::OriginalCellQ24DatasetV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialCompletionV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialReceiptConfigV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialReceiptErrorV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialReceiptFilesV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialReceiptOwnersV1;
pub use cell_q24_material_receipt_owner::OriginalCellQ24MaterialReceiptSourcesV1;
pub use cell_q24_model_proposal::CellQ24ModelProposalErrorV1;
pub use cell_q24_model_proposal::CellQ24ModelProposalInputsV1;
pub use cell_q24_model_proposal::CellQ24ModelProposalOwnerV1;
pub use cell_q24_model_proposal::CellQ24ModelProposalReceiptV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingCompletionV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingReceiptErrorV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingReceiptOwnerV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingSigningConfigV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingStageErrorV1;
pub use cell_q24_training_receipt_owner::OriginalCellQ24TrainingStageV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_receipt_owner::SourceBoundCellQ24TrainingStageV1;
pub use cell_q24_training_snapshot_readback::OriginalCellQ24TrainingReadbackErrorV1;
pub use cell_q24_training_snapshot_readback::read_cell_q24_training_snapshot_v1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::OriginalCellQ24RemoteTrainingSourceOwnersV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::OriginalCellQ24TrainingSourceConfigV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::OriginalCellQ24TrainingSourceErrorV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::OriginalCellQ24TrainingSourceOwnersV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::OriginalCellQ24TrainingSourceV1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::capture_original_cell_q24_training_source_v1;
#[cfg(target_os = "linux")]
pub use cell_q24_training_source::capture_original_remote_cell_q24_training_source_v1;
pub use cell_temporal_q24::CellTemporalQ24GenerationWorkerV1;
pub use cell_temporal_q24::CellTemporalQ24ModelFilesV1;
pub use cell_temporal_q24::LoadedCellTemporalQ24ModelV1;
#[cfg(target_os = "linux")]
pub use circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionEvaluationSourcesV1;
#[cfg(target_os = "linux")]
pub use circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionReceiptConfigV1;
#[cfg(target_os = "linux")]
pub use circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionReceiptErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionReceiptOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_model_selection_receipt_owner::OriginalCircuitModelSelectionReceiptSourcesV1;
#[cfg(target_os = "linux")]
pub use circuit_next_use_receipt_owner::OriginalCircuitNextUseReceiptConfigV1;
#[cfg(target_os = "linux")]
pub use circuit_next_use_receipt_owner::OriginalCircuitNextUseReceiptErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_next_use_receipt_owner::OriginalCircuitNextUseReceiptOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_next_use_receipt_owner::OriginalCircuitNextUseReceiptSourcesV1;
#[cfg(target_os = "linux")]
pub use circuit_next_use_receipt_owner::OriginalCircuitNextUseRemoteSourcesV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::AgentdQ24CircuitTaskRuntimeV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::CircuitQ24TaskFilesV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::CircuitQ24TaskOpenModeV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::CircuitQ24TaskProfileV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::CircuitQ24TaskRuntimeV1;
#[cfg(target_os = "linux")]
pub use circuit_q24_task_profile::circuit_q24_task_channel_v1;
#[cfg(target_os = "linux")]
pub use circuit_selection_receipt_owner::OriginalCircuitSelectionReceiptConfigV1;
#[cfg(target_os = "linux")]
pub use circuit_selection_receipt_owner::OriginalCircuitSelectionReceiptErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_selection_receipt_owner::OriginalCircuitSelectionReceiptOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_selection_receipt_owner::OriginalCircuitSelectionReceiptSourcesV1;
#[cfg(target_os = "linux")]
pub use circuit_selection_receipt_owner::OriginalCircuitSelectionRemoteSourcesV1;
pub use learning_owner_journal::LearningOriginalOwnerErrorV1;
pub use neuron_cell_evaluation_execution_store::OriginalCellEvaluationExecutionStoreErrorV1;
pub use neuron_cell_evaluation_execution_store::OriginalCellEvaluationExecutionStoreV1;
pub use neuron_cell_evaluation_owner::OriginalCellEvaluationExecutionOwnerV1;
pub use neuron_cell_evaluation_owner::OriginalCellEvaluationSigningConfigV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelErrorV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelMemberOwnersV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelMemberReadbackV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelOwnerV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelReadbackV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelRegistrationV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationPanelTaskV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationQualificationConfigV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationQualificationErrorV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationQualificationOwnerV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationQualificationSourcesV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_receipt_owner::OriginalCellEvaluationReceiptConfigV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_receipt_owner::OriginalCellEvaluationReceiptErrorV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_receipt_owner::OriginalCellEvaluationReceiptOwnerV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_receipt_owner::OriginalCellEvaluationReceiptSourcesV1;
mod neuron_generation;
#[cfg(unix)]
mod neuron_generation_current;
mod neuron_generation_episode;
#[cfg(unix)]
mod neuron_generation_initial;
#[cfg(unix)]
mod neuron_generation_initial_bootstrap;
#[cfg(unix)]
mod neuron_generation_initial_forward;
mod neuron_generation_process_bootstrap;
mod neuron_generation_runtime;
mod neuron_generation_service;
#[cfg(all(test, target_os = "linux"))]
#[path = "../tests/support/neuron_generation.rs"]
mod neuron_generation_test_support;
#[cfg(unix)]
mod neuron_generation_update;
#[cfg(unix)]
mod neuron_generation_update_bootstrap;
#[cfg(unix)]
mod neuron_generation_update_cold;
#[cfg(unix)]
mod neuron_generation_update_forward;
#[cfg(unix)]
mod neuron_generation_update_live;
#[cfg(unix)]
mod neuron_generation_update_selection;
mod neuron_runtime;
#[cfg(target_os = "linux")]
mod neuron_v13_generation_bootstrap;
#[cfg(target_os = "linux")]
mod neuron_v13_generation_initial;
#[cfg(target_os = "linux")]
mod neuron_v13_generation_update;
#[cfg(target_os = "linux")]
mod neuron_v13_generation_update_runtime;
#[cfg(target_os = "linux")]
mod notes_bootstrap;
#[cfg(unix)]
mod notes_channel;
#[cfg(target_os = "linux")]
mod notes_document_observer;
#[cfg(target_os = "linux")]
mod notes_launch_mode;
#[cfg(target_os = "linux")]
mod notes_literal_adapter;
#[cfg(target_os = "linux")]
mod notes_literal_control;
#[cfg(target_os = "linux")]
mod notes_literal_observation;
#[cfg(target_os = "linux")]
mod notes_literal_prepare;
#[cfg(target_os = "linux")]
mod notes_literal_receipts;
#[cfg(target_os = "linux")]
mod notes_organ;
#[cfg(target_os = "linux")]
mod notes_recovery_process;
#[cfg(target_os = "linux")]
mod notes_thread_execution;
#[cfg(target_os = "linux")]
mod notes_thread_seed;
#[cfg(target_os = "linux")]
mod notes_thread_tool;
#[cfg(target_os = "linux")]
mod notes_ui_endpoint;
#[cfg(target_os = "linux")]
mod notes_ui_queue;
#[cfg(target_os = "linux")]
mod notes_ui_wire;
mod objective_runtime;
mod plasticity_anchor_journal;
mod plasticity_host;
mod plasticity_learning_producer;
mod plasticity_owner_evidence;
mod plasticity_process_bootstrap;
mod plasticity_runtime;
#[cfg(target_os = "linux")]
mod production_authority;
#[cfg(target_os = "linux")]
mod production_composition;
#[cfg(target_os = "linux")]
mod production_launcher;
#[cfg(target_os = "linux")]
mod production_root_composition;
mod production_writer_host;
mod prompt_runtime;
mod qualification_writer;
mod runtime;
#[cfg(target_os = "linux")]
pub use calculator_recovery_process::AgentdCalculatorPreviousRecoveryLaunch;
#[cfg(target_os = "linux")]
pub use calculator_recovery_selection::AgentdCalculatorPreviousRecoveryRequest;
#[cfg(target_os = "linux")]
pub use calculator_recovery_selection::AgentdCalculatorRecoverySelector;
#[cfg(target_os = "linux")]
pub use notes_organ::run_notes_organ;
#[cfg(target_os = "linux")]
pub use notes_organ::run_notes_organ_with_previous_recovery;
#[cfg(target_os = "linux")]
pub use notes_recovery_process::AgentdNotesPreviousRecoveryLaunch;
#[cfg(target_os = "linux")]
mod notes_recovery_selection;
#[cfg(target_os = "linux")]
pub use notes_recovery_selection::AgentdNotesPreviousRecoveryRequest;
#[cfg(target_os = "linux")]
pub use notes_recovery_selection::AgentdNotesRecoverySelector;
mod runtime_tasks;
mod shared_terminal_cell;
mod state;
pub mod text_session;
#[cfg(target_os = "linux")]
pub use deployment_issuer::TextIssuerOperation;
#[cfg(target_os = "linux")]
mod text_session_host;
pub use shared_terminal_cell::AgentdSharedReplayHostV1;
pub use shared_terminal_cell::SharedTerminalCandidateV1;
pub use shared_terminal_cell::SharedTerminalCellError;
pub use shared_terminal_cell::SharedTerminalModelV1;
#[doc(hidden)]
pub mod test_support;
mod topology_plasticity_host;

pub use android_runtime::AgentdAndroidRuntimeInputs;
pub use android_runtime::AgentdAndroidRuntimeSession;
pub use android_runtime::AgentdAndroidTextDevice;
pub use android_runtime::AndroidRuntimeAttempt;
pub use android_runtime::prepare_android_runtime_target;
pub use authbus_ingress::authbus_text_claims;
pub use browser_servo::BrowserFinalUseInvocation;
pub use browser_servo::BrowserServoCall;
pub use browser_servo::BrowserServoError;
pub use browser_servo::BrowserServoMethod;
pub use browser_servo::BrowserServoPort;
pub use browser_servo::BrowserServoProcessConfig;
pub use browser_servo::BrowserServoTransport;
pub use browser_servo::ChildBrowserTransport;
#[cfg(target_os = "linux")]
pub use calculator_channel::AgentdCalculatorChannel;
#[cfg(target_os = "linux")]
pub use calculator_channel::AgentdCalculatorRecoveryChannel;
#[cfg(target_os = "linux")]
pub use calculator_observer::AgentdCalculatorStateObserver;
pub use circuit_cell::AgentdCircuitCellOwnerV1;
pub use circuit_cell::CircuitCellErrorV1;
pub use circuit_cell::CircuitCellExecutionV1;
pub use circuit_cell::CircuitCellTimeV1;
pub use circuit_cell_binding::CircuitCellBindingV1;
pub use circuit_cell_binding::CircuitCellRegistryV1;
pub use circuit_cell_binding::CircuitCellRouteV1;
pub use circuit_cell_binding::circuit_cell_operation_id_v1;
pub use circuit_cell_binding::circuit_cell_route_policy_digest_v1;
pub use circuit_cell_binding::circuit_cell_scope_digest_v1;
pub use circuit_cell_causal::CircuitCellCausalRecordV1;
pub use circuit_cell_output::circuit_cell_output_schema_v1;
pub use circuit_cell_ports::CircuitCellActionPortV1;
pub use circuit_cell_ports::CircuitCellPortsV2;
pub use circuit_cell_ports::circuit_cell_output_schema_v2;
pub use circuit_cell_ports::decode_circuit_cell_ports_v2;
pub use circuit_cell_representation_encoder::CircuitCellRepresentationEncoderV1;
pub use circuit_credit::CircuitCreditErrorV1;
pub use circuit_credit::CircuitCreditSupportV1;
pub use circuit_credit::CircuitCreditTargetV1;
pub use circuit_credit::circuit_learning_run_id_v1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::CircuitFeaturePredecessorFilesV1;
#[cfg(target_os = "linux")]
pub(crate) use circuit_feature_current::OriginalCircuitCompletionReadinessClientV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitLearningReadClientV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitLearningReadContextV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitLearningReadErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitLearningReadOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitLearningReadbackV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationContextV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationInputsV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationPredecessorsV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationRecoveryV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationSelectionV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelPublicationV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PreparedOriginalCircuitModelPublicationV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::prepare_original_circuit_model_publication_v1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::recover_original_circuit_model_publication_v1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedArtifactCheckpointV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedPublicationContextV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedPublicationErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedPublicationInputsV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedPublicationRecoveryV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedPublicationSelectionV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedTaskInputsV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionClientV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionHostV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionPublicationV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionReadbackV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitRetainedVersionRecoveryV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PreparedOriginalCircuitRetainedPublicationV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PublishedCircuitCellOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PublishedCircuitFeatureCompletionV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PublishedCircuitFeatureControlV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::PublishedCircuitFeatureTaskV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::circuit_feature_task_digest_v1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::prepare_original_circuit_retained_publication_v1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::recover_original_circuit_retained_publication_v1;
pub use circuit_learning_delivery::deliver_circuit_learning_v1;
pub use circuit_learning_delivery::reconcile_circuit_learning_v1;
pub use circuit_task::CircuitTaskErrorV1;
pub use circuit_task::CircuitTaskHandleV1;
pub use circuit_task::CircuitTaskInputModeV1;
pub use circuit_task::CircuitTaskInputProviderV1;
pub use circuit_task::CircuitTaskReceiptV1;
pub use circuit_task::CircuitTaskRequestV1;
pub use circuit_task::CircuitTaskRuntimeBootstrapV1;
pub use circuit_task::CircuitTaskSourceInputV1;
pub use circuit_task::CircuitTaskSourcePublicationV1;
pub use circuit_task::CircuitTaskSourceReadbackV1;
pub use circuit_task::DurableCircuitTaskSourceV1;
pub use circuit_task::circuit_task_channel_v1;
pub use client::AgentdClient;
pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_AUTOMATION_CALENDAR_V2;
pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;
pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_CANONICAL_INTELLIGENCE_V1;
pub use codex_hepta_agent_protocol::AGENTD_CONTROL_OVERLOAD_FRAME;
pub use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
pub use codex_hepta_agent_protocol::AGENTD_OVERLOAD_RETRY_AFTER_MS;
pub use codex_hepta_agent_protocol::AGENTD_RUN_LIFECYCLE_CAPABILITY_ID;
pub use codex_hepta_agent_protocol::AGENTD_RUN_LIFECYCLE_CAPABILITY_MAJOR;
pub use codex_hepta_agent_protocol::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR;
pub use codex_hepta_agent_protocol::AgentCancellationDisposition;
pub use codex_hepta_agent_protocol::AgentContextAttachment;
pub use codex_hepta_agent_protocol::AgentRunCancellation;
pub use codex_hepta_agent_protocol::AgentRunPhase;
pub use codex_hepta_agent_protocol::AgentRunReceipt;
pub use codex_hepta_agent_protocol::AgentRunSnapshot;
pub use codex_hepta_agent_protocol::AgentdCapability;
pub use codex_hepta_agent_protocol::AgentdCapabilitySet;
pub use codex_hepta_agent_protocol::AgentdEvent;
pub use codex_hepta_agent_protocol::AgentdEventKind;
pub use codex_hepta_agent_protocol::AgentdMethod;
pub use codex_hepta_agent_protocol::AgentdPayload;
pub use codex_hepta_agent_protocol::AgentdRequest;
pub use codex_hepta_agent_protocol::AgentdResponse;
pub use codex_hepta_agent_protocol::AuthBusObjectiveBody;
pub use codex_hepta_agent_protocol::AuthBusObjectiveIngress;
pub use codex_hepta_agent_protocol::AuthBusTextBody;
pub use codex_hepta_agent_protocol::AuthBusTextIngress;
pub use codex_hepta_agent_protocol::AuthBusTextState;
pub use codex_hepta_agent_protocol::AuthBusTextStatus;
pub use codex_hepta_agent_protocol::AutomationEffectObservation;
pub use codex_hepta_agent_protocol::AutomationEffectReconcileSnapshot;
pub use codex_hepta_agent_protocol::AutomationEffectReconcileState;
pub use codex_hepta_agent_protocol::AutomationEffectSnapshot;
pub use codex_hepta_agent_protocol::COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY;
pub use codex_hepta_agent_protocol::CognitiveContextItem;
pub use codex_hepta_agent_protocol::CognitiveContextPlan;
pub use codex_hepta_agent_protocol::CognitiveContextRevalidation;
pub use codex_hepta_agent_protocol::CognitiveContextSnapshot;
pub use codex_hepta_agent_protocol::EventBatch;
pub use codex_hepta_agent_protocol::HealthSnapshot;
pub use codex_hepta_agent_protocol::KernelEvidenceAppendIngress;
pub use codex_hepta_agent_protocol::KernelEvidenceCandidateV1;
pub use codex_hepta_agent_protocol::KernelEvidenceQueryV1;
pub use codex_hepta_agent_protocol::KernelEvidenceResult;
pub use codex_hepta_agent_protocol::KernelEvidenceVerifyV1;
pub use codex_hepta_agent_protocol::LifecycleSnapshot;
pub use codex_hepta_agent_protocol::MAX_AUTOMATION_EFFECT_WIRE_BYTES;
pub use codex_hepta_agent_protocol::MAX_COGNITIVE_CONTEXT_BYTES;
pub use codex_hepta_agent_protocol::MAX_CONTROL_FRAME_BYTES;
pub use codex_hepta_agent_protocol::MAX_EVENT_BATCH;
pub use codex_hepta_agent_protocol::MAX_FEDERATION_CONTROL_LIST;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilityId;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilitySnapshot;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilityState;
pub use codex_hepta_agent_protocol::MemoryFederationScopeKind;
pub use codex_hepta_agent_protocol::ObjectiveAdmissionOutcome;
pub use codex_hepta_agent_protocol::ObjectiveAdmissionPublication;
pub use codex_hepta_agent_protocol::ObjectiveAdmissionQuery;
pub use codex_hepta_agent_protocol::ObjectiveAdmissionUnknownReason;
pub use codex_hepta_agent_protocol::ObjectiveJournalAnchor;
pub use codex_hepta_agent_protocol::ObjectivePublicationOutcome;
pub use codex_hepta_agent_protocol::ObjectiveRunAdmission;
pub use codex_hepta_agent_protocol::ObjectiveStartOutcome;
pub use codex_hepta_agent_protocol::ReadinessSnapshot;
pub use codex_hepta_agent_protocol::SessionIngress;
pub use codex_hepta_agent_protocol::SessionTransport;
pub use codex_hepta_automation::AutomationCalendarScheduleV2;
pub use codex_hepta_automation::AutomationDstGapPolicy;
pub use codex_hepta_automation::AutomationDstOverlapPolicy;
pub use codex_hepta_automation::AutomationMissedRunPolicy;
pub use codex_hepta_automation::AutomationOverlapPolicy;
pub use codex_hepta_automation::AutomationSchedule;
pub use codex_hepta_automation::AutomationTask;
pub use codex_hepta_automation::AutomationTaskDraft;
pub use codex_hepta_automation::AutomationTaskId;
pub use codex_hepta_automation::AutomationTimeZoneProfileV1;
pub use codex_hepta_automation::AutomationTimezoneTransitionV1;
pub use codex_hepta_memory::RetrievalExecutionContextV1;
#[cfg(target_os = "linux")]
pub use cognitive_checkpoint_unix::AgentdCognitiveCheckpointPeer;
#[cfg(target_os = "linux")]
pub use cognitive_checkpoint_unix::AgentdUnixCognitiveCheckpointTransport;
pub use cognitive_ranker::CurrentCognitiveRegistry;
pub use cognitive_ranker::PinnedCognitiveRanker;
pub use cognitive_ranker::cognitive_action_id;
pub use cognitive_ranker::cognitive_sensor_id;
pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;
pub use cognitive_retrieval_learning::CognitiveRetrievalLearningSink;
pub use config::AgentdConfig;
pub use config::AgentdIdentity;
pub use config::CognitiveRetrievalMode;
pub use config::HEPTA_AGENT_GENERATION_ENV;
pub use config::HEPTA_AGENT_HOME_ENV;
pub use config::HEPTA_AGENT_ID_ENV;
pub use config::HEPTA_AGENT_RUN_ROOT_ENV;
pub use config::HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV;
#[cfg(target_os = "linux")]
pub use cpu_policy::CPU_POLICY_INTERVAL_NS;
#[cfg(target_os = "linux")]
pub use cpu_policy::CPU_POLICY_MAX_AGE_NS;
#[cfg(target_os = "linux")]
pub use cpu_policy::CpuBudgetProposal;
#[cfg(target_os = "linux")]
pub use cpu_policy::CpuDemandSample;
#[cfg(target_os = "linux")]
pub use cpu_policy::CpuPolicy;
#[cfg(target_os = "linux")]
pub use cpu_policy::CpuPolicyError;
#[cfg(target_os = "linux")]
pub use cpu_policy::CpuPolicyKind;
#[cfg(target_os = "linux")]
pub use cpu_policy::ObservedCpuDemand;
#[cfg(target_os = "linux")]
pub use cpu_policy_consumer::CpuPolicyConsumer;
#[cfg(target_os = "linux")]
pub use cpu_policy_consumer::CpuPolicySubmission;
#[cfg(target_os = "linux")]
pub use desktop_root_composition::AgentdDesktopProductionAttachment;
#[cfg(target_os = "linux")]
pub use desktop_root_composition::attach_root_desktop_operation_host_with_startup;
#[cfg(target_os = "linux")]
pub use desktop_startup::AgentdDesktopStartupRelease;
#[cfg(target_os = "linux")]
pub use desktop_thread_catalog::original_desktop_thread_tools;
#[cfg(target_os = "linux")]
pub use desktop_thread_execution::ORIGINAL_DESKTOP_THREAD_ENVIRONMENTS_CONFIG;
#[cfg(target_os = "linux")]
pub use desktop_thread_execution::ORIGINAL_DESKTOP_THREAD_EXECUTION_CONFIG;
#[cfg(target_os = "linux")]
pub use desktop_thread_seed::DesktopThreadSeedOptions;
#[cfg(target_os = "linux")]
pub use desktop_thread_seed::DesktopThreadSeedReceipt;
#[cfg(target_os = "linux")]
pub use desktop_thread_seed::seed_original_desktop_thread;
#[cfg(target_os = "linux")]
pub use desktop_thread_seed::verify_original_desktop_thread_seed;
#[cfg(target_os = "linux")]
pub use desktop_thread_tool::AgentdDesktopThreadToolRuntime;
pub use error::AgentdError;
pub use evidence_frontier::EvidenceRecoveryFrontierV1;
pub use evidence_frontier::evidence_recovery_frontier_signing_bytes;
pub use evidence_host::kernel_evidence_claims;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerError;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerPeer;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdUnixFinalUseGrantProvider;
#[cfg(target_os = "linux")]
pub(crate) use final_use_issuer::OriginalRootRetainedVersionIssuerV1;
#[cfg(target_os = "linux")]
pub(crate) use final_use_issuer::OriginalRootModelVersionIssuerV1;
#[cfg(target_os = "linux")]
pub use hos2_device::AgentdHos2Device;
#[cfg(target_os = "linux")]
pub use hos2_device::AgentdHos2Usage;
pub use intelligence_ingress::AgentdIntelligenceInvocationProviderV1;
pub use intelligence_ingress::AgentdIntelligenceInvocationV1;
pub use intelligence_product::AgentdEvaluationBindingV1;
pub use intelligence_product::AgentdIntelligenceAdmittedOutcomeV1;
pub use intelligence_product::AgentdIntelligenceEvaluationError;
pub use intelligence_product::AgentdIntelligenceLedgerError;
pub use intelligence_product::AgentdIntelligenceOwnerInputsV1;
pub use intelligence_product::AgentdIntelligenceProductError;
pub use intelligence_product::AgentdIntelligenceProductOutcomeV1;
pub use intelligence_product::AgentdIntelligenceProductRunnerV1;
pub use intelligence_product::AgentdSignedEvaluationV1;
pub use intelligence_product::IntelligenceAuthorityFileV1;
pub use intelligence_product::IntelligenceAuthorityOwnerFileV1;
pub use intelligence_product::IntelligenceAuthorityVerifierV1;
pub use intelligence_product::PendingIntelligenceLedgerAppendV1;
pub use intelligence_product::PreparedAgentdIntelligenceRunV1;
pub use intelligence_product::intelligence_evaluation_binding_payload_v2;
pub use intuition_policy::AgentdIntuitionDecisionReceiptV1;
pub use intuition_policy::AgentdIntuitionPolicyError;
pub use intuition_policy::AgentdIntuitionPolicyHostV1;
pub use intuition_policy::AgentdIntuitionPolicyPinsV1;
pub use lane_b_runtime::AgentRunCoordinator;
pub use lane_b_runtime::AgentRunError;
pub use lane_b_runtime::CancellationDisposition;
pub use lane_b_runtime::ContextAttachment;
pub use lane_b_runtime::RunPhase;
pub use lane_b_runtime::RunReceipt;
pub use lane_b_runtime::RunRecovery;
pub use lane_b_runtime::RunSnapshot;
pub use lane_b_runtime::RuntimeComposition;
pub use learning_iteration::CircuitLearningDeliveryRegistryV1;
pub use learning_iteration::LearningIterationHandleV1;
pub use learning_iteration::LearningIterationRuntimeBootstrapV1;
pub use learning_iteration::LearningIterationRuntimeErrorV1;
pub use learning_iteration::learning_iteration_channel_scoped_v2;
pub use learning_iteration::learning_iteration_channel_v1;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::AgentdLearningCheckpointClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::HostAuthorityLearningBootstrapV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::HostAuthorityLearningProfileV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_checkpoint::HostAuthorityLearningScopeV2;
#[cfg(unix)]
pub use learning_iteration_checkpoint::LearningIterationCheckpointErrorV1;
#[cfg(unix)]
pub use learning_iteration_checkpoint::LearningIterationCheckpointOwnerV1;
#[cfg(unix)]
pub use learning_iteration_checkpoint::LearningIterationCheckpointRecordV1;
pub use learning_iteration_ports::LearningIterationOwnerFutureV1;
pub use learning_iteration_ports::LearningIterationOwnerPortsV1;
pub use learning_iteration_ports::LearningIterationProposalPayloadV1;
pub use learning_iteration_ports::LearningIterationStageOwnerPortsV1;
pub use learning_iteration_ports::PreparedLearningIterationProposalV1;
pub use neuron_cell_evaluation::CellComparisonContractV1;
pub use neuron_cell_evaluation::CellCostCoverageV1;
pub use neuron_cell_evaluation::CellEvaluationArmRecordV1;
pub use neuron_cell_evaluation::CellEvaluationCostScopeV1;
pub use neuron_cell_evaluation::CellEvaluationErrorV1;
pub use neuron_cell_evaluation::CellEvaluationJournalsV1;
pub use neuron_cell_evaluation::CellEvaluationPlanV1;
pub use neuron_cell_evaluation::CellEvaluationQualificationRequestV1;
pub use neuron_cell_evaluation::CellEvaluationQualificationV1;
pub use neuron_cell_evaluation::CellEvaluationReceiptV1;
pub use neuron_cell_evaluation::CellEvaluationRecordV1;
pub use neuron_cell_evaluation::CellEvaluationRegistrationV1;
pub use neuron_cell_evaluation::CellEvaluationRunnerV1;
pub use neuron_cell_evaluation::CellParameterCapacityV1;
pub use neuron_cell_evaluation::CellRequiredCostMetricV1;
pub use neuron_cell_evaluation::CellSelectiveUpdateV1;
pub use neuron_cell_evaluation::CellTrainingBudgetV1;
pub use neuron_cell_evaluation::CellTrainingObservationV1;
pub use neuron_cell_evaluation::freeze_cell_evaluation_plan_v1;
pub use neuron_cell_evaluation::freeze_cell_learning_evaluation_plan_v1;
pub use neuron_cell_learning_evaluation::CellLearningEvaluationErrorV1;
pub use neuron_cell_learning_evaluation::prepare_cell_learning_evaluation_v1;
pub use neuron_generation::AgentdNeuronGenerationOwnerV2;
#[cfg(unix)]
pub use neuron_generation_current::NeuronGenerationCurrentOwnerV1;
#[cfg(unix)]
pub use neuron_generation_current::NeuronGenerationInitialReadbackV1;
#[cfg(unix)]
pub use neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
#[cfg(unix)]
pub use neuron_generation_current::NeuronGenerationUpdatePublicationV1;
#[cfg(unix)]
pub use neuron_generation_current::NeuronGenerationUpdateReadbackV1;
#[cfg(unix)]
pub use neuron_generation_current::PreparedNeuronGenerationInitialV1;
#[cfg(unix)]
pub use neuron_generation_current::PreparedNeuronGenerationUpdateV1;
#[cfg(unix)]
pub use neuron_generation_current::PublishedNeuronGenerationInitialV1;
#[cfg(unix)]
pub use neuron_generation_current::PublishedNeuronGenerationUpdateV1;
pub use neuron_generation_episode::append_neuron_generation_outcome_credit_v1;
pub use neuron_generation_episode::append_neuron_generation_outcome_v1;
#[cfg(unix)]
pub use neuron_generation_initial::PreparedAgentdGenerationInitialV1;
#[cfg(unix)]
pub use neuron_generation_initial::prepare_agentd_generation_initial_v1;
#[cfg(unix)]
pub use neuron_generation_initial::recover_agentd_generation_initial_v1;
#[cfg(unix)]
pub use neuron_generation_initial_bootstrap::AgentdGenerationInitialRuntimeV1;
#[cfg(unix)]
pub use neuron_generation_initial_bootstrap::ReadyAgentdGenerationInitialV1;
#[cfg(unix)]
pub use neuron_generation_initial_forward::prepare_agentd_generation_initial_forward_recovery_v1;
pub use neuron_generation_process_bootstrap::load_neuron_generation_process_bootstrap_v1;
pub use neuron_generation_process_bootstrap::neuron_generation_process_identity_digest_v1;
#[cfg(unix)]
pub use neuron_generation_runtime::AgentdGenerationLearningUseReadbackV1;
#[cfg(unix)]
pub use neuron_generation_runtime::NeuronGenerationLearningReadErrorV1;
pub use neuron_generation_runtime::NeuronGenerationRuntimeBootstrapV2;
pub use neuron_generation_runtime::NeuronGenerationRuntimeHandleV2;
pub use neuron_generation_runtime::neuron_generation_channel_v2;
#[cfg(unix)]
pub use neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
#[cfg(unix)]
pub use neuron_generation_update::AgentdGenerationUpdateRequestV1;
#[cfg(unix)]
pub use neuron_generation_update::AgentdGenerationUpdateTargetV1;
#[cfg(unix)]
pub use neuron_generation_update::PreparedAgentdGenerationUpdateV1;
#[cfg(unix)]
pub use neuron_generation_update::prepare_agentd_generation_drained_update_v1;
#[cfg(unix)]
pub use neuron_generation_update::prepare_agentd_generation_same_model_task_v1;
#[cfg(unix)]
pub use neuron_generation_update::prepare_agentd_generation_update_v1;
#[cfg(unix)]
pub use neuron_generation_update::recover_agentd_generation_update_v1;
#[cfg(unix)]
pub use neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
#[cfg(unix)]
pub use neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeV1;
#[cfg(unix)]
pub use neuron_generation_update_bootstrap::ReadyAgentdGenerationUpdateV1;
#[cfg(unix)]
pub use neuron_generation_update_bootstrap::learning_retained_task_operation_id_v1;
#[cfg(unix)]
pub use neuron_generation_update_bootstrap::learning_updated_task_operation_id_v1;
#[cfg(unix)]
pub use neuron_generation_update_cold::AgentdGenerationUpdatePredecessorFilesV1;
#[cfg(unix)]
pub use neuron_generation_update_cold::prepare_agentd_generation_cold_drained_update_v1;
#[cfg(unix)]
pub use neuron_generation_update_cold::prepare_agentd_generation_cold_same_model_task_v1;
#[cfg(unix)]
pub use neuron_generation_update_cold::prepare_agentd_generation_cold_update_v1;
#[cfg(unix)]
pub use neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
#[cfg(unix)]
pub use neuron_generation_update_forward::prepare_agentd_generation_forward_recovery_v1;
#[cfg(unix)]
pub use neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
#[cfg(unix)]
pub use neuron_generation_update_selection::AgentdGenerationSelectionFilesV1;
#[cfg(unix)]
pub use neuron_generation_update_selection::AgentdGenerationSelectionObservationV1;
#[cfg(unix)]
pub use neuron_generation_update_selection::AgentdSelectedGenerationV1;
pub use neuron_runtime::AgentdNeuronOwner;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::AgentdV13GenerationBootstrapConfigV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::AgentdV13GenerationWorkerV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::V13GenerationOwnerFilesV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::V13GenerationOwnerModeV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::bootstrap_agentd_v13_generation_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_bootstrap::prepare_agentd_v13_generation_worker_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_initial::PreparedAgentdV13GenerationInitialV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_initial::ReadyAgentdV13GenerationInitialV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_initial::prepare_agentd_v13_generation_initial_forward_recovery_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_initial::prepare_agentd_v13_generation_initial_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_initial::recover_agentd_v13_generation_initial_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::AgentdV13GenerationUpdateInputsV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::PreparedAgentdV13GenerationUpdateV1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_cold_drained_update_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_cold_same_model_task_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_cold_update_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_drained_update_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_forward_recovery_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_same_model_task_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::prepare_agentd_v13_generation_update_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update::recover_agentd_v13_generation_update_v1;
#[cfg(target_os = "linux")]
pub use neuron_v13_generation_update_runtime::ReadyAgentdV13GenerationUpdateV1;
#[cfg(target_os = "linux")]
pub use notes_bootstrap::AgentdNotesStartupRelease;
#[cfg(unix)]
pub use notes_channel::AgentdNotesChannel;
#[cfg(unix)]
pub use notes_channel::AgentdNotesRecoveryChannel;
#[cfg(target_os = "linux")]
pub use notes_document_observer::AgentdNotesDocumentObserver;
#[cfg(target_os = "linux")]
pub use notes_literal_adapter::AgentdNotesLiteralAdapter;
#[cfg(target_os = "linux")]
pub use notes_literal_adapter::AgentdNotesLiteralBindings;
#[cfg(target_os = "linux")]
pub use notes_literal_adapter::AgentdNotesPreparedObjective;
#[cfg(target_os = "linux")]
pub use notes_literal_adapter::AgentdNotesRetainedIntents;
#[cfg(target_os = "linux")]
pub use notes_literal_adapter::AgentdNotesUiRuntime;
#[cfg(target_os = "linux")]
pub use notes_literal_observation::AgentdNotesObservationRetention;
#[cfg(target_os = "linux")]
pub use notes_literal_observation::AgentdNotesSubmissionObservation;
#[cfg(target_os = "linux")]
pub use notes_literal_observation::AgentdNotesSubmissionState;
#[cfg(target_os = "linux")]
pub use notes_thread_execution::ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG;
#[cfg(target_os = "linux")]
pub use notes_thread_execution::ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG;
#[cfg(target_os = "linux")]
pub use notes_thread_seed::NotesThreadSeedOptions;
#[cfg(target_os = "linux")]
pub use notes_thread_seed::NotesThreadSeedReceipt;
#[cfg(target_os = "linux")]
pub use notes_thread_seed::seed_original_notes_thread;
#[cfg(target_os = "linux")]
pub use notes_thread_seed::verify_original_notes_thread_seed;
#[cfg(target_os = "linux")]
pub use notes_thread_tool::AgentdNotesThreadToolRuntime;
#[cfg(target_os = "linux")]
pub use notes_thread_tool::original_notes_thread_tools;
#[cfg(target_os = "linux")]
pub use notes_ui_endpoint::AgentdNotesSessionLifetime;
#[cfg(target_os = "linux")]
pub use notes_ui_endpoint::AgentdNotesUiPeer;
pub use objective_runtime::authbus_objective_claims;
pub use plasticity_host::AgentdPlasticityAdmissionInputV1;
pub use plasticity_host::AgentdPlasticityAnchorStoreV1;
pub use plasticity_host::AgentdPlasticityEvidenceSourcesV1;
pub use plasticity_host::AgentdPlasticityHostErrorV1;
pub use plasticity_host::PlasticityOwnerEvidenceErrorV1;
pub use plasticity_host::PlasticityOwnerEvidenceKindV1;
pub use plasticity_host::PlasticityOwnerEvidencePolicyErrorV1;
pub use plasticity_host::PlasticityOwnerEvidencePolicyV1;
pub use plasticity_host::PlasticityOwnerEvidenceQueryV1;
pub use plasticity_host::PlasticityOwnerEvidenceResolverV1;
pub use plasticity_host::VerifiedPlasticityOwnerEvidenceV1;
pub use plasticity_host::bootstrap_agentd_plasticity_writer_v1;
pub use plasticity_host::propose_agentd_plasticity_v1;
pub use plasticity_host::reopen_agentd_plasticity_writer_v1;
pub use plasticity_host::resolve_agentd_plasticity_admission_v1;
pub use plasticity_host::resolve_agentd_plasticity_owner_evidence_set_v1;
pub use plasticity_host::resume_agentd_plasticity_writer_v1;
pub use plasticity_host::rollover_agentd_plasticity_writer_v1;
pub use plasticity_host::verify_agentd_plasticity_owner_evidence_v1;
pub use plasticity_owner_evidence::ConcretePlasticityOwnerEvidenceResolverV1;
pub use plasticity_owner_evidence::PlasticityArtifactOwnerBindingV1;
pub use plasticity_owner_evidence::PlasticityDynamicOwnerEvidenceResolverV1;
pub use plasticity_owner_evidence::PlasticityDynamicSignalBindingV1;
pub use plasticity_owner_evidence::plasticity_eligibility_digest_v1;
pub use plasticity_owner_evidence::plasticity_modulator_broadcast_digest_v1;
pub use plasticity_owner_evidence::plasticity_modulator_digest_v1;
pub use plasticity_owner_evidence::plasticity_parameter_signal_digest_v1;
pub use plasticity_process_bootstrap::load_plasticity_process_bootstrap_v1;
pub use plasticity_runtime::PlasticityRuntimeBootstrapV1;
pub use plasticity_runtime::PlasticityRuntimeCallErrorV1;
pub use plasticity_runtime::PlasticityRuntimeHandleV1;
pub use plasticity_runtime::PlasticityRuntimeOwnerV1;
pub use plasticity_runtime::plasticity_runtime_channel_v1;
#[cfg(target_os = "linux")]
pub use production_authority::AgentdFinalUseHostInputs;
#[cfg(target_os = "linux")]
pub use production_composition::AgentdProductionHostInputs;
#[cfg(target_os = "linux")]
pub use production_composition::AgentdProductionNotesInputs;
#[cfg(target_os = "linux")]
pub use production_composition::attach_production_operation_host;
#[cfg(target_os = "linux")]
pub use production_launcher::AgentdProductionLaunch;
#[cfg(target_os = "linux")]
pub use production_launcher::AgentdProductionStartup;
#[cfg(target_os = "linux")]
pub use production_root_composition::AgentdRootProductionAttachment;
#[cfg(target_os = "linux")]
pub use production_root_composition::attach_root_notes_operation_host;
#[cfg(target_os = "linux")]
pub use production_root_composition::attach_root_notes_operation_host_with_startup;
#[cfg(target_os = "linux")]
pub use production_root_composition::attach_root_production_operation_host;
#[cfg(target_os = "linux")]
pub use production_root_composition::attach_root_production_operation_host_with_startup;
pub use production_writer_host::AgentdFinalUseGrantProvider;
pub use production_writer_host::AgentdProductionOperationRuntimeConfig;
pub use production_writer_host::AgentdProductionWriterHost;
pub use production_writer_host::AgentdProtectedCheckpointInputs;
pub use prompt_runtime::AgentdPromptPipelineError;
pub use prompt_runtime::AgentdPromptPipelineOwner;
pub use prompt_runtime::AgentdPromptRuntimeError;
pub use prompt_runtime::AgentdPromptRuntimeOwner;
pub use prompt_runtime::PromptRuntimeStageDisposition;
pub use runtime::run;
pub use runtime::run_with_shutdown;
pub use runtime_tasks::RuntimeTaskFailure;
pub use runtime_tasks::RuntimeTasks;
pub use state::AgentdCircuitTaskInvocationProviderV1;
pub use state::AgentdDesktopObjectiveConfig;
pub use state::AgentdNotesObjectiveConfig;
pub use topology_plasticity_host::AgentdTopologyAdmissionInputV1;
pub use topology_plasticity_host::AgentdTopologyAnchorStoreV1;
pub use topology_plasticity_host::AgentdTopologyHostErrorV1;
pub use topology_plasticity_host::AgentdTopologyWriterStateV1;
pub use topology_plasticity_host::AgentdTopologyWriterV1;
pub use topology_plasticity_host::bootstrap_agentd_topology_writer_v1;
pub use topology_plasticity_host::propose_agentd_topology_plasticity_v1;
pub use topology_plasticity_host::reopen_agentd_topology_writer_v1;
pub use topology_plasticity_host::resolve_agentd_topology_admission_v1;
pub use topology_plasticity_host::resume_agentd_topology_writer_v1;
pub use topology_plasticity_host::rollover_agentd_topology_writer_v1;

use control::AgentdControlServer;
use event_buffer::EventBuffer;
use state::AgentdState;

mod terminal_learning;
mod terminal_learning_runtime;
mod terminal_learning_types;

pub use terminal_learning::AgentdTerminalLearningOwnerV1;
pub use terminal_learning_runtime::TerminalLearningHandleV1;
pub use terminal_learning_runtime::TerminalLearningRuntimeBootstrapV1;
pub use terminal_learning_runtime::terminal_learning_channel_v1;
pub use terminal_learning_types::TerminalLearningBudgetV1;
pub use terminal_learning_types::TerminalLearningErrorV1;
pub use terminal_learning_types::TerminalLearningReceiptV1;
pub use terminal_learning_types::TerminalLearningRequestV1;
pub use terminal_learning_types::TerminalLearningSourceLineageV1;

#[cfg(all(test, target_os = "linux"))]
#[path = "authority_host_learning_service_root_tests.rs"]
mod authority_host_learning_service_root_tests;

#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationCohortConfigV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationCohortCurrentV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationCohortReadbackV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationCohortRuleV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationCohortV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationEpisodeV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationProviderErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationSourceOwnersV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationSourceV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitEvaluationTargetV1;
#[cfg(target_os = "linux")]
pub use circuit_original_evaluation_provider::OriginalCircuitFinalHoldoutProviderV1;

#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationCommandClientV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationCommandConnectionV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationCommandErrorV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationHostV1;
#[cfg(target_os = "linux")]
pub(crate) use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationModelInputV1;
#[cfg(target_os = "linux")]
pub(crate) use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationModelReadV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationModelMaterialClientV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationModelMaterialConnectionV1;
#[cfg(target_os = "linux")]
pub use neuron_cell_evaluation_qualification_owner::OriginalCellEvaluationModelMaterialV1;

#[cfg(target_os = "linux")]
pub use artifact_original_head::ArtifactHeadSigningConfigV1;
#[cfg(target_os = "linux")]
pub use artifact_original_head::OriginalArtifactHeadConnectionV1;
#[cfg(target_os = "linux")]
pub use artifact_original_head::OriginalArtifactHeadErrorV1;
#[cfg(target_os = "linux")]
pub use artifact_original_head::OriginalArtifactHeadOwnerV1;
#[cfg(target_os = "linux")]
pub use artifact_original_head::OriginalArtifactRegistrySourceClientV1;
#[cfg(target_os = "linux")]
pub use artifact_original_head::OriginalArtifactRegistrySourceOwnerV1;

#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitCandidateNextUseCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitCandidateNextUseCommandContextV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitCandidateNextUseCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitCandidateNextUseCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitCandidateNextUseCommandReceiptV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitCandidateLearningReadClientV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitCandidateLearningReadContextV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitCandidateLearningReadErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitCandidateLearningReadOwnerV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitCandidateLearningReadbackV1;
#[cfg(target_os = "linux")]
pub(crate) use circuit_feature_current::OriginalCircuitCandidateCompletionReadinessClientV1;

#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitModelSelectionCommandClientV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitModelSelectionCommandErrorV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitModelSelectionCommandOwnerV1;
#[cfg(target_os = "linux")]
pub use learning_iteration_evidence_client::OriginalCircuitModelSelectionCommandReceiptV1;

#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelArtifactCheckpointV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelTaskInputsV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionClientV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionErrorV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionHostV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionPublicationV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionReadbackV1;
#[cfg(target_os = "linux")]
pub use circuit_feature_current::OriginalCircuitModelVersionRecoveryV1;

#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCellEvaluationCohortCustodyV1;
#[cfg(target_os = "linux")]
pub(crate) use circuit_on_policy_evaluation::OriginalCellEvaluationCohortCurrentV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyAdmissionV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyCohortConfigV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyCohortCurrentV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyCohortReadbackV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyCohortRuleV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyCohortV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyFinalHoldoutProviderV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyHistoryV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyPairV1;
#[cfg(target_os = "linux")]
pub use circuit_on_policy_evaluation::OriginalCircuitOnPolicyProtocolV1;
pub use neuron_cell_evaluation::freeze_paired_cell_learning_evaluation_plan_v1;
