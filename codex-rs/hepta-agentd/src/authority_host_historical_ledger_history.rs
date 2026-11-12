//! Existing Root-retained Ledger data, opened only inside its independent
//! durable refusal arm. The complete new-recipient Root action stays inside
//! that arm; this observation alone never grants Dataset or learning access.

use std::path::Path;
use std::time::Instant;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerReadOnlyCutV1;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_learning_ledger::encode_readonly_ledger_data_v1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::JournalAnchor;

use super::*;
use crate::HistoricalCircuitTaskSourceObservationV1;
use crate::authority_host_runtime::RegisteredInitialLearningTrustV1;
use crate::authority_host_runtime::RootHistoricalLedgerDeploymentV1;
use crate::root_historical_ledger_data::LEDGER_READ_DATA_PURPOSE;
use crate::root_historical_ledger_data::RootHistoricalLedgerFilePinV1;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_historical_ledger_data::RootHistoricalLedgerSourceDataV1;

enum HistoryState {
    Unobserved,
    Verifying,
    Complete {
        observed: Box<OriginalLedgerObservation>,
        held: OriginalLedgerReadGuard,
        trust: RegisteredInitialLearningTrustV1,
    },
}

/// Opaque data, usable only after the outer whole-task context returns. The
/// four actual file locks remain owned by the pending action until then.
pub(crate) struct RootOriginalHistoricalLedgerObservationV1 {
    record: LedgerRecord,
    source: SourcePin,
    ledger_image: Vec<u8>,
}

pub(crate) struct PendingOriginalLedgerHistoryV1<'a> {
    service: &'a HostAuthorityService,
    files: OriginalLedgerFiles,
    record: LedgerRecord,
    identity: crate::AgentdIdentity,
    end: Instant,
    state: HistoryState,
}

