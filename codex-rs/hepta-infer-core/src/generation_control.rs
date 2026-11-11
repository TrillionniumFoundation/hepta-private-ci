//! Opaque generation results belong to the existing control journal owner.
//! These records grant neither model authority nor Cell state/output commit rights.

use std::collections::BTreeMap;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::validate_identity;

pub const MAX_GENERATION_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_GENERATION_RESULT_BYTES: usize = 1024 * 1024;
pub(super) const JOURNAL_PREFIX: &str = "generation-v1|";
// JSON u8 arrays use at most four bytes per element. Metadata reserves also
// cover the longest permitted ID, digest, timestamp and event discriminant.
const METADATA_RESERVE: u64 = 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationBindingV1 {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub manifest_digest: [u8; 32],
    pub request_digest: [u8; 32],
    pub predecessor_digest: [u8; 32],
    pub payload_digest: [u8; 32],
    pub payload_bytes: u32,
    pub result_limit_bytes: u32,
    /// The caller's live monotonic clock domain, identical to Cell admission.
    pub deadline_micros: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationResultV1 {
    pub bytes: Vec<u8>,
    pub digest: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationRecordV1 {
    pub binding: GenerationBindingV1,
    pub admitted_at_micros: u64,
    pub dispatched_at_micros: Option<u64>,
    pub cancel_requested: bool,
    pub aborted_before_dispatch: bool,
    /// None is unresolved, including after cancellation, process loss or reopen.
    /// Opaque terminal bytes retain the original proposal and its unknown costs.
    pub result: Option<GenerationResultV1>,
}

/// A non-cloneable, non-serializable local permission to cross one dispatch
/// boundary. Replaying admission never recreates it. It is not a model grant.
pub struct GenerationDispatchTokenV1 {
    binding: GenerationBindingV1,
    owner: Arc<()>,
}

impl std::fmt::Debug for GenerationDispatchTokenV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("GenerationDispatchTokenV1([LOCAL ONLY])")
    }
}

#[derive(Clone, Debug, Default)]
pub(super) struct GenerationJournal {
    pub(super) records: BTreeMap<String, GenerationRecordV1>,
    owner: Arc<()>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Admit {
        binding: GenerationBindingV1,
        observed_at_micros: u64,
    },
    Dispatch {
        request_id: String,
        observed_at_micros: u64,
    },
    Cancel {
        request_id: String,
    },
    Result {
        request_id: String,
        result: GenerationResultV1,
    },
    AbortBeforeDispatch {
        request_id: String,
        result: GenerationResultV1,
    },
}

