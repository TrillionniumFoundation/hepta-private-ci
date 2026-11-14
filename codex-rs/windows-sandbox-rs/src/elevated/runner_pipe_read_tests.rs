use super::super::test_support::pipe_pair;
use super::read_frame;
use crate::ipc_framed::FramedMessage;
use crate::ipc_framed::IPC_PROTOCOL_VERSION;
use crate::ipc_framed::Message;
use crate::ipc_framed::OutputPayload;
use crate::ipc_framed::OutputStream;
use crate::ipc_framed::decode_bytes;
use crate::ipc_framed::encode_bytes;
use crate::ipc_framed::write_frame;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::time::Duration;
use std::time::Instant;

#[test]
fn pipe_reader_decodes_frame_larger_than_native_pipe_buffer() -> Result<()> {
    let (mut reader, mut writer) = pipe_pair()?;
    let expected = vec![b'x'; 32_768];
    let frame = FramedMessage {
        version: IPC_PROTOCOL_VERSION,
        message: Message::Output {
            payload: OutputPayload {
                data_b64: encode_bytes(&expected),
                stream: OutputStream::Stdout,
            },
        },
    };
    let writer = std::thread::spawn(move || write_frame(&mut writer, &frame));
    let frame = read_frame(
        &mut reader,
        Some(Instant::now() + Duration::from_secs(5)),
        || false,
    );
    drop(reader);
    let written = writer
        .join()
        .map_err(|_| anyhow::anyhow!("pipe writer panicked"))?;
    let frame = frame?.context("real pipe frame")?;
    written?;
    let Message::Output { payload } = frame.message else {
        anyhow::bail!("unexpected pipe frame");
    };
    assert_eq!(frame.version, IPC_PROTOCOL_VERSION);
    assert_eq!(decode_bytes(&payload.data_b64)?, expected);
    Ok(())
}

#[test]
fn pipe_reader_preserves_original_partial_eof_and_size_limit() -> Result<()> {
    let (mut reader, mut writer) = pipe_pair()?;
    writer.write_all(&[1, 0])?;
    drop(writer);
    assert!(read_frame(&mut reader, None, || false)?.is_none());

    let (mut reader, mut writer) = pipe_pair()?;
    writer.write_all(&8_u32.to_le_bytes())?;
    writer.write_all(b"{")?;
    drop(writer);
    let error = read_frame(&mut reader, None, || false).expect_err("partial payload");
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(std::io::ErrorKind::UnexpectedEof)
    );

    let (mut reader, mut writer) = pipe_pair()?;
    writer.write_all(&(8_u32 * 1024 * 1024 + 1).to_le_bytes())?;
    let error = read_frame(&mut reader, None, || false).expect_err("original frame limit");
    assert!(error.to_string().contains("frame too large"));
    Ok(())
}

#[test]
fn pipe_reader_partial_frame_uses_original_absolute_deadline() -> Result<()> {
    let (mut reader, mut writer) = pipe_pair()?;
    writer.write_all(&8_u32.to_le_bytes())?;
    writer.write_all(b"{")?;
    let deadline = Instant::now() + Duration::from_millis(100);
    let error =
        read_frame(&mut reader, Some(deadline), || false).expect_err("incomplete live pipe");
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(std::io::ErrorKind::TimedOut)
    );
    assert!(Instant::now() >= deadline);
    Ok(())
}

#[test]
fn pipe_reader_cancelled_live_pipe_returns_error_without_retry() -> Result<()> {
    let (mut reader, _writer) = pipe_pair()?;
    let error = read_frame(&mut reader, None, || true).expect_err("cancelled live pipe");
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(std::io::ErrorKind::Other)
    );
    assert!(error.to_string().contains("observation cancelled"));
    Ok(())
}
