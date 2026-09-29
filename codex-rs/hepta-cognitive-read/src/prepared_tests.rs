use std::error::Error as StdError;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::PreparedReadSnapshotV1;
use crate::Error;
use crate::ReadFieldV1;
use crate::ReadIdsError;
use crate::ReadIdsRequestV1;
use crate::read_ids_v1;

type TestResult = Result<(), Box<dyn StdError>>;

fn snapshot(generation: u64) -> Result<CognitiveSnapshot, Box<dyn StdError>> {
    let records = (0..1_100)
        .map(|index| {
            Ok(MemoryRecord {
                record_id: StableId::new(format!("memory:{index:04}"))?,
                revision: Revision::new(1)?,
                kind: MemoryKind::Fact,
                content_digest: Digest32::of_bytes(format!("content:{index}").as_bytes()),
                predecessor_digest: None,
                citations: vec![Citation {
                    source_id: StableId::new("source:one")?,
                    source_digest: Digest32::of_bytes(b"source"),
                }],
                state: RecordState::Live,
            })
        })
        .collect::<Result<Vec<_>, Box<dyn StdError>>>()?;
    Ok(build_snapshot(Generation::new(generation)?, records)?)
}

fn request(snapshot: &CognitiveSnapshot) -> Result<ReadIdsRequestV1, Box<dyn StdError>> {
    Ok(ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: vec![
            StableId::new("memory:1099")?,
            StableId::new("memory:missing")?,
        ],
        fields: Vec::new(),
        maximum_encoded_bytes: 4096,
    })
}

#[test]
fn prepared_reads_match_one_shot_for_all_field_sets_and_permutations() -> TestResult {
    let snapshot = snapshot(/*generation*/ 1)?;
    let prepared = PreparedReadSnapshotV1::new(&snapshot)?;
    let fields = [
        ReadFieldV1::ContentDigest,
        ReadFieldV1::PredecessorDigest,
        ReadFieldV1::Citations,
    ];
    for mask in 0usize..8 {
        let mut request = request(&snapshot)?;
        request.fields = fields
            .iter()
            .enumerate()
            .filter(|(index, _)| mask & (1usize << *index) != 0)
            .map(|(_, field)| *field)
            .collect();
        let expected = read_ids_v1(&snapshot, request.clone())?;
        assert_eq!(prepared.read_ids(request.clone())?, expected);
        request.record_ids.reverse();
        request.fields.reverse();
        assert_eq!(prepared.read_ids(request)?, expected);
        assert_eq!(expected.authority(), AuthorityPosture::DENY_ALL);
    }
    Ok(())
}

#[test]
fn prepared_reads_preserve_exact_total_byte_boundary() -> TestResult {
    let snapshot = snapshot(/*generation*/ 1)?;
    let prepared = PreparedReadSnapshotV1::new(&snapshot)?;
    let mut request = request(&snapshot)?;
    request.fields = vec![ReadFieldV1::ContentDigest, ReadFieldV1::Citations];
    let length = prepared.read_ids(request.clone())?.total_encoded_bytes();
    request.maximum_encoded_bytes = length;
    assert_eq!(
        prepared.read_ids(request.clone()),
        read_ids_v1(&snapshot, request.clone())
    );
    assert_eq!(
        prepared.read_ids(request.clone())?.total_encoded_bytes(),
        length
    );
    request.maximum_encoded_bytes = length - 1;
    assert_eq!(
        prepared.read_ids(request),
        Err(ReadIdsError::EncodedResultTooLarge {
            actual: length,
            maximum: length - 1,
        })
    );
    Ok(())
}

#[test]
fn prepared_reads_repeat_request_checks_and_reject_other_generations() -> TestResult {
    let first = snapshot(/*generation*/ 1)?;
    let second = snapshot(/*generation*/ 2)?;
    let prepared = PreparedReadSnapshotV1::new(&first)?;
    assert_eq!(
        prepared.read_ids(request(&second)?),
        Err(ReadIdsError::Read(Error::SnapshotMismatch))
    );
    let mut duplicate = request(&first)?;
    duplicate.record_ids.push(duplicate.record_ids[0].clone());
    assert_eq!(
        prepared.read_ids(duplicate.clone()),
        read_ids_v1(&first, duplicate)
    );
    let mut duplicate_field = request(&first)?;
    duplicate_field.fields = vec![ReadFieldV1::Citations, ReadFieldV1::Citations];
    assert_eq!(
        prepared.read_ids(duplicate_field),
        Err(ReadIdsError::DuplicateField)
    );
    Ok(())
}

#[test]
fn preparation_rejects_corruption_outside_the_requested_ids() -> TestResult {
    let mut snapshot = snapshot(/*generation*/ 1)?;
    snapshot.records[0].content_digest = Digest32::of_bytes(b"changed without resealing");
    assert!(matches!(
        PreparedReadSnapshotV1::new(&snapshot),
        Err(Error::SnapshotMismatch)
    ));
    Ok(())
}
