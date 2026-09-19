//! Actual evaluated-shadow admission and authenticated production Decision writes,
//! with synthetic signed qualification inputs from the existing test fixture.
//! No production selection.
use super::*;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
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

fn writer(
    root: &std::path::Path,
    fixture: &Fixture,
    binding: Digest32,
    bounds: LedgerSegmentLimits,
) -> LedgerWriter {
    let journal = SegmentedLedger::create(
        open(root, "owner", true),
        open(root, "0", true),
        binding,
        bounds,
    )
    .unwrap();
    let witness = LedgerWitnessStore::create(open(root, "witness", true), binding).unwrap();
    LedgerWriter::from_segmented(journal, witness, fixture.trust_activation()).unwrap()
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
    let mut journal = writer(root, &fixture, binding, bounds);

    let first = run_evaluated_shadow_v1(
        fixture.request(),
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    let anchor = journal.witness_frontier().unwrap().anchor;
    let rotated = journal
        .rotate_segment(open(root, "1", true), anchor)
        .unwrap();
    assert_eq!(rotated.segment, 1);
    assert!(!rotated.sealed);

    fixture.run.run_id = id("second-run");
    fixture.intuition.decision_id = fixture.run.run_id.clone();
    let mut second_request = fixture.request();
    second_request.episode_id = id("second-episode");
    second_request.expected_ledger_head = anchor.chain_digest;
    second_request.decision_evidence = fixture.decision_evidence_for(
        &second_request.run,
        &second_request.intuition,
        &second_request.episode_id,
    );
    let second = run_evaluated_shadow_v1(
        second_request,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(second.learning.unwrap().sequence.get(), 2);

    let checkpoint = journal.segmented_checkpoint().unwrap().unwrap();
    let snapshot = journal.snapshot().unwrap();
    let witnessed = journal.witness_frontier().unwrap();
    assert_eq!(witnessed.anchor, checkpoint.anchor);
    assert_eq!(witnessed.segment, Some(checkpoint.segment));
    drop(journal);

    let before = fs::read(root.join("1")).unwrap();
    let recovered = SegmentedLedger::recover(
        open(root, "owner", false),
        vec![open(root, "0", false), open(root, "1", false)],
        binding,
        bounds,
        checkpoint,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(open(root, "witness", false), binding).unwrap();
    let mut recovered =
        LedgerWriter::from_segmented(recovered, witness, first_fixture.trust_activation()).unwrap();
    let replay = run_evaluated_shadow_v1(
        first_fixture.request(),
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
    let bounds = LedgerSegmentLimits {
        records: 1,
        bytes: 4096,
    };
    let binding = digest("owner-authorized-segment-series");
    let mut journal = writer(root, &fixture, binding, bounds);
    let before = journal.snapshot().unwrap();
    let mut ports = Ports::new(&fixture);
    assert!(
        run_evaluated_shadow_v1(
            fixture.request(),
            &mut journal,
            &mut ports,
            /*now*/ 50,
        )
        .is_err()
    );
    assert!(ports.calls.is_empty());
    assert_eq!(journal.snapshot().unwrap(), before);
}
