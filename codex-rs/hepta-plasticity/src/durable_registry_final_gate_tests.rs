use super::*;

#[test]
fn durable_final_admission_rejection_preserves_history_and_rechecks_identical_retry() {
    let fixture = TestFile::new("final-gate");
    let mut store =
        DurableProposalRegistry::open(fixture.create(), digest(b"gate-scope"), 7, 8).expect("open");
    let proposal = proposal("proposal:final-gate", b"window-gate");
    let empty = std::fs::read(&fixture.path).expect("empty bytes");
    let denied = store.append_v2_after_admission(Digest32::ZERO, proposal.clone(), || {
        Err(DurableProposalRegistryError::InvalidAnchor)
    });
    assert_eq!(denied, Err(DurableProposalRegistryError::InvalidAnchor));
    assert_eq!(
        std::fs::read(&fixture.path).expect("unchanged bytes"),
        empty
    );
    assert_eq!(store.record_count(), Ok(0));
    let mut calls = 0;
    let receipt = store
        .append_v2_after_admission(Digest32::ZERO, proposal.clone(), || {
            calls += 1;
            Ok::<(), DurableProposalRegistryError>(())
        })
        .expect("fresh admission");
    assert_eq!(calls, 1);
    let committed = std::fs::read(&fixture.path).expect("committed bytes");
    let denied_retry =
        store.append_v2_after_admission(receipt.frame_digest, proposal.clone(), || {
            Err(DurableProposalRegistryError::InvalidAnchor)
        });
    assert_eq!(
        denied_retry,
        Err(DurableProposalRegistryError::InvalidAnchor)
    );
    assert_eq!(
        std::fs::read(&fixture.path).expect("original bytes"),
        committed
    );
    assert_eq!(store.record_count(), Ok(1));
    let mut original = receipt;
    original.disposition = AppendDisposition::Unchanged;
    assert_eq!(
        store.append_v2_after_admission(original.frame_digest, proposal, || Ok::<
            (),
            DurableProposalRegistryError,
        >(())),
        Ok(original)
    );
}

#[test]
fn durable_final_admission_runs_only_after_read_only_conflict_checks() {
    let fixture = TestFile::new("final-gate");
    let mut store =
        DurableProposalRegistry::open(fixture.create(), digest(b"gate-scope"), 7, 8).expect("open");
    let before = std::fs::read(&fixture.path).expect("before");
    let mut calls = 0;
    let result = store.append_v2_after_admission(
        digest(b"wrong predecessor"),
        proposal("proposal:final-gate", b"window-gate"),
        || {
            calls += 1;
            Ok::<(), DurableProposalRegistryError>(())
        },
    );
    assert_eq!(result, Err(DurableProposalRegistryError::Conflict));
    assert_eq!(calls, 0);
    assert_eq!(std::fs::read(&fixture.path).expect("after"), before);
}
