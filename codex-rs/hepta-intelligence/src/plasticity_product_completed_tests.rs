//! Actual original file cold reopen, full materials and external anchor checks.
use super::*;
use codex_hepta_plasticity::DurableCompletedProposalV1;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

#[test]
fn completed_parameter_cold_recovery_preserves_receipt_and_file_without_propose() {
    let fixture = Fixture::new(false);
    let request = fixture.request();
    let file = tempfile().expect("registry");
    let mut probe = file.try_clone().expect("probe");
    let scope = digest("completed-cold-scope");
    let mut owner = AnchoredPlasticityWriterV1::bootstrap_new(file, scope, 17, 32).expect("owner");
    let mut anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    assert!(
        owner
            .observe_completed_parameter_v1(&request, &fixture.verifier, 50, None)
            .expect("absent")
            .is_none()
    );
    let receipt = propose_authenticated_parameter_plasticity_v1(
        request.clone(),
        &fixture.verifier,
        &mut owner,
        &mut anchor,
        50,
    )
    .expect("actual commit");
    let request_bytes = encode_parameter_plasticity_request_v1(&request).expect("whole request");
    assert_eq!(
        decode_parameter_plasticity_request_v1(&request_bytes).expect("raw request"),
        request
    );
    let receipt_bytes = encode_parameter_plasticity_receipt_v1(&receipt).expect("whole receipt");
    assert_eq!(
        decode_parameter_plasticity_receipt_v1(&receipt_bytes).expect("raw receipt"),
        receipt
    );
    probe.seek(SeekFrom::Start(0)).expect("seek");
    let mut before = Vec::new();
    probe.read_to_end(&mut before).expect("before");
    drop(owner);
    let cold = AnchoredPlasticityWriterV1::reopen_anchored(
        probe.try_clone().expect("cold file"),
        scope,
        17,
        32,
        anchor.anchor.expect("independent anchor"),
    )
    .expect("cold owner");
    assert!(
        cold.observe_completed_parameter_v1(&request, &fixture.verifier, 50, None)
            .is_err()
    );
    let recovered = cold
        .observe_completed_parameter_v1(&request, &fixture.verifier, 50, anchor.anchor)
        .expect("completed only")
        .expect("actual row");
    assert_eq!(recovered, receipt);
    let whole = cold
        .observe_completed_proposal_v1(&request.proposal_id, anchor.anchor)
        .expect("whole")
        .expect("row");
    let whole_bytes = whole.to_bytes().expect("original frame");
    assert_eq!(
        DurableCompletedProposalV1::from_bytes(&whole_bytes).expect("integrity only"),
        whole
    );
    let mut tampered = whole_bytes;
    tampered[20] ^= 1;
    assert!(DurableCompletedProposalV1::from_bytes(&tampered).is_err());
    let mut mismatch = request.clone();
    mismatch.expected_registry_predecessor = digest("foreign predecessor");
    assert!(
        cold.observe_completed_parameter_v1(&mismatch, &fixture.verifier, 50, anchor.anchor)
            .is_err()
    );
    assert!(
        cold.observe_completed_parameter_v1(&request, &fixture.verifier, 101, anchor.anchor)
            .is_err()
    );
    assert_eq!(cold.record_count().expect("count"), 1);
    probe.seek(SeekFrom::Start(0)).expect("seek");
    let mut after = Vec::new();
    probe.read_to_end(&mut after).expect("after");
    assert_eq!(before, after);
    let mut bad_request = request_bytes;
    bad_request[30] ^= 1;
    assert!(decode_parameter_plasticity_request_v1(&bad_request).is_err());
    let mut bad_receipt = receipt_bytes;
    bad_receipt.push(0);
    assert!(decode_parameter_plasticity_receipt_v1(&bad_receipt).is_err());
}

#[test]
fn completed_no_change_preserves_original_terminal_evaluator_and_denies_update() {
    let fixture = Fixture::new(false);
    let request = fixture.no_change_request();
    let bytes = encode_parameter_plasticity_request_v1(&request).expect("whole no-change");
    assert_eq!(
        decode_parameter_plasticity_request_v1(&bytes).expect("original no-change evidence"),
        request
    );
    let file = tempfile().expect("registry");
    let cold_file = file.try_clone().expect("cold file");
    let scope = digest("completed-no-change-scope");
    let mut owner = AnchoredPlasticityWriterV1::bootstrap_new(file, scope, 19, 32).expect("owner");
    let mut anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let receipt = propose_authenticated_parameter_plasticity_v1(
        request.clone(),
        &fixture.verifier,
        &mut owner,
        &mut anchor,
        50,
    )
    .expect("actual no-change commit");
    assert_eq!(
        receipt.disposition,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate
    );
    let bytes = encode_parameter_plasticity_receipt_v1(&receipt).expect("whole receipt");
    assert_eq!(
        decode_parameter_plasticity_receipt_v1(&bytes).expect("receipt"),
        receipt
    );
    drop(owner);
    let cold = AnchoredPlasticityWriterV1::reopen_anchored(
        cold_file,
        scope,
        19,
        32,
        anchor.anchor.expect("independent anchor"),
    )
    .expect("cold original owner");
    assert_eq!(
        cold.observe_completed_parameter_v1(&request, &fixture.verifier, 50, anchor.anchor)
            .expect("read completed only"),
        Some(receipt)
    );
    let mut missing_terminal_evaluator = request;
    missing_terminal_evaluator.no_change_attestation = None;
    assert!(
        cold.observe_completed_parameter_v1(
            &missing_terminal_evaluator,
            &fixture.verifier,
            50,
            anchor.anchor,
        )
        .is_err()
    );
    assert_eq!(cold.record_count().expect("no re-propose"), 1);
}
