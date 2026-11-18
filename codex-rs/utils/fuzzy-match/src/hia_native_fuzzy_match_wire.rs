//! Fixed-width transport for the borrowed fuzzy matcher.

use std::ops::Index;

pub(super) type Error = &'static str;

pub(super) const VERSION: u64 = 1;
pub(super) const WORD_BYTES: usize = 8;
pub(super) const STATE_WORDS: usize = 32;
pub(super) const INPUT_PREFIX: usize = 320;
pub(super) const OUTPUT_HEADER: usize = 128;
pub(super) const OUTPUT_PREFIX: usize = 384;
pub(super) const FRAME_BYTES: usize = 4096;
pub(super) const WINDOW_RECORDS: usize = 128;
pub(super) const HAY_RECORD_BYTES: usize = 24;
pub(super) const COMMAND_BYTES: usize = 24;
pub(super) const RECORD_WORDS: usize = 3;
pub(super) const MATCH_CAPACITY: usize = 2048;
pub(super) const END: u64 = 1;
pub(super) const NORMAL_SIGMA: u32 = 0x03c3;
pub(super) const FINAL_SIGMA: u32 = 0x03c2;
pub(super) const MAPPING_SLOTS: u64 = 3;
pub(super) const UTF8_SCALAR_BYTES: u64 = 4;
pub(super) const FRESH: u64 = 0;
pub(super) const HAYSTACK: u64 = 1;
pub(super) const NEEDLE: u64 = 2;
pub(super) const MATCHING: u64 = 3;
pub(super) const DONE: u64 = 4;
pub(super) const CONTINUE: u64 = 0;
pub(super) const SOME: u64 = 1;
pub(super) const NONE: u64 = 2;

pub(super) mod field {
    pub const PHASE: usize = 0;
    pub const HAY_TOTAL: usize = 1;
    pub const NEEDLE_TOTAL: usize = 2;
    pub const HAY_SEEN: usize = 3;
    pub const NEEDLE_SEEN: usize = 4;
    pub const HAY_ORIGINAL: usize = 5;
    pub const HAY_LOWER: usize = 6;
    pub const NEEDLE_ORIGINAL: usize = 7;
    pub const NEEDLE_LOWER: usize = 8;
    pub const PREVIOUS_CASED: usize = 9;
    pub const SIGMA_PENDING: usize = 10;
    pub const SIGMA_SLOT: usize = 11;
    pub const HAY_CURSOR: usize = 12;
    pub const NEEDLE_CURSOR: usize = 13;
    pub const LAST_START: usize = 14;
    pub const FIRST_ORIGINAL: usize = 15;
    pub const FIRST_START: usize = 16;
    pub const LAST_HIT: usize = 17;
    pub const LAST_ORIGINAL: usize = 18;
    pub const UNIQUE: usize = 19;
    pub const OUTCOME: usize = 20;
    pub const SCORE: usize = 21;
    pub const OVERFLOW_OP: usize = 22;
    pub const OVERFLOW_LHS: usize = 23;
    pub const OVERFLOW_RHS: usize = 24;
    pub const R1: usize = 25;
    pub const R2: usize = 26;
    pub const R3: usize = 27;
    pub const SCANNED_ORIGINAL: usize = 28;
    pub const SCANNED_START: usize = 29;
    pub const FIRST_HIT: usize = 30;
    pub const OVERFLOW_MASK: usize = 31;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct State(pub(super) [u64; STATE_WORDS]);

impl State {
    pub(super) const INITIAL: Self = Self([0; STATE_WORDS]);
}

impl Index<usize> for State {
    type Output = u64;

    fn index(&self, index: usize) -> &Self::Output {
        &self.0[index]
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u64)]
pub(super) enum Operation {
    Begin = 0,
    LowerHaystack = 1,
    LowerNeedle = 2,
    Match = 3,
}

pub(super) struct Request<'a> {
    pub(super) operation: Operation,
    pub(super) flags: u64,
    pub(super) state: State,
    pub(super) argument_a: u64,
    pub(super) argument_b: u64,
    pub(super) payload: &'a [u8],
}

