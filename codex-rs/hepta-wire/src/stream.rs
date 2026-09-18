use std::error::Error;
use std::fmt;
use std::io::ErrorKind;
use std::io::Read;

use crate::WireError;
use crate::WireFrame;
use crate::envelope::HEADER_FIXED_BYTES;
use crate::envelope::MAGIC;
use crate::envelope::body_offsets;
use crate::envelope::read_u16;
use crate::envelope::read_u32;
use crate::envelope::read_u64;
use crate::envelope::validate_identity_lengths;
use crate::envelope::validate_payload_length;
use crate::integrity::HPTA_V1;
use crate::integrity::HPTA_V2;

/// Reads exactly one bounded HPTA frame from a byte stream.
///
/// The fixed header is admitted before the variable body is allocated. Read
/// deadlines remain owned by the transport; this synchronous helper does not
/// invent timeout policy.
pub fn read_frame<R: Read>(reader: &mut R) -> Result<WireFrame, StreamWireError> {
    let mut header = [0_u8; HEADER_FIXED_BYTES];
    read_exact(reader, &mut header)?;

    if header[..4] != MAGIC {
        return Err(StreamWireError::Wire(WireError::Magic));
    }
    let version = read_u16(&header, 4).map_err(StreamWireError::Wire)?;
    if !matches!(version, HPTA_V1 | HPTA_V2) {
        return Err(StreamWireError::Wire(WireError::Version(version)));
    }

    let schema_length =
        usize::from(read_u16(&header, 6).map_err(StreamWireError::Wire)?);
    let producer_length =
        usize::from(read_u16(&header, 8).map_err(StreamWireError::Wire)?);
    validate_identity_lengths(schema_length, producer_length)
        .map_err(StreamWireError::Wire)?;

    let generation = read_u64(&header, 10).map_err(StreamWireError::Wire)?;
    if generation == 0 {
        return Err(StreamWireError::Wire(WireError::Generation));
    }

    let payload_length = usize::try_from(
        read_u32(&header, 50).map_err(StreamWireError::Wire)?,
    )
    .map_err(|_| StreamWireError::Wire(WireError::PayloadLength))?;
    validate_payload_length(payload_length).map_err(StreamWireError::Wire)?;

    let (_, _, total_length) =
        body_offsets(schema_length, producer_length, payload_length)
            .map_err(StreamWireError::Wire)?;
    let body_length = total_length
        .checked_sub(HEADER_FIXED_BYTES)
        .ok_or(StreamWireError::Wire(WireError::PayloadLength))?;

    let mut encoded = Vec::with_capacity(total_length);
    encoded.extend_from_slice(&header);
    let mut body = vec![0_u8; body_length];
    read_exact(reader, &mut body)?;
    encoded.extend_from_slice(&body);

    WireFrame::decode(&encoded).map_err(StreamWireError::Wire)
}

fn read_exact<R: Read>(reader: &mut R, output: &mut [u8]) -> Result<(), StreamWireError> {
    match reader.read_exact(output) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == ErrorKind::UnexpectedEof => {
            Err(StreamWireError::Wire(WireError::Truncated))
        }
        Err(error) => Err(StreamWireError::Io(error.kind())),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamWireError {
    Wire(WireError),
    Io(ErrorKind),
}

impl fmt::Display for StreamWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Wire(error) => error.fmt(formatter),
            Self::Io(kind) => write!(formatter, "wire stream I/O error: {kind:?}"),
        }
    }
}

impl Error for StreamWireError {}