impl HostAuthorityService {
    pub(crate) fn with_retained_original_ledger<T>(
        &self,
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
        deployment_path: &Path,
        end: Instant,
        action: impl FnOnce(&mut PendingOriginalLedgerHistoryV1<'_>) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        let refusal = RootDataRefusalV1::open_existing(
            Arc::clone(&root),
            RootDataKind::HistoricalLedger,
            target,
        )?;
        refusal.inspect(|| {
            if Instant::now() >= end {
                return Err(io::Error::other("historical Ledger deadline expired"));
            }
            // Even open() reads the primary. No primary, metadata, identity
            // path or original descriptor is opened before the durable arm.
            let owner = ledger_owner(target)?;
            let store =
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
            let record: LedgerRecord = store.load(&owner).map_err(io::Error::other)?;
            if record.schema != 1
                || record.purpose != LEDGER_PURPOSE
                || &record.target != target
                || record.registered_at == 0
                || !matches!(record.phase, LedgerPhase::Captured { .. })
            {
                return Err(io::Error::other("captured original Ledger record required"));
            }
            let registration: HostAuthorityRegisteredIdentity =
                serde_json::from_str(&record.registered_identity).map_err(io::Error::other)?;
            let identity = registration.identity()?;
            if serde_json::to_string(&registration).map_err(io::Error::other)?
                != record.registered_identity
                || crate::neuron_generation_process_identity_digest_v1(&identity)
                    .map_err(io::Error::other)?
                    .to_string()
                    != record.identity
            {
                return Err(io::Error::other("original Ledger identity differs"));
            }
            let deployment = RootHistoricalLedgerDeploymentV1::open_original(deployment_path)?;
            let files = OriginalLedgerFiles::retain_original_ledger(
                deployment,
                record.publisher.uid,
                record.peer_gid,
            )?;
            if files.file_pins() != &record.files
                || files.deployment.metadata_digest().to_string() != record.metadata
                || &files.deployment.initial.target != target
            {
                return Err(io::Error::other("retained original Ledger custody differs"));
            }
            record.trust.require_target(target)?;
            let mut pending = PendingOriginalLedgerHistoryV1 {
                service: self,
                files,
                record: record.clone(),
                identity,
                end,
                state: HistoryState::Unobserved,
            };
            // The caller encloses the complete authenticated new-recipient
            // context and every other original-data arm, including postchecks.
            let result = action(&mut pending)?;
            let HistoryState::Complete {
                observed,
                mut held,
                trust,
            } = pending.state
            else {
                return Err(io::Error::other("original Ledger observation unfinished"));
            };
            held.require_unchanged(&observed)?;
            pending.files.require_original_files()?;
            trust.revalidate(
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            if store.load(&owner).map_err(io::Error::other)? != record || Instant::now() >= end {
                return Err(io::Error::other(
                    "historical Ledger changed after Root context",
                ));
            }
            Ok(result)
        })
    }
}

impl PendingOriginalLedgerHistoryV1<'_> {
    pub(crate) fn observe_original_terminal(
        &mut self,
        pin: &RootHistoricalSourcePinV1,
        source: &HistoricalCircuitTaskSourceObservationV1,
        definition: &CellDefinitionV1,
        cell: &CellDecisionReceiptV1,
    ) -> io::Result<RootOriginalHistoricalLedgerObservationV1> {
        original_root()?;
        // A caught failure or second observation cannot clear this attempt.
        if !matches!(
            std::mem::replace(&mut self.state, HistoryState::Verifying),
            HistoryState::Unobserved
        ) || Instant::now() >= self.end
        {
            return Err(io::Error::other(
                "original Ledger read already attempted or expired",
            ));
        }
        let now = self
            .service
            .clock
            .refresh_projection()
            .map_err(io::Error::other)?
            .observed_unix_ms;
        let record = &self.record;
        let original = &pin.expected;
        // The whole-task caller holds the Source arm. Reading its already
        // retained opaque record here must not start a nested same-kind arm.
        if original.fenced
            || original.pin.schema != 1
            || original.pin.purpose != PIN_PURPOSE
            || original.pin.initial_profile != record.initial_profile
            || original.pin.identity != record.identity
            || original.pin.spawn_generation != self.identity.spawn_generation
            || original.pin.writer != record.writer
            || original.pin.target != record.target
            || original.pin.publisher != record.publisher
            || original.pin.publisher_epoch != record.publisher_epoch
            || source.original_identity() != &self.identity
            || original.pin.source_configuration != source.binding_digest().to_string()
            || original.pin.source_sequence != source.journal_anchor().sequence
            || original.pin.source_checkpoint
                != source.journal_anchor().checkpoint_digest.to_string()
            || original.pin.publication != source.publication().publication_digest().to_string()
            || record.registered_at > now / 1_000
        {
            return Err(io::Error::other(
                "historical Source and Ledger registration differ",
            ));
        }
        require_target(&record.target, definition, source.original_source())?;
        let source_pin = Digest32::of_parts(&[
            b"hepta.root.historical-source-pin.v1\0",
            &serde_json::to_vec(original).map_err(io::Error::other)?,
        ]);
        let LedgerPhase::Captured { cut } = &record.phase else {
            return Err(io::Error::other("original Ledger capture missing"));
        };
        let trust_files: Arc<crate::authority_host_runtime::RootInitialLearningTrustFilesV1> =
            Arc::clone(&self.files.deployment.trust);
        let trust: RegisteredInitialLearningTrustV1 =
            trust_files.bind_original(&self.identity, &self.files.deployment.initial, now)?;
        if trust.pin != record.trust {
            return Err(io::Error::other("historical original trust pin differs"));
        }
        let (activated, generator, observer) = trust
            .read_original_payload(now)?
            .activate_pinned_genesis(now / 1_000)?;
        // Recreate only the original plain contract at its retained Root
        // enrollment time. This never creates a fresh claim window or signer.
        let config = self
            .files
            .deployment
            .ledger
            .configuration(generator, observer, record.registered_at)
            .map_err(io::Error::other)?;
        let context = OriginalTaskLedgerHistoryContextV1 {
            identity: &self.identity,
            definition,
            source: source.original_source(),
            config: &config,
            ledger_binding: Digest32::from_array(self.files.deployment.ledger.binding),
            verifier: activated.verifier(),
        };
        let mode = OriginalLedgerReadModeV1::Retained {
            ledger: LedgerReadOnlyCutV1 {
                binding: cut.ledger_binding.parse().map_err(io::Error::other)?,
                frontier: LedgerWitnessFrontier {
                    anchor: LedgerAnchor {
                        sequence: cut.ledger_sequence,
                        chain_digest: cut.ledger_chain.parse().map_err(io::Error::other)?,
                    },
                    segment: None,
                    sealed: false,
                },
                ledger_length: cut.ledger_length,
                ledger_digest: cut.ledger_image.parse().map_err(io::Error::other)?,
                witness_length: cut.witness_length,
                witness_digest: cut.witness_image.parse().map_err(io::Error::other)?,
            },
            signatures: JournalAnchor {
                sequence: cut.signature_sequence,
                checkpoint_digest: cut.signature_checkpoint.parse().map_err(io::Error::other)?,
            },
        };
        let mut held = self.files.open_original_terminal(&context, mode)?;
        let observed = OriginalLedgerReadGuard::observe_original_terminal(
            &mut held,
            &context,
            source.publication(),
            cell,
            now / 1_000,
        )?;
        if CapturedLedgerCut::from_original(&observed, source.publication(), cell, source_pin)?
            != **cut
        {
            return Err(io::Error::other(
                "original complete four-file Ledger cut differs",
            ));
        }
        self.files.require_original_files()?;
        held.require_unchanged(&observed)?;
        trust.revalidate(
            self.service
                .clock
                .refresh_projection()
                .map_err(io::Error::other)?
                .observed_unix_ms,
        )?;
        if Instant::now() >= self.end {
            return Err(io::Error::other(
                "historical Ledger ended during observation",
            ));
        }
        // Encode only the two facts from this actual, fully verified physical
        // observation. Matching the entire retained image prevents the wire
        // data from replacing a record or selecting a different prefix.
        let ledger_image = encode_readonly_ledger_data_v1(
            observed.cut.binding,
            &[
                observed.facts.decision.clone(),
                observed.facts.outcome.clone(),
            ],
        )
        .map_err(io::Error::other)?;
        if ledger_image.len() as u64 != observed.cut.ledger_length
            || Digest32::of_bytes(&ledger_image) != observed.cut.ledger_digest
        {
            return Err(io::Error::other("original Ledger data image differs"));
        }
        self.state = HistoryState::Complete {
            observed: Box::new(observed),
            held,
            trust,
        };
        Ok(RootOriginalHistoricalLedgerObservationV1 {
            record: record.clone(),
            source: original.pin.clone(),
            ledger_image,
        })
    }
}

