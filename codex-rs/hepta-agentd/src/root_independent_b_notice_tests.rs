//! Real socket framing and cancellation, not Root admission or evaluation.

use pretty_assertions::assert_eq;

use super::*;

#[test]
fn original_b_notice_requires_full_bounded_data_and_eof() -> io::Result<()> {
    let (writer, reader) = OriginalBNoticeWriter::pair()?;
    let end = Instant::now() + Duration::from_secs(1);
    std::thread::scope(|scope| {
        let sending = scope.spawn(|| writer.send(b"candidate DATA", end, || Ok(())));
        assert_eq!(
            receive_stream(UnixStream::from(OwnedFd::from(reader)), end, || Ok(()))?,
            b"candidate DATA"
        );
        sending
            .join()
            .map_err(|_| io::Error::other("notification test panicked"))?
    })
}

#[test]
fn original_b_notice_rejects_partial_extra_oversized_and_missing_eof() -> io::Result<()> {
    let valid = [MAGIC.as_slice(), &4_u32.to_le_bytes(), b"data"].concat();
    for image in [
        Vec::new(),
        valid[..15].to_vec(),
        [valid.as_slice(), b"x"].concat(),
        [MAGIC.as_slice(), &((BOUND + 1) as u32).to_le_bytes()].concat(),
    ] {
        let (mut writer, reader) = UnixStream::pair()?;
        writer.write_all(&image)?;
        drop(writer);
        assert!(
            receive_stream(reader, Instant::now() + Duration::from_secs(1), || Ok(())).is_err()
        );
    }
    let (mut writer, reader) = UnixStream::pair()?;
    writer.write_all(&valid)?;
    assert!(
        receive_stream(
            reader,
            Instant::now() + Duration::from_millis(20),
            || Ok(())
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn original_b_notice_cancellation_and_expiry_do_not_receive_data() -> io::Result<()> {
    let (writer, reader) = OriginalBNoticeWriter::pair()?;
    assert!(writer.send(b"data", Instant::now(), || Ok(())).is_err());
    assert!(
        receive_stream(
            UnixStream::from(OwnedFd::from(reader)),
            Instant::now() + Duration::from_secs(1),
            || Ok(())
        )
        .is_err()
    );
    let (_writer, reader) = OriginalBNoticeWriter::pair()?;
    assert!(
        receive_stream(
            UnixStream::from(OwnedFd::from(reader)),
            Instant::now() + Duration::from_secs(1),
            || Err(io::Error::other("actual owner ended"))
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn original_b_notice_reader_has_no_reverse_write_side() -> io::Result<()> {
    let (_writer, reader) = OriginalBNoticeWriter::pair()?;
    let mut reader = UnixStream::from(OwnedFd::from(reader));
    assert!(reader.write_all(b"not a request").is_err());
    assert!(require_original_notice_reader(&File::open("/dev/null")?, std::process::id()).is_err());
    Ok(())
}
