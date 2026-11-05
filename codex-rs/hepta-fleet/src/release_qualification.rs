//! Explicit qualification publisher and external trust services. This helper
//! uses actual M15 signatures and the ordinary Registry/Unix interfaces. Its
//! fixture keys and synthetic build declarations are not production custody or
//! reproducible-build evidence, and the normal daemon never constructs it.

use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::ReleaseFrontierV1;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_paths::HeptaFleetRoot;
use trnm_release_bundle::pq_release::PqReleaseAuthorityV1;
use trnm_release_bundle::pq_release::PqReleaseMetadataV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;
use trnm_release_bundle::pq_release::PqReleaseSignatureV1;
use trnm_release_bundle::pq_release::pq_release_signature_digest_v1;

use crate::FleetRegistry;
use crate::FleetReleaseTrustConfig;
use crate::RegisteredRelease;
use crate::ReleaseId;
use crate::release_authority_set::MemberRecord;
use crate::release_authority_set::SignedReleaseSet;
use crate::release_authority_set::record_bytes;
use crate::release_authority_wire::*;
use crate::release_qualification_bundle;
use crate::release_qualification_trust::NOW;
use crate::release_qualification_trust::OWNER;
use crate::release_qualification_trust::TrustService;
use crate::release_qualification_trust::read_frontier;

pub type QualificationResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub struct PqReleaseQualification {
    pub(crate) config: FleetReleaseTrustConfig,
    pub(crate) root: RootRecord,
    pub(crate) keys: BTreeMap<[u8; 32], PqNativeSigningKey>,
    pub(crate) publisher: PqReleaseAuthorityV1,
    pub(crate) members: Vec<MemberRecord>,
    pub(crate) trust: TrustService,
    config_path: PathBuf,
}

impl PqReleaseQualification {
    pub fn initialize(
        external_root: &Path,
        fleet_root: HeptaFleetRoot,
    ) -> QualificationResult<(Self, FleetRegistry)> {
        let trust = TrustService::start(external_root)?;
        let (root, keys) = root_keys(/*offset*/ 0)?;
        let native_root = PqReleaseRootV1::try_from(&root)?;
        let initial_root_sha256 = native_root.digest()?;
        let publisher =
            PqReleaseAuthorityV1::bootstrap_pinned(native_root, initial_root_sha256, NOW)?;
        let config = FleetReleaseTrustConfig {
            schema_version: 1,
            profile: "hepta.fleet.release-trust.pq.v1".into(),
            owner_id: OWNER.into(),
            initial_root_sha256,
            network_id: root.network_id,
            platform_sha256: release_qualification_bundle::PLATFORM,
            clock: trust.config.clone(),
            frontier: trust.config.clone(),
        };
        let config_path = external_root.join("release-trust.json");
        write_config(&config_path, &config)?;
        let registry = FleetRegistry::initialize_with_release_authority(
            fleet_root,
            config.clone(),
            &record_bytes(&root)?,
        )?;
        Ok((
            Self {
                config,
                root,
                keys,
                publisher,
                members: Vec::new(),
                trust,
                config_path,
            },
            registry,
        ))
    }

    pub fn config(&self) -> FleetReleaseTrustConfig {
        self.config.clone()
    }
    pub fn config_path(&self) -> &Path {
        &self.config_path
    }

    pub fn install_release(
        &mut self,
        registry: &FleetRegistry,
        id: ReleaseId,
        agentd: &Path,
        args: Vec<String>,
    ) -> QualificationResult<RegisteredRelease> {
        self.install_release_bundle(
            registry,
            id,
            agentd,
            args,
            /*matrixd*/ None,
            Vec::new(),
        )
    }

    pub fn install_release_bundle(
        &mut self,
        registry: &FleetRegistry,
        id: ReleaseId,
        agentd: &Path,
        args: Vec<String>,
        matrixd: Option<&Path>,
        matrix_args: Vec<String>,
    ) -> QualificationResult<RegisteredRelease> {
        let member = release_qualification_bundle::member(
            id.clone(),
            agentd,
            args.clone(),
            matrixd,
            matrix_args.clone(),
        )?;
        if self
            .members
            .iter()
            .any(|item| item.release.release_id == id)
        {
            return Err("duplicate qualification release".into());
        }
        self.members.push(member);
        let members = self.members.clone();
        self.publish_members(registry, members, NOW + 3600)?;
        Ok(registry.install_release_bundle(id, agentd, args, matrixd, matrix_args)?)
    }

    /// Publishes a new, explicitly signed rolling set. Local allow markers
    /// cannot keep an omitted member authorized.
    pub fn publish_member_ids(
        &mut self,
        registry: &FleetRegistry,
        ids: &[ReleaseId],
        expires_at: u64,
    ) -> QualificationResult<()> {
        let mut members = Vec::new();
        for id in ids {
            members.push(
                self.members
                    .iter()
                    .find(|member| &member.release.release_id == id)
                    .ok_or("unknown qualification member")?
                    .clone(),
            );
        }
        self.publish_members(registry, members, expires_at)
    }

