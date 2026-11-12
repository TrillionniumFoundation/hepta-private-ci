//! Strict data from Root's actual four-file capture. Deserialization and these
//! structural checks grant nothing. Only the same authenticated historical
//! client may place this data in its private current-admission receipt.

use std::io;

use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerReadOnlyCutV1;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::HostAuthorityRegisteredIdentity;
use crate::root_initial_learning_trust_data::LearningTrustPinV1;

pub(crate) const LEDGER_READ_DATA_PURPOSE: &str = "runtime.learning.historical-ledger-read-data.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootHistoricalLedgerFilePinV1 {
    pub(crate) device: u64,
    pub(crate) inode: u64,
    pub(crate) uid: u32,
    pub(crate) gid: u32,
    pub(crate) mode: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootHistoricalLedgerSourceDataV1 {
    pub(crate) files: [RootHistoricalLedgerFilePinV1; 2],
    pub(crate) target_files: String,
    pub(crate) configuration: String,
    pub(crate) witness_context: String,
    pub(crate) sequence: u64,
    pub(crate) checkpoint: String,
    pub(crate) publication: String,
    pub(crate) completed_task: String,
    pub(crate) fence: String,
}

/// All four images and both independently witnessed frontiers, including the
/// exact actual Source/Cell/Decision/Outcome join. No completion flag or path.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootHistoricalLedgerCutDataV1 {
    pub(crate) source_pin: String,
    pub(crate) source_publication: String,
    pub(crate) cell_decision: String,
    pub(crate) ledger_binding: String,
    pub(crate) ledger_sequence: u64,
    pub(crate) ledger_chain: String,
    pub(crate) ledger_length: u64,
    pub(crate) ledger_image: String,
    pub(crate) witness_length: u64,
    pub(crate) witness_image: String,
    pub(crate) signature_binding: String,
    pub(crate) signature_sequence: u64,
    pub(crate) signature_checkpoint: String,
    pub(crate) signature_length: u64,
    pub(crate) signature_image: String,
    pub(crate) signature_witness_length: u64,
    pub(crate) signature_witness_image: String,
    pub(crate) decision_chain: String,
    pub(crate) outcome_chain: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootHistoricalLedgerReadDataV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) initial_profile: String,
    pub(crate) identity: String,
    pub(crate) registered_identity: String,
    pub(crate) writer: String,
    pub(crate) publisher_epoch: u64,
    pub(crate) publisher: CognitiveCheckpointPeerLifetime,
    pub(crate) peer_gid: u32,
    pub(crate) target: CellGenerationOwnerBindingV1,
    pub(crate) files: [RootHistoricalLedgerFilePinV1; 4],
    pub(crate) metadata: String,
    pub(crate) registered_at: u64,
    pub(crate) trust: LearningTrustPinV1,
    pub(crate) source: RootHistoricalLedgerSourceDataV1,
    pub(crate) cut: RootHistoricalLedgerCutDataV1,
}

