use super::*;
use std::io::Write as _;

#[test]
fn real_anonymous_pipe_distinguishes_no_data_bytes_and_eof() {
    let (mut reader, mut writer) = std::io::pipe().unwrap();
    configure_writer(&writer).unwrap();
    let mut bytes = [0; 16];
    assert_eq!(
        read_available(&mut reader, &mut bytes).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    assert_eq!(writer.write(b"literal bytes").unwrap(), 13);
    let length = read_available(&mut reader, &mut bytes).unwrap();
    assert_eq!(&bytes[..length], b"literal bytes");
    drop(writer);
    assert_eq!(read_available(&mut reader, &mut bytes).unwrap(), 0);
}

#[test]
fn anonymous_pipe_full_writer_returns_without_a_reader() {
    let (_reader, mut writer) = std::io::pipe().unwrap();
    configure_writer(&writer).unwrap();
    let started = std::time::Instant::now();
    let block = [0_u8; 8192];
    let mut written = 0;
    loop {
        match writer.write(&block) {
            Ok(0) => break,
            Ok(length) => written += length,
            Err(error)
                if error.raw_os_error() == Some(232)
                    || error.kind() == io::ErrorKind::WouldBlock =>
            {
                break;
            }
            Err(error) => panic!("unexpected pipe error: {error}"),
        }
        assert!(
            written < 1024 * 1024,
            "fixture exceeded expected anonymous-pipe quota"
        );
    }
    assert!(started.elapsed() < std::time::Duration::from_secs(2));
}
