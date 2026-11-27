use std::error::Error;
use std::fmt;

/// The first invalid or incomplete sequence in a borrowed UTF-8 byte slice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Utf8ValidationError {
    pub(super) valid_up_to: usize,
    pub(super) error_len: Option<usize>,
}

impl Utf8ValidationError {
    /// Number of valid UTF-8 bytes before the failing sequence.
    pub fn valid_up_to(self) -> usize {
        self.valid_up_to
    }

    /// Invalid sequence length, or `None` for an incomplete sequence at EOF.
    pub fn error_len(self) -> Option<usize> {
        self.error_len
    }
}

impl fmt::Display for Utf8ValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.error_len {
            Some(length) => write!(
                f,
                "invalid utf-8 sequence of {length} bytes from index {}",
                self.valid_up_to
            ),
            None => write!(
                f,
                "incomplete utf-8 byte sequence from index {}",
                self.valid_up_to
            ),
        }
    }
}

impl Error for Utf8ValidationError {}

/// Validate the entire byte slice without copying it or replacing invalid bytes.
///
/// The `hia-native` selection uses the same HIA validator as streamed text.
/// Both selections preserve the exact failing offset and incomplete-EOF result.
pub fn validate_utf8(bytes: &[u8]) -> Result<&str, Utf8ValidationError> {
    #[cfg(feature = "hia-native")]
    {
        crate::hia_native_utf8_stream::validate(bytes)
    }
    #[cfg(not(feature = "hia-native"))]
    {
        std::str::from_utf8(bytes).map_err(|error| Utf8ValidationError {
            valid_up_to: error.valid_up_to(),
            error_len: error.error_len(),
        })
    }
}

#[cfg(test)]
#[path = "utf8_validation_tests.rs"]
mod tests;
