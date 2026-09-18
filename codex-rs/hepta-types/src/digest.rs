use std::error::Error;
use std::fmt;
use std::io;
use std::io::Read;
use std::str::FromStr;

use sha2::Digest;
use sha2::Sha256;

/// A content digest whose display and parse forms are exactly 64 lowercase hex
/// characters.
#[derive(Clone, Copy, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Digest32([u8; 32]);

impl Digest32 {
    pub const ZERO: Self = Self([0; 32]);

    pub const fn from_array(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    pub fn of_bytes(bytes: &[u8]) -> Self {
        let digest = Sha256::digest(bytes);
        let mut value = [0; 32];
        value.copy_from_slice(&digest);
        Self(value)
    }

    /// Hash an already-authorized reader with fixed scratch space. Read at
    /// most `maximum_bytes + 1` bytes; excess input and I/O errors never return
    /// a digest of a silently truncated prefix. No path is opened here.
    pub fn of_reader(mut reader: impl Read, maximum_bytes: u64) -> io::Result<Self> {
        let mut hasher = Sha256::new();
        let mut buffer = [0_u8; 32 * 1024];
        let mut remaining = maximum_bytes;
        loop {
            let limit = remaining.saturating_add(1).min(buffer.len() as u64) as usize;
            let count = match reader.read(&mut buffer[..limit]) {
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                result => result?,
            };
            if count == 0 {
                let digest = hasher.finalize();
                let mut value = [0; 32];
                value.copy_from_slice(&digest);
                return Ok(Self(value));
            }
            if count as u64 > remaining {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "digest input limit",
                ));
            }
            remaining -= count as u64;
            hasher.update(&buffer[..count]);
        }
    }

    pub const fn as_array(&self) -> &[u8; 32] {
        &self.0
    }

    pub const fn into_array(self) -> [u8; 32] {
        self.0
    }

    pub fn is_zero(self) -> bool {
        self == Self::ZERO
    }
}

impl fmt::Debug for Digest32 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("Digest32")
            .field(&self.to_string())
            .finish()
    }
}

impl fmt::Display for Digest32 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

impl FromStr for Digest32 {
    type Err = DigestParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.len() != 64 {
            return Err(DigestParseError::Length(value.len()));
        }
        let bytes = value.as_bytes();
        let mut digest = [0; 32];
        for (index, output) in digest.iter_mut().enumerate() {
            let high =
                decode_hex(bytes[index * 2]).ok_or(DigestParseError::Character(index * 2))?;
            let low = decode_hex(bytes[index * 2 + 1])
                .ok_or(DigestParseError::Character(index * 2 + 1))?;
            *output = (high << 4) | low;
        }
        Ok(Self(digest))
    }
}

fn decode_hex(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DigestParseError {
    Length(usize),
    Character(usize),
}

impl fmt::Display for DigestParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Length(length) => write!(formatter, "digest length must be 64, found {length}"),
            Self::Character(index) => write!(formatter, "invalid lowercase hex at byte {index}"),
        }
    }
}

impl Error for DigestParseError {}

#[cfg(test)]
#[path = "digest_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "digest_stream_tests.rs"]
mod stream_tests;
