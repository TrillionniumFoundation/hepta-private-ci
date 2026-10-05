use super::*;

fn registry_bytes(store: &mut DurableTopologyProposalRegistryV1) -> Vec<u8> {
    let position = store.file.stream_position().expect("registry cursor");
    store.file.seek(SeekFrom::Start(0)).expect("registry start");
    let mut bytes = Vec::new();
    store
        .file
        .read_to_end(&mut bytes)
        .expect("complete registry bytes");
    store
        .file
        .seek(SeekFrom::Start(position))
        .expect("restore registry cursor");
    bytes
}

#[test]
fn topology_final_admission_rejection_preserves_history_and_rechecks_identical_retry() {
    let fixture = TestFile::new();
    let mut store = DurableTopologyProposalRegistryV1::bootstrap_empty(
        fixture.create(),
        digest("gate-scope"),
        7,
        8,
    )
    .expect("open");
    let proposal = governed("final-gate");
    let empty = registry_bytes(&mut store);
    let denied = store.append_after_admission(Digest32::ZERO, proposal.clone(), || {
        Err(DurableTopologyRegistryErrorV1::InvalidAnchor)
    });
    assert_eq!(denied, Err(DurableTopologyRegistryErrorV1::InvalidAnchor));
    assert_eq!(registry_bytes(&mut store), empty);
    assert_eq!(store.record_count(), Ok(0));
    let mut calls = 0;
    let receipt = store
        .append_after_admission(Digest32::ZERO, proposal.clone(), || {
            calls += 1;
            Ok::<(), DurableTopologyRegistryErrorV1>(())
        })
        .expect("fresh admission");
    assert_eq!(calls, 1);
    let committed = registry_bytes(&mut store);
    let denied_retry = store.append_after_admission(receipt.frame_digest, proposal.clone(), || {
        Err(DurableTopologyRegistryErrorV1::InvalidAnchor)
    });
    assert_eq!(
        denied_retry,
        Err(DurableTopologyRegistryErrorV1::InvalidAnchor)
    );
    assert_eq!(registry_bytes(&mut store), committed);
    assert_eq!(store.record_count(), Ok(1));
    let mut original = receipt;
    original.disposition = AppendDisposition::Unchanged;
    assert_eq!(
        store.append_after_admission(original.frame_digest, proposal, || Ok::<
            (),
            DurableTopologyRegistryErrorV1,
        >(())),
        Ok(original)
    );
}

#[test]
fn topology_final_admission_runs_only_after_read_only_conflict_checks() {
    let fixture = TestFile::new();
    let mut store = DurableTopologyProposalRegistryV1::bootstrap_empty(
        fixture.create(),
        digest("gate-scope"),
        7,
        8,
    )
    .expect("open");
    let before = registry_bytes(&mut store);
    let mut calls = 0;
    let result =
        store.append_after_admission(digest("wrong predecessor"), governed("final-gate"), || {
            calls += 1;
            Ok::<(), DurableTopologyRegistryErrorV1>(())
        });
    assert_eq!(result, Err(DurableTopologyRegistryErrorV1::Conflict));
    assert_eq!(calls, 0);
    assert_eq!(registry_bytes(&mut store), before);
}
