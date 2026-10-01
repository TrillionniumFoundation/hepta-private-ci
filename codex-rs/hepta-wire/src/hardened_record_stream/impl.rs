impl<C: BoundPayloadCodec> HardenedRecordStream<C> {
    pub fn buffered_bytes(&self) -> usize {
        self.pending.len()
    }

    pub fn buffer_capacity_bytes(&self) -> usize {
        self.pending.capacity()
    }

    pub const fn idle_buffer_limit_bytes(&self) -> usize {
        self.idle_buffer_limit_bytes
    }

    pub fn set_idle_buffer_limit_bytes(&mut self, limit: usize) -> usize {
        self.idle_buffer_limit_bytes = limit.min(self.limits.max_record_bytes);
        self.trim_idle_buffer_to_limit()
    }

    pub fn release_idle_buffer(&mut self) -> usize {
        if !self.pending.is_empty() || self.expected.is_some() {
            return 0;
        }
        let released = self.pending.capacity();
        self.pending = Vec::new();
        released
    }

    fn trim_idle_buffer_to_limit(&mut self) -> usize {
        if self.pending.capacity() > self.idle_buffer_limit_bytes {
            self.release_idle_buffer()
        } else {
            0
        }
    }

    pub fn is_terminal(&self) -> bool {
        self.terminal || self.owner.state() != SessionLifecycleState::Active
    }

    pub fn retire(&mut self) {
        self.owner.retire();
        self.pending = Vec::new();
        self.expected = None;
        self.terminal = true;
    }

    /// Seal one typed value through the stream's exact bound codec.
    pub fn seal_bound_typed(
        &mut self,
        producer: StableId,
        generation: Generation,
        value: &C::Value,
    ) -> Result<Vec<u8>, HardenedRecordStreamError> {
        if self.is_terminal() {
            return Err(HardenedRecordStreamError::Terminated);
        }
        match self
            .owner
            .seal_bound_typed(producer, generation, &self.codec, value)
        {
            Ok(record) if record.len() <= self.limits.max_record_bytes => Ok(record),
            Ok(_) => {
                self.retire();
                Err(HardenedRecordStreamError::RecordLimit)
            }
            Err(error) => {
                self.retire();
                Err(HardenedRecordStreamError::Session(error))
            }
        }
    }

    fn reserve_admitted(&mut self, additional: usize) -> Result<(), HardenedRecordStreamError> {
        let needed = self
            .pending
            .len()
            .checked_add(additional)
            .ok_or(HardenedRecordStreamError::RecordLimit)?;
        if needed > self.limits.max_record_bytes {
            return Err(HardenedRecordStreamError::RecordLimit);
        }
        if needed <= self.pending.capacity() {
            return Ok(());
        }
        let ceiling = self.expected.unwrap_or(PREFIX_BYTES);
        let capacity = needed
            .max(PREFIX_BYTES)
            .max(self.pending.capacity().saturating_mul(2))
            .min(ceiling);
        self.pending
            .try_reserve_exact(capacity - self.pending.len())
            .map_err(|_| HardenedRecordStreamError::Allocation)
    }

    fn admitted_record_length(&self, prefix: &[u8]) -> Result<usize, HardenedRecordStreamError> {
        if prefix[..4] != *b"HPTM" || prefix[4..6] != [0, 1] {
            return Err(HardenedRecordStreamError::InvalidPrefix);
        }
        if &prefix[6..38] != self.owner.session_id().as_array() {
            return Err(HardenedRecordStreamError::SessionIdentityMismatch);
        }
        let length = u32::from_be_bytes([prefix[46], prefix[47], prefix[48], prefix[49]]);
        let length =
            usize::try_from(length).map_err(|_| HardenedRecordStreamError::RecordLimit)?;
        if !(WIRE_HEADER_BYTES..=MAX_WIRE_FRAME_BYTES).contains(&length)
            || length > self.limits.max_record_bytes - PREFIX_BYTES - TAG_BYTES
        {
            return Err(HardenedRecordStreamError::RecordLimit);
        }
        Ok(PREFIX_BYTES + length + TAG_BYTES)
    }

    pub fn feed(&mut self, input: &[u8]) -> DecodeFeed<HardenedRecordStreamBatch<C::Value>> {
        let mut allowance = HardenedRecordStreamBudget::new(
            self.limits.max_feed_bytes,
            self.limits.max_records_per_feed,
        );
        self.feed_with_budget(input, &mut allowance)
    }

    /// Process under stream-local ceilings and a shared three-dimensional work
    /// allowance. The caller retains `input[bytes_consumed..]` on yield.
    pub fn feed_with_budget(
        &mut self,
        input: &[u8],
        allowance: &mut HardenedRecordStreamBudget,
    ) -> DecodeFeed<HardenedRecordStreamBatch<C::Value>> {
        let mut batch = HardenedRecordStreamBatch {
            values: Vec::new(),
            terminal_error: None,
            yielded: false,
            required_frame_bytes: None,
        };
        if self.is_terminal() {
            self.retire();
            batch.terminal_error = Some(HardenedRecordStreamError::Terminated);
            return DecodeFeed::new(batch, 0);
        }

        let budget = input
            .len()
            .min(self.limits.max_feed_bytes)
            .min(allowance.remaining_bytes);
        let record_budget = self
            .limits
            .max_records_per_feed
            .min(allowance.remaining_records);
        let mut consumed = 0;
        let mut attempted = 0;
        let mut frame_bytes = 0;

        while consumed < budget && attempted < record_budget {
            if self.pending.is_empty() && budget - consumed >= PREFIX_BYTES {
                let length = match self
                    .admitted_record_length(&input[consumed..consumed + PREFIX_BYTES])
                {
                    Ok(length) => length,
                    Err(error) => {
                        consumed += PREFIX_BYTES;
                        batch.terminal_error = Some(error);
                        break;
                    }
                };
                let required = length - PREFIX_BYTES - TAG_BYTES;
                if required > allowance.remaining_frame_bytes.saturating_sub(frame_bytes) {
                    batch.required_frame_bytes = Some(required);
                    break;
                }
                if length <= budget - consumed {
                    let start = consumed;
                    consumed += length;
                    attempted += 1;
                    frame_bytes += required;
                    match self
                        .owner
                        .open_bound_typed(&input[start..consumed], &self.codec)
                    {
                        Ok(value) => batch.values.push(value),
                        Err(error) => {
                            batch.terminal_error =
                                Some(HardenedRecordStreamError::Session(error));
                            break;
                        }
                    }
                    continue;
                }
            }

            let target = self.expected.unwrap_or(PREFIX_BYTES);
            if self.expected.is_some() {
                let required = target - PREFIX_BYTES - TAG_BYTES;
                if required > allowance.remaining_frame_bytes.saturating_sub(frame_bytes) {
                    batch.required_frame_bytes = Some(required);
                    break;
                }
            }
            let count = (target - self.pending.len()).min(budget - consumed);
            if let Err(error) = self.reserve_admitted(count) {
                batch.terminal_error = Some(error);
                break;
            }
            self.pending
                .extend_from_slice(&input[consumed..consumed + count]);
            consumed += count;
            if self.pending.len() != target {
                continue;
            }
            if self.expected.is_none() {
                match self.admitted_record_length(&self.pending) {
                    Ok(length) => self.expected = Some(length),
                    Err(error) => {
                        batch.terminal_error = Some(error);
                        break;
                    }
                }
                continue;
            }

            attempted += 1;
            frame_bytes += target - PREFIX_BYTES - TAG_BYTES;
            match self.owner.open_bound_typed(&self.pending, &self.codec) {
                Ok(value) => batch.values.push(value),
                Err(error) => {
                    batch.terminal_error = Some(HardenedRecordStreamError::Session(error));
                    break;
                }
            }
            self.pending.clear();
            self.expected = None;
            self.trim_idle_buffer_to_limit();
        }

        allowance.remaining_bytes -= consumed;
        allowance.remaining_records -= attempted;
        allowance.remaining_frame_bytes -= frame_bytes;
        if batch.terminal_error.is_some() {
            self.retire();
        } else {
            batch.yielded = consumed < input.len();
            self.trim_idle_buffer_to_limit();
        }
        DecodeFeed::new(batch, consumed)
    }

    /// Consuming connection-wide EOF. A partial record is terminal.
    pub fn finish(mut self) -> Result<(), HardenedRecordStreamError> {
        let result = if self.is_terminal() {
            Err(HardenedRecordStreamError::Terminated)
        } else if self.pending.is_empty() {
            Ok(())
        } else {
            Err(HardenedRecordStreamError::UnexpectedEof {
                buffered: self.pending.len(),
                expected: self.expected.unwrap_or(PREFIX_BYTES),
            })
        };
        self.retire();
        result
    }
}

