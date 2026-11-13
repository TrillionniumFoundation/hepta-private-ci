//! Fixed two-lane task framing. Wire data never constructs an AutomationStore
//! admission, committed trace or private Circuit task receipt.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_types::Digest32;

use super::Error;

pub(super) const FRAME_LIMIT: usize = 65_536;
pub(super) const REQUEST_LIMIT: u64 = 128;
pub(super) const TIMEOUT: Duration = Duration::from_millis(500);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Operation {
    Build = 1,
    Resolve = 2,
    Execute = 3,
    Decision = 4,
    SavedInput = 5,
    Publish = 6,
    CheckRecord = 7,
    CheckAdmission = 8,
    ReadCompletion = 9,
    Terminal = 10,
    OpenAdmission = 11,
    Clock = 12,
}

impl Operation {
    fn from_byte(value: u8) -> Result<Self, Error> {
        match value {
            1 => Ok(Self::Build),
            2 => Ok(Self::Resolve),
            3 => Ok(Self::Execute),
            4 => Ok(Self::Decision),
            5 => Ok(Self::SavedInput),
            6 => Ok(Self::Publish),
            7 => Ok(Self::CheckRecord),
            8 => Ok(Self::CheckAdmission),
            9 => Ok(Self::ReadCompletion),
            10 => Ok(Self::Terminal),
            11 => Ok(Self::OpenAdmission),
            12 => Ok(Self::Clock),
            _ => Err(Error::InvalidBinding),
        }
    }

    fn task_lane(self) -> bool {
        matches!(self, Self::Build | Self::Resolve | Self::Execute |
            Self::Decision | Self::SavedInput | Self::Publish | Self::Clock)
    }
}

/// Both channels spend this one counter and absolute end in each process.
/// Cloning the budget cannot allocate requests or restart an operation clock.
pub(super) struct Budget {
    used: AtomicU64,
    end: Instant,
}

impl Budget {
    pub(super) fn new(end: Instant) -> Result<Arc<Self>, Error> {
        if Instant::now() >= end {
            return Err(Error::DeadlineExceeded);
        }
        Ok(Arc::new(Self { used: AtomicU64::new(0), end }))
    }

    pub(super) fn before(&self, deadline: Instant) -> Result<(), Error> {
        if Instant::now() >= deadline.min(self.end) {
            return Err(Error::DeadlineExceeded);
        }
        Ok(())
    }

    fn begin(&self) -> Result<Instant, Error> {
        let deadline = (Instant::now() + TIMEOUT).min(self.end);
        self.before(deadline)?;
        self.used.fetch_update(Ordering::AcqRel, Ordering::Acquire, |used| {
            (used < REQUEST_LIMIT).then(|| used + 1)
        }).map_err(|_| Error::Unavailable)?;
        Ok(deadline)
    }
}

pub(super) struct Frame {
    pub(super) operation: Operation,
    pub(super) loan: u64,
    pub(super) body: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum LanePurpose { Task, Loan }

/// Created only by the fixed daemon/Root factories from two actual peer-pinned
/// channels. A failed exchange permanently removes this lane's channel.
pub(super) struct Lane {
    channel: Option<HostAuthorityPeerChannel>,
    binding: Digest32,
    session: [u8; 16],
    sequence: u64,
    purpose: LanePurpose,
    budget: Arc<Budget>,
}

impl Lane {
    pub(super) fn new(
        channel: HostAuthorityPeerChannel,
        binding: Digest32,
        session: [u8; 16],
        purpose: LanePurpose,
        budget: Arc<Budget>,
    ) -> Result<Self, Error> {
        if binding.is_zero() || session == [0; 16] {
            return Err(Error::InvalidBinding);
        }
        channel.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        Ok(Self { channel: Some(channel), binding, session, sequence: 1,
            purpose, budget })
    }

    pub(super) fn call(&mut self, frame: Frame) -> Result<Vec<u8>, Error> {
        let mut channel = self.channel.take().ok_or(Error::Unavailable)?;
        let deadline = self.budget.begin()?;
        let request = self.encode(&frame)?;
        self.budget.before(deadline)?;
        let response = channel.request(&request).map_err(|_| Error::CommitUncertain)?;
        self.budget.before(deadline)?;
        let received = self.decode(&response)?;
        if received.operation != frame.operation || received.loan != frame.loan {
            return Err(Error::InvalidBinding);
        }
        channel.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        self.budget.before(deadline)?;
        self.sequence = self.sequence.checked_add(1).ok_or(Error::Unavailable)?;
        self.channel = Some(channel);
        Ok(received.body)
    }

