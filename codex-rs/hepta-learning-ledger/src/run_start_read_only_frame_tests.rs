use pretty_assertions::assert_eq;

use super::*;

#[test]
fn run_start_read_only_legacy_and_current_ranges_come_from_original_frames() {
    let fixture = Fixture::new();
    drop(fixture.create());
    let mut original = must(fs::read(fixture.path()));
    let first = record("legacy", b"legacy-objective");
    let encoded_current = encode_record(&first);
    let protocol_length = 32 + 4 + first.objective_function_v1_bytes.len();
    let mut payload = RECORD_DOMAIN_V1.to_vec();
    payload.extend_from_slice(
        &encoded_current[RECORD_DOMAIN.len()..encoded_current.len() - protocol_length],
    );
    let record_digest = Digest32::of_bytes(&payload);
    let chain_digest = digest_chain(Digest32::ZERO, /*sequence*/ 1, record_digest);
    let size = must(u32::try_from(payload.len()));
    let mut frame = Vec::new();
    frame.extend_from_slice(&size.to_be_bytes());
    frame.extend_from_slice(&(!size).to_be_bytes());
    frame.extend_from_slice(&1_u64.to_be_bytes());
    frame.extend_from_slice(Digest32::ZERO.as_array());
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(chain_digest.as_array());
    let checksum = Digest32::of_bytes(&frame);
    frame.extend_from_slice(checksum.as_array());
    original.extend_from_slice(&frame);
    replace_bytes(&fixture, &original);
    let first_anchor = RunStartAnchor {
        sequence: 1,
        chain_digest,
    };
    let mut writer = must(fixture.recover(RunStartRecovery::Acknowledged(first_anchor)));
    let mut expected_first = first;
    expected_first.objective_function_v1_digest = Digest32::ZERO;
    expected_first.objective_function_v1_bytes.clear();
    assert_eq!(must(writer.records()), vec![&expected_first]);
    assert_ne!(encode_record(&expected_first).len(), payload.len());
    let second = record("current", b"current-objective");
    let receipt = must(writer.append(chain_digest, second.clone()));
    let physical = must(fs::read(fixture.path()));
    let reader = view(&fixture, anchor(&receipt));
    assert_eq!(
        must(reader.read_with_frame(&id("legacy"))),
        Some(RunStartReadOnlyFrameV1 {
            observed: RunStartReadOnlyPublicationV1 {
                record: expected_first,
                publication: RunStartPublication {
                    sequence: 1,
                    record_digest,
                    chain_digest
                },
            },
            frame_start: HEADER as u64,
            frame_end: original.len() as u64,
            observed_length: physical.len() as u64,
        })
    );
    assert_eq!(
        must(reader.read_with_frame_at_original_prefix(
            &id("current"),
            original.len() as u64,
            Digest32::of_bytes(&original),
        )),
        Some(RunStartReadOnlyFrameV1 {
            observed: RunStartReadOnlyPublicationV1 {
                record: second,
                publication: RunStartPublication {
                    sequence: receipt.sequence,
                    record_digest: receipt.record_digest,
                    chain_digest: receipt.chain_digest,
                },
            },
            frame_start: original.len() as u64,
            frame_end: physical.len() as u64,
            observed_length: physical.len() as u64,
        })
    );
    assert_eq!(must(fs::read(fixture.path())), physical);
}

#[test]
fn run_start_read_only_original_prefix_is_same_image_data_not_fresh_ack() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let original = must(fs::read(fixture.path()));
    let complete = match must(reader.read_with_frame_at_original_prefix(
        &id("original"),
        original.len() as u64,
        Digest32::of_bytes(&original),
    )) {
        Some(frame) => frame,
        None => panic!("actual original RunStart must exist"),
    };
    // The caller still must enforce frame_start >= its independently retained
    // baseline. Matching bytes alone cannot establish a new live acknowledgement.
    assert!(complete.frame_start < original.len() as u64);
    assert_eq!(
        must(reader.read_with_frame_at_original_prefix(
            &id("original"),
            /*prefix_length*/ 0,
            Digest32::of_bytes(&[]),
        )),
        Some(complete)
    );
    assert_eq!(
        reader.read_with_frame_at_original_prefix(
            &id("original"),
            original.len() as u64,
            digest("wrong-original-prefix"),
        ),
        Err(RunStartStoreError::AnchorMismatch)
    );
    assert_eq!(
        reader.read_with_frame_at_original_prefix(
            &id("original"),
            original.len() as u64,
            Digest32::of_bytes(&original),
        ),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn run_start_read_only_original_prefix_cannot_extend_beyond_physical_file() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let original = must(fs::read(fixture.path()));
    assert_eq!(
        reader.read_with_frame_at_original_prefix(
            &id("original"),
            original.len() as u64 + 1,
            Digest32::of_bytes(&original),
        ),
        Err(RunStartStoreError::AnchorMismatch)
    );
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
    assert_eq!(must(fs::read(fixture.path())), original);
}
