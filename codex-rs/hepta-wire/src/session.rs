use std::error::Error;
use std::fmt;

use crate::DecodedEnvelope;
use crate::NegotiatedWire;
use crate::StreamDecodeError;
use crate::StreamingDecoder;
use crate::WireSession;
use crate::WireSessionError;
use crate::WireVersion;

/// Completed frames admitted for one negotiated version, plus an optional
/// terminal connection error observed later in the same chunk.
#[must_use = "consume the completed prefix and inspect the terminal error"]
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
/// This compatibility layer enforces the selected version. Production callers
/// that also require frozen schema, producer and role admission should use
/// [`WireSessionDecoder`].
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
            stream: StreamingDecoder::for_negotiated_version(negotiated.version()),
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
            if observed != self.negotiated.version() {
                return self.fail(
                    admitted,
                    NegotiatedDecodeError::VersionMismatch {
                        negotiated: self.negotiated.version(),
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
                    ..
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

/// Completed frames admitted by one immutable [`WireSession`], plus an
/// optional terminal stream or session-policy error.
#[must_use = "consume the completed prefix and inspect the terminal error"]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireSessionDecodeBatch {
    frames: Vec<DecodedEnvelope>,
    terminal_error: Option<WireSessionDecodeError>,
}

impl WireSessionDecodeBatch {
    pub fn frames(&self) -> &[DecodedEnvelope] {
        &self.frames
    }

    pub fn terminal_error(&self) -> Option<&WireSessionDecodeError> {
        self.terminal_error.as_ref()
    }

    pub fn into_parts(self) -> (Vec<DecodedEnvelope>, Option<WireSessionDecodeError>) {
        (self.frames, self.terminal_error)
    }
}

/// Production incremental decoder bound to the selected version, effective
/// capabilities, frozen registry digest, runtime role and session identity.
///
/// Every completed frame is admitted through the same `WireSession` policy as
/// one-shot and authenticated-record decoding. A stream or policy failure is
/// terminal and clears all partial bytes; a new session is required.
#[derive(Debug)]
pub struct WireSessionDecoder {
    session: WireSession,
    stream: StreamingDecoder,
    terminal_error: Option<WireSessionDecodeError>,
}

impl WireSessionDecoder {
    pub fn new(session: WireSession) -> Self {
        let version = session.negotiated().version();
        Self {
            session,
            stream: StreamingDecoder::for_negotiated_version(version),
            terminal_error: None,
        }
    }

    pub fn session(&self) -> &WireSession {
        &self.session
    }

    pub fn buffered_len(&self) -> usize {
        self.stream.buffered_len()
    }

    pub fn terminal_error(&self) -> Option<&WireSessionDecodeError> {
        self.terminal_error.as_ref()
    }

    pub const fn is_poisoned(&self) -> bool {
        self.terminal_error.is_some()
    }

    pub fn push_batch(&mut self, chunk: &[u8]) -> WireSessionDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return WireSessionDecodeBatch {
                frames: Vec::new(),
                terminal_error: Some(error),
            };
        }

        let (decoded, stream_error) = self.stream.push_batch(chunk).into_parts();
        let mut admitted = Vec::with_capacity(decoded.len());
        for frame in decoded {
            if let Err(error) = self.session.admit_envelope(&frame) {
                return self.fail(admitted, WireSessionDecodeError::Session(error));
            }
            admitted.push(frame);
        }
        if let Some(error) = stream_error {
            return self.fail(admitted, WireSessionDecodeError::Stream(error));
        }
        WireSessionDecodeBatch {
            frames: admitted,
            terminal_error: None,
        }
    }

    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<DecodedEnvelope>, WireSessionDecodeError> {
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
        error: WireSessionDecodeError,
    ) -> WireSessionDecodeBatch {
        self.stream.clear();
        self.terminal_error = Some(error.clone());
        WireSessionDecodeBatch {
            frames,
            terminal_error: Some(error),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireSessionDecodeError {
    Stream(StreamDecodeError),
    Session(WireSessionError),
}

impl fmt::Display for WireSessionDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Stream(error) => error.fmt(formatter),
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for WireSessionDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Stream(error) => Some(error),
            Self::Session(error) => Some(error),
        }
    }
}

#[cfg(test)]
#[path = "session_tests.rs"]
mod tests;