impl RootOriginalHistoricalLedgerObservationV1 {
    /// A stable commitment to the actual protected record and independent
    /// refusal namespace. Ready/attempt is proved by the enclosing action,
    /// never by this digest or a peer-supplied serialized observation.
    pub(crate) fn data_cut_digest(&self) -> io::Result<Digest32> {
        self.ledger_read_data()?.data_cut_digest()
    }

    pub(crate) fn ledger_read_data(&self) -> io::Result<RootHistoricalLedgerReadDataV1> {
        let record = &self.record;
        let source = &self.source;
        let LedgerPhase::Captured { cut } = &record.phase else {
            return Err(io::Error::other("original captured Ledger data missing"));
        };
        let data = RootHistoricalLedgerReadDataV1 {
            schema: 1,
            purpose: LEDGER_READ_DATA_PURPOSE.into(),
            initial_profile: record.initial_profile.clone(),
            identity: record.identity.clone(),
            registered_identity: record.registered_identity.clone(),
            writer: record.writer.clone(),
            publisher_epoch: record.publisher_epoch,
            publisher: record.publisher.clone(),
            peer_gid: record.peer_gid,
            target: record.target.clone(),
            files: record
                .files
                .clone()
                .map(|pin| RootHistoricalLedgerFilePinV1 {
                    device: pin.device,
                    inode: pin.inode,
                    uid: pin.uid,
                    gid: pin.gid,
                    mode: pin.mode,
                }),
            metadata: record.metadata.clone(),
            registered_at: record.registered_at,
            trust: record.trust.clone(),
            source: RootHistoricalLedgerSourceDataV1 {
                files: source
                    .source_files
                    .clone()
                    .map(|pin| RootHistoricalLedgerFilePinV1 {
                        device: pin.device,
                        inode: pin.inode,
                        uid: pin.uid,
                        gid: pin.gid,
                        mode: pin.mode,
                    }),
                target_files: source.target_files.clone(),
                configuration: source.source_configuration.clone(),
                witness_context: source.witness_context.clone(),
                sequence: source.source_sequence,
                checkpoint: source.source_checkpoint.clone(),
                publication: source.publication.clone(),
                completed_task: source.completed_task.clone(),
                fence: source.fence_digest.clone(),
            },
            cut: (**cut).clone(),
            ledger_image_bytes: STANDARD.encode(&self.ledger_image),
        };
        data.validate_data()?;
        Ok(data)
    }
}
