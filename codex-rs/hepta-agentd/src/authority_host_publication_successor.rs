//! Original C custody is registered before CURRENT publication. Only an
//! explicit later retired capture can finalize its data; read never creates
//! or repairs a record. The enclosing publication arm covers every operation.

use super::*;
use crate::RetiredCheckpointPublisher;
use crate::authority_host_runtime::RootOriginalSuccessorFilesV1;
use crate::authority_host_runtime::RootSuccessorTaskCutV1;
use codex_hepta_contracts::RootAuthorityDirectory;

const SUCCESSOR_PURPOSE: &str = "runtime.circuit.original-successor-data.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootCompletedSuccessorDataV1 {
    pub(crate) record_digest: String,
    pub(crate) cut: RootSuccessorTaskCutV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum SuccessorPhase {
    Registered,
    Finalized { cut: Box<RootSuccessorTaskCutV1> },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SuccessorRecord {
    schema: u8,
    purpose: String,
    profile: ReservedPublicationProfile,
    registered_identity: String,
    publisher: CognitiveCheckpointPeerLifetime,
    publisher_epoch: u64,
    peer_gid: u32,
    files: String,
    configuration: String,
    phase: SuccessorPhase,
}

pub(super) struct RegisteredSuccessorData {
    store: HostAuthorityFrontierStore<SuccessorRecord>,
    owner: String,
    original: Mutex<SuccessorRecord>,
    files: Arc<RootOriginalSuccessorFilesV1>,
}

impl RegisteredSuccessorData {
    // Called only inside the existing durable publication arm and actual Root
    // writer context. The Root-fixed holder has no peer constructor.
    pub(super) fn enroll(
        root: Arc<RootAuthorityDirectory>,
        slot: &RegisteredGenerationPublication,
        files: Arc<RootOriginalSuccessorFilesV1>,
        mode: RootGenerationPublicationModeV1,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        identity: &crate::AgentdIdentity,
    ) -> io::Result<Self> {
        original_root()?;
        let original = slot
            .reserved
            .original_for_version(PublicationVersion::DurableV2)?;
        let owner = format!(
            "publication-task/{}",
            Digest32::of_bytes(original.learning_operation.as_bytes())
        );
        let (store, record) = match mode {
            RootGenerationPublicationModeV1::Reserve => {
                let head = slot
                    .current
                    .original_broker_head()
                    .map_err(io::Error::other)?;
                if head.current != original.intent.previous
                    || head.prepared.is_some()
                    || original != &slot.profile
                    || registration.publisher_epoch == 0
                    || registration.checkpoint_owner_agent_id != identity.agent_id
                {
                    return Err(io::Error::other(
                        "successor must precede original CURRENT preparation",
                    ));
                }
                let configuration =
                    files.require_registered_baseline(identity, &original.intent.target)?;
                let record = SuccessorRecord {
                    schema: 1,
                    purpose: SUCCESSOR_PURPOSE.into(),
                    profile: slot.reserved.clone(),
                    registered_identity: serde_json::to_string(&registration.registered_identity)
                        .map_err(io::Error::other)?,
                    publisher: CognitiveCheckpointPeerLifetime {
                        uid: config.peer_uid,
                        pid: registration.peer_pid,
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: registration.process_start_ticks,
                    },
                    publisher_epoch: registration.publisher_epoch,
                    peer_gid: config.peer_gid,
                    files: files.deployment_digest()?.to_string(),
                    configuration: configuration.to_string(),
                    phase: SuccessorPhase::Registered,
                };
                let store =
                    HostAuthorityFrontierStore::initialize(root, owner.clone(), record.clone())
                        .map_err(io::Error::other)?;
                (store, record)
            }
            RootGenerationPublicationModeV1::Recover => {
                let store =
                    HostAuthorityFrontierStore::<SuccessorRecord>::open(root, owner.clone())
                        .map_err(io::Error::other)?;
                let record = store.load(&owner).map_err(io::Error::other)?;
                if record.schema != 1
                    || record.purpose != SUCCESSOR_PURPOSE
                    || record.profile != slot.reserved
                    || record.files != files.deployment_digest()?.to_string()
                    || record.publisher.uid != config.peer_uid
                    || record.peer_gid != config.peer_gid
                    || record.publisher_epoch == 0
                {
                    return Err(io::Error::other("original successor registration differs"));
                }
                (store, record)
            }
        };
        let held = Self {
            store,
            owner,
            original: Mutex::new(record),
            files,
        };
        held.require_exact()?;
        Ok(held)
    }

    pub(super) fn require_exact(&self) -> io::Result<()> {
        let expected = self
            .original
            .try_lock()
            .map_err(|_| io::Error::other("original successor record busy"))?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != *expected {
            return Err(io::Error::other("original successor record changed"));
        }
        let identity = original_identity(&expected)?;
        let profile = expected
            .profile
            .original_for_version(PublicationVersion::DurableV2)?;
        if crate::neuron_generation_process_identity_digest_v1(&identity)
            .map_err(io::Error::other)?
            .to_string()
            != profile.identity
            || identity.agent_id.as_str() != profile.intent.target.scope().agent_id
            || self.files.deployment_digest()?.to_string() != expected.files
        {
            return Err(io::Error::other(
                "original successor publisher binding differs",
            ));
        }
        Ok(())
    }

    pub(super) fn require_baseline(&self) -> io::Result<()> {
        self.require_exact()?;
        let original = self
            .original
            .try_lock()
            .map_err(|_| io::Error::other("original successor record busy"))?;
        if original.phase != SuccessorPhase::Registered {
            return Err(io::Error::other(
                "original successor baseline already consumed",
            ));
        }
        let identity = original_identity(&original)?;
        let profile = original
            .profile
            .original_for_version(PublicationVersion::DurableV2)?;
        if self
            .files
            .require_registered_baseline(&identity, &profile.intent.target)?
            .to_string()
            != original.configuration
        {
            return Err(io::Error::other("original successor baseline changed"));
        }
        Ok(())
    }

    pub(super) fn observe_retired(&self, capture: bool) -> io::Result<RootSuccessorTaskCutV1> {
        self.require_exact()?;
        let mut original = self
            .original
            .try_lock()
            .map_err(|_| io::Error::other("original successor record busy"))?;
        if capture != matches!(original.phase, SuccessorPhase::Registered) {
            return Err(io::Error::other(
                "explicit successor capture/read phase differs",
            ));
        }
        let cut = self.read_physical(&original)?;
        if capture {
            let mut next = original.clone();
            next.phase = SuccessorPhase::Finalized {
                cut: Box::new(cut.clone()),
            };
            self.store
                .compare_and_set(&self.owner, &original, &next)
                .map_err(io::Error::other)?;
            if self.store.load(&self.owner).map_err(io::Error::other)? != next {
                return Err(io::Error::other(
                    "successor capture acknowledgement differs",
                ));
            }
            *original = next;
        } else if !matches!(&original.phase, SuccessorPhase::Finalized { cut: retained } if retained.as_ref() == &cut)
        {
            return Err(io::Error::other(
                "original finalized successor data changed",
            ));
        }
        Ok(cut)
    }

    /// Called after the entire actual Root writer context returns. No successful
    /// reply or durable Ready can precede this complete independent re-read.
    pub(super) fn finish_observed(&self, expected: &RootSuccessorTaskCutV1) -> io::Result<()> {
        if self.observe_retired(false)? != *expected {
            return Err(io::Error::other(
                "successor changed after Root writer postchecks",
            ));
        }
        self.require_exact()
    }

    pub(super) fn read_data(
        &self,
        cut: RootSuccessorTaskCutV1,
    ) -> io::Result<RootCompletedSuccessorDataV1> {
        self.require_exact()?;
        let record = self
            .original
            .try_lock()
            .map_err(|_| io::Error::other("original successor record busy"))?;
        if !matches!(&record.phase, SuccessorPhase::Finalized { cut: retained } if retained.as_ref() == &cut)
        {
            return Err(io::Error::other(
                "successor read data differs from retained cut",
            ));
        }
        Ok(RootCompletedSuccessorDataV1 {
            record_digest: Digest32::of_parts(&[
                b"hepta.root.original-successor-record.v1\0",
                &serde_json::to_vec(&*record).map_err(io::Error::other)?,
            ])
            .to_string(),
            cut,
        })
    }

    fn read_physical(&self, record: &SuccessorRecord) -> io::Result<RootSuccessorTaskCutV1> {
        let _retired = RetiredCheckpointPublisher::observe(record.publisher.clone())
            .map_err(io::Error::other)?;
        let identity = original_identity(record)?;
        let profile = record
            .profile
            .original_for_version(PublicationVersion::DurableV2)?;
        let cut = self
            .files
            .observe_original_successor(&identity, &profile.intent.target)?;
        if cut.configuration != record.configuration {
            return Err(io::Error::other("original successor configuration changed"));
        }
        RetiredCheckpointPublisher::observe(record.publisher.clone()).map_err(io::Error::other)?;
        Ok(cut)
    }
}

fn original_identity(record: &SuccessorRecord) -> io::Result<crate::AgentdIdentity> {
    let registered: HostAuthorityRegisteredIdentity =
        serde_json::from_str(&record.registered_identity).map_err(io::Error::other)?;
    if serde_json::to_string(&registered).map_err(io::Error::other)? != record.registered_identity {
        return Err(io::Error::other(
            "canonical original successor identity required",
        ));
    }
    registered.identity()
}
