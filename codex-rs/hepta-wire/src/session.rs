use std::error::Error;
use std::fmt;

use crate::DecodedEnvelope;
use crate::NegotiatedWire;
use crate::StreamDecodeError;
use crate::StreamingDecoder;
use crate::WireVersion;

/// Completed frames admitted for one negotiated session, plus an optional
/// terminal connection error observed later in the same chunk.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NegotiatedDecodeBatch {
    frames: Vec<DecodedEnvelope>,
    terminal_error: Option<NegotiatedDecodeError>,
}

impl NegotiatedDecodeBatch {
    pub fn frames(&self) -> &[DecodedEnvelope] {
        &self.frames
    }

    pub fn terminal_error(&self) -> Option<&NegotiatedDecodeError> {
        self.terminal_error.as_ref()
    }

    pub fn into_parts(self) -> (Vec<DecodedEnvelope>, Option<NegotiatedDecodeError>) {
        (self.frames, self.terminal_error)
    }
}

/// Incremental frame decoder bound to one completed HPTN negotiation.
///
/// The generic frame parser remains useful for offline inspection, but a live
/// connection should use this type so a peer cannot negotiate one version and
/// subsequently send a different frame version. The selected version is checked
/// at the fixed-header boundary, before body allocation or consumption, and a
/// terminal error discards all partial bytes. Authentication of the
/// negotiation transcript and frame bytes remains the transport/session
/// security owner's responsibility.
#[derive(Debug)]
pub struct NegotiatedStreamingDecoder {
    negotiated: NegotiatedWire,
    stream: StreamingDecoder,
    terminal_error: Option<NegotiatedDecodeError>,
}

impl NegotiatedStreamingDecoder {
    pub fn new(negotiated: NegotiatedWire) -> Self {
        Self {
            negotiated,
            stream: StreamingDecoder::for_negotiated_version(negotiated.version),
            terminal_error: None,
        }
    }

    pub const fn negotiated(&self) -> NegotiatedWire {
        self.negotiated
    }

    pub fn buffered_len(&self) -> usize {
        self.stream.buffered_len()
    }

    pub fn terminal_error(&self) -> Option<&NegotiatedDecodeError> {
        self.terminal_error.as_ref()
    }

    pub const fn is_poisoned(&self) -> bool {
        self.terminal_error.is_some()
    }

    pub fn push_batch(&mut self, chunk: &[u8]) -> NegotiatedDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return NegotiatedDecodeBatch {
                frames: Vec::new(),
                terminal_error: Some(error),
            };
        }

        let stream_batch = self.stream.push_batch(chunk);
        let (decoded, stream_error) = stream_batch.into_parts();
        let mut admitted = Vec::with_capacity(decoded.len());
        for frame in decoded {
            let observed = frame.version();
            if observed != self.negotiated.version {
                return self.fail(
                    admitted,
                    NegotiatedDecodeError::VersionMismatch {
                        negotiated: self.negotiated.version,
                        observed,
                    },
                );
            }
            admitted.push(frame);
        }

        if let Some(error) = stream_error {
            let error = match error {
                StreamDecodeError::NegotiatedVersionMismatch {
                    negotiated,
                    observed,
                } => NegotiatedDecodeError::VersionMismatch {
                    negotiated,
                    observed,
                },
                other => NegotiatedDecodeError::Stream(other),
            };
            return self.fail(admitted, error);
        }

        NegotiatedDecodeBatch {
            frames: admitted,
            terminal_error: None,
        }
    }

    /// Compatibility wrapper. New connection code should use `push_batch` so
    /// a valid prefix and a later terminal error are observed atomically.
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<DecodedEnvelope>, NegotiatedDecodeError> {
        let batch = self.push_batch(chunk);
        let (frames, terminal_error) = batch.into_parts();
        if frames.is_empty()
            && let Some(error) = terminal_error
        {
            return Err(error);
        }
        Ok(frames)
    }

    fn fail(
        &mut self,
        frames: Vec<DecodedEnvelope>,
        error: NegotiatedDecodeError,
    ) -> NegotiatedDecodeBatch {
        self.stream.clear();
        self.terminal_error = Some(error.clone());
        NegotiatedDecodeBatch {
            frames,
            terminal_error: Some(error),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NegotiatedDecodeError {
    Stream(StreamDecodeError),
    VersionMismatch {
        negotiated: WireVersion,
        observed: WireVersion,
    },
}

impl fmt::Display for NegotiatedDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Stream(error) => error.fmt(formatter),
            Self::VersionMismatch {
                negotiated,
                observed,
            } => write!(
                formatter,
                "wire frame version {} does not match negotiated version {}",
                observed.as_u16(),
                negotiated.as_u16()
            ),
        }
    }
}

impl Error for NegotiatedDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Stream(error) => Some(error),
            Self::VersionMismatch { .. } => None,
        }
    }
}

#[cfg(test)]
#[path = "session_tests.rs"]
mod tests;
