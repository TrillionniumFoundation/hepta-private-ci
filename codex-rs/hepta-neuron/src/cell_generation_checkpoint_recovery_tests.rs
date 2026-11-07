use std::fs;

use pretty_assertions::assert_eq;

use super::super::support::*;
use super::*;
use crate::cell_test_support::checked;

#[test]
fn checkpoint_reopen_keeps_intents_and_only_the_first_adopted_input() {
    for disposition in [
        CellGenerationDispositionV2::Advanced,
        CellGenerationDispositionV2::Stopped,
    ] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let mut cancelled = request(&owner, "cancelled-initialization");
        cancelled.input = b"unadopted input".to_vec();
        checked(owner.admit(cancelled.clone(), /*now_micros*/ 10));
        checked(owner.cancel(checked(cancelled.digest())));
        let cancelled_receipt = checked(owner.commit(proposal(&cancelled), /*now_micros*/ 20));
        assert_eq!(
            cancelled_receipt.disposition,
            CellGenerationDispositionV2::Cancelled
        );

        let mut adopted = request(&owner, "adopted-initialization");
        adopted.input = b"adopted input".to_vec();
        checked(owner.admit(adopted.clone(), /*now_micros*/ 21));
        checked(owner.observe_dispatch_time(checked(adopted.digest()), /*observed_at_micros*/ 25));
        checked(owner.checkpoint_to(fixture.file("pending-checkpoint")));
        let pending = checked(owner.observe_generation());
        assert_eq!(pending.first_advance_input_digest(), None);
        assert_eq!(
            pending.pending_request_digest(),
            Some(checked(adopted.digest()))
        );
        drop(owner);

        let mut owner = checked(CellGenerationJournalV2::open(
            fixture.file("pending-checkpoint"),
            fixture.witness(),
            config(),
            /*max_records*/ 128,
        ));
        assert_eq!(owner.observe_generation(), Ok(pending.clone()));
        assert_eq!(
            owner.receipt_for_intent(&checked(cancelled.intent())),
            Ok(Some(cancelled_receipt.clone()))
        );
        assert_eq!(
            owner.receipt_for_intent(&checked(adopted.intent())),
            Ok(None)
        );
        assert_eq!(
            owner.admit(adopted.clone(), /*now_micros*/ 26),
            Err(CellGenerationErrorV2::Pending)
        );
        assert_eq!(
            owner.commit(proposal(&adopted), /*now_micros*/ 24),
            Err(CellGenerationErrorV2::Deadline)
        );
        assert_eq!(owner.observe_generation(), Ok(pending));

        let mut result = proposal(&adopted);
        result.disposition = disposition;
        let adopted_receipt = checked(owner.commit(result, /*now_micros*/ 26));
        checked(owner.checkpoint_to(fixture.file("adopted-checkpoint")));
        let settled = checked(owner.observe_generation());
        assert_eq!(
            settled.first_advance_input_digest(),
            Some(Digest32::of_bytes(&adopted.input).into_array())
        );
        let chunk = checked(settled.pending_output().cloned().ok_or("retained output"));
        drop(owner);

        let owner = checked(CellGenerationJournalV2::open(
            fixture.file("adopted-checkpoint"),
            fixture.witness(),
            config(),
            /*max_records*/ 128,
        ));
        assert_eq!(owner.observe_generation(), Ok(settled));
        assert_eq!(owner.pending_output(), Ok(Some(&chunk)));
        assert_eq!(
            owner.receipt_for_intent(&checked(cancelled.intent())),
            Ok(Some(cancelled_receipt))
        );
        assert_eq!(
            owner.receipt_for_intent(&checked(adopted.intent())),
            Ok(Some(adopted_receipt))
        );
        let mut conflicting = checked(adopted.intent());
        conflicting.input_digest = Digest32::of_bytes(&cancelled.input).into_array();
        assert_eq!(
            owner.receipt_for_intent(&conflicting),
            Err(CellGenerationErrorV2::Conflict)
        );
    }
}

#[test]
fn checkpoint_reopen_rejects_inconsistent_intents_or_first_advance_before_repair() {
    for case in [
        "missing-intent",
        "extra-intent",
        "reordered-intents",
        "wrong-operation",
        "wrong-task",
        "wrong-source-frontier",
        "missing-first-advance",
        "cancelled-input-as-first-advance",
        "first-advance-without-adoption",
    ] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let mut cancelled = request(&owner, "cancelled");
        cancelled.input = b"cancelled input".to_vec();
        checked(owner.admit(cancelled.clone(), /*now_micros*/ 10));
        checked(owner.cancel(checked(cancelled.digest())));
        checked(owner.commit(proposal(&cancelled), /*now_micros*/ 20));
        if case != "first-advance-without-adoption" {
            let mut adopted = request(&owner, "adopted");
            adopted.input = b"adopted input".to_vec();
            checked(owner.admit(adopted.clone(), /*now_micros*/ 21));
            checked(owner.commit(proposal(&adopted), /*now_micros*/ 22));
        }
        let mut invalid = owner.state.clone();
        match case {
            "missing-intent" => {
                let _ = invalid.intents.pop();
            }
            "extra-intent" => invalid.intents.push(invalid.intents[0].clone()),
            "reordered-intents" => invalid.intents.swap(0, 1),
            "wrong-operation" => {
                invalid.intents[0].operation_id = "different-operation".to_string()
            }
            "wrong-task" => invalid.intents[0].task_digest = [99; 32],
            "wrong-source-frontier" => invalid.intents[0].source_frontier = [99; 32],
            "missing-first-advance" => invalid.first_advance_input_digest = None,
            "cancelled-input-as-first-advance" | "first-advance-without-adoption" => {
                invalid.first_advance_input_digest =
                    Some(Digest32::of_bytes(&cancelled.input).into_array());
            }
            _ => unreachable!(),
        }
        // Model a writer that compacted an internally inconsistent state. The
        // frame and independent witness are valid, so hashing alone cannot
        // reject it. The added torn suffix must not be repaired on refusal.
        checked(owner.install_checkpoint(fixture.file("successor"), config(), invalid));
        let witness = checked(owner.witness.current());
        drop(owner);
        let mut bytes = checked(fs::read(fixture.0.join("successor")));
        bytes.push(0);
        checked(fs::write(fixture.0.join("successor"), &bytes));
        assert_eq!(
            CellGenerationJournalV2::open(
                fixture.file("successor"),
                fixture.witness(),
                config(),
                /*max_records*/ 128,
            )
            .err(),
            Some(CellGenerationErrorV2::Corrupt),
            "{case}"
        );
        assert_eq!(
            checked(fs::read(fixture.0.join("successor"))),
            bytes,
            "{case}"
        );
        assert_eq!(checked(fixture.witness().current()), witness, "{case}");
    }
}
