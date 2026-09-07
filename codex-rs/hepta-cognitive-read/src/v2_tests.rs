use super::*;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn revision(value: u64) -> Revision {
    let Ok(value) = Revision::new(value) else {
        panic!("test revision must be valid");
    };
    value
}

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be valid");
    };
    value
}

fn record(name: &str, kind: MemoryKind, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id(name),
        revision: revision(/*value*/ 1),
        kind,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_digest: None,
        citations: Vec::new(),
        state,
    }
}

fn snapshot(records: Vec<MemoryRecord>) -> CognitiveSnapshot {
    let Ok(snapshot) = build_snapshot(generation(/*value*/ 1), records) else {
        panic!("test snapshot must build");
    };
    snapshot
}

fn request(
    snapshot: &CognitiveSnapshot,
    maximum_encoded_bytes: usize,
    include_tombstones: bool,
) -> ReadRequestV2 {
    ReadRequestV2 {
        read_request: ReadRequest {
            snapshot_digest: snapshot.snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 1_024,
            include_tombstones,
        },
        maximum_encoded_bytes,
    }
}

fn sample_snapshot() -> CognitiveSnapshot {
    snapshot(vec![
        record("memory:a", MemoryKind::Fact, RecordState::Live),
        record("memory:b", MemoryKind::Episode, RecordState::Live),
        record("memory:c", MemoryKind::Procedure, RecordState::Tombstone),
    ])
}

fn resign(bytes: &mut [u8]) {
    let digest_offset = bytes.len() - 32;
    let digest = Digest32::of_bytes(&bytes[..digest_offset]);
    bytes[digest_offset..].copy_from_slice(digest.as_array());
}

fn rebind(bytes: &[u8], request: &ReadRequestV2) -> Vec<u8> {
    let mut rebound = bytes.to_vec();
    let binding_offset = READ_RECEIPT_V2_DOMAIN.len() + 4 + 32;
    rebound[binding_offset..binding_offset + 32]
        .copy_from_slice(request.binding_digest().as_array());
    resign(&mut rebound);
    rebound
}

fn first_record_kind_offset(bytes: &[u8]) -> usize {
    let frame_offset = READ_RECEIPT_V2_DOMAIN.len() + 4 + 32 + 32 + 4;
    let id_length_offset = frame_offset + 4;
    let id_length = u32::from_be_bytes(
        bytes[id_length_offset..id_length_offset + 4]
            .try_into()
            .unwrap_or([0; 4]),
    ) as usize;
    id_length_offset + 4 + id_length + 8
}

#[test]
fn complete_envelope_round_trips_and_binds_every_output_byte() {
    let snapshot = sample_snapshot();
    let Ok(result) = read_v2(
        &snapshot,
        request(
            &snapshot,
            MAX_ENCODED_READ_RESULT_BYTES_V2,
            /*include_tombstones*/ true,
        ),
    ) else {
        panic!("V2 read must succeed");
    };
    assert_eq!(result.records().len(), 3);
    assert_eq!(result.omitted_count(), 0);
    assert_eq!(result.snapshot_digest(), snapshot.snapshot_digest);
    assert_eq!(
        result.request_binding_digest(),
        request(
            &snapshot,
            MAX_ENCODED_READ_RESULT_BYTES_V2,
            /*include_tombstones*/ true,
        )
        .binding_digest()
    );
    assert_eq!(result.authority(), AuthorityPosture::DENY_ALL);
    assert!(!result.authority().grants_any());
    assert_eq!(
        result.request_binding_digest().to_string(),
        "6eeb802c77e93e639eb7ca1cf36eb52c91ce7d4d0f049c0ac5de148984f3ae0a"
    );
    assert_eq!(result.canonical_bytes().len(), 333);
    assert_eq!(
        result.receipt_digest().to_string(),
        "3dd1e9f4aa6e52efc7e781487bb9501585b06e140315ff39990c7289c48ad91f"
    );
    let declared_length_offset = READ_RECEIPT_V2_DOMAIN.len();
    let declared_length = u32::from_be_bytes(
        result.canonical_bytes()[declared_length_offset..declared_length_offset + 4]
            .try_into()
            .unwrap_or([0; 4]),
    ) as usize;
    assert_eq!(declared_length, result.canonical_bytes().len());
    assert_eq!(
        &result.canonical_bytes()[result.canonical_bytes().len() - 32..],
        result.receipt_digest().as_array()
    );
    assert_eq!(
        decode_read_result_v2(result.canonical_bytes()),
        Ok(result.clone())
    );

    let mut tampered = result.canonical_bytes().to_vec();
    let last = tampered.len() - 1;
    tampered[last] ^= 1;
    assert_eq!(
        decode_read_result_v2(&tampered),
        Err(ReadV2Error::ReceiptDigestMismatch)
    );
}

