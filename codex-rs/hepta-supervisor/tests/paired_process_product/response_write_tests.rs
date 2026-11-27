use std::io::Error;
use std::io::ErrorKind;
use std::io::Write;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::FixtureResponseWrite;
use super::write_fixture_response;

#[derive(Debug, Eq, PartialEq)]
struct ResponseFaultWriter {
    bytes: Vec<u8>,
    fail_after: Option<usize>,
    error_kind: ErrorKind,
    failures: usize,
    flushes: usize,
}

impl Write for ResponseFaultWriter {
    fn write(&mut self, buffer: &[u8]) -> std::io::Result<usize> {
        let count = match self.fail_after {
            Some(limit) => buffer.len().min(limit.saturating_sub(self.bytes.len())),
            None => buffer.len(),
        };
        if count == 0 && !buffer.is_empty() {
            self.failures += 1;
            return Err(Error::new(self.error_kind, "fixture writer failed"));
        }
        self.bytes.extend_from_slice(&buffer[..count]);
        Ok(count)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        self.flushes += 1;
        Ok(())
    }
}

#[test]
fn response_write_completes_the_original_json_then_newline() -> Result<()> {
    let mut writer = ResponseFaultWriter {
        bytes: Vec::new(),
        fail_after: None,
        error_kind: ErrorKind::BrokenPipe,
        failures: 0,
        flushes: 0,
    };
    assert_eq!(
        write_fixture_response(&mut writer, &"ok")?,
        FixtureResponseWrite::Complete
    );
    assert_eq!(
        writer,
        ResponseFaultWriter {
            bytes: b"\"ok\"\n".to_vec(),
            fail_after: None,
            error_kind: ErrorKind::BrokenPipe,
            failures: 0,
            flushes: 0,
        }
    );
    Ok(())
}

#[test]
fn broken_pipe_during_json_or_newline_is_not_a_complete_response() -> Result<()> {
    for fail_after in [0, 2, 4] {
        let mut writer = ResponseFaultWriter {
            bytes: Vec::new(),
            fail_after: Some(fail_after),
            error_kind: ErrorKind::BrokenPipe,
            failures: 0,
            flushes: 0,
        };
        assert_eq!(
            write_fixture_response(&mut writer, &"ok")?,
            FixtureResponseWrite::PeerClosed
        );
        assert_eq!(
            writer,
            ResponseFaultWriter {
                bytes: b"\"ok\""[..fail_after].to_vec(),
                fail_after: Some(fail_after),
                error_kind: ErrorKind::BrokenPipe,
                failures: 1,
                flushes: 0,
            }
        );
    }
    Ok(())
}

#[test]
fn other_write_errors_keep_their_original_error_types_and_kinds() {
    for error_kind in [
        ErrorKind::PermissionDenied,
        ErrorKind::ConnectionReset,
        ErrorKind::TimedOut,
        ErrorKind::Other,
    ] {
        for fail_after in [0, 4] {
            let mut writer = ResponseFaultWriter {
                bytes: Vec::new(),
                fail_after: Some(fail_after),
                error_kind,
                failures: 0,
                flushes: 0,
            };
            let error = write_fixture_response(&mut writer, &"ok")
                .expect_err("non-BrokenPipe write failure remains fatal");
            if fail_after == 0 {
                let json_error = error
                    .downcast_ref::<serde_json::Error>()
                    .expect("original JSON writer error");
                assert_eq!(json_error.io_error_kind(), Some(error_kind));
            } else {
                let io_error = error
                    .downcast_ref::<Error>()
                    .expect("original newline writer error");
                assert_eq!(io_error.kind(), error_kind);
            }
            assert_eq!(error.to_string(), "fixture writer failed");
            assert_eq!(
                writer,
                ResponseFaultWriter {
                    bytes: b"\"ok\""[..fail_after].to_vec(),
                    fail_after: Some(fail_after),
                    error_kind,
                    failures: 1,
                    flushes: 0,
                }
            );
        }
    }
}

struct RefusesSerialization;

impl serde::Serialize for RefusesSerialization {
    fn serialize<S>(&self, _serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        Err(serde::ser::Error::custom("fixture serialization rejected"))
    }
}

#[test]
fn non_io_serialization_failure_is_not_a_closed_connection() {
    let mut writer = Vec::<u8>::new();
    let error = write_fixture_response(&mut writer, &RefusesSerialization)
        .expect_err("serialization failure remains fatal");
    let json_error = error
        .downcast_ref::<serde_json::Error>()
        .expect("original serialization error");
    assert_eq!(
        (
            json_error.classify(),
            json_error.io_error_kind(),
            json_error.to_string(),
            writer,
        ),
        (
            serde_json::error::Category::Data,
            None,
            "fixture serialization rejected".to_string(),
            Vec::<u8>::new(),
        )
    );
}
