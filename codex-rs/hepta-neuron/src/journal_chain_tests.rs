use super::*;

use pretty_assertions::assert_eq;

fn complete_chain() -> (Fixture, JournalAnchor, SparseSignalReceipt) {
    let fixture = Fixture::new();
    checked(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(fixture.root.join("middle")),
    );
    let fourth = {
        let mut root = checked(SparseJournal::open(
            fixture.file("root"),
            config(),
            scope(),
            /*max_records*/ 1,
        ));
        let first = checked(root.commit(Digest32::ZERO, &tick(1)));
        let mut middle = checked(root.start_successor(fixture.file("middle"), /*max_records*/ 1));
        let second = checked(middle.commit(first.checkpoint_after, &tick(2)));
        let mut last =
            checked(middle.start_successor(fixture.file("successor"), /*max_records*/ 2));
        let third = checked(last.commit(second.checkpoint_after, &tick(3)));
        checked(last.commit(third.checkpoint_after, &tick(4)))
    };
    let acknowledged = JournalAnchor {
        sequence: 4,
        checkpoint_digest: fourth.checkpoint_after,
    };
    (fixture, acknowledged, fourth)
}

fn chain_files(fixture: &Fixture) -> Vec<(File, usize)> {
    [("root", 1), ("middle", 1), ("successor", 2)]
        .into_iter()
        .map(|(name, capacity)| (fixture.file(name), capacity))
        .collect()
}

fn chain_bytes(fixture: &Fixture) -> Vec<Vec<u8>> {
    ["root", "middle", "successor"]
        .map(|name| fixture.bytes(name))
        .to_vec()
}

fn append_partial(fixture: &Fixture, name: &str) {
    let mut file = checked(
        OpenOptions::new()
            .append(true)
            .open(fixture.root.join(name)),
    );
    checked(file.write_all(b"partial-frame"));
    checked(file.sync_all());
}

#[test]
fn valid_chain_repairs_tails_and_retains_the_final_owner() {
    let (fixture, acknowledged, fourth) = complete_chain();
    let complete = chain_bytes(&fixture);
    for name in ["root", "middle", "successor"] {
        append_partial(&fixture, name);
    }
    let mut recovered = checked(SparseJournal::recover_chain_anchored(
        chain_files(&fixture),
        config(),
        scope(),
        acknowledged,
    ));
    assert_eq!(checked(recovered.current_anchor()), Some(acknowledged));
    assert_eq!(
        checked(recovered.commit(fourth.checkpoint_before, &tick(4))),
        fourth
    );
    assert_eq!(checked(recovered.remaining_capacity()), 0);
    assert_eq!(
        LockedFile::acquire(fixture.file("successor")).err(),
        Some(JournalError::Busy)
    );
    drop(recovered);
    assert_eq!(chain_bytes(&fixture), complete);
}

#[test]
fn final_anchor_refusal_preserves_every_unrepaired_segment() {
    let (fixture, acknowledged, fourth) = complete_chain();
    for name in ["root", "middle", "successor"] {
        append_partial(&fixture, name);
    }
    let before = chain_bytes(&fixture);
    for rejected in [
        JournalAnchor {
            checkpoint_digest: Digest32::of_bytes(b"wrong-witness"),
            ..acknowledged
        },
        JournalAnchor {
            sequence: 3,
            checkpoint_digest: fourth.checkpoint_before,
        },
    ] {
        assert_eq!(
            SparseJournal::recover_chain_anchored(
                chain_files(&fixture),
                config(),
                scope(),
                rejected
            )
            .err(),
            Some(JournalError::AnchorMismatch)
        );
        assert_eq!(chain_bytes(&fixture), before);
    }
}

#[test]
fn later_corruption_preserves_earlier_partial_tails() {
    let (fixture, acknowledged, _) = complete_chain();
    append_partial(&fixture, "root");
    append_partial(&fixture, "middle");
    let mut damaged = fixture.bytes("successor");
    damaged[SUCCESSOR_HEADER + 1] ^= 1;
    checked(fs::write(fixture.root.join("successor"), damaged));
    let before = chain_bytes(&fixture);
    assert_eq!(
        SparseJournal::recover_chain_anchored(
            chain_files(&fixture),
            config(),
            scope(),
            acknowledged
        )
        .err(),
        Some(JournalError::Corrupt)
    );
    assert_eq!(chain_bytes(&fixture), before);
}

#[test]
fn busy_or_duplicate_handle_preserves_all_original_bytes() {
    let (fixture, acknowledged, _) = complete_chain();
    append_partial(&fixture, "root");
    let before = chain_bytes(&fixture);
    let held = checked(LockedFile::acquire(fixture.file("successor")));
    assert_eq!(
        SparseJournal::recover_chain_anchored(
            chain_files(&fixture),
            config(),
            scope(),
            acknowledged
        )
        .err(),
        Some(JournalError::Busy)
    );
    drop(held);
    assert_eq!(chain_bytes(&fixture), before);
    let duplicate = vec![
        (fixture.file("root"), 1),
        (fixture.file("root"), 1),
        (fixture.file("successor"), 2),
    ];
    assert_eq!(
        SparseJournal::recover_chain_anchored(duplicate, config(), scope(), acknowledged).err(),
        Some(JournalError::Busy)
    );
    assert_eq!(chain_bytes(&fixture), before);
}

#[test]
fn empty_later_file_is_not_initialized_and_prefixes_are_not_repaired() {
    let (fixture, acknowledged, _) = complete_chain();
    append_partial(&fixture, "root");
    checked(fs::write(fixture.root.join("successor"), b""));
    let before = chain_bytes(&fixture);
    assert_eq!(
        SparseJournal::recover_chain_anchored(
            chain_files(&fixture),
            config(),
            scope(),
            acknowledged
        )
        .err(),
        Some(JournalError::AcknowledgedHistoryMissing)
    );
    assert_eq!(chain_bytes(&fixture), before);
}

#[test]
fn single_segment_keeps_complete_frames_after_its_minimum_witness() {
    let fixture = Fixture::new();
    let acknowledged = {
        let mut root = checked(SparseJournal::open(
            fixture.file("root"),
            config(),
            scope(),
            /*max_records*/ 2,
        ));
        let first = checked(root.commit(Digest32::ZERO, &tick(1)));
        checked(root.commit(first.checkpoint_after, &tick(2)));
        JournalAnchor {
            sequence: 1,
            checkpoint_digest: first.checkpoint_after,
        }
    };
    let complete = fixture.bytes("root");
    append_partial(&fixture, "root");
    let recovered = checked(SparseJournal::recover_chain_anchored(
        vec![(fixture.file("root"), 2)],
        config(),
        scope(),
        acknowledged,
    ));
    assert_eq!(
        checked(recovered.current()).map(SparseCheckpoint::sequence),
        Some(2)
    );
    assert!(checked(recovered.contains_anchor(acknowledged)));
    drop(recovered);
    assert_eq!(fixture.bytes("root"), complete);
}
