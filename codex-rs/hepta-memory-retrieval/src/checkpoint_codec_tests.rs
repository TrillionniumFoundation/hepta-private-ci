use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::Codec;
use super::ENGRAM_MAGIC;
use super::MAX_ENGRAM_CHECKPOINT_BYTES_V1;
use super::MemoryCheckpointCodecErrorV1;
use super::Reader;
use super::Writer;
use super::decode_engram_checkpoint_v1;
use super::encode;
use super::encode_engram_checkpoint_v1;
use crate::EngramSnapshotV1;

fn snapshot() -> EngramSnapshotV1 {
    EngramSnapshotV1::new(
        Digest32::of_bytes(b"owner-generation"),
        Digest32::of_bytes(b"engram-generation"),
        Vec::new(),
        Vec::new(),
    )
    .unwrap()
}

#[test]
fn decoder_rejects_changed_bytes_wrong_owner_hash_and_every_truncation() {
    let bytes = encode_engram_checkpoint_v1(&snapshot()).unwrap();
    let expected = Digest32::of_bytes(&bytes);
    let mut changed = bytes.clone();
    changed[ENGRAM_MAGIC.len()] ^= 1;
    assert_eq!(
        decode_engram_checkpoint_v1(&changed, expected),
        Err(MemoryCheckpointCodecErrorV1::ContentDigestMismatch)
    );
    assert_eq!(
        decode_engram_checkpoint_v1(&bytes, Digest32::of_bytes(b"other owner")),
        Err(MemoryCheckpointCodecErrorV1::ContentDigestMismatch)
    );
    for end in 0..bytes.len() {
        let truncated = &bytes[..end];
        assert!(decode_engram_checkpoint_v1(truncated, Digest32::of_bytes(truncated)).is_err());
    }
    let mut trailing = bytes;
    trailing.push(0);
    assert_eq!(
        decode_engram_checkpoint_v1(&trailing, Digest32::of_bytes(&trailing)),
        Err(MemoryCheckpointCodecErrorV1::TrailingBytes)
    );
}

#[test]
fn correct_content_hash_does_not_bypass_logical_validation_or_authority() {
    let mut invalid = snapshot();
    invalid.snapshot_digest = Digest32::of_bytes(b"wrong logical digest");
    let bytes = encode(&invalid, ENGRAM_MAGIC, MAX_ENGRAM_CHECKPOINT_BYTES_V1).unwrap();
    assert!(matches!(
        decode_engram_checkpoint_v1(&bytes, Digest32::of_bytes(&bytes)),
        Err(MemoryCheckpointCodecErrorV1::InvalidContract(_))
    ));
    let mut bytes = encode_engram_checkpoint_v1(&snapshot()).unwrap();
    *bytes.last_mut().unwrap() = 1;
    assert_eq!(
        decode_engram_checkpoint_v1(&bytes, Digest32::of_bytes(&bytes)),
        Err(MemoryCheckpointCodecErrorV1::InvalidValue("authority"))
    );
    assert_eq!(
        AuthorityPosture::read(&mut Reader { remaining: &[255] }),
        Err(MemoryCheckpointCodecErrorV1::InvalidValue("authority"))
    );
}

#[test]
fn hostile_lengths_and_total_bytes_are_rejected_before_payload_allocation() {
    let mut bytes = encode_engram_checkpoint_v1(&snapshot()).unwrap();
    let nodes_length_offset = ENGRAM_MAGIC.len() + 64;
    bytes[nodes_length_offset..nodes_length_offset + 4].copy_from_slice(&u32::MAX.to_be_bytes());
    assert_eq!(
        decode_engram_checkpoint_v1(&bytes, Digest32::of_bytes(&bytes)),
        Err(MemoryCheckpointCodecErrorV1::SizeLimit)
    );
    let excess = vec![0; MAX_ENGRAM_CHECKPOINT_BYTES_V1 + 1];
    assert_eq!(
        decode_engram_checkpoint_v1(&excess, Digest32::of_bytes(&excess)),
        Err(MemoryCheckpointCodecErrorV1::SizeLimit)
    );
    let mut writer = Writer {
        bytes: Vec::new(),
        maximum: 4,
    };
    assert_eq!(
        writer.append(&[0; 5]),
        Err(MemoryCheckpointCodecErrorV1::SizeLimit)
    );
    assert!(writer.bytes.is_empty());
}