#[test]
fn a_valid_result_cannot_be_replayed_as_a_different_query() {
    let snapshot = sample_snapshot();
    let original_request = request(
        &snapshot,
        MAX_ENCODED_READ_RESULT_BYTES_V2,
        /*include_tombstones*/ true,
    );
    let Ok(result) = read_v2(&snapshot, original_request.clone()) else {
        panic!("V2 read must succeed");
    };
    assert_eq!(
        ReadResultV2::from_canonical_bytes_for_request(result.canonical_bytes(), &original_request,),
        Ok(result.clone())
    );

    let mut different_request = original_request;
    different_request.read_request.allowed_kinds = vec![MemoryKind::Fact];
    assert_eq!(
        ReadResultV2::from_canonical_bytes_for_request(
            result.canonical_bytes(),
            &different_request,
        ),
        Err(ReadV2Error::RequestBindingMismatch)
    );
}

#[test]
fn recomputed_digests_cannot_bypass_request_semantics() {
    let snapshot = sample_snapshot();
    let original_request = request(
        &snapshot,
        MAX_ENCODED_READ_RESULT_BYTES_V2,
        /*include_tombstones*/ true,
    );
    let Ok(result) = read_v2(&snapshot, original_request.clone()) else {
        panic!("V2 read must succeed");
    };

    let mut changed = original_request.clone();
    changed.maximum_encoded_bytes = result.canonical_bytes().len() - 1;
    let rebound = rebind(result.canonical_bytes(), &changed);
    assert_eq!(
        ReadResultV2::from_canonical_bytes_for_request(&rebound, &changed),
        Err(ReadV2Error::EncodedResultTooLarge {
            actual: rebound.len(),
            maximum: changed.maximum_encoded_bytes,
        })
    );

    let mut semantic_variants = Vec::new();
    let mut changed = original_request.clone();
    changed.read_request.snapshot_digest = Digest32::of_bytes(b"other snapshot");
    semantic_variants.push(changed);
    let mut changed = original_request.clone();
    changed.read_request.maximum_results = 1;
    semantic_variants.push(changed);
    let mut changed = original_request.clone();
    changed.read_request.allowed_kinds = vec![MemoryKind::Fact];
    semantic_variants.push(changed);
    let mut changed = original_request;
    changed.read_request.include_tombstones = false;
    semantic_variants.push(changed);

    for changed in semantic_variants {
        let rebound = rebind(result.canonical_bytes(), &changed);
        assert_eq!(
            ReadResultV2::from_canonical_bytes_for_request(&rebound, &changed),
            Err(ReadV2Error::ResultViolatesRequest)
        );
    }

    let mut invalid = request(
        &snapshot,
        MAX_ENCODED_READ_RESULT_BYTES_V2,
        /*include_tombstones*/ true,
    );
    invalid.read_request.maximum_results = 0;
    assert_eq!(
        ReadResultV2::from_canonical_bytes_for_request(result.canonical_bytes(), &invalid),
        Err(ReadV2Error::Read(Error::InvalidMaximumResults))
    );
    invalid.read_request.maximum_results = 8;
    invalid.read_request.allowed_kinds = vec![MemoryKind::Fact, MemoryKind::Fact];
    assert_eq!(
        ReadResultV2::from_canonical_bytes_for_request(result.canonical_bytes(), &invalid),
        Err(ReadV2Error::Read(Error::DuplicateKind))
    );
}

#[test]
fn exact_cap_is_accepted_and_the_next_record_is_omitted() {
    let snapshot = sample_snapshot();
    let Ok(full) = read_v2(
        &snapshot,
        request(
            &snapshot,
            MAX_ENCODED_READ_RESULT_BYTES_V2,
            /*include_tombstones*/ true,
        ),
    ) else {
        panic!("full V2 read must succeed");
    };
    let exact_cap = full.canonical_bytes().len();
    let Ok(exact) = read_v2(
        &snapshot,
        request(&snapshot, exact_cap, /*include_tombstones*/ true),
    ) else {
        panic!("the exact encoded cap must be accepted");
    };
    assert_eq!(exact.records(), full.records());
    assert_eq!(exact.omitted_count(), full.omitted_count());
    assert_eq!(exact.canonical_bytes().len(), exact_cap);
    assert_ne!(
        exact.request_binding_digest(),
        full.request_binding_digest()
    );

    let smaller_cap = exact_cap - 1;
    let Ok(smaller) = read_v2(
        &snapshot,
        request(&snapshot, smaller_cap, /*include_tombstones*/ true),
    ) else {
        panic!("a smaller cap must return the fitting canonical prefix");
    };
    assert_eq!(smaller.records().len(), full.records().len() - 1);
    assert_eq!(smaller.omitted_count(), 1);
    assert!(smaller.canonical_bytes().len() <= smaller_cap);
}

