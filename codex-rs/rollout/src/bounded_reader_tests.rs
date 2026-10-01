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
    for suffix in ["jsonl", "jsonl.zst"] {
        // Resolution prefers a plain sibling, even when given the .zst path.
        // Isolate representations so the truncated plain case cannot shadow zstd.
        let directory = tempfile::tempdir().unwrap();
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

#[cfg(unix)]
#[test]
fn a_fifo_replacement_after_preflight_cannot_strand_the_open_worker() {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let directory = tempfile::tempdir().unwrap();
    for suffix in ["jsonl", "jsonl.zst"] {
        let path = directory.path().join(format!("rollout.{suffix}"));
        std::fs::write(&path, b"original\n").unwrap();
        let expected = std::fs::symlink_metadata(&path).unwrap();
        std::fs::remove_file(&path).unwrap();
        let fifo_path = CString::new(path.as_os_str().as_bytes()).unwrap();
        // SAFETY: the owned CString is a valid nul-terminated pathname.
        assert_eq!(
            unsafe {
                libc::mkfifo(fifo_path.as_ptr(), /*mode*/ 0o600)
            },
            0
        );

        let opening_path = path.clone();
        let (done, received) = mpsc::channel();
        let worker = std::thread::spawn(move || {
            let _ = done.send(open_regular_rollout(&opening_path, &expected));
        });
        let first = received.recv_timeout(Duration::from_secs(1));
        let finished_without_writer = first.is_ok();
        // If NONBLOCK regresses, a controlled reader/writer wakes the actual
        // blocked open before the failing assertion. The test never awaits an
        // unbounded Tokio blocking-task shutdown or joins before completion.
        let _cleanup_keeper = (!finished_without_writer).then(|| {
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW)
                .open(&path)
                .unwrap()
        });
        let result = first.unwrap_or_else(|_| {
            received
                .recv_timeout(Duration::from_secs(1))
                .expect("FIFO cleanup must release the open worker")
        });
        worker.join().unwrap();
        assert!(
            finished_without_writer,
            "opening a replacement FIFO waited for a writer"
        );
        assert_eq!(result.unwrap_err().kind(), io::ErrorKind::InvalidData);
    }
}

#[cfg(unix)]
#[tokio::test]
async fn stable_parent_aliases_preserve_plain_and_compressed_observation() {
    let directory = tempfile::tempdir().unwrap();
    let actual = directory.path().join("actual");
    let alias = directory.path().join("alias");
    std::fs::create_dir(&actual).unwrap();
    std::os::unix::fs::symlink(&actual, &alias).unwrap();
    for suffix in ["jsonl", "jsonl.zst"] {
        let bytes = if suffix.ends_with("zst") {
            zstd::stream::encode_all(b"complete\n".as_slice(), /*level*/ 0).unwrap()
        } else {
            b"complete\n".to_vec()
        };
        std::fs::write(actual.join(format!("rollout.{suffix}")), bytes).unwrap();
        let mut reader = open_bounded_rollout_line_reader(
            &alias.join(format!("rollout.{suffix}")),
            /*max_line_bytes*/ 32,
        )
        .await
        .unwrap();
        assert_eq!(
            reader.next_line().await.unwrap(),
            Some("complete".to_string())
        );
        assert_eq!(reader.next_line().await.unwrap(), None);
        std::fs::remove_file(actual.join(format!("rollout.{suffix}"))).unwrap();
    }
}

#[cfg(unix)]
#[tokio::test]
async fn a_leaf_symlink_never_supplies_historical_evidence() {
    let directory = tempfile::tempdir().unwrap();
    let actual = directory.path().join("actual.jsonl");
    let alias = directory.path().join("alias.jsonl");
    std::fs::write(&actual, b"complete\n").unwrap();
    std::os::unix::fs::symlink(&actual, &alias).unwrap();
    let result = open_bounded_rollout_line_reader(&alias, /*max_line_bytes*/ 32).await;
    assert_eq!(result.err().unwrap().kind(), io::ErrorKind::InvalidData);
}

