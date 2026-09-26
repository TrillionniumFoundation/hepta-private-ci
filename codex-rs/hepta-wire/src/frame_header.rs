use std::error::Error;
use std::fmt;

use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireVersion;

pub const WIRE_MAGIC: [u8; 4] = *b"HPTA";
pub const WIRE_HEADER_BYTES: usize = 54;
pub const MAX_WIRE_IDENTITY_BYTES: usize = 128;
pub const MAX_WIRE_FRAME_BYTES: usize =
    WIRE_HEADER_BYTES + MAX_WIRE_IDENTITY_BYTES * 2 + MAX_WIRE_PAYLOAD_BYTES;

const VERSION_OFFSET: usize = 4;
const SCHEMA_LENGTH_OFFSET: usize = 6;
const PRODUCER_LENGTH_OFFSET: usize = 8;
const GENERATION_OFFSET: usize = 10;
const PAYLOAD_LENGTH_OFFSET: usize = 50;

/// Canonical parse of the common fixed wire header.
///
/// Both one-shot and streaming decoders use this type so offsets, field widths,
/// magic and version handling have one owner. Structural resource validation is
/// explicit through [`FrameHeader::validate`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FrameHeader {
    version: WireVersion,
    schema_length: usize,
    producer_length: usize,
    generation: u64,
    payload_length: usize,
}

impl FrameHeader {
    pub fn parse(encoded: &[u8]) -> Result<Self, FrameHeaderParseError> {
        if encoded.len() < WIRE_HEADER_BYTES {
            return Err(FrameHeaderParseError::Truncated {
                actual: encoded.len(),
                minimum: WIRE_HEADER_BYTES,
                byte_offset: encoded.len(),
            });
        }
        let actual_magic: [u8; 4] = encoded[..4]
            .try_into()
            .expect("fixed header admission guarantees four magic bytes");
        if actual_magic != WIRE_MAGIC {
            return Err(FrameHeaderParseError::Magic {
                actual: actual_magic,
                expected: WIRE_MAGIC,
                byte_offset: 0,
            });
        }
        let raw_version = read_u16(encoded, VERSION_OFFSET);
        let version = match raw_version {
            1 => WireVersion::V1,
            2 => WireVersion::V2,
            actual => {
                return Err(FrameHeaderParseError::Version {
                    actual,
                    byte_offset: VERSION_OFFSET,
                });
            }
        };
        Ok(Self {
            version,
            schema_length: usize::from(read_u16(encoded, SCHEMA_LENGTH_OFFSET)),
            producer_length: usize::from(read_u16(encoded, PRODUCER_LENGTH_OFFSET)),
            generation: read_u64(encoded, GENERATION_OFFSET),
            payload_length: usize::try_from(read_u32(encoded, PAYLOAD_LENGTH_OFFSET)).map_err(
                |_| FrameHeaderParseError::PlatformLength {
                    actual: u64::from(read_u32(encoded, PAYLOAD_LENGTH_OFFSET)),
                    maximum: usize::MAX,
                    byte_offset: PAYLOAD_LENGTH_OFFSET,
                },
            )?,
        })
    }

    pub const fn version(self) -> WireVersion {
        self.version
    }

    pub const fn schema_length(self) -> usize {
        self.schema_length
    }

    pub const fn producer_length(self) -> usize {
        self.producer_length
    }

    pub const fn generation(self) -> u64 {
        self.generation
    }

    pub const fn payload_length(self) -> usize {
        self.payload_length
    }

