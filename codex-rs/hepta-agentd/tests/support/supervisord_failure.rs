use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

const TAIL_BYTES: usize = 8192;
const MESSAGE_BYTES: usize = 8192;
const ENDING_BYTES: usize = 64;

pub(super) fn child_log_tail(path: &Path) -> String {
    let mut bytes = [0_u8; TAIL_BYTES];
    let observation = (|| -> io::Result<(u64, u64, usize, usize)> {
        let mut file = File::open(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file() {
            return Err(io::Error::from(io::ErrorKind::InvalidData));
        }
        let extent = metadata.len();
        let start = extent.saturating_sub(TAIL_BYTES as u64);
        let requested = usize::try_from(extent - start)
            .map_err(|_| io::Error::from(io::ErrorKind::InvalidData))?;
        file.seek(SeekFrom::Start(start))?;
        // A single bounded read: no waiting for the daemon, retry, or claim
        // that an appendable log's observed extent is its eventual EOF.
        let read = file.read(&mut bytes[..requested])?;
        Ok((extent, start, requested, read))
    })();

    let mut message = [0_u8; MESSAGE_BYTES];
    let (written, format_complete) = {
        let mut output = &mut message[..MESSAGE_BYTES - ENDING_BYTES];
        let result = match observation {
            Ok((extent, start, requested, read)) => {
                let range_complete = read == requested;
                let lossy = std::str::from_utf8(&bytes[..read]).is_err();
                let tail = String::from_utf8_lossy(&bytes[..read]);
                write!(
                    output,
                    "child_log_read=ok observed_extent={extent} start_offset={start} requested_bytes={requested} read_bytes={read} range_complete={range_complete} lossy={lossy} tail={tail:?}"
                )
            }
            Err(error) => {
                let kind = error.kind();
                let raw_os_error = error.raw_os_error();
                write!(
                    output,
                    "child_log_read=error kind={kind:?} raw_os_error={raw_os_error:?}"
                )
            }
        };
        (MESSAGE_BYTES - ENDING_BYTES - output.len(), result.is_ok())
    };
    let valid_len = match std::str::from_utf8(&message[..written]) {
        Ok(_) => written,
        Err(error) => error.valid_up_to(),
    };
    let format_complete = format_complete && valid_len == written;
    let used = {
        let mut ending = &mut message[valid_len..];
        let _ = write!(ending, " child_log_format_complete={format_complete}");
        MESSAGE_BYTES - ending.len()
    };
    String::from_utf8_lossy(&message[..used]).into_owned()
}

#[cfg(test)]
#[path = "supervisord_failure_tests.rs"]
mod tests;
