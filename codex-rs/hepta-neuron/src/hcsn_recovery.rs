//! Complete research-state custody alongside unchanged V1 clock metadata.
//! Restoring bytes grants no live-model mutation or topology activation authority.

use crate::HcsnClockCheckpointV1;
use crate::HcsnClockIdentityV1;
use crate::HcsnTimeProfileV1;
use codex_hepta_types::Digest32;

const MAGIC: &[u8] = b"hepta.hcsn.complete-research-state.v2\0";
const MAX_BYTES: usize = 64 * 1_024 * 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HcsnRecoveryBindingV2 {
    pub request_digest: Digest32,
    pub base_checkpoint_digest: Digest32,
    pub code_digest: Digest32,
    pub dataset_digest: Digest32,
    pub runtime_digest: Digest32,
    /// Exact full-state schema: backend tensors, density/content, pending events,
    /// renewal clocks and learning state. Tensor shapes alone are insufficient.
    pub backend_state_schema_digest: Digest32,
    pub parameter_mask_digest: Digest32,
    pub learning_rule_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HcsnOptimizerStateV2 {
    NotUsed,
    Snapshot(Vec<u8>),
}

/// Each byte section has its own schema in the admitted backend codec. Empty
/// sections are forbidden; stateless controllers/RNG/history need explicit encodings.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnResearchStateV2 {
    pub binding: HcsnRecoveryBindingV2,
    pub parameters: Vec<u8>,
    pub backend: Vec<u8>,
    pub optimizer: HcsnOptimizerStateV2,
    pub controller: Vec<u8>,
    pub rng: Vec<u8>,
    pub cost_ledger: Vec<u8>,
    pub history: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnRecoveryErrorV2 {
    Binding,
    Format,
    TooLarge,
    Clock,
    StateMismatch,
    Backend,
}

/// Implementations must validate and reconstruct every backend and learning-state
/// field, including queue/renewal law, optimizer/controller, RNG, costs and history.
/// The verified clock and profile must agree with backend times, pending events
/// and renewal ages. Hash agreement alone cannot establish that consistency.
/// Returning only parameter tensors is not a valid implementation of this port.
pub trait HcsnResearchStateCodecV2 {
    type State;
    fn schema_digest(&self) -> Digest32;
    fn restore_complete_state(
        &self,
        snapshot: &HcsnResearchStateV2,
        clock: &HcsnClockCheckpointV1,
        profile: &HcsnTimeProfileV1,
    ) -> Result<Self::State, HcsnRecoveryErrorV2>;
}

/// Independently retained admitted context; never derive it from untrusted bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnRecoveryContextV2 {
    pub profile: HcsnTimeProfileV1,
    pub identity: HcsnClockIdentityV1,
    pub binding: HcsnRecoveryBindingV2,
    pub checkpoint_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnRestoredResearchStateV2<T> {
    pub clock: HcsnClockCheckpointV1,
    pub state: T,
}

impl HcsnRecoveryBindingV2 {
    fn digests(self) -> [Digest32; 8] {
        [
            self.request_digest,
            self.base_checkpoint_digest,
            self.code_digest,
            self.dataset_digest,
            self.runtime_digest,
            self.backend_state_schema_digest,
            self.parameter_mask_digest,
            self.learning_rule_digest,
        ]
    }
}

impl HcsnResearchStateV2 {
    /// The V1 clock's `state_digest` must hash these exact bytes. Its model digest
    /// independently hashes `parameters`, so weights cannot be substituted.
    pub fn encode(&self) -> Result<Vec<u8>, HcsnRecoveryErrorV2> {
        if self.binding.digests().into_iter().any(Digest32::is_zero) {
            return Err(HcsnRecoveryErrorV2::Binding);
        }
        let (optimizer_tag, optimizer) = match &self.optimizer {
            HcsnOptimizerStateV2::NotUsed => (0, &[][..]),
            HcsnOptimizerStateV2::Snapshot(bytes) if !bytes.is_empty() => (1, bytes.as_slice()),
            HcsnOptimizerStateV2::Snapshot(_) => return Err(HcsnRecoveryErrorV2::Format),
        };
        let sections = [
            &self.parameters,
            &self.backend,
            &self.controller,
            &self.rng,
            &self.cost_ledger,
            &self.history,
        ];
        let mut size = MAGIC.len() + 8 * 32 + 1 + 7 * 8;
        for section in sections {
            if section.is_empty() {
                return Err(HcsnRecoveryErrorV2::Format);
            }
            size = size
                .checked_add(section.len())
                .ok_or(HcsnRecoveryErrorV2::TooLarge)?;
        }
        size = size
            .checked_add(optimizer.len())
            .ok_or(HcsnRecoveryErrorV2::TooLarge)?;
        if size > MAX_BYTES {
            return Err(HcsnRecoveryErrorV2::TooLarge);
        }
        let mut bytes = Vec::with_capacity(size);
        bytes.extend_from_slice(MAGIC);
        for digest in self.binding.digests() {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(optimizer_tag);
        for section in [
            self.parameters.as_slice(),
            self.backend.as_slice(),
            optimizer,
            self.controller.as_slice(),
            self.rng.as_slice(),
            self.cost_ledger.as_slice(),
            self.history.as_slice(),
        ] {
            bytes.extend_from_slice(&(section.len() as u64).to_be_bytes());
            bytes.extend_from_slice(section);
        }
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, HcsnRecoveryErrorV2> {
        if bytes.len() > MAX_BYTES {
            return Err(HcsnRecoveryErrorV2::TooLarge);
        }
        let mut remaining = bytes
            .strip_prefix(MAGIC)
            .ok_or(HcsnRecoveryErrorV2::Format)?;
        let mut digests = [Digest32::ZERO; 8];
        for digest in &mut digests {
            *digest = Digest32::from_array(
                take(&mut remaining, 32)?
                    .try_into()
                    .map_err(|_| HcsnRecoveryErrorV2::Format)?,
            );
        }
        let optimizer_tag = take(&mut remaining, 1)?[0];
        let parameters = read_section(&mut remaining)?;
        let backend = read_section(&mut remaining)?;
        let optimizer_bytes = read_section(&mut remaining)?;
        let optimizer = match (optimizer_tag, optimizer_bytes.is_empty()) {
            (0, true) => HcsnOptimizerStateV2::NotUsed,
            (1, false) => HcsnOptimizerStateV2::Snapshot(optimizer_bytes),
            _ => return Err(HcsnRecoveryErrorV2::Format),
        };
        let snapshot = Self {
            binding: HcsnRecoveryBindingV2 {
                request_digest: digests[0],
                base_checkpoint_digest: digests[1],
                code_digest: digests[2],
                dataset_digest: digests[3],
                runtime_digest: digests[4],
                backend_state_schema_digest: digests[5],
                parameter_mask_digest: digests[6],
                learning_rule_digest: digests[7],
            },
            parameters,
            backend,
            optimizer,
            controller: read_section(&mut remaining)?,
            rng: read_section(&mut remaining)?,
            cost_ledger: read_section(&mut remaining)?,
            history: read_section(&mut remaining)?,
        };
        if !remaining.is_empty() || snapshot.encode()?.as_slice() != bytes {
            return Err(HcsnRecoveryErrorV2::Format);
        }
        Ok(snapshot)
    }
}

fn take<'a>(bytes: &mut &'a [u8], count: usize) -> Result<&'a [u8], HcsnRecoveryErrorV2> {
    let section = bytes.get(..count).ok_or(HcsnRecoveryErrorV2::Format)?;
    *bytes = &bytes[count..];
    Ok(section)
}

fn read_section(bytes: &mut &[u8]) -> Result<Vec<u8>, HcsnRecoveryErrorV2> {
    let length = u64::from_be_bytes(
        take(bytes, 8)?
            .try_into()
            .map_err(|_| HcsnRecoveryErrorV2::Format)?,
    );
    let count = usize::try_from(length).map_err(|_| HcsnRecoveryErrorV2::TooLarge)?;
    Ok(take(bytes, count)?.to_vec())
}

pub fn restore_hcsn_research_state_v2<C: HcsnResearchStateCodecV2>(
    context: &HcsnRecoveryContextV2,
    clock_bytes: &[u8],
    state_bytes: &[u8],
    codec: &C,
) -> Result<HcsnRestoredResearchStateV2<C::State>, HcsnRecoveryErrorV2> {
    if state_bytes.len() > MAX_BYTES {
        return Err(HcsnRecoveryErrorV2::TooLarge);
    }
    let clock = HcsnClockCheckpointV1::restore(
        &context.profile,
        context.identity,
        clock_bytes,
        context.checkpoint_digest,
    )
    .map_err(|_| HcsnRecoveryErrorV2::Clock)?;
    if clock.state_digest() != Digest32::of_bytes(state_bytes) {
        return Err(HcsnRecoveryErrorV2::StateMismatch);
    }
    let snapshot = HcsnResearchStateV2::decode(state_bytes)?;
    if snapshot.binding != context.binding
        || context.binding.backend_state_schema_digest != codec.schema_digest()
        || Digest32::of_bytes(&snapshot.parameters) != context.identity.model_digest
    {
        return Err(HcsnRecoveryErrorV2::Binding);
    }
    let state = codec.restore_complete_state(&snapshot, &clock, &context.profile)?;
    Ok(HcsnRestoredResearchStateV2 { clock, state })
}

#[cfg(test)]
#[path = "hcsn_recovery_tests.rs"]
mod tests;
