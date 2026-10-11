//! Exact native owner-footprint guards for shared-Stem transitive deployments.
//! These static bounds do not imply live CPU/RSS, real Jina execution or NDU.

#[test]
fn long_lived_owner_outcome_enums_do_not_embed_large_mutable_snapshots() {
    use std::mem::size_of;

    // One pointer plus the discriminant; the full TaskFlow receipt is
    // materialized only at the Agentd response boundary after revalidation.
    assert!(size_of::<crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome>() <= 32);

    // A PreparedAgentdIntelligenceRunV1 is >1 KiB. The admission/result
    // envelopes keep only its owned pointer while preserving full contents.
    assert!(size_of::<crate::AgentdIntelligenceProductOutcomeV1>() <= 32);
    assert!(size_of::<crate::AgentdIntelligenceAdmittedOutcomeV1>() <= 256);

    // Indeterminate ledger work remains recoverable, but its complete
    // checkpoint + event payload must not inflate every error variant.
    assert!(size_of::<crate::intelligence_product::AgentdIntelligenceLedgerError>() <= 128);
}
