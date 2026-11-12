//! Durable acknowledgement of one original publisher's data cut. A source pin
//! alone never proves this handoff completed. Even an acknowledged handoff is
//! data: retirement, a new recipient and the Cell/RunStart/Ledger join remain
//! separate requirements before any historical learning authority is issued.
//! The peer ACK and the completed original-context checks are separate durable
//! stages. Finalized records only that the preceding context returned success;
//! it proves neither delivery of the final reply nor a learning authorization.

use super::*;
use crate::RootHistoricalSourceCaptureReceiptV1;
use historical_source_pin::RootHistoricalSourcePinV1;

const HANDOFF_PURPOSE: &str = "runtime.circuit.historical-source-handoff.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum HandoffPhase {
    Pending,
    PeerAcknowledged,
    Finalized,
    Fenced,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HandoffRecord {
    schema: u8,
    purpose: String,
    pin: String,
    initial_profile: String,
    identity: String,
    writer: String,
    publisher_epoch: u64,
    publisher: CognitiveCheckpointPeerLifetime,
    target: CellGenerationOwnerBindingV1,
    phase: HandoffPhase,
}

/// Only the original Root handler creates Pending from an actual captured pin.
/// Reopening never creates or acknowledges a record from present source bytes.
pub(super) struct RootHistoricalSourceHandoffV1 {
    store: HostAuthorityFrontierStore<HandoffRecord>,
    owner: String,
    expected: HandoffRecord,
    poisoned: bool,
    refusal: HistoricalSourceRefusalV1,
}

impl RootHistoricalSourceHandoffV1 {
    pub(super) fn begin(
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        receipt: &RootHistoricalSourceCaptureReceiptV1,
    ) -> io::Result<Self> {
        original_root()?;
        receipt.require_original_capture_session()?;
        if slot.mode != RootGenerationInitialModeV1::Reserve {
            return Err(io::Error::other("recovery cannot create a source handoff"));
        }
        let pin = RootHistoricalSourcePinV1::open_existing(
            Arc::clone(&slot.root),
            &slot.profile.deployment.target,
        )?;
        pin.require_original_registration(&slot.profile, config, registration)?;
        if pin.readback_digest()? != receipt.pin_digest() {
            return Err(io::Error::other("original handoff data pin differs"));
        }
        Self::create_pending(
            Arc::clone(&slot.root),
            HandoffRecord {
                schema: 1,
                purpose: HANDOFF_PURPOSE.into(),
                pin: receipt.pin_digest().to_string(),
                initial_profile: slot.profile.binding.clone(),
                identity: slot.profile.identity.clone(),
                writer: slot.profile.writer.clone(),
                publisher_epoch: registration.publisher_epoch,
                publisher: CognitiveCheckpointPeerLifetime {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                    boot_id: registration.boot_id.clone(),
                    process_start_ticks: registration.process_start_ticks,
                },
                target: slot.profile.deployment.target.clone(),
                phase: HandoffPhase::Pending,
            },
        )
    }

    fn create_pending(
        root: Arc<RootAuthorityDirectory>,
        expected: HandoffRecord,
    ) -> io::Result<Self> {
        original_root()?;
        if expected.phase != HandoffPhase::Pending {
            return Err(io::Error::other("new handoff must remain pending"));
        }
        let owner = owner(&expected.target)?;
        let (refusal, registration) =
            HistoricalSourceRefusalV1::register_original(Arc::clone(&root), &owner)?;
        if !matches!(registration, historical_source_refusal::Registration::New) {
            return Err(io::Error::other(
                "original handoff registration already exists",
            ));
        }
        // No prior record, including an incomplete ACK, can be reused.
        let store =
            match HostAuthorityFrontierStore::initialize(root, owner.clone(), expected.clone()) {
                Ok(store) => store,
                Err(error) => {
                    HistoricalSourceRefusalV1::refuse(&refusal)?;
                    return Err(io::Error::other(error));
                }
            };
        HistoricalSourceRefusalV1::complete_original_registration(&refusal)?;
        let mut retained = Self {
            store,
            owner,
            expected,
            poisoned: false,
            refusal,
        };
        retained.require_exact()?;
        Ok(retained)
    }

    /// Read finalized data only. A peer ACK left by a Root crash is insufficient
    /// and is never completed by recovery from the present files.
    pub(super) fn open_finalized(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        let mut retained = Self::open_record(Arc::clone(&root), target)?;
        retained.require_finalized()?;
        let pin = RootHistoricalSourcePinV1::open_existing(root, target)?;
        if pin.readback_digest()?.to_string() != retained.expected.pin {
            retained.poisoned = true;
            HistoricalSourceRefusalV1::refuse(&retained.refusal)?;
            return Err(io::Error::other("finalized handoff pin changed"));
        }
        retained.require_finalized()?;
        Ok(retained)
    }