impl Request<'_> {
    pub(super) fn capacity(&self) -> Result<usize, Error> {
        require(self.payload.len() <= FRAME_BYTES, "input frame size")?;
        let records = match self.operation {
            Operation::Begin => 0,
            Operation::LowerHaystack => self.payload.len() * 72,
            Operation::LowerNeedle => (4 * self.payload.len() + 1) * COMMAND_BYTES,
            Operation::Match => return Ok(MATCH_CAPACITY),
        };
        OUTPUT_PREFIX.checked_add(records).ok_or("output capacity")
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        let capacity = INPUT_PREFIX
            .checked_add(self.payload.len())
            .ok_or("input capacity")?;
        let header = [
            VERSION,
            self.operation as u64,
            self.flags,
            to_u64(self.payload.len())?,
            self.argument_a,
            self.argument_b,
            0,
            0,
        ];
        let mut bytes = Vec::with_capacity(capacity);
        for word in header.into_iter().chain(self.state.0) {
            bytes.extend_from_slice(&word.to_le_bytes());
        }
        bytes.extend_from_slice(self.payload);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct Response {
    pub(super) state: State,
    pub(super) advance_a: u64,
    pub(super) advance_b: u64,
    pub(super) record_count: usize,
    pub(super) records: Vec<u64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct HayRecord {
    pub(super) scalar: u32,
    pub(super) original: u64,
    pub(super) start: u64,
}

pub(super) fn decode(
    request: &Request<'_>,
    returned: u64,
    output: &[u8],
) -> Result<Response, Error> {
    require(returned >> 32 == 0, "wrapper status")?;
    match returned {
        0 => {}
        1 => return Err("native invalid input"),
        2 => return Err("native short output"),
        3 => return Err("native counter overflow"),
        _ => return Err("unknown native status"),
    }
    require(output.len() == request.capacity()?, "output reservation")?;
    let header = read_words::<16>(&output[..OUTPUT_HEADER])?;
    let state = State(read_words(&output[OUTPUT_HEADER..OUTPUT_PREFIX])?);
    require(header[0] == VERSION, "output version")?;
    require(header[1] == request.operation as u64, "output operation")?;
    require(header[2] == state[field::OUTCOME], "output outcome")?;
    require(header[3] == request.operation as u64, "record kind")?;
    require(header[9..].iter().all(|word| *word == 0), "reserved output")?;
    let count = to_usize(header[6])?;
    let width = match request.operation {
        Operation::Begin => 0,
        Operation::LowerHaystack => HAY_RECORD_BYTES,
        Operation::LowerNeedle => COMMAND_BYTES,
        Operation::Match => WORD_BYTES,
    };
    if request.operation == Operation::Begin {
        require(count == 0, "begin records")?;
    }
    let record_bytes = count.checked_mul(width).ok_or("record byte count")?;
    let defined = OUTPUT_PREFIX
        .checked_add(record_bytes)
        .ok_or("defined output size")?;
    require(header[7] == to_u64(record_bytes)?, "record byte count")?;
    require(header[8] == to_u64(defined)?, "defined output size")?;
    require(defined <= output.len(), "output extent")?;
    // Invocation supplies a zero-filled buffer, so its unused tail must stay zero.
    require(
        output[defined..].iter().all(|byte| *byte == 0),
        "output tail",
    )?;
    let records = output[OUTPUT_PREFIX..defined]
        .chunks_exact(WORD_BYTES)
        .map(|chunk| {
            let bytes = chunk.try_into().map_err(|_| "record word")?;
            Ok(u64::from_le_bytes(bytes))
        })
        .collect::<Result<Vec<_>, Error>>()?;
    Ok(Response {
        state,
        advance_a: header[4],
        advance_b: header[5],
        record_count: count,
        records,
    })
}

fn read_words<const N: usize>(bytes: &[u8]) -> Result<[u64; N], Error> {
    require(bytes.len() == N * WORD_BYTES, "word array size")?;
    let mut words = [0; N];
    for (word, chunk) in words.iter_mut().zip(bytes.chunks_exact(WORD_BYTES)) {
        let bytes = chunk.try_into().map_err(|_| "word width")?;
        *word = u64::from_le_bytes(bytes);
    }
    Ok(words)
}

pub(super) fn require(condition: bool, error: Error) -> Result<(), Error> {
    if condition { Ok(()) } else { Err(error) }
}

pub(super) fn to_u64(value: usize) -> Result<u64, Error> {
    u64::try_from(value).map_err(|_| "host length exceeds u64")
}

pub(super) fn to_usize(value: u64) -> Result<usize, Error> {
    usize::try_from(value).map_err(|_| "native index exceeds usize")
}

pub(super) fn scalar(value: u64) -> Result<u32, Error> {
    require(
        value <= 0x10ffff && !(0xd800..=0xdfff).contains(&value),
        "Unicode scalar",
    )?;
    u32::try_from(value).map_err(|_| "Unicode scalar width")
}
