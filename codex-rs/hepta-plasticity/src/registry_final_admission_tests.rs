use super::*;

#[derive(Debug, PartialEq, Eq)]
enum AdmissionFailure {
    Denied,
    Parameter(DurableProposalRegistryError),
    Topology(DurableTopologyRegistryErrorV1),
}

impl From<DurableProposalRegistryError> for AdmissionFailure {
    fn from(error: DurableProposalRegistryError) -> Self {
        Self::Parameter(error)
    }
}

impl From<DurableTopologyRegistryErrorV1> for AdmissionFailure {
    fn from(error: DurableTopologyRegistryErrorV1) -> Self {
        Self::Topology(error)
    }
}

#[test]
fn parameter_final_admission_gates_insert_and_retry_without_poisoning_rejection() {
    let (_fixture, mut file) = TestFile::create();
    let mut registry = DurableProposalRegistry::open_bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        2,
    )
    .expect("registry");
    let first = parameter("first");
    let receipt = registry
        .append_v2(Digest32::ZERO, first.clone())
        .expect("first");
    let before = image(&mut file);
    let mut calls = 0;
    for candidate in [parameter("second"), first.clone()] {
        assert_eq!(
            registry.append_v2_with_final_admission(receipt.frame_digest, candidate, || {
                calls += 1;
                Err(AdmissionFailure::Denied)
            }),
            Err(AdmissionFailure::Denied)
        );
        assert_eq!(image(&mut file), before);
        assert!(!registry.is_poisoned());
        assert_eq!(registry.record_count(), Ok(1));
        assert_eq!(
            registry.current_anchor(),
            Ok(Some(DurableRegistryAnchorV1 {
                sequence: 1,
                frame_digest: receipt.frame_digest,
            }))
        );
    }
    assert_eq!(calls, 2);
    assert_eq!(
        registry.append_v2_with_final_admission(Digest32::ZERO, parameter("second"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Parameter(
            DurableProposalRegistryError::Conflict
        ))
    );
    assert_eq!(calls, 2);
    assert_eq!(image(&mut file), before);
    let second = registry
        .append_v2_with_final_admission(receipt.frame_digest, parameter("second"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        })
        .expect("admitted insertion");
    assert_eq!(second.disposition, AppendDisposition::Inserted);
    let after = image(&mut file);
    let retry = registry
        .append_v2_with_final_admission(Digest32::ZERO, first, || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        })
        .expect("admitted older retry");
    let mut expected_retry = receipt;
    expected_retry.disposition = AppendDisposition::Unchanged;
    assert_eq!(retry, expected_retry);
    assert_eq!(calls, 4);
    assert_eq!(image(&mut file), after);
    assert_eq!(
        registry.append_v2_with_final_admission(second.frame_digest, parameter("third"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Parameter(
            DurableProposalRegistryError::Capacity
        ))
    );
    assert_eq!(calls, 4);
    assert_eq!(image(&mut file), after);
    assert!(!registry.is_poisoned());
    assert_eq!(registry.record_count(), Ok(2));
}

#[test]
fn topology_final_admission_gates_insert_and_retry_without_poisoning_rejection() {
    let (_fixture, mut file) = TestFile::create();
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        2,
    )
    .expect("registry");
    let first = topology("first");
    let receipt = registry
        .append(Digest32::ZERO, first.clone())
        .expect("first");
    let before = image(&mut file);
    let mut calls = 0;
    for candidate in [topology("second"), first.clone()] {
        assert_eq!(
            registry.append_with_final_admission(receipt.frame_digest, candidate, || {
                calls += 1;
                Err(AdmissionFailure::Denied)
            }),
            Err(AdmissionFailure::Denied)
        );
        assert_eq!(image(&mut file), before);
        assert!(!registry.is_poisoned());
        assert_eq!(registry.record_count(), Ok(1));
        assert_eq!(
            registry.current_anchor(),
            Ok(Some(DurableTopologyRegistryAnchorV1 {
                sequence: 1,
                frame_digest: receipt.frame_digest,
            }))
        );
    }
    assert_eq!(calls, 2);
    assert_eq!(
        registry.append_with_final_admission(Digest32::ZERO, topology("second"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Topology(
            DurableTopologyRegistryErrorV1::Conflict
        ))
    );
    assert_eq!(calls, 2);
    assert_eq!(image(&mut file), before);
    let second = registry
        .append_with_final_admission(receipt.frame_digest, topology("second"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        })
        .expect("admitted insertion");
    assert_eq!(second.disposition, AppendDisposition::Inserted);
    let after = image(&mut file);
    let retry = registry
        .append_with_final_admission(Digest32::ZERO, first, || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        })
        .expect("admitted older retry");
    let mut expected_retry = receipt;
    expected_retry.disposition = AppendDisposition::Unchanged;
    assert_eq!(retry, expected_retry);
    assert_eq!(calls, 4);
    assert_eq!(image(&mut file), after);
    assert_eq!(
        registry.append_with_final_admission(second.frame_digest, topology("third"), || {
            calls += 1;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Topology(
            DurableTopologyRegistryErrorV1::Capacity
        ))
    );
    assert_eq!(calls, 4);
    assert_eq!(image(&mut file), after);
    assert!(!registry.is_poisoned());
    assert_eq!(registry.record_count(), Ok(2));
}

