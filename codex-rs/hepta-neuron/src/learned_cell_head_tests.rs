use super::*;
use crate::learned_cell_features::{LEARNED_FEATURE_MAGIC_770_V1, LearnedFeaturePins770V1};
use pretty_assertions::assert_eq;

fn digest(value: &str) -> Digest32 { value.parse().unwrap_or_else(|e| panic!("{e:?}")) }
fn generation(value: u64) -> Generation { Generation::new(value).unwrap_or_else(|e| panic!("{e:?}")) }
fn identity() -> Digest32 { Digest32::of_bytes(b"synthetic-feature-identity") }

fn fixture(mode: u8) -> (Vec<u8>, LearnedHeadPins770V1) {
    // Digests and numerical answers were independently constructed with Python
    // stdlib canonical JSON/struct/math; these are synthetic ABI regression data.
    let expected = [
        "ffdfa314952ed7fafc227f9ebea0298aec3443049f1907567389178f31c67a61",
        "b0af5230a6399cb54c0bb190b038491168e471538e368759426ede76ba0ddc0f",
        "4287c797880e6457a80dd9036a6a18050a379a7703d4c77f71fceee4427e910e",
    ];
    let mut p = vec![0.0_f64; [1542, 3082, 9242][usize::from(mode)]];
    let w = if mode == 2 { 6160 } else { 0 };
    p[w..w + 4].copy_from_slice(&[0.25, -0.5, -0.75, 0.125]);
    let b = w + 1540 + if mode == 0 { 0 } else { 770 };
    p[b..b + 2].copy_from_slice(&[0.1, -0.2]);
    if mode != 0 {
        p[w + 1540..w + 1542].copy_from_slice(&[0.03, -0.02]);
        p[b + 2..b + 4].copy_from_slice(&[0.2, -0.1]);
    }
    if mode == 2 { p[0] = 0.25; p[1] = -0.125; p[3080] = 0.02; p[3084] = -0.03; }
    let mut pins = LearnedHeadPins770V1 {
        artifact_digest: Digest32::ZERO, feature_identity_digest: identity(),
        generation: generation(1), task_digest: Digest32::of_bytes(b"action_usefulness"),
        predictor_digest: digest(expected[usize::from(mode)]),
    };
    let mut bytes = LEARNED_HEAD_MAGIC_770_V1.to_vec();
    bytes.push(mode);
    bytes.extend_from_slice(pins.feature_identity_digest.as_array());
    bytes.extend_from_slice(&pins.generation.get().to_le_bytes());
    bytes.extend_from_slice(pins.task_digest.as_array());
    bytes.extend_from_slice(pins.predictor_digest.as_array());
    for value in p { bytes.extend_from_slice(&value.to_le_bytes()); }
    pins.artifact_digest = Digest32::of_bytes(&bytes);
    (bytes, pins)
}

fn features(identity: Digest32, generation: Generation) -> SharedLearnedFeatures770V1 {
    let mut bytes = LEARNED_FEATURE_MAGIC_770_V1.to_vec();
    bytes.extend_from_slice(identity.as_array());
    bytes.extend_from_slice(&generation.get().to_le_bytes());
    bytes.extend_from_slice(&2_u64.to_le_bytes());
    for id in [b"source-one", b"source-two"] { bytes.extend_from_slice(Digest32::of_bytes(id).as_array()); }
    for sign in [1.0_f64, -1.0] {
        for i in 0..770 {
            let x = sign * if i == 0 { 3.0 } else if i == 1 { 4.0 } else { 0.0 };
            bytes.extend_from_slice(&x.to_le_bytes());
        }
    }
    let pins = LearnedFeaturePins770V1 { artifact_digest: Digest32::of_bytes(&bytes), feature_identity_digest: identity, generation };
    SharedLearnedFeatures770V1::import(&bytes, &pins).unwrap_or_else(|e| panic!("{e:?}"))
}

fn load(bytes: &[u8], pins: &LearnedHeadPins770V1) -> LearnedCellHead770V1 {
    LearnedCellHead770V1::import(bytes, pins).unwrap_or_else(|e| panic!("{e:?}"))
}

fn repin(bytes: &mut [u8], pins: &mut LearnedHeadPins770V1, value: &str) {
    pins.predictor_digest = digest(value);
    bytes[HEADER_BYTES - 32..HEADER_BYTES].copy_from_slice(pins.predictor_digest.as_array());
    pins.artifact_digest = Digest32::of_bytes(bytes);
}

