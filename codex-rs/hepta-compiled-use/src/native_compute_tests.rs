use super::*;

fn verifier() -> NativeComputeVerifierV1 {
    NativeComputeVerifierV1 {
        generation: 19,
        task_digest: Digest32::of_bytes(b"fixed-immutable-test-task"),
        kernel_digest: approved_q24_dot_kernel_digest_v1(),
        maximum_lanes: 16,
    }
}
fn request(sequence: u64) -> NativeComputeFrameV1 {
    let mut features_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
    let mut weights_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
    features_q24[0] = 1 << 24;
    features_q24[1] = -(1 << 23);
    weights_q24[0] = 2 << 24;
    weights_q24[1] = 1 << 24;
    NativeComputeFrameV1 {
        generation: verifier().generation,
        sequence,
        task_digest: verifier().task_digest,
        kernel_digest: verifier().kernel_digest,
        lanes: 2,
        features_q24,
        weights_q24,
    }
}
#[test]
fn physically_executes_compiled_cpu_q24_dot_and_fixed_wires() {
    let original = request(1);
    let bytes = original.encode().expect("encode");
    assert_eq!(NativeComputeFrameV1::decode(&bytes).expect("decode"), original);
    assert_eq!(&bytes[..4], b"HNC1");
    assert!(bytes[89..96].iter().all(|v| *v == 0));
    let observation = run_shadow_native_compute_v1(verifier(), &original).expect("native compute");
    assert_eq!(observation.output_q24, 3_i64 << 23); // 2 - 0.5 = 1.5
    assert!(!observation.authority.grants_any());
    let returned = observation.encode().expect("result wire");
    assert_eq!(&returned[..4], b"HNR1");
    assert_eq!(
        decode_shadow_native_result_v1(&original, &returned).expect("result"),
        observation
    );
}
#[test]
fn native_cpu_rounding_is_signed_ties_even() {
    let mut frame = request(2);
    frame.lanes = 1;
    frame.features_q24[1] = 0;
    frame.weights_q24[1] = 0;
    frame.features_q24[0] = 1;
    frame.weights_q24[0] = 1 << 23;
    assert_eq!(run_shadow_native_compute_v1(verifier(), &frame).unwrap().output_q24, 0);
    frame.features_q24[0] = 3;
    assert_eq!(run_shadow_native_compute_v1(verifier(), &frame).unwrap().output_q24, 2);
    frame.features_q24[0] = -3;
    assert_eq!(run_shadow_native_compute_v1(verifier(), &frame).unwrap().output_q24, -2);
    frame.features_q24[0] = -1;
    assert_eq!(run_shadow_native_compute_v1(verifier(), &frame).unwrap().output_q24, 0);
}
#[test]
fn rejects_unapproved_code_identity_and_generation_without_execution() {
    let mut x = request(1);
    x.kernel_digest = Digest32::of_bytes(b"unapproved-executable");
    assert_eq!(x.encode(), Err(NativeComputeErrorV1::UnsupportedKernel));
    x = request(1);
    x.generation += 1;
    assert_eq!(
        run_shadow_native_compute_v1(verifier(), &x),
        Err(NativeComputeErrorV1::GenerationMismatch)
    );
    x = request(1);
    x.task_digest = Digest32::of_bytes(b"another-source");
    assert_eq!(
        run_shadow_native_compute_v1(verifier(), &x),
        Err(NativeComputeErrorV1::ScopeMismatch)
    );
}
#[test]
fn rejects_outside_lane_budget_and_noncanonical_extra_input() {
    let mut x = request(1);
    x.lanes = 17;
    assert_eq!(x.encode(), Err(NativeComputeErrorV1::LaneLimit));
    x = request(1);
    x.features_q24[2] = 1;
    assert_eq!(x.encode(), Err(NativeComputeErrorV1::NonCanonicalFrame));
    x = request(1);
    x.features_q24[0] = 9 << 24;
    assert_eq!(x.encode(), Err(NativeComputeErrorV1::InputLimit));
    x = request(1);
    x.sequence = 0;
    assert_eq!(x.encode(), Err(NativeComputeErrorV1::MissingBinding));
    x = request(1);
    assert_eq!(
        NativeComputeVerifierV1 { maximum_lanes: 1, ..verifier() }.verify(&x),
        Err(NativeComputeErrorV1::LaneLimit)
    );
}
#[test]
fn tampered_request_checksum_and_noncanonical_padding_are_denied() {
    let mut encoded = request(1).encode().unwrap();
    encoded[97] ^= 1;
    assert_eq!(
        NativeComputeFrameV1::decode(&encoded),
        Err(NativeComputeErrorV1::ChecksumMismatch)
    );
    let mut encoded = request(1).encode().unwrap();
    encoded[89] = 1;
    assert_eq!(
        NativeComputeFrameV1::decode(&encoded),
        Err(NativeComputeErrorV1::NonCanonicalFrame)
    );
    let mut encoded = request(1).encode().unwrap();
    encoded[4] ^= 1;
    assert_eq!(
        NativeComputeFrameV1::decode(&encoded),
        Err(NativeComputeErrorV1::NonCanonicalFrame)
    );
}
#[test]
fn result_replay_wrong_sequence_and_fabricated_content_are_rejected() {
    let x = request(5);
    let result = run_shadow_native_compute_v1(verifier(), &x).unwrap();
    let mut wire = result.encode().unwrap();
    assert_eq!(
        decode_shadow_native_result_v1(&request(6), &wire),
        Err(NativeComputeErrorV1::SequenceMismatch)
    );
    wire[20] ^= 1;
    assert_eq!(
        decode_shadow_native_result_v1(&x, &wire),
        Err(NativeComputeErrorV1::ChecksumMismatch)
    );
    wire = result.encode().unwrap();
    wire[60] = 1;
    assert_eq!(
        decode_shadow_native_result_v1(&x, &wire),
        Err(NativeComputeErrorV1::NonCanonicalFrame)
    );
}
#[test]
fn worst_allowed_values_do_not_overflow_or_emit_authority() {
    let mut x = request(77);
    x.lanes = 16;
    x.features_q24.fill(8 << 24);
    x.weights_q24.fill(-(8 << 24));
    let result = run_shadow_native_compute_v1(verifier(), &x).unwrap();
    assert_eq!(result.output_q24, -(1024_i64 << 24));
    assert!(!result.authority.grants_any());
    assert_eq!(
        decode_shadow_native_result_v1(&x, &result.encode().unwrap()).unwrap(), result
    );
}