impl RootHistoricalLedgerReadDataV1 {
    pub(crate) fn validate_data(&self) -> io::Result<()> {
        if self.schema != 1
            || self.purpose != LEDGER_READ_DATA_PURPOSE
            || self.publisher.uid == 0
            || self.peer_gid == 0
            || self.publisher.pid == 0
            || self.publisher.process_start_ticks == 0
            || self.publisher_epoch == 0
            || self.publisher.boot_id.is_empty()
            || self.publisher.boot_id.len() > 128
            || self.publisher.boot_id.contains('\0')
            || self.registered_at == 0
            || self.registered_identity.len() > 4096
            || self.cut.ledger_sequence != 2
            || self.cut.signature_sequence != 5
            || !(72..=8 * 1024 * 1024).contains(&self.cut.ledger_length)
            || self.cut.witness_length != 72 + 88 * 2
            || !(1..=32 * 1024 * 1024).contains(&self.cut.signature_length)
            || !(1..=1024 * 1024).contains(&self.cut.signature_witness_length)
            || self.cut.outcome_chain != self.cut.ledger_chain
            || self.cut.decision_chain == self.cut.outcome_chain
            || self.source.sequence == 0
            || self.source.publication != self.cut.source_publication
        {
            return Err(io::Error::other("invalid original Ledger read data"));
        }
        // Decode only data. identity() would resolve filesystem paths and is
        // reserved for the actual Root registration/physical verification.
        let registered: HostAuthorityRegisteredIdentity =
            serde_json::from_str(&self.registered_identity).map_err(io::Error::other)?;
        if serde_json::to_string(&registered).map_err(io::Error::other)? != self.registered_identity
            || registered.spawn_generation == 0
            || !registered.fleet_root.is_absolute()
            || !registered.workspace.is_absolute()
            || registered.agent_id.as_str() != self.target.scope().agent_id
        {
            return Err(io::Error::other(
                "invalid original Ledger registration data",
            ));
        }
        self.target.digest().map_err(io::Error::other)?;
        self.trust.require_target(&self.target)?;
        let pins = self
            .files
            .iter()
            .chain(&self.source.files)
            .collect::<Vec<_>>();
        for pin in &pins {
            if pin.mode & 0o170000 != 0o100000
                || pin.mode & 0o7777 != 0o600
                || ![(0, 0), (self.publisher.uid, self.peer_gid)].contains(&(pin.uid, pin.gid))
            {
                return Err(io::Error::other("invalid original private Ledger pin"));
            }
        }
        for (index, pin) in pins.iter().enumerate() {
            if pins[..index]
                .iter()
                .any(|other| (other.device, other.inode) == (pin.device, pin.inode))
            {
                return Err(io::Error::other("distinct original Ledger pins required"));
            }
        }
        for digest in [
            &self.initial_profile,
            &self.identity,
            &self.writer,
            &self.metadata,
            &self.trust.mapping,
            &self.trust.target,
            &self.trust.task,
            &self.trust.source_metadata,
            &self.trust.root,
            &self.trust.distribution,
            &self.trust.trust,
            &self.trust.learning_scope,
            &self.trust.objective,
            &self.trust.roles,
            &self.cut.source_pin,
            &self.cut.source_publication,
            &self.cut.cell_decision,
            &self.cut.ledger_binding,
            &self.cut.ledger_chain,
            &self.cut.ledger_image,
            &self.cut.witness_image,
            &self.cut.signature_binding,
            &self.cut.signature_checkpoint,
            &self.cut.signature_image,
            &self.cut.signature_witness_image,
            &self.cut.decision_chain,
            &self.cut.outcome_chain,
            &self.source.target_files,
            &self.source.configuration,
            &self.source.witness_context,
            &self.source.checkpoint,
            &self.source.publication,
            &self.source.completed_task,
            &self.source.fence,
        ] {
            if digest
                .parse::<Digest32>()
                .map_err(io::Error::other)?
                .is_zero()
            {
                return Err(io::Error::other(
                    "nonzero original Ledger commitments required",
                ));
            }
        }
        if serde_json::to_vec(self).map_err(io::Error::other)?.len() > 12 * 1024 {
            return Err(io::Error::other(
                "original Ledger data exceeds bounded lane",
            ));
        }
        Ok(())
    }

    pub(crate) fn data_cut_digest(&self) -> io::Result<Digest32> {
        self.validate_data()?;
        Ok(Digest32::of_parts(&[
            b"hepta.root.original-historical-ledger-read-data-cut.v1\0",
            b"initial-data-refusal/historical-ledger\0",
            &self.target.digest().map_err(io::Error::other)?,
            &serde_json::to_vec(self).map_err(io::Error::other)?,
        ]))
    }

    /// Data conversion only. The consumer must hold the real original-client
    /// admission while opening its four already existing read-only files.
    pub(crate) fn ledger_cut(&self) -> io::Result<LedgerReadOnlyCutV1> {
        self.validate_data()?;
        Ok(LedgerReadOnlyCutV1 {
            binding: self.cut.ledger_binding.parse().map_err(io::Error::other)?,
            frontier: LedgerWitnessFrontier {
                anchor: LedgerAnchor {
                    sequence: self.cut.ledger_sequence,
                    chain_digest: self.cut.ledger_chain.parse().map_err(io::Error::other)?,
                },
                segment: None,
                sealed: false,
            },
            ledger_length: self.cut.ledger_length,
            ledger_digest: self.cut.ledger_image.parse().map_err(io::Error::other)?,
            witness_length: self.cut.witness_length,
            witness_digest: self.cut.witness_image.parse().map_err(io::Error::other)?,
        })
    }
}