    pub(crate) fn signed_members(
        &self,
        members: Vec<MemberRecord>,
        expires_at: u64,
    ) -> QualificationResult<SignedReleaseSet> {
        let role = PqReleaseRoleV1::NodeSoftware;
        let version = self.publisher.role_version(role) + 1;
        let mut release_set = release_qualification_bundle::release_set(
            members,
            version,
            self.publisher.bundle_signer_identity(role),
            self.publisher.current_content(role),
        )?;
        let metadata = MetadataRecord {
            network_id: self.root.network_id,
            role: RoleRecord::NodeSoftware,
            root_generation: self.publisher.root_generation(),
            role_version: version,
            expires_at,
            expected_checkpoint: self.publisher.checkpoint(),
            previous_content: self.publisher.current_content(role),
            content: release_set.bundle.bundle_digest,
            approved_content_rollback: false,
        };
        let native = PqReleaseMetadataV1::from(&metadata);
        let role_keys = &self
            .root
            .roles
            .iter()
            .find(|entry| entry.role == RoleRecord::NodeSoftware)
            .ok_or("missing fixture role")?
            .keys;
        let signatures = role_keys
            .keys
            .iter()
            .map(|key| -> QualificationResult<SignatureRecord> {
                Ok(SignatureRecord {
                    key_id: key.key_id,
                    signature: self.keys[&key.key_id]
                        .sign_exact_message(&native.signing_message())?
                        .to_vec(),
                })
            })
            .collect::<QualificationResult<Vec<_>>>()?;
        release_set.bundle.signature_digest = pq_release_signature_digest_v1(
            &signatures
                .iter()
                .map(PqReleaseSignatureV1::from)
                .collect::<Vec<_>>(),
        )?;
        Ok(SignedReleaseSet {
            release_set,
            metadata,
            signatures,
        })
    }

    fn publish_members(
        &mut self,
        registry: &FleetRegistry,
        members: Vec<MemberRecord>,
        expires_at: u64,
    ) -> QualificationResult<()> {
        let signed = self.signed_members(members, expires_at)?;
        registry.publish_release_set(&record_bytes(&signed)?)?;
        let binding = signed.release_set.bind(self.config.platform_sha256)?;
        self.publisher.accept_bundle(
            &binding.bundle,
            &binding.required_packages,
            &PqReleaseMetadataV1::from(&signed.metadata),
            &signed
                .signatures
                .iter()
                .map(PqReleaseSignatureV1::from)
                .collect::<Vec<_>>(),
            self.trust.now.load(Ordering::Acquire) / 1000,
        )?;
        Ok(())
    }

    pub fn advance_clock_to(&self, unix_seconds: u64) {
        self.trust.now.store(unix_seconds * 1000, Ordering::Release);
    }

    /// Deterministic qualification-only responses from the actual signed PQ
    /// clock service. Used to cross expiry after the owner's real file fsync.
    pub fn advance_clock_after_reads(
        &self,
        successful_reads: u64,
        unix_seconds: u64,
    ) -> QualificationResult<()> {
        let unix_ms = unix_seconds
            .checked_mul(1000)
            .ok_or("qualification clock overflow")?;
        self.trust
            .advance_clock_after_reads
            .store(successful_reads, Ordering::Release);
        self.trust
            .advance_clock_to_ms
            .store(unix_ms, Ordering::Release);
        Ok(())
    }

    pub fn current_unix_seconds(&self) -> u64 {
        self.trust.now.load(Ordering::Acquire) / 1000
    }

    pub fn frontier(&self) -> QualificationResult<Option<ReleaseFrontierV1>> {
        read_frontier(&self.trust.frontier_path)
    }
    pub fn cas_attempts(&self) -> u64 {
        self.trust.cas_attempts.load(Ordering::Acquire)
    }

    pub fn drop_next_committed_cas_reply(&self) {
        self.trust.cas_mode.store(1, Ordering::Release);
    }
    pub fn drop_next_cas_without_commit(&self) {
        self.trust.cas_mode.store(2, Ordering::Release);
    }

    /// Retain the actual next received request, drop its reply, and execute it
    /// just before the following competing CAS. This models a late original
    /// effect; intervening successful reads still return the old frontier.
    pub fn defer_next_cas_until_competing_attempt(&self) {
        self.trust.cas_mode.store(3, Ordering::Release);
    }

