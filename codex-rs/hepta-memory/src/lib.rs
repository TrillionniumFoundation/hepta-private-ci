#![forbid(unsafe_code)]

mod cognitive_compact;
mod cognitive_federation;
mod cognitive_intelligence_writer;
mod cognitive_kg_store;
mod cognitive_memory_store;
mod cognitive_model;
mod cognitive_retrieval;
mod cognitive_runtime;
mod cognitive_store;
mod compact_persistence;
mod framing;
mod h7_feedback;
mod h7_runtime;
mod h7_signed_artifact;
mod h7_trajectory_store;
mod intuition_shadow;
mod local_atomic_witness;
mod local_compact_executor;
mod local_compact_hooks;
mod local_lease_outbox;
mod local_memory_saga;
mod local_policy;
mod local_turn_binding;
mod logical_turn_registry;
mod memory_admission;
mod model_receipt;
mod neuron_proposal;
mod production_writer;
mod recall;
mod shadow_advisory;
mod shadow_model_runtime;

pub use cognitive_compact::COGNITIVE_COMPACT_HOOK_NAMESPACE;
pub use cognitive_compact::COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION;
pub use cognitive_compact::CognitiveCompactError;
pub use cognitive_compact::CompactCheckpoint;
pub use cognitive_compact::CompactCommitDecision;
pub use cognitive_compact::CompactConflictReason;
pub use cognitive_compact::CompactFence;
pub use cognitive_compact::CompactLease;
pub use cognitive_compact::CompactLossReport;
pub use cognitive_compact::CompactParentSnapshot;
pub use cognitive_compact::CompactProtectedRef;
pub use cognitive_compact::CompactRejectReason;
pub use cognitive_compact::CompactSummaryReceipt;
pub use cognitive_compact::RehydrationPlan;
pub use cognitive_compact::RehydrationStatus;
pub use cognitive_federation::FederatedMemoryExplanation;
pub use cognitive_federation::FederatedMemoryReader;
pub use cognitive_federation::FederatedMemoryRevalidationBinding;
pub use cognitive_federation::FederatedRecallSet;
pub use cognitive_federation::FederatedRetrievalBatch;
pub use cognitive_federation::FederatedRetrievalCandidate;
pub use cognitive_federation::FederatedRevalidationStatus;
pub use cognitive_federation::FederationCapability;
pub use cognitive_federation::FederationCapabilityId;
pub use cognitive_federation::FederationCapabilityState;
pub use cognitive_federation::FederationCapabilityStatus;
pub use cognitive_federation::FederationConsumerAccess;
pub use cognitive_federation::FederationGrantRequest;
pub use cognitive_federation::FederationGrantScope;
pub use cognitive_federation::FederationRevalidationDrift;
pub use cognitive_federation::FederationRevocation;
pub use cognitive_federation::MAX_FEDERATION_CAPABILITIES_PER_STORE;
pub use cognitive_federation::MAX_FEDERATION_CAPABILITY_REVISIONS;
pub use cognitive_federation::MAX_FEDERATION_GRANT_LIFETIME_SECONDS;
pub use cognitive_federation::MAX_FEDERATION_SOURCES_PER_AGENT;
pub use cognitive_memory_store::ForgetMemoryDraft;
pub use cognitive_model::CognitiveAccess;
pub use cognitive_model::CognitiveProjectionReceipt;
pub use cognitive_model::CognitiveScope;
pub use cognitive_model::CognitiveWriteReceipt;
pub use cognitive_model::KgEdge;
pub use cognitive_model::KgEntityFactDraft;
pub use cognitive_model::KgFactSetDraft;
pub use cognitive_model::KgNode;
pub use cognitive_model::KgRelationFactDraft;
pub use cognitive_model::LedgerSourceKind;
pub use cognitive_model::MemoryDraft;
pub use cognitive_model::MemoryLifecycleState;
pub use cognitive_model::MemoryRevisionDraft;
pub use cognitive_model::MemoryRevisionId;
pub use cognitive_model::MemoryRevisionRecord;
pub use cognitive_model::MemoryVerification;
pub use cognitive_model::ProjectionGeneration;
pub use cognitive_model::SourceDraft;
pub use cognitive_model::SourceEventId;
pub use cognitive_model::SourceRevisionId;
pub use cognitive_model::StableMemoryId;
pub use cognitive_retrieval::MAX_RETRIEVAL_CHANNEL_CANDIDATES;
pub use cognitive_retrieval::MAX_RETRIEVAL_QUERY_BYTES;
pub use cognitive_retrieval::MAX_RETRIEVAL_RESULTS;
pub use cognitive_retrieval::MemoryExplanation;
pub use cognitive_retrieval::MemoryRevalidationBinding;
pub use cognitive_retrieval::RetrievalBatch;
pub use cognitive_retrieval::RetrievalCandidate;
pub use cognitive_retrieval::RetrievalChannel;
pub use cognitive_retrieval::RetrievalRequest;
pub use cognitive_retrieval::RevalidationDrift;
pub use cognitive_retrieval::RevalidationStatus;
pub use cognitive_retrieval::SourceCitationRecord;
pub use cognitive_retrieval::SourceRevalidationBinding;
pub use cognitive_runtime::CognitiveRuntime;
pub use cognitive_runtime::CognitiveUnavailableReason;
pub use cognitive_store::CognitiveRecoveryAnchor;
pub use cognitive_store::CognitiveRecoveryRequirement;
pub use cognitive_store::CognitiveStore;
pub use cognitive_store::CognitiveStoreError;
pub use compact_persistence::COMPACT_PERSISTENCE_EXTERNAL_EFFECTS;
pub use compact_persistence::COMPACT_PERSISTENCE_KG_WRITE_AUTHORITY;
pub use compact_persistence::COMPACT_PERSISTENCE_NAMESPACE;
pub use compact_persistence::COMPACT_PERSISTENCE_SCHEMA_VERSION;
pub use compact_persistence::CompactPersistenceAppend;
pub use compact_persistence::CompactPersistenceError;
pub use compact_persistence::CompactPersistenceEvent;
pub use compact_persistence::CompactPersistenceEventKind;
pub use compact_persistence::CompactPersistenceJournal;
pub use compact_persistence::CompactPersistenceSnapshot;
pub use compact_persistence::CompactPersistenceState;
pub use compact_persistence::CompactReconcileOutcome;
pub use compact_persistence::CompactRehydrationRecord;
pub use compact_persistence::checkpoint_digest;
pub use framing::workspace_binding_digest;
pub use h7_feedback::H7_FEEDBACK_BPS_SCALE;
pub use h7_feedback::H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED;
pub use h7_feedback::H7_FEEDBACK_EXTERNAL_EFFECTS;
pub use h7_feedback::H7_FEEDBACK_KG_WRITE_AUTHORITY;
pub use h7_feedback::H7_FEEDBACK_MAX_RECORDS;
pub use h7_feedback::H7_FEEDBACK_MAX_TEXT_BYTES;
pub use h7_feedback::H7_FEEDBACK_MAX_WEIGHT_CAP_SCALED;
pub use h7_feedback::H7_FEEDBACK_NAMESPACE;
pub use h7_feedback::H7_FEEDBACK_PRODUCTION_AUTHORITY;
pub use h7_feedback::H7_FEEDBACK_PRODUCTION_CALLER;
pub use h7_feedback::H7_FEEDBACK_REPLAY_ONLY;
pub use h7_feedback::H7_FEEDBACK_SCALE;
pub use h7_feedback::H7_FEEDBACK_SCHEMA_VERSION;
pub use h7_feedback::H7AttemptLeaseScope;
pub use h7_feedback::H7CreditLedger;
pub use h7_feedback::H7FeedbackAppend;
pub use h7_feedback::H7FeedbackBinding;
pub use h7_feedback::H7FeedbackError;
pub use h7_feedback::H7FeedbackKey;
pub use h7_feedback::H7FeedbackOracle;
pub use h7_feedback::H7FeedbackRecord;
pub use h7_feedback::H7OfflineEvaluation;
pub use h7_feedback::H7PolicyAction;
pub use h7_feedback::H7Propensity;
pub use h7_feedback::H7Support;
pub use h7_runtime::H7_QUALIFICATION_RUNTIME_EXTERNAL_EFFECTS;
pub use h7_runtime::H7_QUALIFICATION_RUNTIME_NAMESPACE;
pub use h7_runtime::H7_QUALIFICATION_RUNTIME_PRODUCTION_AUTHORITY;
pub use h7_runtime::H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION;
pub use h7_runtime::H7Approval;
pub use h7_runtime::H7Artifact;
pub use h7_runtime::H7Evaluation;
pub use h7_runtime::H7QualificationRuntime;
pub use h7_runtime::H7RuntimeError;
pub use h7_runtime::H7RuntimeState;
pub use h7_runtime::H7Trajectory;
pub use h7_runtime::H7TrajectoryEvent;
pub use h7_runtime::H7Transition;
pub use h7_signed_artifact::H7_SIGNED_ARTIFACT_MAX_LIFETIME_SECONDS;
pub use h7_signed_artifact::H7_SIGNED_ARTIFACT_NAMESPACE;
pub use h7_signed_artifact::H7_SIGNED_ARTIFACT_SCHEMA_VERSION;
pub use h7_signed_artifact::H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM;
pub use h7_signed_artifact::H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN;
pub use h7_signed_artifact::H7ArtifactSigner;
pub use h7_signed_artifact::H7ArtifactVerifier;
pub use h7_signed_artifact::H7OpeEnvelope;
pub use h7_signed_artifact::H7SignedArtifact;
pub use h7_signed_artifact::H7SignedArtifactEnvelope;
pub use h7_signed_artifact::H7SignedArtifactError;
pub use h7_signed_artifact::H7SignedArtifactTransition;
pub use h7_signed_artifact::H7SignedOpeEnvelope;
pub use h7_trajectory_store::H7_TRAJECTORY_EXTERNAL_EFFECTS;
pub use h7_trajectory_store::H7_TRAJECTORY_KG_WRITE_AUTHORITY;
pub use h7_trajectory_store::H7_TRAJECTORY_NAMESPACE;
pub use h7_trajectory_store::H7_TRAJECTORY_PRODUCTION_CALLER;
pub use h7_trajectory_store::H7_TRAJECTORY_SCHEMA_VERSION;
pub use h7_trajectory_store::H7ExpiredTerminalWitness;
pub use h7_trajectory_store::H7TrajectoryAppend;
pub use h7_trajectory_store::H7TrajectoryEventKind;
pub use h7_trajectory_store::H7TrajectoryRead;
pub use h7_trajectory_store::H7TrajectoryRecord;
pub use h7_trajectory_store::H7TrajectoryRecoveryRead;
pub use h7_trajectory_store::H7TrajectoryStoreError;
pub use h7_trajectory_store::append_h7_trajectory_event_bound;
pub use h7_trajectory_store::h7_trajectory_local_receipt_digest;
pub use h7_trajectory_store::inspect_expired_terminal_h7;
pub use h7_trajectory_store::read_h7_trajectory_bound;
pub use h7_trajectory_store::read_h7_trajectory_bound_for_recovery;
pub use intuition_shadow::H6_INTUITION_SHADOW_NAMESPACE;
pub use intuition_shadow::H6_INTUITION_SHADOW_SCHEMA_VERSION;
pub use intuition_shadow::IntuitionAbstainReason;
pub use intuition_shadow::IntuitionCandidate;
pub use intuition_shadow::IntuitionDecision;
pub use intuition_shadow::IntuitionMode;
pub use intuition_shadow::IntuitionShadowAuthority;
pub use intuition_shadow::IntuitionShadowError;
pub use intuition_shadow::IntuitionShadowInput;
pub use intuition_shadow::IntuitionShadowPhase;
pub use intuition_shadow::IntuitionShadowReceipt;
pub use intuition_shadow::MAX_INTUITION_CANDIDATE_ID_BYTES;
pub use intuition_shadow::MAX_INTUITION_CANDIDATES;
pub use intuition_shadow::intuition_schema_digest;
pub use intuition_shadow::shadow_intuition_decide;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_EXTERNAL_EFFECTS;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_KG_WRITE_AUTHORITY;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_LEASE_EPOCH_BOUND;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_LEASE_EXPIRY_BOUND;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_LIFECYCLE_REGISTERED;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_NAMESPACE;
pub use local_atomic_witness::LOCAL_ATOMIC_WITNESS_SCHEMA_VERSION;
pub use local_atomic_witness::LocalAtomicWitnessError;
pub use local_atomic_witness::LocalAtomicWitnessFault;
pub use local_atomic_witness::LocalRehydrationWitnessReceipt;
pub use local_atomic_witness::LocalRehydrationWitnessWrite;
pub use local_atomic_witness::write_local_rehydration_witness;
pub use local_atomic_witness::write_local_rehydration_witness_with_fault;
pub use local_compact_executor::LOCAL_COMPACT_EXECUTOR_EXTERNAL_EFFECTS;
pub use local_compact_executor::LOCAL_COMPACT_EXECUTOR_KG_WRITE_AUTHORITY;
pub use local_compact_executor::LOCAL_COMPACT_EXECUTOR_NAMESPACE;
pub use local_compact_executor::LOCAL_COMPACT_EXECUTOR_SCHEMA_VERSION;
pub use local_compact_executor::LocalCompactExecutor;
pub use local_compact_executor::LocalCompactExecutorError;
pub use local_compact_executor::LocalCompactLeaseBinding;
pub use local_compact_executor::LocalRehydrationRead;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_NAMESPACE;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_PROMOTION;
pub use local_compact_hooks::LOCAL_COMPACT_HOOKS_SCHEMA_VERSION;
pub use local_compact_hooks::LocalCompactHook;
pub use local_compact_hooks::LocalCompactHookReceipt;
pub use local_compact_hooks::LocalCompactHooksError;
pub use local_lease_outbox::LOCAL_LEASE_OUTBOX_EXTERNAL_EFFECTS;
pub use local_lease_outbox::LOCAL_LEASE_OUTBOX_KG_WRITE_AUTHORITY;
pub use local_lease_outbox::LOCAL_LEASE_OUTBOX_NAMESPACE;
pub use local_lease_outbox::LOCAL_LEASE_OUTBOX_PRODUCTION_CALLER;
pub use local_lease_outbox::LOCAL_LEASE_OUTBOX_SCHEMA_VERSION;
pub use local_lease_outbox::LocalAdmission;
pub use local_lease_outbox::LocalAdmissionFault;
pub use local_lease_outbox::LocalLease;
pub use local_lease_outbox::LocalLeaseAcquire;
pub use local_lease_outbox::LocalLeaseBinding;
pub use local_lease_outbox::LocalLeaseHeadDisposition;
pub use local_lease_outbox::LocalLeaseHeadInspection;
pub use local_lease_outbox::LocalLeaseOutbox;
pub use local_lease_outbox::LocalLeaseOutboxCounts;
pub use local_lease_outbox::LocalLeaseOutboxError;
pub use local_lease_outbox::LocalLeaseState;
pub use local_lease_outbox::LocalOutcomeReceipt;
pub use local_lease_outbox::LocalOutcomeState;
pub use local_lease_outbox::LocalReconcileOutcome;
pub use local_lease_outbox::LocalReplayFinalization;
pub use local_lease_outbox::QueuedReceipt;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_NAMESPACE;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION;
pub use local_memory_saga::LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION;
pub use local_memory_saga::LocalMemoryAdmissionError;
pub use local_memory_saga::LocalMemoryAdmissionReceipt;
pub use local_memory_saga::LocalMemoryAdmissionState;
pub use local_policy::LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_NAMESPACE;
pub use local_policy::LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_SCHEMA_VERSION;
pub use local_policy::LocalDevelopmentLifecyclePolicy;
pub use local_policy::LocalDevelopmentLifecyclePolicyError;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_EXTERNAL_EFFECTS;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_KG_WRITE_AUTHORITY;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_LIFECYCLE_REGISTERED;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_NAMESPACE;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_PRODUCTION_CALLER;
pub use local_turn_binding::LOCAL_TURN_LIFECYCLE_BINDING_SCHEMA_VERSION;
pub use local_turn_binding::LocalTurnLifecycleBinding;
pub use local_turn_binding::LocalTurnLifecycleBindingError;
pub use logical_turn_registry::LOGICAL_TURN_REGISTRY_EXTERNAL_EFFECTS;
pub use logical_turn_registry::LOGICAL_TURN_REGISTRY_KG_WRITE_AUTHORITY;
pub use logical_turn_registry::LOGICAL_TURN_REGISTRY_NAMESPACE;
pub use logical_turn_registry::LOGICAL_TURN_REGISTRY_PRODUCTION_CALLER;
pub use logical_turn_registry::LOGICAL_TURN_REGISTRY_SCHEMA_VERSION;
pub use logical_turn_registry::LogicalTurnAttempt;
pub use logical_turn_registry::LogicalTurnAttemptRequest;
pub use logical_turn_registry::LogicalTurnAttemptTransition;
pub use logical_turn_registry::LogicalTurnEvidence;
pub use logical_turn_registry::LogicalTurnInspection;
pub use logical_turn_registry::LogicalTurnInspectionDisposition;
pub use logical_turn_registry::LogicalTurnRegistryError;
pub use logical_turn_registry::LogicalTurnRequest;
pub use logical_turn_registry::LogicalTurnReservation;
pub use memory_admission::MemoryAdmissionEvidence;
pub use memory_admission::MemoryAdmissionReceipt;
pub use memory_admission::MemoryCandidateDraft;
pub use memory_admission::MemoryCandidateOrigin;
pub use memory_admission::MemoryCandidateState;
pub use model_receipt::MODEL_RECEIPT_EFFECT_AUTHORITY;
pub use model_receipt::MODEL_RECEIPT_EXECUTE_ALLOWED;
pub use model_receipt::MODEL_RECEIPT_EXTERNAL_EFFECTS;
pub use model_receipt::MODEL_RECEIPT_G5_ALLOWED;
pub use model_receipt::MODEL_RECEIPT_NAMESPACE;
pub use model_receipt::MODEL_RECEIPT_OPERATOR_ACCEPTANCE;
pub use model_receipt::MODEL_RECEIPT_PRODUCTION_AUTHORITY;
pub use model_receipt::MODEL_RECEIPT_PRODUCTION_CALLER;
pub use model_receipt::MODEL_RECEIPT_PRODUCTION_WRITER;
pub use model_receipt::MODEL_RECEIPT_PROMOTION;
pub use model_receipt::MODEL_RECEIPT_RUNTIME_AUTHORITY;
pub use model_receipt::MODEL_RECEIPT_SCHEMA_VERSION;
pub use model_receipt::MODEL_RECEIPT_SHADOW_ONLY;
pub use model_receipt::ModelApprovalState;
pub use model_receipt::ModelClaimLevel;
pub use model_receipt::ModelEfficacyStatus;
pub use model_receipt::ModelEvidenceClass;
pub use model_receipt::ModelEvidenceStatus;
pub use model_receipt::ModelReceipt;
pub use model_receipt::ModelReceiptBindings;
pub use model_receipt::ModelReceiptChain;
pub use model_receipt::ModelReceiptError;
pub use neuron_proposal::H5_NEURON_PROPOSAL_SCHEMA_VERSION;
pub use neuron_proposal::MAX_NEURON_FEATURE_KEY_BYTES;
pub use neuron_proposal::MAX_NEURON_FEATURES;
pub use neuron_proposal::MAX_NEURON_UPDATE_BPS;
pub use neuron_proposal::NeuronAbstainReason;
pub use neuron_proposal::NeuronFeature;
pub use neuron_proposal::NeuronParameter;
pub use neuron_proposal::NeuronPosition;
pub use neuron_proposal::NeuronProposal;
pub use neuron_proposal::NeuronProposalAuthority;
pub use neuron_proposal::NeuronProposalDecision;
pub use neuron_proposal::NeuronProposalError;
pub use neuron_proposal::NeuronProposalInput;
pub use neuron_proposal::NeuronProposalPhase;
pub use neuron_proposal::shadow_neuron_propose;
pub use production_writer::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
pub use production_writer::PRODUCTION_DURABLE_WRITER_NAMESPACE;
pub use production_writer::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
pub use production_writer::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;
pub use production_writer::ProductionAuthorityLease;
pub use production_writer::ProductionAuthorityToken;
pub use production_writer::ProductionAuthorityVerifier;
pub use production_writer::ProductionDispatchFuture;
pub use production_writer::ProductionDispatchReceipt;
pub use production_writer::ProductionDispatchRequest;
pub use production_writer::ProductionDurableWriter;
pub use production_writer::ProductionLeaseReceipt;
pub use production_writer::ProductionOutboxDispatcher;
pub use production_writer::ProductionOutboxTarget;
pub use production_writer::ProductionOutcomeReceipt;
pub use production_writer::ProductionQueuedReceipt;
pub use production_writer::ProductionRecoveryReceipt;
pub use production_writer::ProductionTargetOutcome;
pub use production_writer::ProductionWriterError;
pub use recall::RECALL_OBSERVATION_SCHEMA_VERSION;
pub use recall::RecallCandidate;
pub use recall::RecallCounts;
pub use recall::RecallObservation;
pub use recall::RecallObservationId;
pub use recall::RecallObservationReason;
pub use recall::shadow_recall;
pub use shadow_advisory::SHADOW_ADVISORY_NAMESPACE;
pub use shadow_advisory::SHADOW_ADVISORY_SCHEMA_VERSION;
pub use shadow_advisory::ShadowAdvisoryError;
pub use shadow_advisory::ShadowAdvisoryInput;
pub use shadow_advisory::ShadowAdvisoryReceipt;
pub use shadow_advisory::shadow_advisory_evaluate;
pub use shadow_model_runtime::MODEL_RECEIPT_SCHEMA_GAPS;
pub use shadow_model_runtime::RunStartSnapshot;
pub use shadow_model_runtime::RunStartSnapshotInput;
pub use shadow_model_runtime::SHADOW_MODEL_RUNTIME_NAMESPACE;
pub use shadow_model_runtime::SHADOW_MODEL_RUNTIME_SCHEMA_VERSION;
pub use shadow_model_runtime::ShadowExecutionScope;
pub use shadow_model_runtime::ShadowModelRuntimeBinding;
pub use shadow_model_runtime::ShadowModelRuntimeError;
pub use shadow_model_runtime::ShadowPrivacyProfile;
pub use shadow_model_runtime::ShadowResourceBudget;
pub use shadow_model_runtime::ShadowRunFence;

