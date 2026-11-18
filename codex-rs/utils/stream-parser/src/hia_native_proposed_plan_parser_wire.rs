//! Checked framing for the borrowed ProposedPlan command protocol.

pub(super) const FRAME_BYTES: usize = 4096;
pub(super) const FIRST: u64 = 1;
pub(super) const FINAL: u64 = 2;
pub(super) const INPUT_BYTES: usize = 88;
pub(super) const OUTPUT_BYTES: usize = 80;
pub(super) const COMMAND_BYTES: usize = 32;
const WORD_BYTES: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum WireError {
    Request,
    State,
    WrapperStatus,
    NativeError,
    Result,
    Command,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct State {
    pub(super) active: u64,
    pub(super) detect: u64,
    pub(super) prefix_id: u64,
    pub(super) leading_bytes: u64,
    pub(super) trailing_bytes: u64,
    pub(super) pending_bytes: u64,
    pub(super) call_open: u64,
    pub(super) last_text_kind: u64,
}

impl State {
    pub(super) const INITIAL: Self = Self {
        active: 0,
        detect: 1,
        prefix_id: 0,
        leading_bytes: 0,
        trailing_bytes: 0,
        pending_bytes: 0,
        call_open: 0,
        last_text_kind: 0,
    };

    pub(super) fn validate(self) -> Result<(), WireError> {
        if self.active > 1 || self.detect > 1 || self.call_open > 1 || self.last_text_kind > 2 {
            return Err(WireError::State);
        }
        if self.call_open == 0 && self.last_text_kind != 0 {
            return Err(WireError::State);
        }
        if self.last_text_kind != 0 && self.last_text_kind != self.active + 1 {
            return Err(WireError::State);
        }
        if self.detect == 0 {
            if self.prefix_id != 0
                || self.leading_bytes != 0
                || self.trailing_bytes != 0
                || self.pending_bytes != 0
            {
                return Err(WireError::State);
            }
            return Ok(());
        }
        let prefix_bytes = match self.prefix_id {
            0..=15 => self.prefix_id,
            16..=30 => self.prefix_id - 14,
            _ => return Err(WireError::State),
        };
        if self.prefix_id == 0 && self.trailing_bytes != 0 {
            return Err(WireError::State);
        }
        if self
            .leading_bytes
            .checked_add(prefix_bytes)
            .and_then(|bytes| bytes.checked_add(self.trailing_bytes))
            != Some(self.pending_bytes)
        {
            return Err(WireError::State);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub(super) enum Operation {
    Push = 0,
    Finish = 1,
    Inspect = 2,
}

#[derive(Debug, Clone, Copy)]
pub(super) struct Request<'a> {
    pub(super) operation: Operation,
    pub(super) flags: u64,
    pub(super) state: State,
    pub(super) payload: &'a str,
}

impl Request<'_> {
    pub(super) fn validate(&self, pending_len: usize) -> Result<(), WireError> {
        self.state.validate()?;
        let pending_len = u64::try_from(pending_len).map_err(|_| WireError::Request)?;
        let payload_len = u64::try_from(self.payload.len()).map_err(|_| WireError::Request)?;
        if pending_len != self.state.pending_bytes {
            return Err(WireError::Request);
        }
        match self.operation {
            Operation::Push => {
                if self.payload.len() > FRAME_BYTES
                    || self.flags > (FIRST | FINAL)
                    || ((self.flags & FIRST != 0) != (self.state.call_open == 0))
                    || self.state.pending_bytes.checked_add(payload_len).is_none()
                {
                    return Err(WireError::Request);
                }
            }
            Operation::Finish | Operation::Inspect => {
                if self.flags != 0 || !self.payload.is_empty() || self.state.call_open != 0 {
                    return Err(WireError::Request);
                }
            }
        }
        Ok(())
    }

    pub(super) fn encode(&self, pending_len: usize) -> Result<Vec<u8>, WireError> {
        self.validate(pending_len)?;
        let payload_len = u64::try_from(self.payload.len()).map_err(|_| WireError::Request)?;
        let mut source = Vec::with_capacity(INPUT_BYTES + self.payload.len());
        for word in [
            self.operation as u64,
            self.flags,
            payload_len,
            self.state.active,
            self.state.detect,
            self.state.prefix_id,
            self.state.leading_bytes,
            self.state.trailing_bytes,
            self.state.pending_bytes,
            self.state.call_open,
            self.state.last_text_kind,
        ] {
            source.extend_from_slice(&word.to_le_bytes());
        }
        source.extend_from_slice(self.payload.as_bytes());
        Ok(source)
    }

    pub(super) fn capacity(&self) -> Result<usize, WireError> {
        match self.operation {
            Operation::Push => self
                .payload
                .len()
                .checked_mul(/*rhs*/ 96)
                .and_then(|bytes| bytes.checked_add(OUTPUT_BYTES))
                .ok_or(WireError::Request),
            Operation::Finish => Ok(176),
            Operation::Inspect => Ok(OUTPUT_BYTES),
        }
    }
}

pub(super) struct Response<'a> {
    pub(super) state: State,
    pub(super) records: &'a [u8],
}

pub(super) fn read_words<const N: usize>(bytes: &[u8]) -> Result<[u64; N], WireError> {
    let size = N.checked_mul(WORD_BYTES).ok_or(WireError::Result)?;
    let bytes = bytes.get(..size).ok_or(WireError::Result)?;
    let mut words = [0; N];
    for (word, chunk) in words.iter_mut().zip(bytes.chunks_exact(WORD_BYTES)) {
        let mut value = [0; WORD_BYTES];
        value.copy_from_slice(chunk);
        *word = u64::from_le_bytes(value);
    }
    Ok(words)
}

pub(super) fn decode<'a>(
    request: &Request<'_>,
    pending_len: usize,
    returned: u64,
    output: &'a [u8],
) -> Result<Response<'a>, WireError> {
    request.validate(pending_len)?;
    if returned >> 32 != 0 {
        return Err(WireError::WrapperStatus);
    }
    if returned == 4_294_967_295 || returned == 4_294_967_294 {
        return Err(WireError::NativeError);
    }
    let written = usize::try_from(returned).map_err(|_| WireError::Result)?;
    if written < OUTPUT_BYTES || written > output.len() || output.len() < request.capacity()? {
        return Err(WireError::Result);
    }
    let [
        active,
        detect,
        prefix_id,
        leading_bytes,
        trailing_bytes,
        pending_bytes,
        call_open,
        last_text_kind,
        count,
        reserved,
    ] = read_words::<10>(output)?;
    let state = State {
        active,
        detect,
        prefix_id,
        leading_bytes,
        trailing_bytes,
        pending_bytes,
        call_open,
        last_text_kind,
    };
    state.validate()?;
    let limit = match request.operation {
        Operation::Push => u64::try_from(request.payload.len())
            .map_err(|_| WireError::Result)?
            .checked_mul(/*rhs*/ 3)
            .ok_or(WireError::Result)?,
        Operation::Finish => 3,
        Operation::Inspect => 0,
    };
    let extent = count
        .checked_mul(/*rhs*/ 32)
        .and_then(|bytes| bytes.checked_add(/*rhs*/ 80))
        .ok_or(WireError::Result)?;
    if reserved != 0 || count > limit || extent != returned {
        return Err(WireError::Result);
    }
    match request.operation {
        Operation::Push => {
            if state.call_open != u64::from(request.flags & FINAL == 0) {
                return Err(WireError::State);
            }
        }
        Operation::Finish => {
            if state != State::INITIAL {
                return Err(WireError::State);
            }
        }
        Operation::Inspect => {
            if state != request.state {
                return Err(WireError::State);
            }
        }
    }
    Ok(Response {
        state,
        records: &output[OUTPUT_BYTES..written],
    })
}
