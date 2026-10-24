use super::*;
use pretty_assertions::assert_eq;

fn fixture(rows: usize) -> (Vec<u8>, LearnedFeaturePins770V1) {
    let mut pins = LearnedFeaturePins770V1 {
        artifact_digest: Digest32::ZERO,
        feature_identity_digest: Digest32::of_bytes(b"synthetic-feature-identity"),
        generation: Generation::new(1).unwrap_or_else(|e| panic!("{e:?}")),
    };
    let mut bytes = LEARNED_FEATURE_MAGIC_770_V1.to_vec();
    bytes.extend_from_slice(pins.feature_identity_digest.as_array());
    bytes.extend_from_slice(&pins.generation.get().to_le_bytes());
    bytes.extend_from_slice(&(rows as u64).to_le_bytes());
    for i in 0..rows {
        bytes.extend_from_slice(Digest32::of_bytes(&i.to_le_bytes()).as_array());
    }
    bytes.extend_from_slice(&vec![0; rows * 770 * 8]);
    pins.artifact_digest = Digest32::of_bytes(&bytes);
    (bytes, pins)
}

fn load(bytes: &[u8], pins: &LearnedFeaturePins770V1) -> SharedLearnedFeatures770V1 {
    SharedLearnedFeatures770V1::import(bytes, pins).unwrap_or_else(|e| panic!("{e:?}"))
}

fn failure(bytes: &[u8], pins: &LearnedFeaturePins770V1) -> LearnedFeatureError770V1 {
    SharedLearnedFeatures770V1::import(bytes, pins)
        .err()
        .unwrap_or_else(|| panic!("invalid input accepted"))
}

#[test]
fn normalizes_once_and_shares_an_immutable_owned_buffer() {
    let (mut bytes, mut pins) = fixture(2);
    let start = HEADER_BYTES + 64;
    bytes[start..start + 8].copy_from_slice(&3_f64.to_le_bytes());
    bytes[start + 8..start + 16].copy_from_slice(&4_f64.to_le_bytes());
    pins.artifact_digest = Digest32::of_bytes(&bytes);
    let batch = load(&bytes, &pins);
    let alias = batch.clone();
    bytes.fill(0);
    assert!(Arc::ptr_eq(&batch.normalized, &alias.normalized));
    assert_eq!(&batch.normalized[..2], &[0.6 * 770_f64.sqrt(), 0.8 * 770_f64.sqrt()]);
    assert!(batch.normalized[2..].iter().all(|x| *x == 0.0));
    assert_eq!(batch.tensor_bytes(), 2 * 770 * 8);
    assert_eq!(batch.source_record_digests(), alias.source_record_digests());
}

#[test]
fn external_identity_generation_and_complete_source_bytes_are_bound() {
    let (mut bytes, pins) = fixture(2);
    let mut changed = pins;
    changed.feature_identity_digest = Digest32::of_bytes(b"other-space");
    assert_eq!(failure(&bytes, &changed), LearnedFeatureError770V1::IdentityMismatch);
    changed = pins;
    changed.generation = Generation::new(2).unwrap_or_else(|e| panic!("{e:?}"));
    assert_eq!(failure(&bytes, &changed), LearnedFeatureError770V1::GenerationMismatch);
    bytes[HEADER_BYTES..HEADER_BYTES + 64].rotate_left(32);
    assert_eq!(failure(&bytes, &pins), LearnedFeatureError770V1::ArtifactDigestMismatch);
}

#[test]
fn refuses_invalid_rows_trailing_bytes_and_duplicate_or_zero_sources() {
    for rows in [0, 65] {
        let (bytes, pins) = fixture(rows);
        assert_eq!(failure(&bytes, &pins), LearnedFeatureError770V1::InvalidEnvelope);
    }
    let (mut bytes, mut pins) = fixture(1);
    bytes.push(0);
    pins.artifact_digest = Digest32::of_bytes(&bytes);
    assert_eq!(failure(&bytes, &pins), LearnedFeatureError770V1::InvalidEnvelope);
    for zero in [false, true] {
        let (mut bytes, mut pins) = fixture(2);
        if zero {
            bytes[HEADER_BYTES..HEADER_BYTES + 32].fill(0);
        } else {
            bytes.copy_within(HEADER_BYTES..HEADER_BYTES + 32, HEADER_BYTES + 32);
        }
        pins.artifact_digest = Digest32::of_bytes(&bytes);
        assert_eq!(failure(&bytes, &pins), LearnedFeatureError770V1::InvalidSource);
    }
}

#[test]
fn refuses_nonfinite_values_and_normalization_overflow() {
    for value in [f64::NAN, f64::INFINITY, f64::MAX] {
        let (mut bytes, mut pins) = fixture(1);
        let start = HEADER_BYTES + 32;
        bytes[start..start + 8].copy_from_slice(&value.to_le_bytes());
        pins.artifact_digest = Digest32::of_bytes(&bytes);
        assert_eq!(failure(&bytes, &pins), LearnedFeatureError770V1::Nonfinite);
    }
}
