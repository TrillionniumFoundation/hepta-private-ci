//! Bounded borrowed-buffer transport for the citation stream parser.

pub(super) const CHUNK_BYTES: usize = 4096;
const WORD_BYTES: usize = 8;
const SOURCE_HEADER_BYTES: usize = 40;
const RESULT_HEADER_BYTES: usize = 48;
const RECORD_HEADER_BYTES: usize = 16;
const VERSION: u64 = 1;

pub(super) type NativeResult<T> = Result<T, &'static str>;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub(super) struct State {
    pub(super) active: u64,
    pub(super) prefix_len: u64,
}

impl State {
    fn valid(self) -> bool {
        self.active <= 1 && self.prefix_len <= 17 + self.active
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub(super) enum Operation {
    Push = 0,
    Finish = 1,
    Inspect = 2,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Visible,
    Body,
    Commit,
    Pending,
}

pub(super) struct Event {
    pub(super) kind: Kind,
    pub(super) start: usize,
    pub(super) end: usize,
}

pub(super) struct Reply {
    pub(super) state: State,
    pub(super) bytes: Vec<u8>,
    pub(super) events: Vec<Event>,
}

unsafe extern "C" {
    fn codex_hia_citation_stream_parser(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn call(operation: Operation, state: State, payload: &[u8]) -> NativeResult<Reply> {
    if !state.valid()
        || payload.len() > CHUNK_BYTES
        || (operation != Operation::Push && !payload.is_empty())
    {
        return Err("invalid citation request shape");
    }
    let capacity = match operation {
        Operation::Push => 98 + 33 * payload.len(),
        Operation::Finish => 98,
        Operation::Inspect => 64 + count(state.prefix_len)?,
    };
    let mut source = Vec::with_capacity(SOURCE_HEADER_BYTES + payload.len());
    for word in [
        VERSION,
        operation as u64,
        state.active,
        state.prefix_len,
        payload.len() as u64,
    ] {
        source.extend_from_slice(&word.to_le_bytes());
    }
    source.extend_from_slice(payload);
    let mut output = vec![0_u8; capacity];
    let mut workspace = [];
    // SAFETY: separate live buffers cover every advertised range for this
    // synchronous call. The checked native entry retains no pointers and
    // never reads or writes the zero-length workspace.
    let status = unsafe {
        codex_hia_citation_stream_parser(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    if status >> 32 != 0 {
        return Err("native citation wrapper rejected the request");
    }
    match status as u32 {
        u32::MAX => return Err("native citation frame or state is invalid"),
        value if value == u32::MAX - 1 => {
            return Err("native citation output capacity is insufficient");
        }
        _ => {}
    }
    decode(operation, state, payload.len(), output, count(status)?)
}

fn count(value: u64) -> NativeResult<usize> {
    usize::try_from(value).map_err(|_| "native citation count does not fit usize")
}

fn word(bytes: &[u8], offset: usize) -> NativeResult<u64> {
    let end = offset
        .checked_add(WORD_BYTES)
        .ok_or("native citation word offset overflow")?;
    let field = bytes
        .get(offset..end)
        .ok_or("native citation word is incomplete")?;
    let mut encoded = [0_u8; WORD_BYTES];
    encoded.copy_from_slice(field);
    Ok(u64::from_le_bytes(encoded))
}

fn decode(
    operation: Operation,
    state: State,
    payload_len: usize,
    mut bytes: Vec<u8>,
    written: usize,
) -> NativeResult<Reply> {
    if payload_len > CHUNK_BYTES || written < RESULT_HEADER_BYTES || written > bytes.len() {
        return Err("native citation result extent is invalid");
    }
    bytes.truncate(written);
    let mut header = [0_u64; 6];
    for (value, field) in header
        .iter_mut()
        .zip(bytes[..RESULT_HEADER_BYTES].chunks_exact(WORD_BYTES))
    {
        let mut encoded = [0_u8; WORD_BYTES];
        encoded.copy_from_slice(field);
        *value = u64::from_le_bytes(encoded);
    }
    let next = State {
        active: header[2],
        prefix_len: header[3],
    };
    if header[0] != VERSION || header[1] != operation as u64 || !next.valid() {
        return Err("native citation result identity is invalid");
    }
    let event_count = count(header[4])?;
    let payload_bytes = count(header[5])?;
    let (max_events, max_payload) = match operation {
        Operation::Push => (2 * payload_len + 2, payload_len + 18),
        Operation::Finish => (2, 18),
        Operation::Inspect => (1, count(state.prefix_len)?),
    };
    let extent = event_count
        .checked_mul(RECORD_HEADER_BYTES)
        .and_then(|size| size.checked_add(RESULT_HEADER_BYTES))
        .and_then(|size| size.checked_add(payload_bytes))
        .ok_or("native citation result length overflow")?;
    if event_count > max_events || payload_bytes > max_payload || extent != written {
        return Err("native citation result counts are invalid");
    }
    if operation == Operation::Finish && next != State::default() {
        return Err("native citation finish did not reset state");
    }
    if operation == Operation::Inspect
        && (next != state || event_count != 1 || payload_bytes != count(state.prefix_len)?)
    {
        return Err("native citation inspection changed state or shape");
    }
    let mut events = Vec::with_capacity(event_count);
    let mut cursor = RESULT_HEADER_BYTES;
    let mut total = 0_usize;
    let mut previous = None;
    for index in 0..event_count {
        let raw_kind = word(&bytes, cursor)?;
        let length_offset = cursor
            .checked_add(WORD_BYTES)
            .ok_or("native citation record offset overflow")?;
        let length = count(word(&bytes, length_offset)?)?;
        let start = cursor
            .checked_add(RECORD_HEADER_BYTES)
            .ok_or("native citation payload offset overflow")?;
        let end = start
            .checked_add(length)
            .ok_or("native citation payload end overflow")?;
        if end > written {
            return Err("native citation record exceeds the result");
        }
        let kind = match raw_kind {
            0 if operation != Operation::Inspect && length != 0 => Kind::Visible,
            1 if operation != Operation::Inspect && length != 0 => Kind::Body,
            2 if operation != Operation::Inspect && length == 0 => Kind::Commit,
            3 if operation == Operation::Inspect && length == count(state.prefix_len)? => {
                Kind::Pending
            }
            _ => return Err("native citation record kind or length is invalid"),
        };
        if previous == Some(kind) && matches!(kind, Kind::Visible | Kind::Body) {
            return Err("native citation adjacent payload records were not merged");
        }
        if operation == Operation::Finish
            && ((kind == Kind::Commit && index + 1 != event_count)
                || (index != 0 && kind != Kind::Commit))
        {
            return Err("native citation finish records are invalid");
        }
        total = total
            .checked_add(length)
            .ok_or("native citation payload total overflow")?;
        events.push(Event { kind, start, end });
        previous = Some(kind);
        cursor = end;
    }
    if cursor != written || total != payload_bytes {
        return Err("native citation result has trailing or missing bytes");
    }
    Ok(Reply {
        state: next,
        bytes,
        events,
    })
}