impl<C: BoundPayloadCodec> fmt::Debug for HardenedRecordStream<C> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HardenedRecordStream")
            .field("session_id", &self.owner.session_id())
            .field("limits", &self.limits)
            .field("buffered_bytes", &self.pending.len())
            .field("buffer_capacity_bytes", &self.pending.capacity())
            .field("idle_buffer_limit_bytes", &self.idle_buffer_limit_bytes)
            .field("terminal", &self.is_terminal())
            .finish()
    }
}

#[derive(Debug)]
pub enum HardenedRecordStreamError {
    InvalidLimits,
    InvalidPrefix,
    SessionIdentityMismatch,
    RecordLimit,
    Allocation,
    Terminated,
    UnexpectedEof { buffered: usize, expected: usize },
    Session(HardenedManagedSessionError),
}

impl fmt::Display for HardenedRecordStreamError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLimits => formatter.write_str("invalid hardened record stream limits"),
            Self::InvalidPrefix => formatter.write_str("invalid HPTM V1 prefix"),
            Self::SessionIdentityMismatch => {
                formatter.write_str("HPTM record belongs to a different hardened session")
            }
            Self::RecordLimit => {
                formatter.write_str("authenticated record exceeds admission bounds")
            }
            Self::Allocation => formatter.write_str("hardened stream allocation failed"),
            Self::Terminated => formatter.write_str("hardened record stream is terminal"),
            Self::UnexpectedEof { buffered, expected } => write!(
                formatter,
                "hardened record stream ended after {buffered} of {expected} bytes"
            ),
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for HardenedRecordStreamError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Session(error) => Some(error),
            Self::InvalidLimits
            | Self::InvalidPrefix
            | Self::SessionIdentityMismatch
            | Self::RecordLimit
            | Self::Allocation
            | Self::Terminated
            | Self::UnexpectedEof { .. } => None,
        }
    }
}