impl DurableInferenceControl {
    /// Bind actual payload bytes before issuing the only live dispatch token.
    /// Exact retries are read-only even after the deadline; they return no token.
    /// A fresh observation at/after deadline is retained truthfully. Its token
    /// can only abort: no dispatch time can be both >= admission and < deadline.
    pub fn admit_generation(
        &mut self,
        now_micros: u64,
        binding: GenerationBindingV1,
        payload: &[u8],
    ) -> Result<(GenerationRecordV1, Option<GenerationDispatchTokenV1>), Error> {
        validate_binding(&binding)?;
        if payload.len() != binding.payload_bytes as usize
            || *Digest32::of_bytes(payload).as_array() != binding.payload_digest
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.generation_record(&binding)? {
            return Ok((record.clone(), None));
        }
        if self.records.len() + self.native.records.len() + self.generation.records.len()
            >= self.capacity
        {
            return Err(Error::CapacityExceeded);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity(
                    "generation journal must be owner-only",
                ));
            }
        }
        let record = self.commit_generation(
            Event::Admit {
                binding: binding.clone(),
                observed_at_micros: now_micros,
            },
            /*token*/ None,
        )?;
        let token = GenerationDispatchTokenV1 {
            binding,
            owner: Arc::clone(&self.generation.owner),
        };
        Ok((record, Some(token)))
    }

    /// Recheck cancellation and the live deadline immediately before dispatch.
    /// Preflight failure retains the token for a proven local abort; an attempted
    /// durable append consumes it, including on an uncertain write/sync failure.
    pub fn dispatch_generation(
        &mut self,
        now_micros: u64,
        token: &mut Option<GenerationDispatchTokenV1>,
    ) -> Result<GenerationRecordV1, Error> {
        let request_id = self
            .require_generation_token(token)?
            .binding
            .request_id
            .clone();
        self.commit_generation(
            Event::Dispatch {
                request_id,
                observed_at_micros: now_micros,
            },
            Some(token),
        )
    }

    /// Only this live, unspent token proves no dispatch occurred. The caller
    /// supplies a real bounded proposal, including admission/queue measurements;
    /// the control owner never manufactures zero usage or a terminal disposition.
    pub fn abort_generation(
        &mut self,
        token: &mut Option<GenerationDispatchTokenV1>,
        bytes: Vec<u8>,
    ) -> Result<GenerationRecordV1, Error> {
        let record = self.require_generation_token(token)?;
        let result = opaque_result(&record.binding, bytes)?;
        let request_id = record.binding.request_id.clone();
        self.commit_generation(
            Event::AbortBeforeDispatch { request_id, result },
            Some(token),
        )
    }

    /// Cancellation is durable intent. It cannot release an unknown execution.
    pub fn cancel_generation(
        &mut self,
        binding: &GenerationBindingV1,
    ) -> Result<GenerationRecordV1, Error> {
        let record = self
            .generation_record(binding)?
            .ok_or(Error::RequestNotFound)?;
        if record.cancel_requested || record.result.is_some() {
            return Ok(record.clone());
        }
        self.commit_generation(
            Event::Cancel {
                request_id: binding.request_id.clone(),
            },
            /*token*/ None,
        )
    }

    /// Store exact original terminal bytes before returning them to a Cell owner.
    /// Late results are retained after deadline/cancel, with no payload rewriting.
    pub fn settle_generation(
        &mut self,
        binding: &GenerationBindingV1,
        bytes: Vec<u8>,
    ) -> Result<GenerationRecordV1, Error> {
        let record = self
            .generation_record(binding)?
            .ok_or(Error::RequestNotFound)?;
        let result = opaque_result(binding, bytes)?;
        if let Some(previous) = &record.result {
            return if previous == &result {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        self.commit_generation(
            Event::Result {
                request_id: binding.request_id.clone(),
                result,
            },
            /*token*/ None,
        )
    }

    /// Inspect only the original exact binding. No submission, token or compute
    /// is created when a result is absent, including on a freshly reopened owner.
    pub fn generation_record(
        &self,
        binding: &GenerationBindingV1,
    ) -> Result<Option<&GenerationRecordV1>, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        validate_binding(binding)?;
        if self.records.contains_key(&binding.request_id)
            || self.native.records.contains_key(&binding.request_id)
        {
            return Err(Error::Conflict);
        }
        let record = self.generation.records.get(&binding.request_id);
        if record.is_some_and(|record| &record.binding != binding) {
            return Err(Error::Conflict);
        }
        Ok(record)
    }

    /// The single worker slot must include durable unresolved operations after
    /// reopen, even when the adapter has no corresponding in-memory worker.
    pub fn generation_has_unresolved(&self) -> Result<bool, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        Ok(self
            .generation
            .records
            .values()
            .any(|record| record.result.is_none()))
    }

    fn require_generation_token(
        &self,
        token: &Option<GenerationDispatchTokenV1>,
    ) -> Result<&GenerationRecordV1, Error> {
        let token = token.as_ref().ok_or(Error::InvalidTransition)?;
        if !Arc::ptr_eq(&token.owner, &self.generation.owner) {
            return Err(Error::Conflict);
        }
        let record = self
            .generation_record(&token.binding)?
            .ok_or(Error::RequestNotFound)?;
        if record.dispatched_at_micros.is_some() || record.result.is_some() {
            return Err(Error::InvalidTransition);
        }
        Ok(record)
    }

    fn commit_generation(
        &mut self,
        event: Event,
        token: Option<&mut Option<GenerationDispatchTokenV1>>,
    ) -> Result<GenerationRecordV1, Error> {
        let request_id = event.request_id().to_owned();
        let mut next = self.generation.clone();
        next.apply(event.clone())?;
        let json = serde_json::to_string(&event)
            .map_err(|_| Error::CorruptJournal("generation encode"))?;
        let encoded = format!("{JOURNAL_PREFIX}{json}\n");
        let reserved = next.reserved_bytes()?;
        let next_bytes = self.ensure_append_capacity(&encoded, reserved)?;
        // A new family must not consume the existing native caller's dispatch /
        // terminal headroom. Its original serial-call policy remains unchanged.
        if matches!(event, Event::Admit { .. })
            && self
                .native
                .records
                .values()
                .any(|record| record.state != super::native::NativeReservationState::Released)
            && next_bytes + reserved
                > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        if let Some(token) = token {
            drop(token.take());
        }
        self.append_with_generation_reserve(&encoded, reserved)?;
        self.generation = next;
        self.generation
            .records
            .get(&request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }
}

