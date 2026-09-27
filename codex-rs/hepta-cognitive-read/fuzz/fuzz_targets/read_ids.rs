#![no_main]

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::read_ids_v1;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use libfuzzer_sys::fuzz_target;

struct Input<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> Input<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn byte(&mut self) -> u8 {
        if self.bytes.is_empty() {
            return 0;
        }
        let value = self.bytes[self.cursor % self.bytes.len()];
        self.cursor = self.cursor.wrapping_add(1);
        value
    }

    fn u16(&mut self) -> u16 {
        u16::from_be_bytes([self.byte(), self.byte()])
    }
}

fn stable_id(prefix: &str, value: usize) -> StableId {
    StableId::new(&format!("{prefix}:{value:04x}")).expect("generated stable id")
}

fuzz_target!(|data: &[u8]| {
    let mut input = Input::new(data);
    let record_count = usize::from(input.byte() % 32) + 1;
    let mut records = Vec::with_capacity(record_count);

    for index in 0..record_count {
        let citation_count = usize::from(input.byte() % 5);
        let citations = (0..citation_count)
            .map(|citation| {
                let source_id = stable_id("source", index * 8 + citation);
                Citation {
                    source_digest: Digest32::of_bytes(source_id.as_str().as_bytes()),
                    source_id,
                }
            })
            .collect();
        let record_id = stable_id("memory", index);
        records.push(MemoryRecord {
            content_digest: Digest32::of_bytes(record_id.as_str().as_bytes()),
            record_id,
            revision: Revision::new(1).expect("non-zero revision"),
            kind: match input.byte() % 4 {
                0 => MemoryKind::Episode,
                1 => MemoryKind::Fact,
                2 => MemoryKind::Preference,
                _ => MemoryKind::Procedure,
            },
            predecessor_digest: None,
            citations,
            state: if input.byte() % 7 == 0 {
                RecordState::Tombstone
            } else {
                RecordState::Live
            },
        });
    }

    let snapshot = build_snapshot(
        Generation::new(1).expect("non-zero generation"),
        records,
    )
    .expect("generated snapshot");

    let requested_count = usize::from(input.byte() % 40);
    let mut record_ids = Vec::with_capacity(requested_count);
    for _ in 0..requested_count {
        let selected = usize::from(input.byte()) % (record_count + 8);
        record_ids.push(stable_id("memory", selected));
    }

    let mut fields = Vec::new();
    let field_mask = input.byte();
    if field_mask & 1 != 0 {
        fields.push(ReadFieldV1::ContentDigest);
    }
    if field_mask & 2 != 0 {
        fields.push(ReadFieldV1::PredecessorDigest);
    }
    if field_mask & 4 != 0 {
        fields.push(ReadFieldV1::Citations);
    }
    if field_mask & 8 != 0 && !fields.is_empty() {
        fields.push(fields[0]);
    }

    let selector = input.byte() % 16;
    let maximum_encoded_bytes = match selector {
        0 => 0,
        1 => MAX_ENCODED_READ_RESULT_BYTES_V2 + 1,
        _ => usize::from(input.u16()).max(1),
    };

    if let Ok(result) = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids,
            fields,
            maximum_encoded_bytes,
        },
    ) {
        assert!(result.total_encoded_bytes() <= maximum_encoded_bytes);
        assert_eq!(result.canonical_bytes().len(), result.total_encoded_bytes());
        assert_eq!(
            Digest32::of_bytes(
                &result.canonical_bytes()[..result.payload_encoded_bytes()]
            ),
            result.receipt_digest()
        );
        assert!(!result.authority().grants_any());
    }
});
