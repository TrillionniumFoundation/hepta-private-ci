//! Mechanism fixtures with real writer files, source exchanges and HEAD journal.
//! Only the transport policy permits this test process at both socket ends.
//! Production constructors retain independent UID/process/pidfd admission.
//! Keys and payload are explicit fixtures, never ordinary learning acceptance.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::OriginalArtifactPreparedPublicationV1;
use codex_hepta_learning_artifacts::OriginalArtifactPublicationContextV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::super::*;

pub(super) type Owner = super::super::super::OriginalArtifactHeadOwnerV1<FileAnchorWitnessStore>;
pub(super) type Thread = std::thread::JoinHandle<anyhow::Result<u64>>;

fn id(value: &str) -> anyhow::Result<StableId> {
    Ok(StableId::new(value)?)
}
fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    // SAFETY: pidfd_open returns a new descriptor for this fixture process.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(raw >= 0, "{}", std::io::Error::last_os_error());
    // SAFETY: this successful new descriptor has no other owner.
    let pidfd = unsafe { OwnedFd::from_raw_fd(i32::try_from(raw)?) };
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: geteuid only reads the fixture process credential.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(30),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd,
    )?)
}

pub(super) struct Fixture {
    pub(super) root: PathBuf,
    pub(super) writer: Arc<Mutex<LearningArtifactOwnerService>>,
    pub(super) config: ArtifactHeadSigningConfigV1,
    pub(super) prepared: Option<OriginalArtifactPreparedPublicationV1>,
    head_key: Option<SigningKey>,
    source: Arc<OriginalArtifactRegistrySourceOwnerV1>,
    _directory: tempfile::TempDir,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let at = now()?;
        let expires = at.checked_add(600_000).ok_or_else(|| anyhow::anyhow!("fixture expiry"))?;
        let writer_key = SigningKey::from_bytes(&[104; 32]);
        let head_key = SigningKey::from_bytes(&[105; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("head-test-dataset-authority")?,
            registry_id: id("head-test-withdrawals")?,
            scope_id: id("head-test-scope")?,
        });
        let scope = withdrawals.scope_digest().ok_or_else(|| anyhow::anyhow!("scope"))?;
        let signer = |name: &str, key: &SigningKey| -> anyhow::Result<TrustedArtifactSignerV1> {
            Ok(TrustedArtifactSignerV1 {
                signer_id: id(name)?,
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: at,
                expires_at: expires,
                revoked_at: None,
            })
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("head-test-artifacts")?,
            withdrawal_scope_digest: scope,
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer("head-test-writer-authority", &writer_key)?],
            head_signers: vec![signer("head-test-head-authority", &head_key)?],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("head-test-original-writer-lease")?,
            producer_id: id("head-test-producer")?,
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            signer_id: id("head-test-writer-authority")?,
            signing_key_digest: Digest32::of_bytes(&writer_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: at,
            expires_at: expires,
            signature: [0; 64],
        };
        lease.signature = writer_key.sign(&lease.signing_bytes()).to_bytes();
        let manifest = LearningArtifactManifestV2 {
            artifact_id: id("head-test-candidate")?,
            kind: ArtifactKind::Model,
            generation: Generation::new(1)?,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![d("dataset")],
            lineage_digests: vec![d("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: d("payload"),
            encoded_size_bytes: 7,
            training_code_digest: d("code"),
            runtime_tuple_digest: d("runtime"),
            device_profile_digest: d("device"),
            objective_class_digest: d("objective"),
            compatibility_digest: d("compatibility"),
            schema_profile_digest: d("schema"),
            normalization_digest: d("normalization"),
            producer_id: lease.producer_id.clone(),
            created_at: at,
            expires_at: expires,
        };
        let context = OriginalArtifactPublicationContextV1 {
            operation_id: id("head-test-original-operation")?,
            admission: admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), manifest, at)?,
            expected_registry_predecessor_head: Digest32::ZERO,
        };
        let config = ArtifactHeadSigningConfigV1 {
            publication: context.clone(),
            trust: trust.clone(),
            writer_lease: lease.clone(),
            storage_binding: d("head-test-storage"),
            signer_id: id("head-test-head-authority")?,
            authority_epoch: 1,
            signature_expires_at: expires,
        };
        let mut writer = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: root.join("artifact"),
            trust,
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: config.storage_binding,
            now: at,
        })?;
        let prepared = writer.prepare_original_registry(context, b"payload")?;
        let writer = Arc::new(Mutex::new(writer));
        let source = Arc::new(OriginalArtifactRegistrySourceOwnerV1::from_original_writer(Arc::clone(&writer), config.clone())?);
        Ok(Self { root, writer, config, prepared: Some(prepared), head_key: Some(head_key), source, _directory: directory })
    }

    fn file(&self, name: &str, create: bool) -> anyhow::Result<File> {
        Ok(OpenOptions::new().read(true).write(true).create_new(create).mode(0o600).open(self.root.join(name))?)
    }
    fn witness(&self, create: bool) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(self.file("head-witness", create)?, JournalScope {
            scope_digest: d("head-test-journal-scope"),
            objective_digest: d("head-test-journal-objective"),
        }, Generation::new(1)?, 64)?)
    }
    fn connection(&self) -> anyhow::Result<(OriginalArtifactRegistrySourceClientV1, Thread)> {
        let (stream, server) = UnixStream::pair()?;
        let client = OriginalArtifactRegistrySourceClientV1 {
            config: self.config.clone(),
            binding: self.config.binding()?,
            channel: Mutex::new(Some(Channel { peer: channel(stream)?, next: 1, source_at: 0, subject: None })),
            initial_at: now()?,
        };
        let mut channel = channel(server)?;
        let source = Arc::clone(&self.source);
        let thread = std::thread::spawn(move || {
            for nonce in 1..=128 {
                if !channel.exchange(|bytes| source.respond(bytes, nonce).map_err(|_| HostIssuerTransportError::InvalidRequest))? {
                    return Ok(nonce - 1);
                }
            }
            anyhow::bail!("fixture source bound exhausted")
        });
        Ok((client, thread))
    }
    pub(super) async fn create(&mut self) -> anyhow::Result<(Owner, Thread)> {
        let (source, thread) = self.connection()?;
        let key = self.head_key.take().ok_or_else(|| anyhow::anyhow!("consumed fixture key"))?;
        let owner = Owner::create(self.file("head-record", true)?, self.witness(true)?, key, source).await?;
        Ok((owner, thread))
    }
    pub(super) async fn recover(&self) -> anyhow::Result<(Owner, Thread)> {
        let (source, thread) = self.connection()?;
        let owner = Owner::recover(self.file("head-record", false)?, self.witness(false)?, source).await?;
        Ok((owner, thread))
    }
    pub(super) fn head_bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([fs::read(self.root.join("head-record"))?, fs::read(self.root.join("head-witness"))?])
    }
}