#[test]
fn parameter_corrupt_preflight_never_calls_final_admission() {
    let (_fixture, mut file) = TestFile::create();
    let mut registry = DurableProposalRegistry::open_bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        3,
    )
    .expect("registry");
    let first = registry
        .append_v2(Digest32::ZERO, parameter("first"))
        .expect("first");
    let second = registry
        .append_v2(first.frame_digest, parameter("second"))
        .expect("second");
    mutate(&mut file, Mutation::ReauthenticatedOldBody);
    let before = image(&mut file);
    let mut called = false;
    assert_eq!(
        registry.append_v2_with_final_admission(second.frame_digest, parameter("third"), || {
            called = true;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Parameter(
            DurableProposalRegistryError::Corrupt
        ))
    );
    assert!(!called);
    assert!(registry.is_poisoned());
    assert_eq!(image(&mut file), before);
    assert_eq!(
        registry.record_count(),
        Err(DurableProposalRegistryError::Poisoned)
    );
}

#[test]
fn topology_corrupt_preflight_never_calls_final_admission() {
    let (_fixture, mut file) = TestFile::create();
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        3,
    )
    .expect("registry");
    let first = registry
        .append(Digest32::ZERO, topology("first"))
        .expect("first");
    let second = registry
        .append(first.frame_digest, topology("second"))
        .expect("second");
    mutate(&mut file, Mutation::Header);
    let before = image(&mut file);
    let mut called = false;
    assert_eq!(
        registry.append_with_final_admission(second.frame_digest, topology("third"), || {
            called = true;
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Topology(
            DurableTopologyRegistryErrorV1::Corrupt
        ))
    );
    assert!(!called);
    assert!(registry.is_poisoned());
    assert_eq!(image(&mut file), before);
    assert_eq!(
        registry.record_count(),
        Err(DurableTopologyRegistryErrorV1::Poisoned)
    );
}

// These deterministic phase faults deliberately violate the host's exclusive
// file-description contract. They exercise the postwrite verifier with real
// files; they do not emulate hardware write, sync or read failures.
#[test]
fn parameter_postwrite_verification_rejects_callback_phase_corruption() {
    let (_fixture, mut file) = TestFile::create();
    let scope = digest("scope");
    let mut registry = DurableProposalRegistry::open_bootstrap_empty(
        file.try_clone().expect("registry clone"),
        scope,
        17,
        3,
    )
    .expect("registry");
    let first = registry
        .append_v2(Digest32::ZERO, parameter("first"))
        .expect("first");
    let before = image(&mut file);
    let mut called = false;
    assert_eq!(
        registry.append_v2_with_final_admission(first.frame_digest, parameter("second"), || {
            called = true;
            mutate(&mut file, Mutation::Header);
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Parameter(
            DurableProposalRegistryError::Corrupt
        ))
    );
    assert!(called);
    assert!(registry.is_poisoned());
    let after = image(&mut file);
    assert!(
        after.len() > before.len(),
        "the physical append preceded rejection"
    );
    assert_eq!(after[0], before[0] ^ 1);
    assert_eq!(
        registry.current_anchor(),
        Err(DurableProposalRegistryError::Poisoned)
    );
    assert_eq!(
        registry.record_count(),
        Err(DurableProposalRegistryError::Poisoned)
    );
    drop(registry);
    assert_eq!(
        DurableProposalRegistry::open_anchored(
            file.try_clone().expect("reopen clone"),
            scope,
            17,
            3,
            DurableRegistryAnchorV1 {
                sequence: 1,
                frame_digest: first.frame_digest
            },
        )
        .err(),
        Some(DurableProposalRegistryError::Corrupt)
    );
    assert_eq!(image(&mut file), after);
}

#[test]
fn topology_postwrite_verification_rejects_callback_phase_corruption() {
    let (_fixture, mut file) = TestFile::create();
    let scope = digest("scope");
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        file.try_clone().expect("registry clone"),
        scope,
        17,
        3,
    )
    .expect("registry");
    let first = registry
        .append(Digest32::ZERO, topology("first"))
        .expect("first");
    let before = image(&mut file);
    let mut called = false;
    assert_eq!(
        registry.append_with_final_admission(first.frame_digest, topology("second"), || {
            called = true;
            mutate(&mut file, Mutation::Header);
            Ok::<(), AdmissionFailure>(())
        }),
        Err(AdmissionFailure::Topology(
            DurableTopologyRegistryErrorV1::Corrupt
        ))
    );
    assert!(called);
    assert!(registry.is_poisoned());
    let after = image(&mut file);
    assert!(
        after.len() > before.len(),
        "the physical append preceded rejection"
    );
    assert_eq!(after[0], before[0] ^ 1);
    assert_eq!(
        registry.current_anchor(),
        Err(DurableTopologyRegistryErrorV1::Poisoned)
    );
    assert_eq!(
        registry.record_count(),
        Err(DurableTopologyRegistryErrorV1::Poisoned)
    );
    drop(registry);
    assert_eq!(
        DurableTopologyProposalRegistryV1::reopen_anchored(
            file.try_clone().expect("reopen clone"),
            scope,
            17,
            3,
            DurableTopologyRegistryAnchorV1 {
                sequence: 1,
                frame_digest: first.frame_digest
            },
        )
        .err(),
        Some(DurableTopologyRegistryErrorV1::Corrupt)
    );
    assert_eq!(image(&mut file), after);
}
