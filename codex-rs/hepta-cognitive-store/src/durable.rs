//! Canonical production boundary for the durable cognitive owner.
//!
//! `hepta-cognitive-store` owns the module API and semantic invariants.
//! `hepta-memory::CognitiveStore` remains the single physical SQLite owner;
//! this module re-exports typed contracts rather than introducing a second
//! database, migration set, writer identity, or synchronization path.
//!
//! The mutable backend alias is intentionally feature-gated. Ordinary product
//! crates receive contracts, receipts and read projections but cannot name the
//! raw writer type. Only the named Agentd production host, or an explicit
//! qualification build, may opt into that alias. Repository architecture
//! verification separately rejects direct semantic mutations outside the
//! physical owner and the sealed Agentd capability boundary.

pub const DURABLE_BACKEND_ID: &str = "hepta-memory::CognitiveStore";
pub const DURABLE_DATABASE_BASENAME: &str = "cognitive_1.sqlite3";
pub const DURABLE_SINGLE_WRITER: bool = true;

pub use codex_hepta_memory::CognitiveAccess;
pub use codex_hepta_memory::CognitiveRecoveryAnchor;
pub use codex_hepta_memory::CognitiveRecoveryError;
pub use codex_hepta_memory::CognitiveRecoveryRequirement;
pub use codex_hepta_memory::CognitiveScope;
#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
pub use codex_hepta_memory::CognitiveStore as DurableCognitiveStore;
pub use codex_hepta_memory::CognitiveStoreError as DurableCognitiveStoreError;
pub use codex_hepta_memory::CognitiveWriteReceipt;
pub use codex_hepta_memory::DurableCognitiveSnapshot;
pub use codex_hepta_memory::DurableCognitiveSnapshotCursor;
pub use codex_hepta_memory::DurableCognitiveSnapshotPage;
pub use codex_hepta_memory::ForgetMemoryDraft;
pub use codex_hepta_memory::KgFactSetDraft;
pub use codex_hepta_memory::LedgerSourceKind;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_CITATIONS;
pub use codex_hepta_memory::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
pub use codex_hepta_memory::MemoryDraft;
pub use codex_hepta_memory::MemoryLifecycleState;
pub use codex_hepta_memory::MemoryRevisionDraft;
pub use codex_hepta_memory::MemoryVerification;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION;
pub use codex_hepta_memory::ProductionAuthorityLease;
pub use codex_hepta_memory::ProductionAuthorityToken;
pub use codex_hepta_memory::ProductionAuthorityVerifier;
pub use codex_hepta_memory::ProductionCognitiveMutation;
pub use codex_hepta_memory::ProductionCognitiveMutationCapability;
pub use codex_hepta_memory::ProductionCognitiveMutationError;
pub use codex_hepta_memory::ProductionCognitiveMutationFuture;
pub use codex_hepta_memory::ProductionDispatchFuture;
pub use codex_hepta_memory::ProductionDispatchReceipt;
pub use codex_hepta_memory::ProductionDispatchRequest;
pub use codex_hepta_memory::ProductionDurableWriter;
pub use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
pub use codex_hepta_memory::ProductionOutboxTarget;
pub use codex_hepta_memory::ProductionQueuedReceipt;
pub use codex_hepta_memory::ProductionWriterError;
pub use codex_hepta_memory::RecoveredCognitiveReadOnly;
pub use codex_hepta_memory::SourceDraft;
pub use codex_hepta_memory::StableMemoryId;
