//! Actual evaluated-shadow admission and Decision writes, with synthetic signed
//! qualification inputs from the existing test fixture. No production selection.
use super::*;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::SegmentedLedger;
use pretty_assertions::assert_eq;

fn open(root: &std::path::Path, name: &str, create: bool) -> std::fs::File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(root.join(name))
        .unwrap()
}

#[test]
fn existing_consumer_continues_after_rotation_and_replays_old_run_after_recovery() {
    let mut fixture = Fixture::new();
    let first_fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let bounds = LedgerSegmentLimits {
        records: 1,
        bytes: 4096,
    };
    let binding = digest("owner-authorized-segment-series");
    let mut journal = SegmentedLedger::create(
        open(root, "owner", true),
        open(root, "0", true),
        binding,
        bounds,
    )
    .unwrap();
    let first = run_evaluated_shadow_v2(
        fixture.request(),
        &fixture.verifier,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    let anchor = journal.anchor().unwrap();
    journal.rotate(open(root, "1", true), anchor).unwrap();
    fixture.run.run_id = id("second-run");
    fixture.intuition.decision_id = fixture.run.run_id.clone();
    let mut second_request = fixture.request();
    second_request.episode_id = id("second-episode");
    second_request.expected_ledger_head = anchor.chain_digest;
    let second = run_evaluated_shadow_v2(
        second_request,
        &fixture.verifier,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(second.learning.unwrap().sequence.get(), 2);
    let checkpoint = journal.checkpoint().unwrap();
    let snapshot = journal.snapshot().unwrap();
    drop(journal);
    let before = fs::read(root.join("1")).unwrap();
    let mut recovered = SegmentedLedger::recover(
        open(root, "owner", false),
        vec![open(root, "0", false), open(root, "1", false)],
        binding,
        bounds,
        checkpoint,
    )
    .unwrap();
    let replay = run_evaluated_shadow_v2(
        first_fixture.request(),
        &first_fixture.verifier,
        &mut recovered,
        &mut Ports::new(&first_fixture),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(
        replay.learning.unwrap().disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.pipeline, first.pipeline);
    assert_eq!(recovered.snapshot().unwrap(), snapshot);
    drop(recovered);
    assert_eq!(fs::read(root.join("1")).unwrap(), before);
}

#[test]
fn bad_evaluator_signature_does_not_enter_ports_or_modify_a_segmented_journal() {
    let mut fixture = Fixture::new();
    fixture.candidate_evidence.signature[0] ^= 1;
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let mut journal = SegmentedLedger::create(
        open(root, "owner", true),
        open(root, "0", true),
        digest("owner-authorized-segment-series"),
        LedgerSegmentLimits {
            records: 1,
            bytes: 4096,
        },
    )
    .unwrap();
    let before = journal.snapshot().unwrap();
    let mut ports = Ports::new(&fixture);
    assert!(
        run_evaluated_shadow_v2(
            fixture.request(),
            &fixture.verifier,
            &mut journal,
            &mut ports,
            /*now*/ 50,
        )
        .is_err()
    );
    assert!(ports.calls.is_empty());
    assert_eq!(journal.snapshot().unwrap(), before);
}