#[cfg(test)]
#[path = "cognitive_store_tests.rs"]
mod cognitive_store_tests;

#[cfg(test)]
#[path = "cognitive_federation_tests.rs"]
mod cognitive_federation_tests;

#[cfg(test)]
#[path = "cognitive_memory_store_tests.rs"]
mod cognitive_memory_store_tests;

#[cfg(test)]
#[path = "cognitive_kg_store_tests.rs"]
mod cognitive_kg_store_tests;

#[cfg(test)]
#[path = "cognitive_intelligence_writer_tests.rs"]
mod cognitive_intelligence_writer_tests;

#[cfg(test)]
#[path = "cognitive_retrieval_tests.rs"]
mod cognitive_retrieval_tests;

#[cfg(test)]
#[path = "cognitive_runtime_tests.rs"]
mod cognitive_runtime_tests;

#[cfg(test)]
#[path = "cognitive_compact_tests.rs"]
mod cognitive_compact_tests;

#[cfg(test)]
#[path = "local_atomic_witness_tests.rs"]
mod local_atomic_witness_tests;

#[cfg(test)]
#[path = "compact_persistence_tests.rs"]
mod compact_persistence_tests;

#[cfg(test)]
#[path = "local_compact_executor_tests.rs"]
mod local_compact_executor_tests;

#[cfg(test)]
#[path = "local_lease_outbox_tests.rs"]
mod local_lease_outbox_tests;

#[cfg(test)]
#[path = "logical_turn_registry_tests.rs"]
mod logical_turn_registry_tests;

#[cfg(test)]
#[path = "h7_artifact_qualification_tests.rs"]
mod h7_artifact_qualification_tests;

#[cfg(test)]
#[path = "h7_trajectory_store_tests.rs"]
mod h7_trajectory_store_tests;

#[cfg(test)]
#[path = "h7_feedback_tests.rs"]
mod h7_feedback_tests;

#[cfg(test)]
#[path = "model_receipt_tests.rs"]
mod model_receipt_tests;

#[cfg(test)]
mod cognitive_test_support;
