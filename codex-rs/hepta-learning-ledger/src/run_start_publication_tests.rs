use super::*;
use pretty_assertions::assert_eq;

#[test]
fn publication_and_anchor_read_retained_prefix_without_writing() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = must(journal.append(Digest32::ZERO, record("run.first", b"first")));
    let second = must(journal.append_conflict(
        first.chain_digest,
        conflict_record("run.conflict", b"conflict"),
    ));
    let before = locked_bytes(&journal.file.0);
    for (name, receipt) in [("run.first", first), ("run.conflict", second)] {
        assert_eq!(
            must(journal.publication(&id(name))),
            Some(RunStartPublication {
                sequence: receipt.sequence,
                record_digest: receipt.record_digest,
                chain_digest: receipt.chain_digest,
            })
        );
        must(journal.verify_anchor(RunStartAnchor {
            sequence: receipt.sequence,
            chain_digest: receipt.chain_digest,
        }));
    }
    assert_eq!(must(journal.publication(&id("run.absent"))), None);
    assert_eq!(locked_bytes(&journal.file.0), before);
    journal.poisoned = true;
    assert_eq!(
        journal.publication(&id("run.first")),
        Err(RunStartStoreError::Poisoned)
    );
    assert_eq!(
        journal.verify_anchor(RunStartAnchor {
            sequence: 1,
            chain_digest: digest("anything")
        }),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn publication_anchor_detects_recovered_rollback_and_changed_chain() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = must(journal.append(Digest32::ZERO, record("run.first", b"first")));
    let retained_length = journal.durable_length;
    let second = must(journal.append(first.chain_digest, record("run.second", b"second")));
    drop(journal);
    must(fixture.file().set_len(retained_length));
    let reopened = must(fixture.recover(RunStartRecovery::Unacknowledged));
    assert_eq!(
        reopened.verify_anchor(RunStartAnchor {
            sequence: second.sequence,
            chain_digest: second.chain_digest
        }),
        Err(RunStartStoreError::AcknowledgedHistoryMissing)
    );
    assert_eq!(
        reopened.verify_anchor(RunStartAnchor {
            sequence: first.sequence,
            chain_digest: second.chain_digest
        }),
        Err(RunStartStoreError::AnchorMismatch)
    );
    assert_eq!(must(reopened.publication(&id("run.second"))), None);
}