#[tokio::test]
async fn a_changed_file_or_selected_path_invalidates_a_complete_prefix() {
    let directory = tempfile::tempdir().unwrap();
    for suffix in ["jsonl", "jsonl.zst"] {
        for replace_path in [false, true] {
            let path = directory.path().join(format!("rollout.{suffix}"));
            let bytes = if suffix.ends_with("zst") {
                zstd::stream::encode_all(b"complete\n".as_slice(), /*level*/ 0).unwrap()
            } else {
                b"complete\n".to_vec()
            };
            std::fs::write(&path, &bytes).unwrap();
            let mut reader = open_bounded_rollout_line_reader(&path, /*max_line_bytes*/ 32)
                .await
                .unwrap();
            assert_eq!(
                reader.next_line().await.unwrap(),
                Some("complete".to_string())
            );
            if replace_path {
                std::fs::rename(&path, path.with_extension("old")).unwrap();
                std::fs::write(&path, &bytes).unwrap();
            } else {
                std::fs::OpenOptions::new()
                    .append(true)
                    .open(&path)
                    .unwrap()
                    .write_all(b"changed")
                    .unwrap();
            }
            assert_eq!(
                reader.next_line().await.unwrap_err().kind(),
                io::ErrorKind::InvalidData
            );
            std::fs::remove_file(&path).unwrap();
        }
    }
}

#[test]
fn appended_empty_frames_cannot_turn_an_encoded_budget_into_eof() {
    use std::io::Seek;

    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl.zst");
    let prefix = zstd::stream::encode_all(b"terminal\n".as_slice(), /*level*/ 3).unwrap();
    let empty = zstd::stream::encode_all(b"".as_slice(), /*level*/ 3).unwrap();
    std::fs::write(&path, &prefix).unwrap();
    let metadata = std::fs::symlink_metadata(&path).unwrap();
    let file = open_regular_rollout(&path, &metadata).unwrap();
    std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(&empty.repeat(/*n*/ 1024))
        .unwrap();

    let encoded = BoundedEncodedRead {
        inner: file,
        remaining: metadata.len(),
        deadline: Instant::now() + READ_WORK_BUDGET,
    };
    let decoder = zstd::stream::read::Decoder::new(encoded).unwrap();
    let mut reader = std::io::BufReader::new(decoder);
    let mut line = Vec::new();
    io::BufRead::read_until(&mut reader, b'\n', &mut line).unwrap();
    assert_eq!(line, b"terminal\n");
    line.clear();
    assert_eq!(
        io::BufRead::read_until(&mut reader, b'\n', &mut line)
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidData
    );
    // The same production wrapper consumed at most the original snapshot and
    // one true-EOF probe, rather than traversing the appended empty frames.
    let mut encoded = reader.into_inner().finish().into_inner();
    assert_eq!(encoded.inner.stream_position().unwrap(), metadata.len() + 1);
    assert_eq!(encoded.remaining, 0);
}

#[tokio::test]
async fn oversized_encoded_history_is_rejected_before_decompression() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl.zst");
    let file = std::fs::File::create(&path).unwrap();
    // A sparse file exercises the metadata limit without allocating the input.
    file.set_len(MAX_ENCODED_ROLLOUT_BYTES + 1).unwrap();
    let result = open_bounded_rollout_line_reader(&path, /*max_line_bytes*/ 32).await;
    let error = result.err().unwrap();
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert_eq!(
        error.to_string(),
        "compressed rollout exceeds its encoded byte limit"
    );
}

#[tokio::test]
async fn complete_multiframe_compressed_history_reaches_real_eof() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl.zst");
    let mut encoded = Vec::new();
    for decoded in [b"first\n".as_slice(), b"", b"second\n", b""] {
        encoded.extend(zstd::stream::encode_all(decoded, /*level*/ 3).unwrap());
    }
    std::fs::write(&path, encoded).unwrap();
    let mut reader = open_bounded_rollout_line_reader(&path, /*max_line_bytes*/ 32)
        .await
        .unwrap();
    assert_eq!(reader.next_line().await.unwrap(), Some("first".to_string()));
    assert_eq!(
        reader.next_line().await.unwrap(),
        Some("second".to_string())
    );
    assert_eq!(reader.next_line().await.unwrap(), None);
}

#[test]
fn an_expired_encoded_worker_deadline_prevents_physical_reads() {
    use std::io::Read;
    use std::io::Seek;

    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rollout.jsonl.zst");
    let encoded = zstd::stream::encode_all(b"complete\n".as_slice(), /*level*/ 3).unwrap();
    std::fs::write(&path, &encoded).unwrap();
    let input = BoundedEncodedRead {
        inner: std::fs::File::open(&path).unwrap(),
        remaining: encoded.len() as u64,
        deadline: Instant::now() - Duration::from_secs(/*secs*/ 1),
    };
    let mut decoder = zstd::stream::read::Decoder::new(input).unwrap();
    assert_eq!(
        decoder.read(&mut [0; 1]).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
    let mut input = decoder.finish().into_inner();
    assert_eq!(input.inner.stream_position().unwrap(), 0);
    assert_eq!(input.remaining, encoded.len() as u64);
}
