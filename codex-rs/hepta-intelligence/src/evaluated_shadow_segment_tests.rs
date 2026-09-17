//! Actual evaluated-shadow admission and Decision writes, with synthetic signed
//! qualification inputs from the existing test fixture. No production selection.
use super::*;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::LongHorizonSegmentedLedgerV1;
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
    let first = run_evaluated_shadow_v1(
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
    let second = run_evaluated_shadow_v1(
        second_request,
        &fixture.verifier,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(second.learning.unwrap().sequence.get(), 2);
    let checkpoint = journal.checkpoint().unwrap();
    let snapshot = journal
        .snapshot_with_archives(vec![open(root, "0", false)])
        .unwrap();
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
    let replay = run_evaluated_shadow_v1(
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
    assert_eq!(
        recovered
            .snapshot_with_archives(vec![open(root, "0", false)])
            .unwrap(),
        snapshot
    );
    drop(recovered);
    assert_eq!(fs::read(root.join("1")).unwrap(), before);
}

#[test]
fn existing_consumer_switches_to_long_horizon_backend_without_a_consumer_branch() {
    let mut fixture = Fixture::new();
    let first_fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let index_root = root.join("long-horizon-index");
    let bounds = LedgerSegmentLimits {
        records: 1,
        bytes: 4096,
    };
    let binding = digest("owner-authorized-long-horizon-series");
    let mut journal = LongHorizonSegmentedLedgerV1::create(
        open(root, "lh-owner", true),
        open(root, "lh-0", true),
        &index_root,
        binding,
        bounds,
        /*cache_limit*/ 4,
    )
    .unwrap();

    let first = run_evaluated_shadow_v1(
        fixture.request(),
        &fixture.verifier,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    let first_append = first.learning.clone().unwrap();
    assert_eq!(first_append.sequence.get(), 1);
    let first_anchor = journal.head_anchor();
    let rotated = journal
        .rotate(open(root, "lh-1", true), first_anchor)
        .unwrap();
    assert_eq!(rotated.active_segment, 1);
    assert_eq!(journal.metrics().unwrap().retained_payload_records, 0);

    fixture.run.run_id = id("long-horizon-second-run");
    fixture.intuition.decision_id = fixture.run.run_id.clone();
    let mut second_request = fixture.request();
    second_request.episode_id = id("long-horizon-second-episode");
    second_request.expected_ledger_head = first_anchor.chain_digest;
    let second = run_evaluated_shadow_v1(
        second_request,
        &fixture.verifier,
        &mut journal,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(second.learning.unwrap().sequence.get(), 2);
    let checkpoint = journal.checkpoint().unwrap();
    let metrics = journal.metrics().unwrap();
    assert_eq!(metrics.active_segment, 1);
    assert_eq!(metrics.retained_payload_records, 1);
    assert!(metrics.historical_cache_entries <= metrics.historical_cache_limit);
    drop(journal);

    let before = fs::read(root.join("lh-1")).unwrap();
    let mut recovered = LongHorizonSegmentedLedgerV1::recover(
        open(root, "lh-owner", false),
        open(root, "lh-1", false),
        &index_root,
        binding,
        bounds,
        /*cache_limit*/ 4,
        checkpoint,
    )
    .unwrap();
    let replay = run_evaluated_shadow_v1(
        first_fixture.request(),
        &first_fixture.verifier,
        &mut recovered,
        &mut Ports::new(&first_fixture),
        /*now*/ 50,
    )
    .unwrap();
    let replay_append = replay.learning.unwrap();
    assert_eq!(replay_append.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay_append.sequence, first_append.sequence);
    assert_eq!(replay_append.chain_digest, first_append.chain_digest);
    assert_eq!(replay.pipeline, first.pipeline);
    assert_eq!(recovered.metrics().unwrap().retained_payload_records, 1);
    drop(recovered);
    assert_eq!(fs::read(root.join("lh-1")).unwrap(), before);
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
        run_evaluated_shadow_v1(
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
