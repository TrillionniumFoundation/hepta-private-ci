//! Borrowed-byte validation for the HIA UTF-8 owner.
//!
//! HIA classifies the complete byte slice before any inner parser sees it.
//! Rust retains the original pending buffer and commit/rollback ordering.

const OUTPUT_BYTES: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct ValidationError {
    valid_up_to: usize,
    error_len: Option<usize>,
}

impl ValidationError {
    pub(super) fn valid_up_to(self) -> usize {
        self.valid_up_to
    }

    pub(super) fn error_len(self) -> Option<usize> {
        self.error_len
    }
}

unsafe extern "C" {
    fn codex_hia_utf8_stream(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn validate(bytes: &[u8]) -> Result<&str, ValidationError> {
    let mut output = [0_u8; OUTPUT_BYTES];
    let mut workspace = [];
    // SAFETY: the distinct live slices cover the supplied lengths. The linked
    // HIA entry borrows them synchronously, writes at most OUTPUT_BYTES, never
    // touches workspace and retains no pointer.
    let status = unsafe {
        codex_hia_utf8_stream(
            bytes.as_ptr(),
            bytes.len() as u64,
            output.as_mut_ptr(),
            OUTPUT_BYTES as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, OUTPUT_BYTES as u64, "HIA UTF-8 validation failed");
    match decode(output, bytes.len()) {
        Ok(None) => {
            // SAFETY: the HIA validator's complete result establishes UTF-8
            // validity for this exact borrowed byte slice. decode has checked
            // its version, full-extent success and zero error length before
            // constructing the view; the bytes cannot change during the call.
            Ok(unsafe { std::str::from_utf8_unchecked(bytes) })
        }
        Ok(Some(error)) => Err(error),
        Err(reason) => panic!("HIA UTF-8 validation result is invalid: {reason}"),
    }
}

fn decode(
    output: [u8; OUTPUT_BYTES],
    source_len: usize,
) -> Result<Option<ValidationError>, &'static str> {
    let mut words = [0_u64; 4];
    for (word, bytes) in words.iter_mut().zip(output.chunks_exact(8)) {
        let mut encoded = [0_u8; 8];
        encoded.copy_from_slice(bytes);
        *word = u64::from_le_bytes(encoded);
    }
    let [version, kind, valid_up_to, error_len] = words;
    let valid_up_to = usize::try_from(valid_up_to).map_err(|_| "offset does not fit usize")?;
    let error_len = usize::try_from(error_len).map_err(|_| "error length does not fit usize")?;
    if version != 1 || valid_up_to > source_len {
        return Err("version or prefix extent differs");
    }
    let remaining = source_len - valid_up_to;
    match kind {
        0 if remaining == 0 && error_len == 0 => Ok(None),
        1 if (1..=3).contains(&error_len) && error_len <= remaining => Ok(Some(ValidationError {
            valid_up_to,
            error_len: Some(error_len),
        })),
        2 if (1..=3).contains(&remaining) && error_len == 0 => Ok(Some(ValidationError {
            valid_up_to,
            error_len: None,
        })),
        _ => Err("classification or error extent differs"),
    }
}

#[cfg(test)]
#[path = "hia_native_utf8_stream_tests.rs"]
mod tests;