    pub fn publish_protocol_configuration(
        &mut self,
        registry: &FleetRegistry,
        policy_bytes: &[u8],
        expires_at: u64,
    ) -> QualificationResult<()> {
        use sha2::Digest;
        let role = PqReleaseRoleV1::ProtocolConfiguration;
        let metadata = MetadataRecord {
            network_id: self.root.network_id,
            role: RoleRecord::ProtocolConfiguration,
            root_generation: self.publisher.root_generation(),
            role_version: self.publisher.role_version(role) + 1,
            expires_at,
            expected_checkpoint: self.publisher.checkpoint(),
            previous_content: self.publisher.current_content(role),
            content: sha2::Sha256::digest(policy_bytes).into(),
            approved_content_rollback: false,
        };
        let native = PqReleaseMetadataV1::from(&metadata);
        let role_keys = &self
            .root
            .roles
            .iter()
            .find(|entry| entry.role == RoleRecord::ProtocolConfiguration)
            .ok_or("missing fixture protocol role")?
            .keys;
        let signatures = role_keys
            .keys
            .iter()
            .map(|key| -> QualificationResult<SignatureRecord> {
                Ok(SignatureRecord {
                    key_id: key.key_id,
                    signature: self.keys[&key.key_id]
                        .sign_exact_message(&native.signing_message())?
                        .to_vec(),
                })
            })
            .collect::<QualificationResult<Vec<_>>>()?;
        registry.publish_protocol_configuration(&serde_json::to_vec(
            &serde_json::json!({"metadata": metadata, "signatures": signatures}),
        )?)?;
        self.publisher.accept(
            &native,
            &signatures
                .iter()
                .map(PqReleaseSignatureV1::from)
                .collect::<Vec<_>>(),
            self.trust.now.load(Ordering::Acquire) / 1000,
        )?;
        Ok(())
    }

    pub fn rotate_publisher_root(&mut self, registry: &FleetRegistry) -> QualificationResult<()> {
        let (mut next, keys) = root_keys(/*offset*/ 80)?;
        next.generation = self.root.generation + 1;
        next.previous_root_digest = PqReleaseRootV1::try_from(&self.root)?.digest()?;
        let native = PqReleaseRootV1::try_from(&next)?;
        let message = native.signing_message()?;
        let sign = |role: &KeysRecord,
                    keys: &BTreeMap<[u8; 32], PqNativeSigningKey>|
         -> QualificationResult<Vec<SignatureRecord>> {
            role.keys
                .iter()
                .map(|key| {
                    Ok(SignatureRecord {
                        key_id: key.key_id,
                        signature: keys[&key.key_id].sign_exact_message(&message)?.to_vec(),
                    })
                })
                .collect()
        };
        let old_signatures = sign(&self.root.offline_root, &self.keys)?;
        let new_signatures = sign(&next.offline_root, &keys)?;
        registry.rotate_release_root(&serde_json::to_vec(&serde_json::json!({"root": next, "old_signatures": old_signatures, "new_signatures": new_signatures}))?)?;
        self.publisher.rotate_root(
            native,
            &old_signatures
                .iter()
                .map(PqReleaseSignatureV1::from)
                .collect::<Vec<_>>(),
            &new_signatures
                .iter()
                .map(PqReleaseSignatureV1::from)
                .collect::<Vec<_>>(),
            self.trust.now.load(Ordering::Acquire) / 1000,
        )?;
        self.root = next;
        self.keys = keys;
        Ok(())
    }
}

fn root_keys(
    offset: u8,
) -> QualificationResult<(RootRecord, BTreeMap<[u8; 32], PqNativeSigningKey>)> {
    let mut keys = BTreeMap::new();
    let mut group = |start: u8| -> QualificationResult<KeysRecord> {
        let mut public = Vec::new();
        for seed_byte in start..start + 2 {
            let seed = [seed_byte + offset; 32].into();
            let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
            let key_id = ml_dsa_65_key_id_from_spki(&spki)?;
            keys.insert(key_id, PqNativeSigningKey::from_owned_seed(seed, key_id)?);
            public.push(KeyRecord {
                key_id,
                public_key_spki: spki.to_vec(),
            });
        }
        Ok(KeysRecord {
            threshold: 2,
            keys: public,
        })
    };
    let offline_root = group(31)?;
    let mut roles = Vec::new();
    for (index, role) in [
        RoleRecord::NodeSoftware,
        RoleRecord::ProtocolConfiguration,
        RoleRecord::CellManifest,
        RoleRecord::CellActivation,
    ]
    .into_iter()
    .enumerate()
    {
        roles.push(RoleKeysRecord {
            role,
            keys: group(41 + index as u8 * 2)?,
        });
    }
    Ok((
        RootRecord {
            network_id: [111; 32],
            generation: 1,
            expires_at: NOW + 86400,
            previous_root_digest: [0; 32],
            offline_root,
            roles,
        },
        keys,
    ))
}

fn write_config(path: &Path, config: &FleetReleaseTrustConfig) -> QualificationResult<()> {
    use std::os::unix::fs::PermissionsExt;
    let endpoint =
        |entry: &codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig| {
            serde_json::json!({
                "socket_path": entry.socket_path, "peer_uid": entry.peer_uid, "service_id": entry.service_id,
                "key_generation": entry.key_generation, "public_key_id": entry.public_key_id,
                "public_key_spki": entry.public_key_spki, "timeout_ms": entry.timeout_ms,
            })
        };
    let value = serde_json::json!({
        "schema_version": config.schema_version, "profile": config.profile, "owner_id": config.owner_id,
        "initial_root_sha256": config.initial_root_sha256, "network_id": config.network_id, "platform_sha256": config.platform_sha256,
        "clock": endpoint(&config.clock), "frontier": endpoint(&config.frontier),
    });
    std::fs::write(path, serde_json::to_vec(&value)?)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o444))?;
    Ok(())
}
