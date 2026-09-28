// Keep the reviewed durable-learning implementation at the original module
// depth. The nested current-time boundary below can access its private payload,
// destination-observation and authority helpers without duplicating the outbox
// or introducing another writer.
//
// Generated-source anchors retained from the included implementation body:
// - append_intelligence_decision_v1
// - append_intelligence_outcome_v1
// - DurableOperationStore
// - reconcile_unsettled
// - VerifiedEvidenceBindingPayloadV1
// - record.event == expected
// - intelligence_physical_terminal_binding_digest_v1
// - AgentdIntelligenceLearningDispositionV1
include!("intelligence_learning_base.rs");

#[path = "intelligence_learning_current.rs"]
mod current_time;
