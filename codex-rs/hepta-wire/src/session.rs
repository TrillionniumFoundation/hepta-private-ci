use std::error::Error;
use std::fmt;

use crate::DecodeFeed;
use crate::DecodedEnvelope;
use crate::NegotiatedWire;
use crate::StreamDecodeBatch;
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

    /// Consume a bounded prefix, preserving caller ownership of the suffix.
    /// A work-budget yield never resets negotiation or poisons the session.
    pub fn feed(&mut self, chunk: &[u8]) -> DecodeFeed<NegotiatedDecodeBatch> {
        if let Some(error) = self.terminal_error.clone() {
            return DecodeFeed::new(
                NegotiatedDecodeBatch {
                    frames: Vec::new(),
                    terminal_error: Some(error),
                },
                0,
            );
        }
        let (stream_batch, consumed) = self.stream.feed(chunk).into_parts();
        DecodeFeed::new(self.admit_stream_batch(stream_batch), consumed)
    }

    /// Finalize this connection and reject a retained truncated frame.
    pub fn finish(mut self) -> NegotiatedDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return self.fail(Vec::new(), error);
        }
        let stream = std::mem::take(&mut self.stream);
        self.admit_stream_batch(stream.finish())
    }

    /// Strict compatibility call; the whole input must fit its per-call budget.
    pub fn push_batch(&mut self, chunk: &[u8]) -> NegotiatedDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return NegotiatedDecodeBatch {
                frames: Vec::new(),
                terminal_error: Some(error),
            };
        }
        let stream_batch = self.stream.push_batch(chunk);
        self.admit_stream_batch(stream_batch)
    }

    fn admit_stream_batch(&mut self, stream_batch: StreamDecodeBatch) -> NegotiatedDecodeBatch {
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

    /// Lossless convenience alias. A terminal error can never be hidden behind
    /// a successful result containing the valid prefix.
    #[must_use = "consume the completed prefix and inspect the terminal error"]
    pub fn push(&mut self, chunk: &[u8]) -> NegotiatedDecodeBatch {
        self.push_batch(chunk)
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

    /// Process bounded input; resubmit the unconsumed suffix after each yield.
    /// Protocol or policy failure preserves the admitted prefix and is fatal.
    pub fn feed(&mut self, chunk: &[u8]) -> DecodeFeed<WireSessionDecodeBatch> {
        if let Some(error) = self.terminal_error.clone() {
            return DecodeFeed::new(
                WireSessionDecodeBatch {
                    frames: Vec::new(),
                    terminal_error: Some(error),
                },
                0,
            );
        }
        let (stream_batch, consumed) = self.stream.feed(chunk).into_parts();
        DecodeFeed::new(self.admit_stream_batch(stream_batch), consumed)
    }

    /// Finalize this connection and reject a retained truncated frame.
    pub fn finish(mut self) -> WireSessionDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return self.fail(Vec::new(), error);
        }
        let stream = std::mem::take(&mut self.stream);
        self.admit_stream_batch(stream.finish())
    }

    /// Strict compatibility call; the whole input must fit its per-call budget.
    pub fn push_batch(&mut self, chunk: &[u8]) -> WireSessionDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return WireSessionDecodeBatch {
                frames: Vec::new(),
                terminal_error: Some(error),
            };
        }
        let stream_batch = self.stream.push_batch(chunk);
        self.admit_stream_batch(stream_batch)
    }

    fn admit_stream_batch(&mut self, stream_batch: StreamDecodeBatch) -> WireSessionDecodeBatch {
        let (decoded, stream_error) = stream_batch.into_parts();
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

    /// Lossless convenience alias. Session-policy and stream failures always
    /// remain visible alongside any valid prefix from the same bounded call.
    #[must_use = "consume the completed prefix and inspect the terminal error"]
    pub fn push(&mut self, chunk: &[u8]) -> WireSessionDecodeBatch {
        self.push_batch(chunk)
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