impl Event {
    fn request_id(&self) -> &str {
        match self {
            Self::Admit { binding, .. } => &binding.request_id,
            Self::Dispatch { request_id, .. }
            | Self::Cancel { request_id }
            | Self::Result { request_id, .. }
            | Self::AbortBeforeDispatch { request_id, .. } => request_id,
        }
    }
}

impl GenerationJournal {
    pub(super) fn reserved_bytes(&self) -> Result<u64, Error> {
        self.records
            .values()
            .filter(|record| record.result.is_none())
            .try_fold(0_u64, |total, record| {
                let metadata = u64::from(record.dispatched_at_micros.is_none())
                    + u64::from(!record.cancel_requested)
                    + 1;
                total
                    .checked_add(
                        u64::from(record.binding.result_limit_bytes) * 4
                            + metadata * METADATA_RESERVE,
                    )
                    .ok_or(Error::ArithmeticOverflow)
            })
    }

    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("generation decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if let Event::Admit {
            binding,
            observed_at_micros,
        } = event
        {
            validate_binding(&binding)?;
            if self.records.contains_key(&binding.request_id) {
                return Err(Error::Conflict);
            }
            self.records.insert(
                binding.request_id.clone(),
                GenerationRecordV1 {
                    binding,
                    admitted_at_micros: observed_at_micros,
                    dispatched_at_micros: None,
                    cancel_requested: false,
                    aborted_before_dispatch: false,
                    result: None,
                },
            );
            return Ok(());
        }
        let record = self
            .records
            .get_mut(event.request_id())
            .ok_or(Error::RequestNotFound)?;
        if record.result.is_some() {
            return Err(Error::InvalidTransition);
        }
        match event {
            Event::Admit { .. } => return Err(Error::InvalidTransition),
            Event::Dispatch {
                observed_at_micros, ..
            } => {
                if record.dispatched_at_micros.is_some() || record.cancel_requested {
                    return Err(Error::InvalidTransition);
                }
                if observed_at_micros < record.admitted_at_micros
                    || observed_at_micros >= record.binding.deadline_micros
                {
                    return Err(Error::InvalidTime);
                }
                record.dispatched_at_micros = Some(observed_at_micros);
            }
            Event::Cancel { .. } => {
                if record.cancel_requested {
                    return Err(Error::InvalidTransition);
                }
                record.cancel_requested = true;
            }
            Event::Result { result, .. } => {
                if record.dispatched_at_micros.is_none() {
                    return Err(Error::InvalidTransition);
                }
                validate_result(record, &result)?;
                record.result = Some(result);
            }
            Event::AbortBeforeDispatch { result, .. } => {
                if record.dispatched_at_micros.is_some() {
                    return Err(Error::InvalidTransition);
                }
                validate_result(record, &result)?;
                record.aborted_before_dispatch = true;
                record.result = Some(result);
            }
        }
        Ok(())
    }
}

fn validate_binding(binding: &GenerationBindingV1) -> Result<(), Error> {
    validate_identity(&binding.request_id, "generation request")?;
    validate_identity(&binding.principal_id, "generation principal")?;
    if binding.worker_generation == 0 {
        return Err(Error::InvalidIdentity("generation worker"));
    }
    if [
        binding.manifest_digest,
        binding.request_digest,
        binding.predecessor_digest,
        binding.payload_digest,
    ]
    .contains(&[0; 32])
    {
        return Err(Error::InvalidDigest("generation binding"));
    }
    if binding.deadline_micros == 0 {
        return Err(Error::InvalidTime);
    }
    if !(1..=MAX_GENERATION_PAYLOAD_BYTES).contains(&(binding.payload_bytes as usize))
        || !(1..=MAX_GENERATION_RESULT_BYTES).contains(&(binding.result_limit_bytes as usize))
    {
        return Err(Error::CapacityExceeded);
    }
    Ok(())
}

fn opaque_result(
    binding: &GenerationBindingV1,
    bytes: Vec<u8>,
) -> Result<GenerationResultV1, Error> {
    if bytes.is_empty() || bytes.len() > binding.result_limit_bytes as usize {
        return Err(Error::CapacityExceeded);
    }
    Ok(GenerationResultV1 {
        digest: *Digest32::of_bytes(&bytes).as_array(),
        bytes,
    })
}

fn validate_result(record: &GenerationRecordV1, result: &GenerationResultV1) -> Result<(), Error> {
    if result.bytes.is_empty() || result.bytes.len() > record.binding.result_limit_bytes as usize {
        return Err(Error::CapacityExceeded);
    }
    if *Digest32::of_bytes(&result.bytes).as_array() != result.digest {
        return Err(Error::InvalidDigest("generation result"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "generation_control_tests.rs"]
mod tests;
