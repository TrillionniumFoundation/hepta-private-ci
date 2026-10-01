//! Streaming artifact byte limits remain enforced after filesystem metadata
//! checks, including when a selected file grows before or during the read.

use std::io;
use std::io::Read;

pub(super) fn stream_bounded(
    input: &mut impl Read,
    maximum: usize,
    mut consume: impl FnMut(&[u8]),
) -> io::Result<()> {
    let limit = u64::try_from(maximum)
        .ok()
        .and_then(|maximum| maximum.checked_add(1))
        .ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "artifact byte limit overflow")
        })?;
    let mut input = input.take(limit);
    let mut buffer = [0u8; 16_384];
    let mut total = 0;
    loop {
        let count = input.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        if count > maximum - total {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "artifact exceeds byte limit",
            ));
        }
        total += count;
        consume(&buffer[..count]);
    }
    if total == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "artifact is empty",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "browser_servo_artifact_tests.rs"]
mod tests;