#[test]
fn all_three_modes_match_external_answers_and_borrow_one_shared_buffer() {
    let expected = [
        [[-12.38699323296045, -5.749774770204643], [12.586993232960449, 5.349774770204642]],
        [[-3.233921572806305, -4.742367097796952], [8.07063592271784, 1.7199350066576635]],
        [[-3.28410933991227, -4.697198107401583], [8.120823689823801, 1.6747660162622953]],
    ];
    let batch = features(identity(), generation(1));
    let pointer = batch.normalized.as_ptr();
    for mode in 0..3 {
        let (mut bytes, pins) = fixture(mode);
        let head = load(&bytes, &pins);
        bytes.fill(0);
        let result = head.evaluate(&batch).unwrap_or_else(|e| panic!("{e:?}"));
        for (row, expected) in result.raw_logits.iter().zip(expected[usize::from(mode)]) {
            for (value, expected) in row.iter().zip(expected) { assert!((value - expected).abs() < 1e-12); }
        }
        assert_eq!(head.evaluate(&batch).unwrap_or_else(|e| panic!("{e:?}")), result);
        assert_eq!(batch.normalized.as_ptr(), pointer);
        assert_eq!(result.predictor_digest, pins.predictor_digest);
        assert_eq!(result.feature_batch_digest, batch.artifact_digest());
    }
}

#[test]
fn refuses_stale_external_task_feature_and_generation_bindings() {
    let (bytes, pins) = fixture(1);
    for field in [0, 1, 2] {
        let mut changed = pins;
        match field { 0 => changed.feature_identity_digest = Digest32::of_bytes(b"other"),
            1 => changed.task_digest = Digest32::of_bytes(b"other"),
            _ => changed.predictor_digest = Digest32::of_bytes(b"other") }
        assert_eq!(LearnedCellHead770V1::import(&bytes, &changed).err(), Some(LearnedHeadError770V1::IdentityMismatch));
    }
    let mut changed = pins; changed.generation = generation(2);
    assert_eq!(LearnedCellHead770V1::import(&bytes, &changed).err(), Some(LearnedHeadError770V1::GenerationMismatch));
    let head = load(&bytes, &pins);
    assert_eq!(head.evaluate(&features(identity(), generation(2))).err(), Some(LearnedHeadError770V1::GenerationMismatch));
    assert_eq!(head.evaluate(&features(Digest32::of_bytes(b"other"), generation(1))).err(), Some(LearnedHeadError770V1::IdentityMismatch));
}

#[test]
fn authenticates_all_tensor_bytes_and_rejects_shape_or_mode_changes() {
    let (mut bytes, mut pins) = fixture(2);
    bytes[HEADER_BYTES + 17] ^= 1;
    assert_eq!(LearnedCellHead770V1::import(&bytes, &pins).err(), Some(LearnedHeadError770V1::ArtifactDigestMismatch));
    pins.artifact_digest = Digest32::of_bytes(&bytes);
    assert_eq!(LearnedCellHead770V1::import(&bytes, &pins).err(), Some(LearnedHeadError770V1::PredictorDigestMismatch));
    bytes.pop(); pins.artifact_digest = Digest32::of_bytes(&bytes);
    assert_eq!(LearnedCellHead770V1::import(&bytes, &pins).err(), Some(LearnedHeadError770V1::InvalidEnvelope));
    let (mut bytes, mut pins) = fixture(0);
    bytes[LEARNED_HEAD_MAGIC_770_V1.len()] = 255; pins.artifact_digest = Digest32::of_bytes(&bytes);
    assert_eq!(LearnedCellHead770V1::import(&bytes, &pins).err(), Some(LearnedHeadError770V1::InvalidEnvelope));
}

#[test]
fn rejects_authenticated_nonfinite_parameters_and_arithmetic_overflow() {
    let (mut bytes, mut pins) = fixture(0);
    bytes[HEADER_BYTES..HEADER_BYTES + 8].copy_from_slice(&f64::from_bits(0x7ff8_0000_0000_0000).to_le_bytes());
    repin(&mut bytes, &mut pins, "9735dbe77cd6e5401c0d7c92805e64c0f8fa9216f2fb70d0761f431f740fdccb");
    assert_eq!(LearnedCellHead770V1::import(&bytes, &pins).err(), Some(LearnedHeadError770V1::Nonfinite));
    bytes[HEADER_BYTES..HEADER_BYTES + 8].copy_from_slice(&f64::MAX.to_le_bytes());
    repin(&mut bytes, &mut pins, "24018d83f8271866acb50173cb38cc4f33ed5fb1d8d7f84c931368dce2792920");
    assert_eq!(load(&bytes, &pins).evaluate(&features(identity(), generation(1))).err(), Some(LearnedHeadError770V1::Nonfinite));
}

#[test]
fn applies_the_declared_gate_clipping_before_exponentiation() {
    let (mut bytes, mut pins) = fixture(1);
    let start = HEADER_BYTES + (1540 + 770 + 2) * 8;
    bytes[start..start + 8].copy_from_slice(&100_f64.to_le_bytes());
    bytes[start + 8..start + 16].copy_from_slice(&(-100_f64).to_le_bytes());
    repin(&mut bytes, &mut pins, "47be48b76454ca6d0a611395bdaf3e04a88ed39c1f19487956c5473c53ee69c0");
    let result = load(&bytes, &pins).evaluate(&features(identity(), generation(1))).unwrap_or_else(|e| panic!("{e:?}"));
    for (value, expected) in result.raw_logits[0].iter().zip([4.2623310776534815, -8.524662155306963]) {
        assert!((value - expected).abs() < 1e-12);
    }
}