    fn open_record(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let owner = owner(target)?;
        let refusal = HistoricalSourceRefusalV1::open_existing(Arc::clone(&root), &owner)?;
        let store = match HostAuthorityFrontierStore::open(root, owner.clone()) {
            Ok(store) => store,
            Err(error) => {
                HistoricalSourceRefusalV1::refuse(&refusal)?;
                return Err(io::Error::other(error));
            }
        };
        let expected: HandoffRecord = match store.load(&owner) {
            Ok(expected) => expected,
            Err(error) => {
                HistoricalSourceRefusalV1::refuse(&refusal)?;
                return Err(io::Error::other(error));
            }
        };
        if expected.schema != 1
            || expected.purpose != HANDOFF_PURPOSE
            || expected.phase == HandoffPhase::Fenced
        {
            HistoricalSourceRefusalV1::refuse(&refusal)?;
            return Err(io::Error::other("original handoff registration differs"));
        }
        if &expected.target != target {
            return Err(io::Error::other("original handoff target differs"));
        }
        HistoricalSourceRefusalV1::require_open(&refusal)?;
        Ok(Self {
            store,
            owner,
            expected,
            poisoned: false,
            refusal,
        })
    }

    pub(super) fn acknowledge(&mut self) -> io::Result<()> {
        self.require_exact()?;
        if self.expected.phase != HandoffPhase::Pending {
            self.poisoned = true;
            return Err(io::Error::other("original handoff ACK already consumed"));
        }
        let mut next = self.expected.clone();
        next.phase = HandoffPhase::PeerAcknowledged;
        if let Err(error) = self
            .store
            .compare_and_set(&self.owner, &self.expected, &next)
        {
            self.poisoned = true;
            HistoricalSourceRefusalV1::refuse(&self.refusal)?;
            return Err(io::Error::other(error));
        }
        self.expected = next;
        self.require_exact()
    }

    /// Called only after the original context, including its postchecks, has
    /// returned Ok and the same receipt deadline has been checked again.
    pub(super) fn finalize_after_verified_context(&mut self) -> io::Result<()> {
        self.require_exact()?;
        if self.expected.phase != HandoffPhase::PeerAcknowledged {
            self.poisoned = true;
            return Err(io::Error::other(
                "original peer ACK required before finalization",
            ));
        }
        let mut next = self.expected.clone();
        next.phase = HandoffPhase::Finalized;
        if let Err(error) = self
            .store
            .compare_and_set(&self.owner, &self.expected, &next)
        {
            self.poisoned = true;
            HistoricalSourceRefusalV1::refuse(&self.refusal)?;
            return Err(io::Error::other(error));
        }
        self.expected = next;
        self.require_finalized()
    }

    fn require_exact(&mut self) -> io::Result<()> {
        original_root()?;
        HistoricalSourceRefusalV1::require_open(&self.refusal)?;
        if self.poisoned
            || !matches!(self.store.load(&self.owner), Ok(record) if record == self.expected)
        {
            self.poisoned = true;
            HistoricalSourceRefusalV1::refuse(&self.refusal)?;
            return Err(io::Error::other("original handoff record changed"));
        }
        HistoricalSourceRefusalV1::require_open(&self.refusal)?;
        Ok(())
    }

    fn require_finalized(&mut self) -> io::Result<()> {
        self.require_exact()?;
        if self.expected.phase != HandoffPhase::Finalized {
            return Err(io::Error::other(
                "original publisher handoff was not finalized",
            ));
        }
        Ok(())
    }

    pub(super) fn fence(&mut self) -> io::Result<()> {
        original_root()?;
        self.poisoned = true;
        HistoricalSourceRefusalV1::refuse(&self.refusal)?;
        let observed = self.store.load(&self.owner).map_err(io::Error::other)?;
        let mut same_binding = observed.clone();
        same_binding.phase = self.expected.phase;
        if same_binding != self.expected {
            return Err(io::Error::other("cannot overwrite a different handoff"));
        }
        if observed.phase == HandoffPhase::Fenced {
            return Ok(());
        }
        let mut next = observed.clone();
        next.phase = HandoffPhase::Fenced;
        self.store
            .compare_and_set(&self.owner, &observed, &next)
            .map_err(io::Error::other)
    }
}

fn owner(target: &CellGenerationOwnerBindingV1) -> io::Result<String> {
    target.digest().map_err(io::Error::other)?;
    Ok(format!(
        "historical-handoff/{}",
        crate::neuron_generation_current::types::scope_digest(target.scope())
            .map_err(io::Error::other)?
    ))
}

#[cfg(test)]
#[path = "authority_host_historical_source_handoff_tests.rs"]
mod tests;
