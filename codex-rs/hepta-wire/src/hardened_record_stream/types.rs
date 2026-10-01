/// Caller-owned allowance shared by hardened streams for one scheduling turn.
///
/// Source bytes, full-record authentication attempts and complete serialized
/// HPTA frame bytes are charged independently. Exhaustion yields without
/// discarding a suffix or resetting session state. This type is deliberately
/// neither `Clone` nor `Copy`.
#[derive(Debug, Eq, PartialEq)]
pub struct HardenedRecordStreamBudget {
    remaining_bytes: usize,
    remaining_records: usize,
    remaining_frame_bytes: usize,
}

impl HardenedRecordStreamBudget {
    pub const fn new(bytes: usize, records: usize) -> Self {
        Self::with_frame_bytes(bytes, records, MAX_WIRE_FRAME_BYTES)
    }

    pub const fn with_frame_bytes(bytes: usize, records: usize, frame_bytes: usize) -> Self {
        Self {
            remaining_bytes: bytes,
            remaining_records: records,
            remaining_frame_bytes: frame_bytes,
        }
    }

    pub const fn remaining_bytes(&self) -> usize {
        self.remaining_bytes
    }

    pub const fn remaining_records(&self) -> usize {
        self.remaining_records
    }

    pub const fn remaining_frame_bytes(&self) -> usize {
        self.remaining_frame_bytes
    }
}

/// Typed values before a terminal suffix remain deliverable exactly once.
#[must_use = "deliver accepted typed values before acting on the terminal error"]
pub struct HardenedRecordStreamBatch<T> {
    values: Vec<T>,
    terminal_error: Option<HardenedRecordStreamError>,
    yielded: bool,
    required_frame_bytes: Option<usize>,
}

impl<T> HardenedRecordStreamBatch<T> {
    pub fn values(&self) -> &[T] {
        &self.values
    }

    pub fn terminal_error(&self) -> Option<&HardenedRecordStreamError> {
        self.terminal_error.as_ref()
    }

    pub const fn yielded(&self) -> bool {
        self.yielded
    }

    /// Full serialized HPTA size of the next record blocked by frame capacity.
    pub const fn required_frame_bytes(&self) -> Option<usize> {
        self.required_frame_bytes
    }

    pub fn into_parts(self) -> (Vec<T>, Option<HardenedRecordStreamError>) {
        (self.values, self.terminal_error)
    }
}

impl<T> fmt::Debug for HardenedRecordStreamBatch<T> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HardenedRecordStreamBatch")
            .field("value_count", &self.values.len())
            .field("terminal_error", &self.terminal_error)
            .field("yielded", &self.yielded)
            .field("required_frame_bytes", &self.required_frame_bytes)
            .finish()
    }
}

/// Unique bounded stream derived from a `HardenedManagedWireSession`.
///
/// The codec is owned by the stream and verified before construction. No raw
/// envelope or lower-level authenticated owner can be recovered from this type.
pub struct HardenedRecordStream<C: BoundPayloadCodec> {
    owner: HardenedManagedWireSession,
    codec: C,
    limits: RecordStreamLimits,
    pending: Vec<u8>,
    expected: Option<usize>,
    terminal: bool,
    idle_buffer_limit_bytes: usize,
}

impl HardenedManagedWireSession {
    pub fn into_record_stream<C: BoundPayloadCodec>(
        mut self,
        codec: C,
        limits: RecordStreamLimits,
    ) -> Result<HardenedRecordStream<C>, HardenedRecordStreamError> {
        let minimum = PREFIX_BYTES + WIRE_HEADER_BYTES + TAG_BYTES;
        if !(minimum..=MAX_AUTHENTICATED_RECORD_BYTES).contains(&limits.max_record_bytes)
            || limits.max_feed_bytes == 0
            || limits.max_feed_bytes > MAX_AUTHENTICATED_RECORD_BYTES
            || limits.max_records_per_feed == 0
            || limits.max_records_per_feed > 1024
        {
            return Err(HardenedRecordStreamError::InvalidLimits);
        }
        if self.state() != SessionLifecycleState::Active {
            return Err(HardenedRecordStreamError::Terminated);
        }
        self.verify_bound_codec(&codec)
            .map_err(HardenedRecordStreamError::Session)?;
        let idle_buffer_limit_bytes = limits.max_feed_bytes.min(limits.max_record_bytes);
        Ok(HardenedRecordStream {
            owner: self,
            codec,
            limits,
            pending: Vec::new(),
            expected: None,
            terminal: false,
            idle_buffer_limit_bytes,
        })
    }
}