    pub fn validate(self) -> Result<ValidatedFrameHeader, FrameHeaderValidationError> {
        validate_identity_length(
            HeaderIdentityField::Schema,
            self.schema_length,
            SCHEMA_LENGTH_OFFSET,
        )?;
        validate_identity_length(
            HeaderIdentityField::Producer,
            self.producer_length,
            PRODUCER_LENGTH_OFFSET,
        )?;
        if self.generation == 0 {
            return Err(FrameHeaderValidationError::Generation {
                actual: self.generation,
                minimum: 1,
                byte_offset: GENERATION_OFFSET,
            });
        }
        if !(1..=MAX_WIRE_PAYLOAD_BYTES).contains(&self.payload_length) {
            return Err(FrameHeaderValidationError::PayloadLength {
                actual: self.payload_length,
                minimum: 1,
                maximum: MAX_WIRE_PAYLOAD_BYTES,
                byte_offset: PAYLOAD_LENGTH_OFFSET,
            });
        }
        let frame_length = WIRE_HEADER_BYTES
            .checked_add(self.schema_length)
            .and_then(|value| value.checked_add(self.producer_length))
            .and_then(|value| value.checked_add(self.payload_length))
            .ok_or(FrameHeaderValidationError::LengthOverflow {
                byte_offset: PAYLOAD_LENGTH_OFFSET,
            })?;
        if frame_length > MAX_WIRE_FRAME_BYTES {
            return Err(FrameHeaderValidationError::FrameLength {
                actual: frame_length,
                maximum: MAX_WIRE_FRAME_BYTES,
                byte_offset: PAYLOAD_LENGTH_OFFSET,
            });
        }
        Ok(ValidatedFrameHeader {
            header: self,
            frame_length,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedFrameHeader {
    header: FrameHeader,
    frame_length: usize,
}

impl ValidatedFrameHeader {
    pub const fn header(self) -> FrameHeader {
        self.header
    }

    pub const fn version(self) -> WireVersion {
        self.header.version()
    }

    pub const fn frame_length(self) -> usize {
        self.frame_length
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HeaderIdentityField {
    Schema,
    Producer,
}

impl fmt::Display for HeaderIdentityField {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Schema => formatter.write_str("schema"),
            Self::Producer => formatter.write_str("producer"),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrameHeaderParseError {
    Truncated {
        actual: usize,
        minimum: usize,
        byte_offset: usize,
    },
    Magic {
        actual: [u8; 4],
        expected: [u8; 4],
        byte_offset: usize,
    },
    Version {
        actual: u16,
        byte_offset: usize,
    },
    PlatformLength {
        actual: u64,
        maximum: usize,
        byte_offset: usize,
    },
}

impl FrameHeaderParseError {
    pub const fn byte_offset(&self) -> usize {
        match self {
            Self::Truncated { byte_offset, .. }
            | Self::Magic { byte_offset, .. }
            | Self::Version { byte_offset, .. }
            | Self::PlatformLength { byte_offset, .. } => *byte_offset,
        }
    }
}

impl fmt::Display for FrameHeaderParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated {
                actual,
                minimum,
                byte_offset,
            } => write!(
                formatter,
                "wire header ended at byte {byte_offset}: {actual} bytes, minimum is {minimum}"
            ),
            Self::Magic {
                actual,
                expected,
                byte_offset,
            } => write!(
                formatter,
                "wire magic at byte {byte_offset} is {actual:02x?}, expected {expected:02x?}"
            ),
            Self::Version {
                actual,
                byte_offset,
            } => write!(
                formatter,
                "wire version at byte {byte_offset} is unsupported: {actual}"
            ),
            Self::PlatformLength {
                actual,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire length at byte {byte_offset} is {actual}, platform maximum is {maximum}"
            ),
        }
    }
}

impl Error for FrameHeaderParseError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrameHeaderValidationError {
    IdentityLength {
        field: HeaderIdentityField,
        actual: usize,
        minimum: usize,
        maximum: usize,
        byte_offset: usize,
    },
    Generation {
        actual: u64,
        minimum: u64,
        byte_offset: usize,
    },
    PayloadLength {
        actual: usize,
        minimum: usize,
        maximum: usize,
        byte_offset: usize,
    },
    FrameLength {
        actual: usize,
        maximum: usize,
        byte_offset: usize,
    },
    LengthOverflow {
        byte_offset: usize,
    },
}

impl FrameHeaderValidationError {
    pub const fn byte_offset(&self) -> usize {
        match self {
            Self::IdentityLength { byte_offset, .. }
            | Self::Generation { byte_offset, .. }
            | Self::PayloadLength { byte_offset, .. }
            | Self::FrameLength { byte_offset, .. }
            | Self::LengthOverflow { byte_offset } => *byte_offset,
        }
    }
}

impl fmt::Display for FrameHeaderValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::IdentityLength {
                field,
                actual,
                minimum,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire {field} length at byte {byte_offset} is {actual}, expected {minimum}..={maximum}"
            ),
            Self::Generation {
                actual,
                minimum,
                byte_offset,
            } => write!(
                formatter,
                "wire generation at byte {byte_offset} is {actual}, minimum is {minimum}"
            ),
            Self::PayloadLength {
                actual,
                minimum,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire payload length at byte {byte_offset} is {actual}, expected {minimum}..={maximum}"
            ),
            Self::FrameLength {
                actual,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire frame length derived at byte {byte_offset} is {actual}, maximum is {maximum}"
            ),
            Self::LengthOverflow { byte_offset } => {
                write!(formatter, "wire frame length overflow at byte {byte_offset}")
            }
        }
    }
}

impl Error for FrameHeaderValidationError {}

fn validate_identity_length(
    field: HeaderIdentityField,
    actual: usize,
    byte_offset: usize,
) -> Result<(), FrameHeaderValidationError> {
    if !(1..=MAX_WIRE_IDENTITY_BYTES).contains(&actual) {
        return Err(FrameHeaderValidationError::IdentityLength {
            field,
            actual,
            minimum: 1,
            maximum: MAX_WIRE_IDENTITY_BYTES,
            byte_offset,
        });
    }
    Ok(())
}

fn read_u16(bytes: &[u8], start: usize) -> u16 {
    u16::from_be_bytes(
        bytes[start..start + 2]
            .try_into()
            .expect("fixed header admission guarantees u16 field"),
    )
}

fn read_u32(bytes: &[u8], start: usize) -> u32 {
    u32::from_be_bytes(
        bytes[start..start + 4]
            .try_into()
            .expect("fixed header admission guarantees u32 field"),
    )
}

fn read_u64(bytes: &[u8], start: usize) -> u64 {
    u64::from_be_bytes(
        bytes[start..start + 8]
            .try_into()
            .expect("fixed header admission guarantees u64 field"),
    )
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use crate::WireEnvelopeV2;

    use super::*;

    #[test]
    fn canonical_header_parses_and_validates_once() -> Result<(), Box<dyn Error>> {
        let frame = WireEnvelopeV2::new(
            StableId::new("schema.header.v1")?,
            StableId::new("producer.header")?,
            Generation::new(7)?,
            b"payload".to_vec(),
        )?
        .encode();
        let parsed = FrameHeader::parse(&frame)?;
        let validated = parsed.validate()?;
        assert_eq!(validated.version(), WireVersion::V2);
        assert_eq!(validated.frame_length(), frame.len());
        assert_eq!(parsed.generation(), 7);
        Ok(())
    }

    #[test]
    fn validation_error_exposes_offset_actual_and_limits() -> Result<(), Box<dyn Error>> {
        let mut frame = WireEnvelopeV2::new(
            StableId::new("s")?,
            StableId::new("p")?,
            Generation::new(1)?,
            vec![1],
        )?
        .encode();
        frame[50..54].copy_from_slice(&0_u32.to_be_bytes());
        assert_eq!(
            FrameHeader::parse(&frame)?.validate(),
            Err(FrameHeaderValidationError::PayloadLength {
                actual: 0,
                minimum: 1,
                maximum: MAX_WIRE_PAYLOAD_BYTES,
                byte_offset: PAYLOAD_LENGTH_OFFSET,
            })
        );
        Ok(())
    }
}
