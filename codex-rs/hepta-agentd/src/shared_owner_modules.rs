// Unique shared original-owner module declarations for Full and Native roots.
// Both roots compile these exact source files; runtime selection grants no authority.

mod lifecycle_signal;
mod process_identity;

#[cfg(target_os = "linux")]
mod authority_host_consumer_frontier;
#[cfg(target_os = "linux")]
pub use authority_host_consumer_frontier::HostConsumerFrontier;
#[cfg(target_os = "linux")]
mod authority_host_checkpoint;
#[cfg(target_os = "linux")]
mod authority_host_material;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::HostCognitiveCheckpoint;
#[cfg(target_os = "linux")]
pub use authority_host_checkpoint::HostCognitiveCheckpointRegistration;
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
pub use authority_host_config::HostAuthorityConsumerConfig;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityConsumersConfig;
#[cfg(target_os = "linux")]
pub use authority_host_config::HostAuthorityRegisteredIdentity;
#[cfg(target_os = "linux")]
mod authority_host_runtime;
#[cfg(target_os = "linux")]
mod authority_host_service;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::initialize_host_authority;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::register_host_writer_authorization;
#[cfg(target_os = "linux")]
pub use authority_host_runtime::serve_host_authority_session;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityBootstrapLocations;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityLane;
#[cfg(target_os = "linux")]
pub use authority_host_service::HostAuthorityService;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesAuthorityStartup;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesAwaitingSession;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesLaunchServer;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesReservedTarget;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesSessionChannels;
#[cfg(target_os = "linux")]
pub use authority_host_service::RootNotesStartupCancellation;
#[cfg(target_os = "linux")]
mod root_notes_host_config;
#[cfg(target_os = "linux")]
mod root_role_executable;
#[cfg(target_os = "linux")]
pub use root_role_executable::RootRoleExecutable;
#[cfg(target_os = "linux")]
mod root_notes_native_launcher;
#[cfg(target_os = "linux")]
mod root_role_child;
#[cfg(target_os = "linux")]
mod root_role_fork;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::RootNativeHostDescriptors;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::RootSessionEnvironment;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::seal_root_notes_host_config;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::spawn_root_native_notes_host;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::spawn_root_notes_host;
#[cfg(target_os = "linux")]
pub use root_notes_native_launcher::spawn_root_notes_session;
#[cfg(target_os = "linux")]
pub use root_role_child::RootRoleChild;
#[cfg(target_os = "linux")]
mod root_notes_launch_channel;
#[cfg(target_os = "linux")]
mod root_notes_launch_io;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::ROOT_NOTES_HOST_CONFIG_BOUND;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::ROOT_NOTES_HOST_CONFIG_OPERATION_V1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesAgentPathsV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesAuthBusPathsV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesDeploymentV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesHostConfigV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesInstalledBindingsV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesInstalledBundleV1;
#[cfg(target_os = "linux")]
pub use root_notes_host_config::RootNotesLaunchEndpointV1;
#[cfg(target_os = "linux")]
pub use root_notes_launch_channel::RootNotesLaunchAbort;
#[cfg(target_os = "linux")]
pub use root_notes_launch_channel::RootNotesLaunchChannel;
#[cfg(target_os = "linux")]
mod root_notes_launch_wire;
#[cfg(target_os = "linux")]
pub use root_notes_launch_wire::ROOT_NOTES_LAUNCH_FRAME_BOUND;
#[cfg(target_os = "linux")]
pub use root_notes_launch_wire::ROOT_NOTES_PREPARATION_NS;
#[cfg(target_os = "linux")]
pub use root_notes_launch_wire::ROOT_NOTES_TOTAL_PREPARATION_NS;
#[cfg(target_os = "linux")]
pub use root_notes_launch_wire::RootNotesLaunchFrame;
#[cfg(target_os = "linux")]
mod root_authority_session;
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
#[cfg(target_os = "linux")]
mod cognitive_checkpoint_unix;
#[cfg(target_os = "linux")]
mod deployment_frontier;
mod process_config;
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
pub use deployment_issuer::RootNotesGrantAdmission;
mod error;
mod event_buffer;
#[cfg(target_os = "linux")]
mod final_use_issuer;
mod grant_provider_worker;
#[cfg(target_os = "linux")]
mod hos2_device;
#[cfg(target_os = "linux")]
mod native_cpu_entry;
#[cfg(target_os = "linux")]
mod native_cpu_ingress;
#[cfg(target_os = "linux")]
mod native_cpu_runtime;
#[cfg(target_os = "linux")]
mod notes_document_observer;
#[cfg(target_os = "linux")]
pub use native_cpu_entry::run_native_cpu_daemon;
mod runtime_tasks;
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
#[cfg(target_os = "linux")]
pub use cognitive_checkpoint_unix::AgentdCognitiveCheckpointPeer;
#[cfg(target_os = "linux")]
pub use cognitive_checkpoint_unix::AgentdUnixCognitiveCheckpointTransport;
pub use config::AgentdIdentity;
use control::AgentdControlServer;
pub use error::AgentdError;
use event_buffer::EventBuffer;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerError;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerPeer;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdUnixFinalUseGrantProvider;
#[cfg(target_os = "linux")]
pub use hos2_device::AgentdHos2Device;
#[cfg(target_os = "linux")]
pub use hos2_device::AgentdHos2Usage;
#[cfg(target_os = "linux")]
pub use notes_document_observer::AgentdNotesDocumentObserver;
pub use objective_runtime::authbus_objective_claims;
pub use process_identity::HEPTA_AGENT_GENERATION_ENV;
pub use process_identity::HEPTA_AGENT_HOME_ENV;
pub use process_identity::HEPTA_AGENT_ID_ENV;
pub use process_identity::HEPTA_AGENT_RUN_ROOT_ENV;
pub use production_writer_host::AgentdFinalUseGrantProvider;
pub use production_writer_host::AgentdProductionOperationRuntimeConfig;
pub use production_writer_host::AgentdProductionWriterHost;
pub use production_writer_host::AgentdProtectedCheckpointInputs;
pub use runtime_tasks::RuntimeTaskFailure;
pub use runtime_tasks::RuntimeTasks;
use state::AgentdState;
