//! BZip2 stream adapters backed by the Apache-2.0 OxiArc implementation.
//!
//! ZIP embeds a single stream followed by container metadata. The decoder uses
//! OxiArc's explicit single-stream mode so no next-entry bytes are consumed.

use std::io::{self, Read, Write};

use oxiarc_core::error::OxiArcError;

#[derive(Clone, Copy)]
pub(crate) struct Compression(u32);

impl Compression {
    pub(crate) const fn new(level: u32) -> Self {
        Self(level)
    }

    pub(crate) const fn fast() -> Self {
        Self(1)
    }

    pub(crate) const fn best() -> Self {
        Self(9)
    }

    pub(crate) const fn level(self) -> u32 {
        self.0
    }
}

impl Default for Compression {
    fn default() -> Self {
        Self(6)
    }
}

fn io_error(error: OxiArcError) -> io::Error {
    match error {
        OxiArcError::Io(error) => error,
        error @ OxiArcError::UnexpectedEof { .. } => {
            io::Error::new(io::ErrorKind::UnexpectedEof, error)
        }
        error => io::Error::new(io::ErrorKind::InvalidData, error),
    }
}

pub(crate) struct BzDecoder<R: Read> {
    inner: oxiarc_bzip2::BzDecoder<R>,
    block: Vec<u8>,
    position: usize,
    finished: bool,
}

impl<R: Read> BzDecoder<R> {
    pub(crate) fn new(reader: R) -> Result<Self, (io::Error, R)> {
        let inner = oxiarc_bzip2::BzDecoder::try_new_single_stream(reader)
            .map_err(|(error, reader)| (io_error(error), reader))?;
        Ok(Self {
            inner,
            block: Vec::new(),
            position: 0,
            finished: false,
        })
    }

    pub(crate) fn get_ref(&self) -> &R {
        self.inner.get_ref()
    }

    pub(crate) fn into_inner(self) -> R {
        self.inner.into_inner()
    }
}

impl<R: Read> Read for BzDecoder<R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        loop {
            if self.position < self.block.len() {
                let amount = output.len().min(self.block.len() - self.position);
                output[..amount].copy_from_slice(&self.block[self.position..self.position + amount]);
                self.position += amount;
                return Ok(amount);
            }
            if self.finished {
                return Ok(0);
            }
            match self.inner.read_block().map_err(io_error)? {
                Some(block) => {
                    self.block = block;
                    self.position = 0;
                }
                None => self.finished = true,
            }
        }
    }
}

pub(crate) struct BzEncoder<W: Write> {
    inner: oxiarc_bzip2::BzEncoder<W>,
}

impl<W: Write> BzEncoder<W> {
    pub(crate) fn new(writer: W, compression: Compression) -> io::Result<Self> {
        let level = u8::try_from(compression.level())
            .ok()
            .filter(|level| (1..=9).contains(level))
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid BZip2 level"))?;
        Ok(Self {
            inner: oxiarc_bzip2::BzEncoder::new(writer, oxiarc_bzip2::CompressionLevel::new(level))
                .map_err(io_error)?,
        })
    }

    pub(crate) fn get_ref(&self) -> &W {
        self.inner.get_ref()
    }

    pub(crate) fn get_mut(&mut self) -> &mut W {
        self.inner.get_mut()
    }

    pub(crate) fn finish(self) -> io::Result<W> {
        self.inner.finish().map_err(io_error)
    }
}

impl<W: Write> Write for BzEncoder<W> {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        self.inner.write_block(input).map_err(io_error)?;
        Ok(input.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush().map_err(io_error)
    }
}

#[cfg(test)]
mod tests {
    use super::{BzDecoder, BzEncoder, Compression};
    use std::io::{self, Cursor, Read, Write};

    #[test]
    fn retains_levels_flush_continuation_and_next_container_bytes() {
        for level in 1..=9 {
            let mut encoder = BzEncoder::new(Vec::new(), Compression::new(level)).unwrap();
            encoder.write_all(b"first block").unwrap();
            encoder.flush().unwrap();
            assert!(!encoder.get_ref().is_empty());
            encoder.write_all(b"; second block").unwrap();
            let mut bytes = encoder.finish().unwrap();
            let boundary = bytes.len();
            bytes.extend_from_slice(b"PK\x03\x04next container header");
            let mut decoder = BzDecoder::new(Cursor::new(bytes)).unwrap();
            let mut decoded = Vec::new();
            decoder.read_to_end(&mut decoded).unwrap();
            assert_eq!(decoded, b"first block; second block");
            assert_eq!(decoder.get_ref().position(), u64::try_from(boundary).unwrap());
            let mut source = decoder.into_inner();
            let mut remaining = Vec::new();
            source.read_to_end(&mut remaining).unwrap();
            assert_eq!(remaining, b"PK\x03\x04next container header");
        }
    }

    #[test]
    fn preserves_legacy_randomised_blocks() {
        let bytes = include_bytes!("../tests/data/randomised_rep_l1.bz2");
        let mut decoder = BzDecoder::new(Cursor::new(bytes)).unwrap();
        let mut output = Vec::new();
        decoder.read_to_end(&mut output).unwrap();
        assert_eq!(output, b"repetitive repetitive repetitive!\n".repeat(64));
    }

    #[test]
    fn rejects_bad_crc_and_truncation() {
        let mut encoder = BzEncoder::new(Vec::new(), Compression::default()).unwrap();
        encoder.write_all(b"CRC must be checked").unwrap();
        let bytes = encoder.finish().unwrap();
        let mut bad_crc = bytes.clone();
        bad_crc[10] ^= 1;
        for bad in [&bytes[..bytes.len() - 2], bad_crc.as_slice()] {
            let mut decoder = BzDecoder::new(Cursor::new(bad)).unwrap();
            assert!(decoder.read_to_end(&mut Vec::new()).is_err());
        }
    }

    #[test]
    fn header_error_returns_source_and_zero_read_does_not_advance() {
        let source = Cursor::new(b"invalid header".to_vec());
        let (error, source) = BzDecoder::new(source).err().unwrap();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        assert_eq!(source.position(), 4);
        let bytes = BzEncoder::new(Vec::new(), Compression::default()).unwrap().finish().unwrap();
        let mut decoder = BzDecoder::new(Cursor::new(bytes)).unwrap();
        let before = decoder.get_ref().position();
        assert_eq!(decoder.read(&mut []).unwrap(), 0);
        assert_eq!(decoder.get_ref().position(), before);
    }
}
