//! Root capture of published A source bytes while its original process is alive.
//! This preserves data for a later admission; it grants no historical access,
//! Dataset authority or replacement writer. No peer wire accepts these inputs.
//! RunStart authentication, physical Cell decisions and Ledger joins remain
//! separate requirements; Root storage does not attest that A really executed.

use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;

use codex_hepta_automation::TaskFlowFence;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;

use super::data_refusal::RootDataRefusalV1;
use super::*;
use crate::CircuitCellRegistryV1;
use crate::CircuitTaskSourceInputV1;
use crate::HistoricalCircuitTaskSourceV1;

const PIN_PURPOSE: &str = "runtime.circuit.historical-source-pin.v1";

#[path = "authority_host_historical_source_inputs.rs"]
mod inputs;
pub(crate) use inputs::RetainedRootHistoricalSourceInputsV1;
#[path = "authority_host_historical_source_data.rs"]
mod captured_data;
#[path = "authority_host_historical_cell_pin.rs"]
pub(crate) mod cell;
#[path = "authority_host_historical_ledger_pin.rs"]
pub(crate) mod ledger;
pub(crate) use captured_data::OriginalSourceDataCaptureV1;

/// Original single-published-task Q24 configuration and Root-held descriptors.
/// There is no serialized observation, generic witness or caller-authored pin.
pub struct RootHistoricalSourceInputsV1 {
    pub journal: File,
    pub witness: File,
    pub witness_scope: JournalScope,
    pub witness_generation: Generation,
    pub witness_records: usize,
    pub fence: TaskFlowFence,
    pub registry: CircuitCellRegistryV1,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FilePin {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

impl FilePin {
    fn read(file: &File, uid: u32, gid: u32) -> io::Result<Self> {
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || ![(0, 0), (uid, gid)].contains(&(metadata.uid(), metadata.gid()))
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(io::Error::other("original private source file required"));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }

    fn readonly(file: &File, uid: u32, gid: u32) -> io::Result<(File, Self)> {
        let pin = Self::read(file, uid, gid)?;
        let readonly = File::open(format!("/proc/self/fd/{}", file.as_raw_fd()))?;
        if Self::read(&readonly, uid, gid)? != pin || Self::read(file, uid, gid)? != pin {
            return Err(io::Error::other("original source descriptor changed"));
        }
        Ok((readonly, pin))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SourcePin {
    schema: u8,
    purpose: String,
    initial_profile: String,
    identity: String,
    spawn_generation: u64,
    publisher_epoch: u64,
    publisher: CognitiveCheckpointPeerLifetime,
    writer: String,
    target: CellGenerationOwnerBindingV1,
    target_files: String,
    source_files: [FilePin; 2],
    source_configuration: String,
    witness_context: String,
    source_sequence: u64,
    source_checkpoint: String,
    publication: String,
    completed_task: String,
    fence_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PinRecord {
    pin: SourcePin,
    fenced: bool,
}

/// Opaque retained Root record. Opening it neither reads a source file nor
/// proves retirement/new-recipient authority. Missing registration stays absent.
pub(crate) struct RootHistoricalSourcePinV1 {
    store: HostAuthorityFrontierStore<PinRecord>,
    owner: String,
    expected: PinRecord,
    poisoned: Mutex<bool>,
    refusal: RootDataRefusalV1,
}

struct RetainedSourcePinRecordV1 {
    store: HostAuthorityFrontierStore<PinRecord>,
    owner: String,
    expected: PinRecord,
}

#[derive(Clone, Copy)]
enum PinRecordAccess {
    Fresh,
    Existing,
}

#[path = "authority_host_historical_source_record.rs"]
mod record;

#[path = "authority_host_historical_task_data.rs"]
mod task_data;

impl HostAuthorityService {
    /// Capture only under this actual Initial owner's original writer/pidfd.
    /// A must still be alive, but its Source writer must have released its lock.
    /// Only the original fixed-input worker reaches this data-only entry.
    pub(crate) fn capture_initial_source_pin(
        &self,
        slot: &RegisteredGenerationInitial,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        publisher_pidfd: &OwnedFd,
        inputs: RetainedRootHistoricalSourceInputsV1,
        data: OriginalSourceDataCaptureV1,
    ) -> io::Result<RootHistoricalSourcePinV1> {
        original_root()?;
        RootHistoricalSourcePinV1::capture(
            Arc::clone(&slot.root),
            &slot.profile.deployment.target,
            |access| {
                OriginalSourceDataCaptureV1::with_original_capture(data, |mut cell, mut ledger| {
                    let mut retained = None;
                    self.with_initial_publication_context(
                        config,
                        registration,
                        publisher_pidfd,
                        |proof| {
                            let inputs = inputs.into_registered(
                                &self.identity,
                                &slot.profile.deployment.target,
                                config.peer_uid,
                                config.peer_gid,
                            )?;
                            if slot.mode != RootGenerationInitialModeV1::Reserve
                                || slot.profile.writer != proof
                                || slot.profile.identity
                                    != crate::neuron_generation_process_identity_digest_v1(
                                        &self.identity,
                                    )
                                    .map_err(io::Error::other)?
                                    .to_string()
                                || self.identity.spawn_generation.checked_add(1)
                                    != Some(inputs.fence.generation)
                                || inputs.fence.owner_agent_id != self.identity.agent_id
                                || registration.checkpoint_owner_agent_id != self.identity.agent_id
                                || registration.publisher_epoch == 0
                            {
                                return Err(io::Error::other("original source publisher differs"));
                            }
                            self.checkpoint
                                .as_ref()
                                .ok_or_else(|| {
                                    io::Error::other("original checkpoint peer missing")
                                })?
                                .validate_peer(codex_hepta_contracts::HostIssuerPeer {
                                    uid: config.peer_uid,
                                    pid: registration.peer_pid,
                                })?;
                            require_target(
                                &slot.profile.deployment.target,
                                &inputs.definition,
                                &inputs.source,
                            )?;
                            slot.require_profile()?;
                            slot.require_selection(
                                self.clock
                                    .refresh_projection()
                                    .map_err(io::Error::other)?
                                    .observed_unix_ms,
                            )?;
                            let current = slot
                                .current
                                .try_lock()
                                .map_err(|_| io::Error::other("initial CURRENT busy"))?;
                            let current = current.as_ref().ok_or_else(|| {
                                io::Error::other("original Initial CURRENT missing")
                            })?;
                            let head = current.original_broker_head().map_err(io::Error::other)?;
                            let (signed, witness) =
                    crate::neuron_generation_current::initial_root::original_initial_record(
                        &slot.profile.prepared,
                        &head,
                    )
                    .map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("original Initial publication required"))?;
                            let revocations = self.issuer.revocations()?;
                            if slot.verify_recorded_use(&signed, &witness)? != revocations {
                                return Err(io::Error::other("original Initial use differs"));
                            }
                            let target = slot.target.observe().map_err(io::Error::other)?;
                            let (journal, journal_pin) = FilePin::readonly(
                                &inputs.journal,
                                config.peer_uid,
                                config.peer_gid,
                            )?;
                            let (witness_file, witness_pin) = FilePin::readonly(
                                &inputs.witness,
                                config.peer_uid,
                                config.peer_gid,
                            )?;
                            if witness_file.metadata()?.len() == 0
                                || (journal_pin.device, journal_pin.inode)
                                    == (witness_pin.device, witness_pin.inode)
                            {
                                return Err(io::Error::other(
                                    "independent source witness required",
                                ));
                            }
                            let physical_witness = FileAnchorWitnessStore::open(
                                witness_file,
                                inputs.witness_scope,
                                inputs.witness_generation,
                                inputs.witness_records,
                            )
                            .map_err(io::Error::other)?;
                            let mut source = HistoricalCircuitTaskSourceV1::open(
                                journal,
                                physical_witness,
                                &self.identity,
                                &inputs.fence,
                                &inputs.registry,
                                vec![inputs.source.clone()],
                            )
                            .map_err(io::Error::other)?;
                            let observed = source
                                .observe_run_publication(&inputs.source.scope.run_id)
                                .map_err(io::Error::other)?;
                            if observed.original_identity() != &self.identity
                                || observed.original_fence() != &inputs.fence
                                || observed.original_source() != &inputs.source
                                || observed.publication().bundle_digest()
                                    != inputs.definition.bundle_digest
                                || slot
                                    .selected
                                    .try_lock()
                                    .map_err(|_| io::Error::other("original selection busy"))?
                                    .manifest()
                                    .bundle_digest
                                    != inputs.definition.bundle_digest.into_array()
                            {
                                return Err(io::Error::other(
                                    "original source publication differs",
                                ));
                            }
                            let anchor = observed.journal_anchor();
                            let pin = SourcePin {
                                schema: 1,
                                purpose: PIN_PURPOSE.into(),
                                initial_profile: slot.profile.binding.clone(),
                                identity: slot.profile.identity.clone(),
                                spawn_generation: self.identity.spawn_generation,
                                publisher_epoch: registration.publisher_epoch,
                                publisher: CognitiveCheckpointPeerLifetime {
                                    uid: config.peer_uid,
                                    pid: registration.peer_pid,
                                    boot_id: registration.boot_id.clone(),
                                    process_start_ticks: registration.process_start_ticks,
                                },
                                writer: proof,
                                target: slot.profile.deployment.target.clone(),
                                target_files: slot.profile.target_files.clone(),
                                source_files: [journal_pin, witness_pin],
                                source_configuration: observed.binding_digest().to_string(),
                                witness_context: Digest32::of_parts(&[
                                    inputs.witness_scope.scope_digest.as_array(),
                                    inputs.witness_scope.objective_digest.as_array(),
                                    &inputs.witness_generation.get().to_be_bytes(),
                                    &(inputs.witness_records as u64).to_be_bytes(),
                                ])
                                .to_string(),
                                source_sequence: anchor.sequence,
                                source_checkpoint: anchor.checkpoint_digest.to_string(),
                                publication: observed
                                    .publication()
                                    .publication_digest()
                                    .to_string(),
                                completed_task: observed
                                    .publication()
                                    .history_digest()
                                    .as_str()
                                    .into(),
                                fence_digest: Digest32::of_parts(&[
                                    b"hepta.root.historical-source-fence.v1\0",
                                    &serde_json::to_vec(&inputs.fence).map_err(io::Error::other)?,
                                ])
                                .to_string(),
                            };
                            retained = Some(RootHistoricalSourcePinV1::retain_unchecked(
                                Arc::clone(&slot.root),
                                pin,
                                access,
                            )?);
                            let decision = cell
                                .as_deref_mut()
                                .map(|cell| {
                                    cell.observe_and_retain_original_cell(
                                        slot,
                                        &inputs,
                                        &observed,
                                        retained.as_ref().ok_or_else(|| {
                                            io::Error::other("source pin missing")
                                        })?,
                                    )
                                })
                                .transpose()?;
                            if let Some(ledger) = ledger.as_deref_mut() {
                                ledger.observe_and_retain_original_ledger(
                                    slot,
                                    ledger::OriginalLedgerCaptureDataV1 {
                                        identity: &self.identity,
                                        inputs: &inputs,
                                        source: &observed,
                                        cell: decision.as_ref().ok_or_else(|| {
                                            io::Error::other(
                                                "actual original Cell decision missing",
                                            )
                                        })?,
                                        retained: retained.as_ref().ok_or_else(|| {
                                            io::Error::other("source pin missing")
                                        })?,
                                    },
                                    self.clock
                                        .refresh_projection()
                                        .map_err(io::Error::other)?
                                        .observed_unix_ms,
                                )?;
                            }
                            if source
                                .observe_run_publication(&inputs.source.scope.run_id)
                                .map_err(io::Error::other)?
                                != observed
                                || slot.target.observe().map_err(io::Error::other)? != target
                                || current.original_broker_head().map_err(io::Error::other)? != head
                                || slot.verify_recorded_use(&signed, &witness)? != revocations
                                || [
                                    FilePin::read(
                                        &inputs.journal,
                                        config.peer_uid,
                                        config.peer_gid,
                                    )?,
                                    FilePin::read(
                                        &inputs.witness,
                                        config.peer_uid,
                                        config.peer_gid,
                                    )?,
                                ] != retained
                                    .as_ref()
                                    .ok_or_else(|| io::Error::other("source pin missing"))?
                                    .expected
                                    .pin
                                    .source_files
                            {
                                return Err(io::Error::other(
                                    "source capture changed during registration",
                                ));
                            }
                            slot.require_profile()?;
                            self.checkpoint
                                .as_ref()
                                .ok_or_else(|| {
                                    io::Error::other("original checkpoint peer missing")
                                })?
                                .validate_peer(codex_hepta_contracts::HostIssuerPeer {
                                    uid: config.peer_uid,
                                    pid: registration.peer_pid,
                                })?;
                            slot.require_selection(
                                self.clock
                                    .refresh_projection()
                                    .map_err(io::Error::other)?
                                    .observed_unix_ms,
                            )
                        },
                    )?;

                    retained.ok_or_else(|| io::Error::other("original source pin capture missing"))
                })
            },
        )
    }
}

fn owner(target: &CellGenerationOwnerBindingV1) -> io::Result<String> {
    target.digest().map_err(io::Error::other)?;
    Ok(format!(
        "historical-source/{}",
        crate::neuron_generation_current::types::scope_digest(target.scope())
            .map_err(io::Error::other)?
    ))
}

fn require_target(
    target: &CellGenerationOwnerBindingV1,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
) -> io::Result<()> {
    let scope = target.scope();
    if scope.agent_id != source.scope.agent_id.as_str()
        || scope.cell_id != source.scope.cell_id.as_str()
        || scope.run_id != source.scope.run_id.as_str()
        || scope.principal_digest != source.scope.principal_digest.into_array()
        || target.source_frontier() != source.source_frontier.into_array()
        || target.task_digest()
            != crate::circuit_feature_task_digest_v1(definition, source)
                .map_err(io::Error::other)?
                .into_array()
    {
        return Err(io::Error::other(
            "source differs from original Initial target",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "authority_host_historical_source_pin_tests.rs"]
mod tests;
