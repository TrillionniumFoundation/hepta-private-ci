use super::*;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn fixture() -> CognitiveSnapshot {
    let records = (0..64)
        .map(|index| MemoryRecord {
            record_id: id(&format!("memory:{index:02}")),
            revision: Revision::new(1).expect("revision"),
            kind: match index % 4 {
                0 => MemoryKind::Episode,
                1 => MemoryKind::Fact,
                2 => MemoryKind::Preference,
                _ => MemoryKind::Procedure,
            },
            content_digest: Digest32::of_bytes(format!("content:{index:02}").as_bytes()),
            predecessor_digest: None,
            citations: (0..index % 5)
                .map(|source| Citation {
                    source_id: id(&format!("source:{index:02}:{source}")),
                    source_digest: Digest32::of_bytes(
                        format!("source:{index:02}:{source}").as_bytes(),
                    ),
                })
                .collect(),
            state: if index % 11 == 0 {
                RecordState::Tombstone
            } else {
                RecordState::Live
            },
        })
        .collect();
    build_snapshot(Generation::new(9).expect("generation"), records).expect("snapshot")
}

fn next(state: &mut u64) -> u64 {
    *state = state
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    *state
}

#[test]
fn deterministic_fuzz_corpus_never_escapes_declared_bounds() {
    let snapshot = fixture();
    let mut state = 0x6a09_e667_f3bc_c909_u64;

    for case in 0..4_096 {
        let id_count = usize::try_from(next(&mut state) % 24).expect("small count");
        let mut record_ids = Vec::with_capacity(id_count);
        for _ in 0..id_count {
            let raw = next(&mut state) % 80;
            record_ids.push(id(&format!("memory:{raw:02}")));
        }

        let mut fields = Vec::new();
        let field_bits = next(&mut state);
        if field_bits & 1 != 0 {
            fields.push(ReadFieldV1::ContentDigest);
        }
        if field_bits & 2 != 0 {
            fields.push(ReadFieldV1::PredecessorDigest);
        }
        if field_bits & 4 != 0 {
            fields.push(ReadFieldV1::Citations);
        }
        if field_bits & 8 != 0 && !fields.is_empty() {
            fields.push(fields[0]);
        }

        let budget_selector = next(&mut state) % 32;
        let maximum_encoded_bytes = match budget_selector {
            0 => 0,
            1 => MAX_ENCODED_READ_RESULT_BYTES_V2 + 1,
            _ => usize::try_from(64 + next(&mut state) % 8_128).expect("small budget"),
        };

        let outcome = read_ids_v1(
            &snapshot,
            ReadIdsRequestV1 {
                snapshot_digest: snapshot.snapshot_digest,
                record_ids,
                fields,
                maximum_encoded_bytes,
            },
        );

        match outcome {
            Ok(result) => {
                assert!(
                    result.total_encoded_bytes() <= maximum_encoded_bytes,
                    "case {case}"
                );
                assert_eq!(result.canonical_bytes().len(), result.total_encoded_bytes());
                assert_eq!(
                    Digest32::of_bytes(
                        &result.canonical_bytes()[..result.payload_encoded_bytes()]
                    ),
                    result.receipt_digest(),
                    "case {case}"
                );
                assert!(!result.authority().grants_any(), "case {case}");
            }
            Err(ReadIdsError::EncodedResultTooLarge { actual, maximum }) => {
                assert!(actual > maximum, "case {case}");
            }
            Err(
                ReadIdsError::DuplicateRecordId
                | ReadIdsError::DuplicateField
                | ReadIdsError::InvalidMaximumEncodedBytes { .. },
            ) => {}
            Err(other) => panic!("unexpected fuzz outcome for case {case}: {other:?}"),
        }
    }
}
