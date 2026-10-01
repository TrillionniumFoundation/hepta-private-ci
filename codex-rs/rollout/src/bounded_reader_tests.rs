use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;

#[tokio::test]
async fn a_tiny_zstd_header_cannot_request_an_unbounded_decoder_window() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl.zst");
    // Standard Zstd magic, non-single-segment frame, 2 GiB window descriptor,
    // and an empty final raw block. The owner profile permits at most 32 MiB.
    std::fs::write(
        &path,
        [0x28, 0xb5, 0x2f, 0xfd, 0x00, 0xa8, 0x01, 0x00, 0x00],
    )
    .unwrap();
    let mut reader = open_bounded_rollout_line_reader(&path, 1024).await.unwrap();
    assert_eq!(
        reader.next_line().await.unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
}

#[tokio::test]
async fn plain_and_compressed_readers_reject_oversized_or_truncated_records() {
    let directory = tempfile::tempdir().unwrap();
    for suffix in ["jsonl", "jsonl.zst"] {
        let path = directory.path().join(format!("rollout.{suffix}"));
        for data in [
            b"small\n".as_slice(),
            b"more-than-eight\n".as_slice(),
            b"small".as_slice(),
        ] {
            let bytes = if suffix.ends_with("zst") {
                zstd::stream::encode_all(data, 0).unwrap()
            } else {
                data.to_vec()
            };
            std::fs::write(&path, bytes).unwrap();
            let mut reader = open_bounded_rollout_line_reader(&path, 8).await.unwrap();
            if data == b"small\n" {
                assert_eq!(reader.next_line().await.unwrap(), Some("small".to_string()));
                assert_eq!(reader.next_line().await.unwrap(), None);
            } else {
                assert_eq!(
                    reader.next_line().await.unwrap_err().kind(),
                    io::ErrorKind::InvalidData
                );
            }
        }
    }
}

#[tokio::test]
async fn a_later_incomplete_record_invalidates_an_earlier_complete_prefix() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl");
    let mut file = std::fs::File::create(&path).unwrap();
    file.write_all(b"first\npartial").unwrap();
    let mut reader = open_bounded_rollout_line_reader(&path, 8).await.unwrap();
    assert_eq!(reader.next_line().await.unwrap(), Some("first".to_string()));
    assert_eq!(
        reader.next_line().await.unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
}