#[test]
fn one_mib_ceiling_bounds_the_actual_complete_envelope() {
    let mut records = Vec::new();
    for record_index in 0..1_024 {
        let name = format!("memory:{record_index:04}");
        let mut value = record(&name, MemoryKind::Fact, RecordState::Live);
        value.citations = (0..64)
            .map(|citation_index| Citation {
                source_id: id(&format!("source:{citation_index:02}")),
                source_digest: Digest32::of_bytes(
                    format!("{record_index}:{citation_index}").as_bytes(),
                ),
            })
            .collect();
        records.push(value);
    }
    let snapshot = snapshot(records);
    let Ok(result) = read_v2(
        &snapshot,
        request(
            &snapshot,
            MAX_ENCODED_READ_RESULT_BYTES_V2,
            /*include_tombstones*/ false,
        ),
    ) else {
        panic!("bounded large read must succeed");
    };
    assert!(result.canonical_bytes().len() <= MAX_ENCODED_READ_RESULT_BYTES_V2);
    assert!(result.records().len() < 1_024);
    assert_eq!(result.records().len() + result.omitted_count(), 1_024);
    let next_record = &snapshot.records[result.records().len()];
    let next_frame_length = 4 + encode_record_v2(next_record).len();
    assert!(result.canonical_bytes().len() + next_frame_length > MAX_ENCODED_READ_RESULT_BYTES_V2);
}

#[test]
fn record_and_citation_permutations_have_identical_canonical_bytes() {
    let mut first = record("memory:a", MemoryKind::Fact, RecordState::Live);
    first.citations = vec![
        Citation {
            source_id: id("source:z"),
            source_digest: Digest32::of_bytes(b"z"),
        },
        Citation {
            source_id: id("source:a"),
            source_digest: Digest32::of_bytes(b"a"),
        },
    ];
    let original = snapshot(vec![
        first,
        record("memory:b", MemoryKind::Episode, RecordState::Live),
    ]);
    let mut permuted = original.clone();
    permuted.records.reverse();
    for record in &mut permuted.records {
        record.citations.reverse();
    }
    assert!(permuted.validate_integrity().is_ok());
    assert_eq!(
        read_v2(
            &original,
            request(
                &original,
                MAX_ENCODED_READ_RESULT_BYTES_V2,
                /*include_tombstones*/ false,
            )
        ),
        read_v2(
            &permuted,
            request(
                &permuted,
                MAX_ENCODED_READ_RESULT_BYTES_V2,
                /*include_tombstones*/ false,
            )
        )
    );
}

#[test]
fn unknown_tags_authority_and_trailing_fields_are_rejected() {
    let snapshot = sample_snapshot();
    let Ok(result) = read_v2(
        &snapshot,
        request(
            &snapshot,
            MAX_ENCODED_READ_RESULT_BYTES_V2,
            /*include_tombstones*/ true,
        ),
    ) else {
        panic!("V2 read must succeed");
    };
    let kind_offset = first_record_kind_offset(result.canonical_bytes());

    for (offset, value, expected) in [
        (kind_offset, 0xff, ReadV2Error::UnknownMemoryKind(0xff)),
        (kind_offset + 1, 0xff, ReadV2Error::UnknownRecordState(0xff)),
        (
            result.canonical_bytes().len() - 33,
            1,
            ReadV2Error::UnknownAuthorityBits(1),
        ),
    ] {
        let mut unknown = result.canonical_bytes().to_vec();
        unknown[offset] = value;
        resign(&mut unknown);
        assert_eq!(decode_read_result_v2(&unknown), Err(expected));
    }

    let digest_offset = result.canonical_bytes().len() - 32;
    let mut trailing = result.canonical_bytes()[..digest_offset].to_vec();
    trailing.push(0xff);
    let encoded_length = u32::try_from(trailing.len() + 32).unwrap_or(u32::MAX);
    let length_offset = READ_RECEIPT_V2_DOMAIN.len();
    trailing[length_offset..length_offset + 4].copy_from_slice(&encoded_length.to_be_bytes());
    let digest = Digest32::of_bytes(&trailing);
    trailing.extend_from_slice(digest.as_array());
    assert_eq!(
        decode_read_result_v2(&trailing),
        Err(ReadV2Error::InvalidCanonicalEncoding)
    );
}

#[test]
fn current_tombstone_or_kind_change_never_resurrects_history() {
    let original = record("memory:history", MemoryKind::Fact, RecordState::Live);
    for (kind, state) in [
        (MemoryKind::Fact, RecordState::Tombstone),
        (MemoryKind::Episode, RecordState::Live),
    ] {
        let mut successor = original.clone();
        successor.revision = revision(/*value*/ 2);
        successor.predecessor_digest = Some(original.record_digest());
        successor.kind = kind;
        successor.state = state;
        let snapshot = snapshot(vec![original.clone(), successor.clone()]);
        let filtered_request = ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: snapshot.snapshot_digest,
                allowed_kinds: vec![MemoryKind::Fact],
                maximum_results: 8,
                include_tombstones: false,
            },
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        };
        let Ok(filtered) = read_v2(&snapshot, filtered_request) else {
            panic!("current-head V2 read must succeed");
        };
        assert_eq!(filtered.records(), &[]);

        let Ok(current) = read_v2(
            &snapshot,
            request(
                &snapshot,
                MAX_ENCODED_READ_RESULT_BYTES_V2,
                /*include_tombstones*/ true,
            ),
        ) else {
            panic!("current head must remain inspectable");
        };
        assert_eq!(current.records(), &[successor]);
    }
}