    pub(super) fn serve_one(
        &mut self,
        handle: impl FnOnce(Frame) -> Result<Vec<u8>, Error>,
    ) -> Result<bool, Error> {
        let mut channel = self.channel.take().ok_or(Error::Unavailable)?;
        let mut observed_deadline = None;
        let result = channel.exchange(|bytes| {
            let deadline = self.budget.begin().map_err(transport_error)?;
            observed_deadline = Some(deadline);
            let frame = self.decode(bytes).map_err(transport_error)?;
            let operation = frame.operation;
            let loan = frame.loan;
            self.budget.before(deadline).map_err(transport_error)?;
            let body = handle(frame).map_err(transport_error)?;
            self.budget.before(deadline).map_err(transport_error)?;
            let encoded = self.encode(&Frame { operation, loan, body })
                .map_err(transport_error)?;
            self.budget.before(deadline).map_err(transport_error)?;
            Ok(encoded)
        }).map_err(|_| Error::CommitUncertain)?;
        if result {
            // The original write can itself consume the remaining time. A
            // delivered late response is Unknown and never restores this lane.
            self.budget.before(observed_deadline.ok_or(Error::Unavailable)?)?;
            channel.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
            self.budget.before(observed_deadline.ok_or(Error::Unavailable)?)?;
            self.sequence = self.sequence.checked_add(1).ok_or(Error::Unavailable)?;
            self.channel = Some(channel);
        }
        Ok(result)
    }

    fn encode(&self, frame: &Frame) -> Result<Vec<u8>, Error> {
        if frame.operation.task_lane() != (self.purpose == LanePurpose::Task) || frame.loan == 0 {
            return Err(Error::InvalidBinding);
        }
        let mut bytes = b"HCRTLOA1".to_vec();
        bytes.extend_from_slice(self.binding.as_array());
        bytes.extend_from_slice(&self.session);
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&frame.loan.to_be_bytes());
        bytes.push(frame.operation as u8);
        bytes.extend_from_slice(&frame.body);
        bounded(&bytes)?;
        Ok(bytes)
    }

    fn decode(&self, bytes: &[u8]) -> Result<Frame, Error> {
        let mut reader = Reader::new(bytes, b"HCRTLOA1")?;
        if reader.take::<32>()? != *self.binding.as_array()
            || reader.take::<16>()? != self.session
            || reader.u64()? != self.sequence
        {
            return Err(Error::InvalidBinding);
        }
        let loan = reader.u64()?;
        let operation = Operation::from_byte(reader.take::<1>()?[0])?;
        if loan == 0 || operation.task_lane() != (self.purpose == LanePurpose::Task) {
            return Err(Error::InvalidBinding);
        }
        Ok(Frame { operation, loan, body: reader.remaining().to_vec() })
    }
}

pub(super) fn bounded(bytes: &[u8]) -> Result<(), Error> {
    if bytes.is_empty() || bytes.len() > FRAME_LIMIT {
        return Err(Error::InvalidBinding);
    }
    Ok(())
}

pub(super) fn blob(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), Error> {
    let length = u32::try_from(value.len()).map_err(|_| Error::InvalidBinding)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
    bounded(bytes)
}

pub(super) struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    pub(super) fn new(bytes: &'a [u8], domain: &[u8]) -> Result<Self, Error> {
        bounded(bytes)?;
        Ok(Self(bytes.strip_prefix(domain).ok_or(Error::InvalidBinding)?))
    }
    pub(super) fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let (value, rest) = self.0.split_at_checked(N).ok_or(Error::InvalidBinding)?;
        self.0 = rest;
        value.try_into().map_err(|_| Error::InvalidBinding)
    }
    pub(super) fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(self.take()?))
    }
    pub(super) fn blob(&mut self) -> Result<&'a [u8], Error> {
        let size = u32::from_be_bytes(self.take()?) as usize;
        let (value, rest) = self.0.split_at_checked(size).ok_or(Error::InvalidBinding)?;
        self.0 = rest;
        Ok(value)
    }
    fn remaining(self) -> &'a [u8] { self.0 }
    pub(super) fn end(self) -> Result<(), Error> {
        if !self.0.is_empty() { return Err(Error::InvalidBinding); }
        Ok(())
    }
}

fn transport_error(_: Error) -> HostIssuerTransportError {
    HostIssuerTransportError::Unavailable
}
