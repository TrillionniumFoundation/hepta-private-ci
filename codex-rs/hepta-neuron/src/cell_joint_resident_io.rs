//! Exact-byte counters and bounded frames for the resident transport.

use std::io::Read;
use std::io::Write;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::cell_joint_protocol::MAX_RESULT_BYTES;

pub(super) fn write_counted(
    output: &mut impl Write,
    mut bytes: &[u8],
    count: &AtomicU64,
) -> std::io::Result<()> {
    while !bytes.is_empty() {
        match output.write(bytes) {
            Ok(0) => return Err(std::io::ErrorKind::WriteZero.into()),
            Ok(length) => {
                count.fetch_add(length as u64, Ordering::Relaxed);
                bytes = &bytes[length..];
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn read_counted(
    input: &mut impl Read,
    mut bytes: &mut [u8],
    count: &AtomicU64,
) -> std::io::Result<()> {
    while !bytes.is_empty() {
        match input.read(bytes) {
            Ok(0) => return Err(std::io::ErrorKind::UnexpectedEof.into()),
            Ok(length) => {
                count.fetch_add(length as u64, Ordering::Relaxed);
                bytes = &mut bytes[length..];
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

pub(super) fn read_frame(input: &mut impl Read, count: &AtomicU64) -> std::io::Result<Vec<u8>> {
    let mut header = [0; 4];
    read_counted(input, &mut header, count)?;
    let length = u32::from_le_bytes(header) as usize;
    if length == 0 || length > MAX_RESULT_BYTES {
        return Err(std::io::Error::other("resident output exceeds bound"));
    }
    let mut bytes = vec![0; length];
    read_counted(input, &mut bytes, count)?;
    Ok(bytes)
}
