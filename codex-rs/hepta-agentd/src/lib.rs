//! One-process-per-workspace Hepta agent host.
//!
//! `agentd` binds exactly one fleet `AgentId`, embeds the existing Codex App
//! Server execution path, and exposes a small local lifecycle/control socket.
//! It does not implement a second runtime kernel or a fleet-wide message bus.

include!("shared_owner_modules.rs");

mod app_runtime;

mod authbus_checkpoint;
mod authbus_dispatch;
mod authbus_ingress;
mod authbus_trust;
mod automation;
mod automation_effect_host;
mod automation_recovery;
mod browser_servo;
mod client;
mod cognitive_context;
mod cognitive_ranker;
mod cognitive_retrieval_context;
mod cognitive_retrieval_learning;
mod config;
mod control;
mod evidence_frontier;
mod evidence_host;
mod evidence_trust;
mod intelligence_ingress;
mod intelligence_product;
mod intuition_policy;
mod lane_b_runtime;
mod neuron_runtime;
#[cfg(target_os = "linux")]
mod notes_bootstrap;
#[cfg(unix)]
mod notes_channel;
#[cfg(target_os = "linux")]
mod notes_organ;
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
mod production_writer_host;
mod prompt_runtime;
mod qualification_writer;
mod runtime;
#[cfg(target_os = "linux")]
pub use notes_organ::run_notes_organ;
#[cfg(target_os = "linux")]
pub use notes_organ::run_notes_organ_until;
mod shared_terminal_cell;
mod state;
pub use shared_terminal_cell::AgentdSharedReplayHostV1;
pub use shared_terminal_cell::SharedTerminalCandidateV1;
pub use shared_terminal_cell::SharedTerminalCellError;
pub use shared_terminal_cell::SharedTerminalModelV1;
#[doc(hidden)]
pub mod test_support;
mod topology_plasticity_host;

pub use authbus_ingress::authbus_text_claims;
pub use browser_servo::BrowserFinalUseInvocation;
pub use browser_servo::BrowserServoCall;
pub use browser_servo::BrowserServoError;
pub use browser_servo::BrowserServoMethod;
pub use browser_servo::BrowserServoPort;
pub use browser_servo::BrowserServoProcessConfig;
pub use browser_servo::BrowserServoTransport;
pub use browser_servo::ChildBrowserTransport;
pub use client::AgentdClient;
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
pub use cognitive_ranker::CurrentCognitiveRegistry;
pub use cognitive_ranker::PinnedCognitiveRanker;
pub use cognitive_ranker::cognitive_action_id;
pub use cognitive_ranker::cognitive_sensor_id;
pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;
pub use cognitive_retrieval_learning::CognitiveRetrievalLearningSink;
pub use config::AgentdConfig;
pub use config::CognitiveRetrievalMode;
pub use config::HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV;
pub use evidence_frontier::EvidenceRecoveryFrontierV1;
pub use evidence_frontier::evidence_recovery_frontier_signing_bytes;
pub use evidence_host::kernel_evidence_claims;
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
pub use intelligence_product::intelligence_evaluation_binding_payload_v1;
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
pub use neuron_runtime::AgentdNeuronOwner;
#[cfg(unix)]
pub use notes_channel::AgentdNotesChannel;
pub use plasticity_host::AgentdPlasticityAdmissionInputV1;
pub use plasticity_host::AgentdPlasticityAnchorStoreV1;
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
pub use prompt_runtime::AgentdPromptPipelineError;
pub use prompt_runtime::AgentdPromptPipelineOwner;
pub use prompt_runtime::AgentdPromptRuntimeError;
pub use prompt_runtime::AgentdPromptRuntimeOwner;
pub use prompt_runtime::PromptRuntimeStageDisposition;
pub use runtime::run;
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
