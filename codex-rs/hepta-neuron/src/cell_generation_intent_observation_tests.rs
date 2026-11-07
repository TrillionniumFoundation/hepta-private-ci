use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::support::*;
use crate::CellCostStageV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationJournalV2;
use crate::cell_test_support::checked;

fn retained(fixture: &Fixture) -> (Vec<u8>, Vec<u8>) {
    (
        fixture.bytes(),
        checked(fs::read(fixture.0.join("witness"))),
    )
}

#[test]
fn missing_pending_and_changed_intents_are_read_only_and_preserve_original_request() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let original = request(&owner, "claimed-response-lost");
    let intent = checked(original.intent());
    let before = retained(&fixture);
    let missing = checked(owner.observe_intent(&intent));
    assert!(missing.is_missing());
    assert_eq!(missing.intent(), &intent);
    assert_eq!(missing.pending_request(), None);
    assert_eq!(missing.receipt(), None);
    assert_eq!(missing.pending_output(), None);
    assert_eq!(owner.observe_intent(&intent), Ok(missing));
    assert_eq!(retained(&fixture), before);

    checked(owner.admit(original.clone(), /*now_micros*/ 11));
    checked(owner.observe_dispatch_time(checked(original.digest()), /*observed_at_micros*/ 12));
    checked(owner.cancel(checked(original.digest())));
    let before = retained(&fixture);
    let pending = checked(owner.observe_intent(&intent));
    assert!(!pending.is_missing());
    assert_eq!(pending.pending_request(), Some(&original));
    assert_eq!(pending.receipt(), None);
    assert_eq!(pending.pending_output(), None);
    assert_eq!(pending.scope(), &original.predecessor.scope);
    assert_eq!(
        pending.manifest_digest(),
        original.predecessor.manifest_digest
    );
    assert_eq!(
        pending.owner_checkpoint(),
        checked(owner.continuity_checkpoint())
    );
    for mutation in 0..5 {
        let mut changed = intent.clone();
        match mutation {
            0 => changed.task_digest = [90; 32],
            1 => changed.source_frontier = [91; 32],
            2 => changed.predecessor_digest = [92; 32],
            3 => changed.input_digest = [93; 32],
            4 => changed.deadline_micros += 1,
            _ => unreachable!(),
        }
        assert_eq!(
            owner.observe_intent(&changed),
            Err(CellGenerationErrorV2::Conflict)
        );
    }
    assert_eq!(retained(&fixture), before);
    drop(owner);
    let reopened = fixture.open();
    assert_eq!(reopened.observe_intent(&intent), Ok(pending));
    assert_eq!(retained(&fixture), before);
}

#[test]
fn original_receipt_cost_and_output_survive_reopen_without_absorbing_other_costs() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    checked(owner.record_cost(charge("before-step", CellCostStageV2::ModelAcquisition)));
    let original = request(&owner, "original");
    let intent = checked(original.intent());
    checked(owner.admit(original.clone(), /*now_micros*/ 11));
    let proposed = proposal(&original);
    let receipt = checked(owner.commit(proposed.clone(), /*now_micros*/ 12));
    checked(owner.record_cost(charge("after-step", CellCostStageV2::Recovery)));
    let output = checked(checked(owner.pending_output()).cloned().ok_or("outbox"));
    let before = retained(&fixture);
    let observed = checked(owner.observe_intent(&intent));
    assert_eq!(observed.receipt(), Some(&receipt));
    assert_eq!(receipt.cost, proposed.cost);
    assert_ne!(checked(owner.task_cost()), &receipt.cost);
    assert_eq!(observed.pending_output(), Some(&output));
    assert_eq!(observed.pending_request(), None);
    assert_eq!(
        observed.owner_checkpoint(),
        checked(owner.continuity_checkpoint())
    );
    assert_eq!(retained(&fixture), before);
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.observe_intent(&intent), Ok(observed.clone()));

    // The delivery bridge must retain this output before ACK. The owner never
    // invents absent old output from another receipt or from a current prefix.
    checked(owner.acknowledge(output, [1; 32], cost()));
    let successor = request(&owner, "successor");
    checked(owner.admit(successor.clone(), /*now_micros*/ 13));
    checked(owner.commit(proposal(&successor), /*now_micros*/ 14));
    let successor_output = checked(owner.pending_output()).cloned();
    let before = retained(&fixture);
    let original_again = checked(owner.observe_intent(&intent));
    assert_eq!(original_again.receipt(), Some(&receipt));
    assert_eq!(original_again.pending_output(), None);
    assert_eq!(original_again.pending_request(), None);
    assert_ne!(
        original_again.owner_checkpoint(),
        observed.owner_checkpoint()
    );
    assert_eq!(
        checked(owner.observe_intent(&checked(successor.intent()))).pending_output(),
        successor_output.as_ref()
    );
    let mut changed = intent.clone();
    changed.input_digest = [97; 32];
    assert_eq!(
        owner.observe_intent(&changed),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(retained(&fixture), before);
    drop(owner);
    let owner = fixture.open();
    assert_eq!(owner.observe_intent(&intent), Ok(original_again));
    assert_eq!(retained(&fixture), before);
}

#[test]
fn uncertain_commit_cannot_mint_a_receipt_observation_before_owner_recovery() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        FailOnce {
            inner: fixture.witness(),
            fail: Arc::clone(&fail),
        },
        config(),
        /*max_records*/ 128,
    ));
    let original = request(&owner, "uncertain-commit");
    let intent = checked(original.intent());
    checked(owner.admit(original.clone(), /*now_micros*/ 11));
    let proposed = proposal(&original);
    fail.store(/*val*/ true, Ordering::SeqCst);
    assert_eq!(
        owner.commit(proposed.clone(), /*now_micros*/ 12),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    let before = retained(&fixture);
    assert_eq!(
        owner.observe_intent(&intent),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(retained(&fixture), before);
    checked(owner.recover());
    let observed = checked(owner.observe_intent(&intent));
    let receipt = checked(observed.receipt().ok_or("witnessed receipt"));
    assert_eq!(receipt.cost, proposed.cost);
    assert_eq!(receipt.request_digest, checked(original.digest()));
    assert!(observed.pending_output().is_some());
    assert_eq!(observed.pending_request(), None);
}
