//! Borrowed windows for the native ASCII JSON fragment encoder.
//!
//! HIA returns an eight-byte consumed-prefix length followed by escaped bytes.
//! A nonfinal window may leave up to three incomplete UTF-8 bytes unconsumed;
//! the next window borrows that same suffix with more input. Workspace byte 0
//! is the final phase and byte 1 requests finalization. Errors commit no writes.

use std::io;

const CHUNK_SIZE: usize = 4096;
const HEADER_SIZE: usize = 8;
const OUTPUT_SIZE: usize = HEADER_SIZE + 3 * CHUNK_SIZE;

unsafe extern "C" {
    fn codex_hia_ascii_json_fragment(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn write_string_fragment<W: ?Sized + io::Write>(
    writer: &mut W,
    fragment: &str,
) -> io::Result<()> {
    let mut position = 0;
    let mut output = [0_u8; OUTPUT_SIZE];
    let mut workspace = [0_u8; 2];
    loop {
        let remaining = &fragment.as_bytes()[position..];
        let frame = &remaining[..remaining.len().min(CHUNK_SIZE)];
        let final_frame = frame.len() == remaining.len();
        workspace[1] = u8::from(final_frame);
        // SAFETY: these distinct buffers are live for the synchronous call.
        // The output accommodates HIA's worst-case expansion and header; its
        // complete input is valid UTF-8, although this borrowed window may end
        // within a scalar. HIA retains no pointers and validates before writing.
        let status = unsafe {
            codex_hia_ascii_json_fragment(
                frame.as_ptr(),
                frame.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                workspace.as_mut_ptr(),
                workspace.len() as u64,
            )
        };
        let invalid = || {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid HIA JSON fragment result",
            )
        };
        let length = usize::try_from(status).map_err(|_| invalid())?;
        if !(HEADER_SIZE..=output.len()).contains(&length) {
            return Err(invalid());
        }
        let encoded = output[..HEADER_SIZE].try_into().map_err(|_| invalid())?;
        let consumed = usize::try_from(u64::from_le_bytes(encoded)).map_err(|_| invalid())?;
        if consumed > frame.len()
            || (final_frame && consumed != frame.len())
            || (!final_frame && (consumed == 0 || frame.len() - consumed > 3))
            || !fragment.is_char_boundary(position + consumed)
            || length - HEADER_SIZE > 3 * consumed
        {
            return Err(invalid());
        }
        writer.write_all(&output[HEADER_SIZE..length])?;
        position += consumed;
        if final_frame {
            return Ok(());
        }
    }
}
