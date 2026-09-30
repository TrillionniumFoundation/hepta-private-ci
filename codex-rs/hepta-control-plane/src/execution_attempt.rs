use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const ATTEMPT_MAGIC: &[u8; 8] = b"HCPEXA01";
const MAX_ATTEMPT_ID_BYTES: usize = 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionAttemptPhaseV1 {
    Prepared,
    GrantRequested,
    Authorized,
    Dispatched,
    TimedOut,
    Indeterminate,
    Succeeded,
    Failed,
    Revoked,
}

impl ExecutionAttemptPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::GrantRequested => 1,
            Self::Authorized => 2,
            Self::Dispatched => 3,
            Self::TimedOut => 4,
            Self::Indeterminate => 5,
            Self::Succeeded => 6,
            Self::Failed => 7,
            Self::Revoked => 8,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, ExecutionAttemptErrorV1> {
        match tag {
            0 => Ok(Self::Prepared),
            1 => Ok(Self::GrantRequested),
            2 => Ok(Self::Authorized),
            3 => Ok(Self::Dispatched),
            4 => Ok(Self::TimedOut),
            5 => Ok(Self::Indeterminate),
            6 => Ok(Self::Succeeded),
            7 => Ok(Self::Failed),
            8 => Ok(Self::Revoked),
            _ => Err(ExecutionAttemptErrorV1::UnknownPhase(tag)),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionTerminalOutcomeV1 {
    Succeeded,
    Failed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionRetryDispositionV1 {
    NotReady,
    NewAttemptRequired,
    ForbiddenUnknownOutcome,
    TerminalSuccess,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionAttemptV1 {
    attempt_id: StableId,
    plan_receipt_digest: Digest32,
    grant_request_set_digest: Option<Digest32>,
    authority_decision_digest: Option<Digest32>,
    dispatch_digest: Option<Digest32>,
    terminal_observation_digest: Option<Digest32>,
    uncertainty_digest: Option<Digest32>,
    phase: ExecutionAttemptPhaseV1,
    created_at_micros: u64,
    deadline_micros: u64,
    updated_at_micros: u64,
    transition_sequence: u64,
    late_terminal_observation: bool,
    state_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionAttemptErrorV1 {
    EmptyDigest(&'static str),
    InvalidDeadline,
    Expired,
    TimeoutTooEarly,
    InvalidTransition,
    LateResultWithoutDispatch,
    Arithmetic,
    CorruptState,
    CorruptEncoding,
    UnknownPhase(u8),
}

impl std::fmt::Display for ExecutionAttemptErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ExecutionAttemptErrorV1 {}

impl ExecutionAttemptV1 {
    pub fn new(
        attempt_id: StableId,
        plan_receipt_digest: Digest32,
        created_at_micros: u64,
        deadline_micros: u64,
    ) -> Result<Self, ExecutionAttemptErrorV1> {
        require_digest(plan_receipt_digest, "plan receipt")?;
        if deadline_micros <= created_at_micros {
            return Err(ExecutionAttemptErrorV1::InvalidDeadline);
        }
        let mut attempt = Self {
            attempt_id,
            plan_receipt_digest,
            grant_request_set_digest: None,
            authority_decision_digest: None,
            dispatch_digest: None,
            terminal_observation_digest: None,
            uncertainty_digest: None,
            phase: ExecutionAttemptPhaseV1::Prepared,
            created_at_micros,
            deadline_micros,
            updated_at_micros: created_at_micros,
            transition_sequence: 0,
            late_terminal_observation: false,
            state_digest: Digest32::ZERO,
        };
        attempt.state_digest = digest_attempt(&attempt);
        Ok(attempt)
    }

    #[must_use]
    pub fn attempt_id(&self) -> &StableId {
        &self.attempt_id
    }

    #[must_use]
    pub const fn plan_receipt_digest(&self) -> Digest32 {
        self.plan_receipt_digest
    }

    #[must_use]
    pub const fn grant_request_set_digest(&self) -> Option<Digest32> {
        self.grant_request_set_digest
    }

    #[must_use]
    pub const fn authority_decision_digest(&self) -> Option<Digest32> {
        self.authority_decision_digest
    }

    #[must_use]
    pub const fn dispatch_digest(&self) -> Option<Digest32> {
        self.dispatch_digest
    }

    #[must_use]
    pub const fn terminal_observation_digest(&self) -> Option<Digest32> {
        self.terminal_observation_digest
    }

    #[must_use]
    pub const fn uncertainty_digest(&self) -> Option<Digest32> {
        self.uncertainty_digest
    }

    #[must_use]
    pub const fn phase(&self) -> ExecutionAttemptPhaseV1 {
        self.phase
    }

    #[must_use]
    pub const fn created_at_micros(&self) -> u64 {
        self.created_at_micros
    }

    #[must_use]
    pub const fn deadline_micros(&self) -> u64 {
        self.deadline_micros
    }

    #[must_use]
    pub const fn updated_at_micros(&self) -> u64 {
        self.updated_at_micros
    }

    #[must_use]
    pub const fn transition_sequence(&self) -> u64 {
        self.transition_sequence
    }

    #[must_use]
    pub const fn late_terminal_observation(&self) -> bool {
        self.late_terminal_observation
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    pub fn verify(&self) -> Result<(), ExecutionAttemptErrorV1> {
        self.verify_invariants()?;
        if self.state_digest != digest_attempt(self) {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        Ok(())
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        let id = self.attempt_id.as_str().as_bytes();
        let mut bytes = Vec::with_capacity(8 + 2 + id.len() + 32 * 7 + 64);
        bytes.extend_from_slice(ATTEMPT_MAGIC);
        bytes.extend_from_slice(&u16::try_from(id.len()).unwrap_or(u16::MAX).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(self.plan_receipt_digest.as_array());
        push_optional_digest(&mut bytes, self.grant_request_set_digest);
        push_optional_digest(&mut bytes, self.authority_decision_digest);
        push_optional_digest(&mut bytes, self.dispatch_digest);
        push_optional_digest(&mut bytes, self.terminal_observation_digest);
        push_optional_digest(&mut bytes, self.uncertainty_digest);
        bytes.push(self.phase.tag());
        bytes.extend_from_slice(&self.created_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_micros.to_be_bytes());
        bytes.extend_from_slice(&self.updated_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.transition_sequence.to_be_bytes());
        bytes.push(u8::from(self.late_terminal_observation));
        bytes.extend_from_slice(self.state_digest.as_array());
        bytes
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, ExecutionAttemptErrorV1> {
        if bytes.len() < 8 + 2 + 32 * 7 + 1 + 8 * 4 + 1 {
            return Err(ExecutionAttemptErrorV1::CorruptEncoding);
        }
        if &bytes[..8] != ATTEMPT_MAGIC {
            return Err(ExecutionAttemptErrorV1::CorruptEncoding);
        }
        let mut offset = 8;
        let id_len = usize::from(read_u16(bytes, &mut offset)?);
        if id_len == 0 || id_len > MAX_ATTEMPT_ID_BYTES {
            return Err(ExecutionAttemptErrorV1::CorruptEncoding);
        }
        let id_end = offset
            .checked_add(id_len)
            .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
        let id = std::str::from_utf8(
            bytes
                .get(offset..id_end)
                .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?,
        )
        .map_err(|_| ExecutionAttemptErrorV1::CorruptEncoding)?;
        let attempt_id =
            StableId::new(id).map_err(|_| ExecutionAttemptErrorV1::CorruptEncoding)?;
        offset = id_end;
        let plan_receipt_digest = read_digest(bytes, &mut offset)?;
        let grant_request_set_digest = read_optional_digest(bytes, &mut offset)?;
        let authority_decision_digest = read_optional_digest(bytes, &mut offset)?;
        let dispatch_digest = read_optional_digest(bytes, &mut offset)?;
        let terminal_observation_digest = read_optional_digest(bytes, &mut offset)?;
        let uncertainty_digest = read_optional_digest(bytes, &mut offset)?;
        let phase = ExecutionAttemptPhaseV1::from_tag(read_u8(bytes, &mut offset)?)?;
        let created_at_micros = read_u64(bytes, &mut offset)?;
        let deadline_micros = read_u64(bytes, &mut offset)?;
        let updated_at_micros = read_u64(bytes, &mut offset)?;
        let transition_sequence = read_u64(bytes, &mut offset)?;
        let late_terminal_observation = match read_u8(bytes, &mut offset)? {
            0 => false,
            1 => true,
            _ => return Err(ExecutionAttemptErrorV1::CorruptEncoding),
        };
        let state_digest = read_digest(bytes, &mut offset)?;
        if offset != bytes.len() {
            return Err(ExecutionAttemptErrorV1::CorruptEncoding);
        }
        let attempt = Self {
            attempt_id,
            plan_receipt_digest,
            grant_request_set_digest,
            authority_decision_digest,
            dispatch_digest,
            terminal_observation_digest,
            uncertainty_digest,
            phase,
            created_at_micros,
            deadline_micros,
            updated_at_micros,
            transition_sequence,
            late_terminal_observation,
            state_digest,
        };
        attempt.verify()?;
        Ok(attempt)
    }

    pub fn record_grant_request(
        &mut self,
        request_set_digest: Digest32,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(request_set_digest, "grant request set")?;
        self.require_phase(ExecutionAttemptPhaseV1::Prepared)?;
        self.require_before_deadline(now_micros)?;
        self.grant_request_set_digest = Some(request_set_digest);
        self.transition(ExecutionAttemptPhaseV1::GrantRequested, now_micros)
    }

    pub fn record_authorization(
        &mut self,
        authority_decision_digest: Digest32,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(authority_decision_digest, "authority decision")?;
        self.require_phase(ExecutionAttemptPhaseV1::GrantRequested)?;
        self.require_before_deadline(now_micros)?;
        self.authority_decision_digest = Some(authority_decision_digest);
        self.transition(ExecutionAttemptPhaseV1::Authorized, now_micros)
    }

    pub fn record_dispatch(
        &mut self,
        dispatch_digest: Digest32,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(dispatch_digest, "dispatch")?;
        self.require_phase(ExecutionAttemptPhaseV1::Authorized)?;
        self.require_before_deadline(now_micros)?;
        self.dispatch_digest = Some(dispatch_digest);
        self.transition(ExecutionAttemptPhaseV1::Dispatched, now_micros)
    }

    pub fn mark_timeout(
        &mut self,
        uncertainty_digest: Option<Digest32>,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        if now_micros < self.deadline_micros {
            return Err(ExecutionAttemptErrorV1::TimeoutTooEarly);
        }
        match self.phase {
            ExecutionAttemptPhaseV1::Prepared | ExecutionAttemptPhaseV1::GrantRequested => {
                self.transition(ExecutionAttemptPhaseV1::TimedOut, now_micros)
            }
            ExecutionAttemptPhaseV1::Authorized | ExecutionAttemptPhaseV1::Dispatched => {
                let uncertainty = uncertainty_digest.ok_or(
                    ExecutionAttemptErrorV1::EmptyDigest("timeout uncertainty"),
                )?;
                require_digest(uncertainty, "timeout uncertainty")?;
                self.uncertainty_digest = Some(uncertainty);
                self.transition(ExecutionAttemptPhaseV1::Indeterminate, now_micros)
            }
            _ => Err(ExecutionAttemptErrorV1::InvalidTransition),
        }
    }

    pub fn mark_indeterminate(
        &mut self,
        uncertainty_digest: Digest32,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(uncertainty_digest, "indeterminate evidence")?;
        if !matches!(
            self.phase,
            ExecutionAttemptPhaseV1::Authorized | ExecutionAttemptPhaseV1::Dispatched
        ) {
            return Err(ExecutionAttemptErrorV1::InvalidTransition);
        }
        self.uncertainty_digest = Some(uncertainty_digest);
        self.transition(ExecutionAttemptPhaseV1::Indeterminate, now_micros)
    }

    pub fn record_terminal_observation(
        &mut self,
        observation_digest: Digest32,
        outcome: ExecutionTerminalOutcomeV1,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(observation_digest, "terminal observation")?;
        if self.dispatch_digest.is_none() {
            return Err(ExecutionAttemptErrorV1::LateResultWithoutDispatch);
        }
        if !matches!(
            self.phase,
            ExecutionAttemptPhaseV1::Dispatched | ExecutionAttemptPhaseV1::Indeterminate
        ) {
            return Err(ExecutionAttemptErrorV1::InvalidTransition);
        }
        self.terminal_observation_digest = Some(observation_digest);
        self.late_terminal_observation = now_micros >= self.deadline_micros
            || self.phase == ExecutionAttemptPhaseV1::Indeterminate;
        let phase = match outcome {
            ExecutionTerminalOutcomeV1::Succeeded => ExecutionAttemptPhaseV1::Succeeded,
            ExecutionTerminalOutcomeV1::Failed => ExecutionAttemptPhaseV1::Failed,
        };
        self.transition(phase, now_micros)
    }

    pub fn revoke(
        &mut self,
        uncertainty_digest: Option<Digest32>,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        match self.phase {
            ExecutionAttemptPhaseV1::Prepared | ExecutionAttemptPhaseV1::GrantRequested => {
                self.transition(ExecutionAttemptPhaseV1::Revoked, now_micros)
            }
            ExecutionAttemptPhaseV1::Authorized | ExecutionAttemptPhaseV1::Dispatched => {
                let uncertainty = uncertainty_digest
                    .ok_or(ExecutionAttemptErrorV1::EmptyDigest("revocation uncertainty"))?;
                require_digest(uncertainty, "revocation uncertainty")?;
                self.uncertainty_digest = Some(uncertainty);
                self.transition(ExecutionAttemptPhaseV1::Indeterminate, now_micros)
            }
            _ => Err(ExecutionAttemptErrorV1::InvalidTransition),
        }
    }

    #[must_use]
    pub const fn retry_disposition(&self) -> ExecutionRetryDispositionV1 {
        match self.phase {
            ExecutionAttemptPhaseV1::TimedOut
            | ExecutionAttemptPhaseV1::Failed
            | ExecutionAttemptPhaseV1::Revoked => ExecutionRetryDispositionV1::NewAttemptRequired,
            ExecutionAttemptPhaseV1::Authorized
            | ExecutionAttemptPhaseV1::Dispatched
            | ExecutionAttemptPhaseV1::Indeterminate => {
                ExecutionRetryDispositionV1::ForbiddenUnknownOutcome
            }
            ExecutionAttemptPhaseV1::Succeeded => ExecutionRetryDispositionV1::TerminalSuccess,
            ExecutionAttemptPhaseV1::Prepared | ExecutionAttemptPhaseV1::GrantRequested => {
                ExecutionRetryDispositionV1::NotReady
            }
        }
    }

    fn verify_invariants(&self) -> Result<(), ExecutionAttemptErrorV1> {
        require_digest(self.plan_receipt_digest, "plan receipt")?;
        if self.deadline_micros <= self.created_at_micros
            || self.updated_at_micros < self.created_at_micros
        {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if self.authority_decision_digest.is_some() && self.grant_request_set_digest.is_none() {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if self.dispatch_digest.is_some() && self.authority_decision_digest.is_none() {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if self.terminal_observation_digest.is_some() && self.dispatch_digest.is_none() {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if matches!(self.phase, ExecutionAttemptPhaseV1::Succeeded | ExecutionAttemptPhaseV1::Failed)
            && self.terminal_observation_digest.is_none()
        {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if self.phase == ExecutionAttemptPhaseV1::Indeterminate
            && (self.authority_decision_digest.is_none() || self.uncertainty_digest.is_none())
        {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        if self.late_terminal_observation && self.terminal_observation_digest.is_none() {
            return Err(ExecutionAttemptErrorV1::CorruptState);
        }
        Ok(())
    }

    fn require_phase(
        &self,
        expected: ExecutionAttemptPhaseV1,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        if self.phase == expected {
            Ok(())
        } else {
            Err(ExecutionAttemptErrorV1::InvalidTransition)
        }
    }

    fn require_before_deadline(&self, now_micros: u64) -> Result<(), ExecutionAttemptErrorV1> {
        if now_micros >= self.deadline_micros {
            Err(ExecutionAttemptErrorV1::Expired)
        } else {
            Ok(())
        }
    }

    fn transition(
        &mut self,
        next: ExecutionAttemptPhaseV1,
        now_micros: u64,
    ) -> Result<(), ExecutionAttemptErrorV1> {
        if now_micros < self.updated_at_micros {
            return Err(ExecutionAttemptErrorV1::InvalidTransition);
        }
        self.transition_sequence = self
            .transition_sequence
            .checked_add(1)
            .ok_or(ExecutionAttemptErrorV1::Arithmetic)?;
        self.phase = next;
        self.updated_at_micros = now_micros;
        self.state_digest = digest_attempt(self);
        Ok(())
    }
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), ExecutionAttemptErrorV1> {
    if digest.is_zero() {
        Err(ExecutionAttemptErrorV1::EmptyDigest(field))
    } else {
        Ok(())
    }
}

fn digest_attempt(attempt: &ExecutionAttemptV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-attempt.v1".to_vec();
    push_text(&mut bytes, attempt.attempt_id.as_str());
    bytes.extend_from_slice(attempt.plan_receipt_digest.as_array());
    push_optional_digest(&mut bytes, attempt.grant_request_set_digest);
    push_optional_digest(&mut bytes, attempt.authority_decision_digest);
    push_optional_digest(&mut bytes, attempt.dispatch_digest);
    push_optional_digest(&mut bytes, attempt.terminal_observation_digest);
    push_optional_digest(&mut bytes, attempt.uncertainty_digest);
    bytes.push(attempt.phase.tag());
    bytes.extend_from_slice(&attempt.created_at_micros.to_be_bytes());
    bytes.extend_from_slice(&attempt.deadline_micros.to_be_bytes());
    bytes.extend_from_slice(&attempt.updated_at_micros.to_be_bytes());
    bytes.extend_from_slice(&attempt.transition_sequence.to_be_bytes());
    bytes.push(u8::from(attempt.late_terminal_observation));
    Digest32::of_bytes(&bytes)
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => {
            bytes.push(0);
            bytes.extend_from_slice(Digest32::ZERO.as_array());
        }
    }
}

fn read_optional_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Option<Digest32>, ExecutionAttemptErrorV1> {
    let tag = read_u8(bytes, offset)?;
    let digest = read_digest(bytes, offset)?;
    match tag {
        0 if digest.is_zero() => Ok(None),
        1 if !digest.is_zero() => Ok(Some(digest)),
        _ => Err(ExecutionAttemptErrorV1::CorruptEncoding),
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, ExecutionAttemptErrorV1> {
    let value = *bytes
        .get(*offset)
        .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
    *offset = (*offset)
        .checked_add(1)
        .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
    Ok(value)
}

fn read_u16(bytes: &[u8], offset: &mut usize) -> Result<u16, ExecutionAttemptErrorV1> {
    let end = (*offset)
        .checked_add(2)
        .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
    let value = u16::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?
            .try_into()
            .map_err(|_| ExecutionAttemptErrorV1::CorruptEncoding)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, ExecutionAttemptErrorV1> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?
            .try_into()
            .map_err(|_| ExecutionAttemptErrorV1::CorruptEncoding)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, ExecutionAttemptErrorV1> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?;
    let digest = Digest32::from_array(
        bytes
            .get(*offset..end)
            .ok_or(ExecutionAttemptErrorV1::CorruptEncoding)?
            .try_into()
            .map_err(|_| ExecutionAttemptErrorV1::CorruptEncoding)?,
    );
    *offset = end;
    Ok(digest)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn exact_attempt_reconciles_a_late_terminal_observation_without_retry() {
        let mut attempt = ExecutionAttemptV1::new(id("attempt-1"), digest("plan"), 10, 20)
            .expect("attempt");
        attempt
            .record_grant_request(digest("requests"), 11)
            .expect("grant request");
        attempt
            .record_authorization(digest("authority"), 12)
            .expect("authorization");
        attempt
            .record_dispatch(digest("dispatch"), 13)
            .expect("dispatch");
        attempt
            .mark_timeout(Some(digest("unknown")), 20)
            .expect("indeterminate timeout");
        assert_eq!(
            attempt.retry_disposition(),
            ExecutionRetryDispositionV1::ForbiddenUnknownOutcome
        );
        attempt
            .record_terminal_observation(
                digest("terminal"),
                ExecutionTerminalOutcomeV1::Succeeded,
                25,
            )
            .expect("late terminal reconciliation");
        assert_eq!(attempt.phase(), ExecutionAttemptPhaseV1::Succeeded);
        assert!(attempt.late_terminal_observation());
        assert_eq!(
            attempt.retry_disposition(),
            ExecutionRetryDispositionV1::TerminalSuccess
        );
        assert_eq!(attempt.verify(), Ok(()));
    }

    #[test]
    fn pre_dispatch_timeout_requires_a_new_attempt_identity() {
        let mut attempt = ExecutionAttemptV1::new(id("attempt-1"), digest("plan"), 10, 20)
            .expect("attempt");
        attempt
            .record_grant_request(digest("requests"), 11)
            .expect("grant request");
        attempt.mark_timeout(None, 20).expect("timeout");
        assert_eq!(attempt.phase(), ExecutionAttemptPhaseV1::TimedOut);
        assert_eq!(
            attempt.retry_disposition(),
            ExecutionRetryDispositionV1::NewAttemptRequired
        );
        assert_eq!(
            attempt.record_terminal_observation(
                digest("terminal"),
                ExecutionTerminalOutcomeV1::Succeeded,
                21,
            ),
            Err(ExecutionAttemptErrorV1::LateResultWithoutDispatch)
        );
    }

    #[test]
    fn revocation_after_authorization_is_indeterminate_not_success() {
        let mut attempt = ExecutionAttemptV1::new(id("attempt-1"), digest("plan"), 10, 20)
            .expect("attempt");
        attempt
            .record_grant_request(digest("requests"), 11)
            .expect("grant request");
        attempt
            .record_authorization(digest("authority"), 12)
            .expect("authorization");
        attempt
            .revoke(Some(digest("cancel-race")), 13)
            .expect("revoke");
        assert_eq!(attempt.phase(), ExecutionAttemptPhaseV1::Indeterminate);
        assert_eq!(
            attempt.retry_disposition(),
            ExecutionRetryDispositionV1::ForbiddenUnknownOutcome
        );
    }

    #[test]
    fn attempt_codec_round_trips_and_rejects_tampering() {
        let mut attempt = ExecutionAttemptV1::new(id("attempt-1"), digest("plan"), 10, 20)
            .expect("attempt");
        attempt
            .record_grant_request(digest("requests"), 11)
            .expect("grant request");
        let bytes = attempt.export_bytes();
        assert_eq!(ExecutionAttemptV1::reopen(&bytes), Ok(attempt.clone()));

        let mut tampered = bytes;
        let last = tampered.len() - 1;
        tampered[last] ^= 1;
        assert_eq!(
            ExecutionAttemptV1::reopen(&tampered),
            Err(ExecutionAttemptErrorV1::CorruptState)
        );
    }
}
