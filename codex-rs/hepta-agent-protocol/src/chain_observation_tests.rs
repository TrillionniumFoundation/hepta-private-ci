use crate::AutomationEffectChainObservation;
use crate::AutomationEffectObservation;
use crate::AutomationEffectReconcileSnapshot;
use crate::AutomationEffectReconcileState;
use crate::AutomationEffectSnapshot;
use codex_hepta_contracts::Sha256Digest;
use serde_json::json;

#[test]
fn legacy_reconcile_without_chain_remains_indeterminate() {
    // Older responses omit chain; neither omission nor null proves absence.
    let expected = AutomationEffectReconcileSnapshot {
        state: AutomationEffectReconcileState::Indeterminate,
        effect: None,
        chain: None,
    };
    for wire in [
        json!({"state": "indeterminate", "effect": null}),
        json!({"state": "indeterminate", "effect": null, "chain": null}),
    ] {
        assert_eq!(
            serde_json::from_value::<AutomationEffectReconcileSnapshot>(wire)
                .expect("parse legacy or explicit-null observation"),
            expected
        );
    }
}

#[test]
fn reconcile_wire_preserves_reorg_observation_and_terminal_effect() {
    // A stored block leaving the active chain does not undo the terminal submit.
    let snapshot = AutomationEffectReconcileSnapshot {
        state: AutomationEffectReconcileState::Terminal,
        effect: Some(AutomationEffectSnapshot {
            run_id: "run-effect".to_string(),
            step_id: "effect".to_string(),
            attempt: 1,
            event_seq: 4,
            receipt_digest: Some(Sha256Digest::for_bytes(b"terminal-receipt")),
            observation: AutomationEffectObservation::Succeeded,
        }),
        chain: Some(AutomationEffectChainObservation {
            schema_version: 1,
            block_id: "a".repeat(64),
            stored_exact: true,
            block_height: Some(10),
            active_tip: "b".repeat(64),
            active_tip_height: 12,
            active_chain_member: false,
            active_depth: None,
            owner_generation: 7,
            local_target_only: true,
            global_absence_authority: false,
            confirmation_authority: false,
            finality_authority: false,
            execution_authority: false,
        }),
    };
    let mut wire = serde_json::to_value(&snapshot).expect("serialize chain observation");
    assert_eq!(
        serde_json::from_value::<AutomationEffectReconcileSnapshot>(wire.clone())
            .expect("parse chain observation"),
        snapshot
    );
    wire["chain"]["unexpected_authority"] = json!(true);
    assert!(serde_json::from_value::<AutomationEffectReconcileSnapshot>(wire).is_err());
}
