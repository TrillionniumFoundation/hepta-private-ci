use super::*;
use crate::LedgerWitnessFrontier;
use crate::LedgerWitnessStore;
use crate::inspect_ledger_witness_frontier;
use pretty_assertions::assert_eq;

#[test]
fn exact_held_source_retains_full_history_offset_lock_and_later_append() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    let first = must(ledger.append(Digest32::ZERO, decision()));
    let second = must(ledger.append(first.chain_digest, outcome()));
    let before = must(ledger.snapshot());
    let mut alias = must(ledger.file.try_clone());
    let offset = must(alias.stream_position());
    let bytes = locked_bytes(&ledger);
    let source = must(ledger.export_canonical_source_v1());
    assert_eq!(source.bytes(), bytes);
    assert_eq!(source.binding(), binding());
    assert_eq!(source.maximum_records(), 16);
    assert_eq!(must(alias.stream_position()), offset);
    assert_eq!(must(ledger.snapshot()), before);
    assert_eq!(
        fixture.recover(anchored(&before)).err(),
        Some(DurableLedgerError::Busy)
    );
    let third = must(ledger.append(second.chain_digest, revocation()));
    assert_eq!(must(ledger.snapshot()).head_digest, third.chain_digest);
    assert_eq!(
        must(ledger.export_canonical_source_v1()).bytes(),
        locked_bytes(&ledger)
    );
}

#[test]
fn copied_source_requires_real_separate_current_witness_not_its_own_head() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    let first = must(ledger.append(Digest32::ZERO, decision()));
    let witness_path = fixture.root.join("witness");
    let mut witness = must(LedgerWitnessStore::create(
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&witness_path),
        ),
        binding(),
    ));
    let witnessed = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: first.sequence.get(),
            chain_digest: first.chain_digest,
        },
        segment: None,
        sealed: false,
    };
    must(witness.advance(LedgerWitnessFrontier::empty(), witnessed));
    let witnessed_bytes = must(witness.export_canonical_source_v1(/*maximum_bytes*/ 8192));
    assert_eq!(must(witness.frontier()), witnessed);
    assert_eq!(
        witness.export_canonical_source_v1(witnessed_bytes.len() - 1),
        Err(DurableLedgerError::Capacity)
    );
    let witness_copy = fixture.root.join("independent-witness-copy");
    must(fs::write(&witness_copy, &witnessed_bytes));
    assert_eq!(
        must(inspect_ledger_witness_frontier(
            must(File::open(&witness_copy)),
            binding(),
            /*maximum_frames*/ 16
        )),
        witnessed
    );
    let second = must(ledger.append(first.chain_digest, outcome()));
    let source = must(ledger.export_canonical_source_v1());
    let copy = fixture.root.join("immutable-copy");
    must(fs::write(&copy, source.bytes()));
    // The export does not advance the independent witness. A stale witness
    // cannot authorize a complete later source, even though its head is valid.
    assert_eq!(must(witness.frontier()), witnessed);
    assert_eq!(
        inspect_ledger(
            must(File::open(&copy)),
            source.binding(),
            source.maximum_records(),
            witnessed.anchor
        ),
        Err(DurableLedgerError::UnwitnessedTail)
    );
    let current = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: second.sequence.get(),
            chain_digest: second.chain_digest,
        },
        segment: None,
        sealed: false,
    };
    must(witness.advance(witnessed, current));
    let current_bytes = must(witness.export_canonical_source_v1(/*maximum_bytes*/ 8192));
    assert_eq!(must(witness.frontier()), current);
    drop(witness);
    let witness_bytes = must(fs::read(&witness_path));
    assert_eq!(witness_bytes, current_bytes);
    let actual = must(inspect_ledger_witness_frontier(
        must(File::open(&witness_path)),
        binding(),
        /*maximum_frames*/ 16,
    ));
    assert_eq!(actual, current);
    assert_eq!(
        must(inspect_ledger(
            must(File::open(&copy)),
            source.binding(),
            source.maximum_records(),
            actual.anchor
        )),
        must(ledger.snapshot())
    );
    assert_eq!(must(fs::read(&witness_path)), witness_bytes);
    assert_eq!(must(fs::read(&copy)), source.bytes());
}

#[test]
fn changing_tail_or_complete_corruption_is_rejected_without_repair() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    must(ledger.append(Digest32::ZERO, decision()));
    let expected = must(ledger.snapshot());
    let original = locked_bytes(&ledger);
    let mut alias = must(ledger.file.try_clone());
    must(alias.seek(SeekFrom::End(0)));
    must(alias.write_all(&[1, 2, 3]));
    let partial = locked_bytes(&ledger);
    assert_eq!(
        ledger.export_canonical_source_v1().err(),
        Some(DurableLedgerError::Conflict)
    );
    assert_eq!(locked_bytes(&ledger), partial);
    must(alias.set_len(original.len() as u64));
    must(alias.seek(SeekFrom::Start(HEADER as u64 + 48)));
    must(alias.write_all(&[0xff]));
    let corrupt = locked_bytes(&ledger);
    assert_eq!(
        ledger.export_canonical_source_v1().err(),
        Some(DurableLedgerError::Corrupt)
    );
    assert_eq!(locked_bytes(&ledger), corrupt);
    assert_eq!(must(ledger.snapshot()), expected);
}

#[test]
fn empty_source_remains_original_header_and_grants_no_acknowledgement() {
    let fixture = Fixture::new();
    let ledger = fixture.create();
    let before = must(ledger.snapshot());
    let source = must(ledger.export_canonical_source_v1());
    assert_eq!(source.bytes(), locked_bytes(&ledger));
    assert_eq!(source.bytes().len(), HEADER);
    assert_eq!(must(ledger.snapshot()), before);
}

#[test]
fn foreign_witness_tail_is_never_truncated_or_promoted_to_an_ack() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    let receipt = must(ledger.append(Digest32::ZERO, decision()));
    let path = fixture.root.join("witness");
    let mut witness = must(LedgerWitnessStore::create(
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&path),
        ),
        binding(),
    ));
    let current = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
        },
        segment: None,
        sealed: false,
    };
    must(witness.advance(LedgerWitnessFrontier::empty(), current));
    let mut foreign = must(OpenOptions::new().append(true).open(&path));
    must(foreign.write_all(&[1, 2, 3]));
    let bytes = must(fs::read(&path));
    assert_eq!(
        witness.export_canonical_source_v1(/*maximum_bytes*/ 8192),
        Err(DurableLedgerError::Conflict)
    );
    assert_eq!(must(witness.frontier()), current);
    assert_eq!(must(fs::read(path)), bytes);
}
