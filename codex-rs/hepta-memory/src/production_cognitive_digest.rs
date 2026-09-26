//! Preserve the existing JSON input identity without allocating a second payload.
//! The encoded ceiling includes the byte-array expansion of a 1 MiB source,
//! escaped Memory text and bounded fact/citation metadata. Owner field validation
//! still applies; this ceiling is a resource fence, not semantic admission.

use std::io;
use std::io::Write;

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::ProductionWriterError;

const MAX_ENCODED_INPUT_BYTES: usize = 8 * 1024 * 1024;

struct InputDigestWriter {
    hasher: Sha256,
    remaining: usize,
    exhausted: bool,
}

impl Write for InputDigestWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.exhausted || bytes.len() > self.remaining {
            self.exhausted = true;
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "production cognitive encoded input exceeds the bounded digest budget",
            ));
        }
        self.hasher.update(bytes);
        self.remaining -= bytes.len();
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub(super) fn input_digest<T: Serialize + ?Sized>(
    input: &T,
) -> Result<Sha256Digest, ProductionWriterError> {
    let mut writer = InputDigestWriter {
        hasher: Sha256::new(),
        remaining: MAX_ENCODED_INPUT_BYTES,
        exhausted: false,
    };
    serde_json::to_writer(&mut writer, input)
        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
    if writer.exhausted {
        return Err(ProductionWriterError::Invalid(
            "production cognitive encoded input exceeded the digest budget".to_string(),
        ));
    }
    Ok(Sha256Digest::from_sha256_output(writer.hasher.finalize()))
}

#[cfg(test)]
#[path = "production_cognitive_digest_tests.rs"]
mod tests;
