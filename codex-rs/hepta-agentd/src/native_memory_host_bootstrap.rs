//! Opt-in reconstruction for the default Linux daemon. The host pins all
//! retained inputs; missing history never falls back to fresh initialization.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::decode_retained_memory_cell_source_claim_v1;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use codex_hepta_ndu::NduOwnerContextV1;
use codex_hepta_types::Digest32;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNativeMemoryRegistrationV1;
use crate::AgentdProductionWriterHost;
use crate::NativeMemoryModelConfigV1;
use crate::NativeMemoryShadowFilesV1;
use crate::NativeMemoryShadowStartV1;
use crate::NativeMemorySourceConfigV1;
use crate::native_memory_process_schema::ProcessDescriptor;
use crate::native_memory_process_schema::ShadowDescriptor;
use crate::native_memory_process_schema::digest;
use crate::native_memory_process_schema::id;
use crate::native_memory_process_trust::FilePin;
use crate::native_memory_process_trust::ProcessClock;
use crate::native_memory_process_trust::ProcessSourceVerifier;
use crate::native_memory_process_trust::string;

pub(crate) struct NativeMemoryProcessHost {
    pub registration: Arc<AgentdNativeMemoryRegistrationV1>,
    pub ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
    pub source: NativeMemorySourceConfigV1,
    pub descriptor: ProcessDescriptor,
    pub descriptor_sha256: Digest32,
    pub identity: AgentdIdentity,
}

/// Explicitly select the local compatibility trust profile. This default-bin
/// path does not certify protected time, a deployed issuer or rollback safety.
pub async fn configure_native_memory_process_v1(
    config: AgentdConfig,
    descriptor_path: &Path,
    expected_digest: Digest32,
) -> Result<AgentdConfig, AgentdError> {
    configure(config, descriptor_path, expected_digest)
        .await
        .map_err(AgentdError::Invalid)
}

async fn configure(
    config: AgentdConfig,
    path: &Path,
    expected: Digest32,
) -> Result<AgentdConfig, String> {
    if config.native_memory_registration().is_some() || config.production_writer_host().is_some() {
        return Err("native process bootstrap cannot replace installed owners".into());
    }
    let identity = config.identity().clone();
    let bytes = FilePin {
        path: path.to_path_buf(),
        sha256: expected.to_string(),
    }
    .read(&identity, /*limit*/ 1_048_576)?;
    let descriptor: ProcessDescriptor = serde_json::from_slice(&bytes).map_err(string)?;
    if descriptor.schema != "hepta.memory-cell.process-bootstrap.v1"
        || descriptor.trust_profile != "linux-local-compatibility-v1"
        || descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.spawn_generation != identity.spawn_generation
        || descriptor.control_socket.parent() != Some(identity.home_root.as_path())
        || descriptor.control_socket == identity.control_socket
        || descriptor.control_socket == identity.app_server_socket
        || descriptor.control_socket.exists()
    {
        return Err("native process identity, trust profile or control path rejected".into());
    }
    let source = &descriptor.source;
    source.key.validate().map_err(string)?;
    let verifier = Arc::new(ProcessSourceVerifier {
        identity: identity.clone(),
        grant: source.grant.clone(),
        signer_id: source.signer_id.clone(),
        verifying_key: source.verifying_key,
        poisoned: AtomicBool::new(false),
    });
    let authority = verifier.current()?;
    let anchor: CognitiveRecoveryAnchor =
        serde_json::from_slice(&source.anchor.read(&identity, /*limit*/ 1_048_576)?)
            .map_err(string)?;
    let claim = decode_retained_memory_cell_source_claim_v1(
        &source.claim.read(&identity, /*limit*/ 1_048_576)?,
    )
    .map_err(string)?;
    let model: NativeMemoryModelConfigV1 =
        serde_json::from_slice(&source.model.read(&identity, /*limit*/ 65_536)?).map_err(string)?;
    model.validate()?;
    descriptor.shadow.profile(&model)?;
    let n = &descriptor.ndu;
    for pin in [
        FilePin {
            path: n.root.join("projection.journal"),
            sha256: n.journal_sha256.clone(),
        },
        FilePin {
            path: n.authority_state.join("authority.json"),
            sha256: n.authority_snapshot_sha256.clone(),
        },
        FilePin {
            path: n.authority_state.join("authority.claims"),
            sha256: n.authority_claims_sha256.clone(),
        },
    ] {
        pin.read(&identity, /*limit*/ 8_388_608)?;
    }
    // Supply the retained head, not the new feed, to the compatibility reopen.
    // This extraction establishes no authority: the owner below validates the
    // complete snapshot, issuer, nonce journal and history before use.
    let retained: serde_json::Value = serde_json::from_slice(
        &FilePin {
            path: n.authority_state.join("authority.json"),
            sha256: n.authority_snapshot_sha256.clone(),
        }
        .read(&identity, /*limit*/ 8_388_608)?,
    )
    .map_err(string)?;
    if retained["schema"] != 3 {
        return Err("current process requires authority snapshot schema 3".into());
    }
    let retained_head: FinalUseRevocations =
        serde_json::from_value(retained["head"].clone()).map_err(string)?;
    let signed_feed: SignedFinalUseRevocationUpdate =
        serde_json::from_slice(&n.feed.read(&identity, /*limit*/ 1_048_576)?).map_err(string)?;
    let clock = Arc::new(ProcessClock {
        identity: identity.clone(),
        feed: n.feed.clone(),
        boot_id: descriptor.linux_boot_id.clone(),
        last_wall: Mutex::new(0),
        poisoned: AtomicBool::new(false),
    });
    // Authenticate before a constructor may advance a retained authority head.
    let feed_key =
        ed25519_dalek::VerifyingKey::from_bytes(&n.feed_verifying_key).map_err(string)?;
    let now = clock.now_unix_ms().map_err(string)?;
    if feed_key.is_weak()
        || signed_feed.update.distributor_id != n.feed_distributor_id
        || now < signed_feed.update.issued_at_unix_ms
        || now >= signed_feed.update.expires_at_unix_ms
    {
        return Err("signed NDU feed identity or freshness rejected".into());
    }
    feed_key
        .verify_strict(
            &signed_feed.update.signing_bytes().map_err(string)?,
            &ed25519_dalek::Signature::from_slice(&signed_feed.signature).map_err(string)?,
        )
        .map_err(string)?;
    let ndu_authority = FinalUseAuthority::open_state_dir_with_clock(
        &n.authority_state,
        n.signer_id.clone(),
        n.verifying_key,
        retained_head.clone(),
        clock.clone(),
    )
    .map_err(string)?;
    if ndu_authority.revocation_head().map_err(string)? != retained_head {
        return Err("retained authority head changed while opening".into());
    }
    let mut ndu = NduAuthenticatedOwnerV1::open(
        &n.root,
        ndu_authority,
        NduOwnerContextV1 {
            principal_id: id(identity.agent_id.as_str())?,
            owner_id: id(&n.owner_id)?,
            host_generation: identity
                .spawn_generation
                .checked_add(1)
                .ok_or("serving generation overflow")?,
            principal_scope_digest: digest(&n.principal_scope_digest)?,
            fence_digest: digest(&n.fence_digest)?,
            revocation_frontier_digest: digest(&n.revocation_frontier_digest)?,
        },
        n.policy.build()?,
    )
    .map_err(string)?
    .with_current_reads(
        FinalUseRevocationFeedVerifier::new(n.feed_distributor_id.clone(), n.feed_verifying_key)
            .map_err(string)?,
        clock.clone(),
    );
    ndu.apply_read_revocation_update(&signed_feed)
        .map_err(string)?;
    let ndu = Arc::new(Mutex::new(ndu));
    let writer = Arc::new(
        AgentdProductionWriterHost::open(
            &config,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            authority,
            verifier,
            source.lease_id.clone(),
            source.lease_generation,
        )
        .await
        .map_err(string)?,
    );
    let registration = Arc::new(AgentdNativeMemoryRegistrationV1::new(
        Arc::clone(&ndu),
        clock,
    ));
    let host = Arc::new(NativeMemoryProcessHost {
        registration: Arc::clone(&registration),
        ndu,
        source: NativeMemorySourceConfigV1 {
            access: CognitiveAccess::agent_private(identity.agent_id.clone()),
            key: source.key.clone(),
            claim,
            model,
        },
        descriptor,
        descriptor_sha256: expected,
        identity,
    });
    config
        .with_production_writer_host(writer)
        .map_err(string)?
        .with_native_memory_registration(registration)
        .map_err(string)?
        .with_native_memory_process_host(host)
        .map_err(string)
}

impl NativeMemoryProcessHost {
    pub fn source(&self) -> NativeMemorySourceConfigV1 {
        NativeMemorySourceConfigV1 {
            access: self.source.access.clone(),
            key: self.source.key.clone(),
            claim: self.source.claim.clone(),
            model: self.source.model.clone(),
        }
    }

    pub fn files(&self) -> Result<NativeMemoryShadowFilesV1, String> {
        let shadow = &self.descriptor.shadow;
        if shadow.journal == shadow.witness {
            return Err("independent shadow files required".into());
        }
        Ok(NativeMemoryShadowFilesV1 {
            journal: open_shadow_file(&shadow.journal, shadow, &self.identity)?,
            witness: open_shadow_file(&shadow.witness, shadow, &self.identity)?,
            start: if shadow.recover {
                NativeMemoryShadowStartV1::Recover
            } else {
                NativeMemoryShadowStartV1::Bootstrap
            },
        })
    }
}

fn open_shadow_file(
    path: &Path,
    shadow: &ShadowDescriptor,
    identity: &AgentdIdentity,
) -> Result<File, String> {
    if path.parent() != Some(identity.home_root.as_path()) || !path.is_absolute() {
        return Err("shadow files must be direct children of the canonical Agent home".into());
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).mode(0o600);
    if shadow.recover {
        let before = std::fs::symlink_metadata(path).map_err(string)?;
        if !before.is_file()
            || before.nlink() != 1
            || before.mode() & 0o077 != 0
            || before.uid()
                != std::fs::metadata(&identity.home_root)
                    .map_err(string)?
                    .uid()
        {
            return Err("private existing shadow history required".into());
        }
        let file = options.open(path).map_err(string)?;
        let opened = file.metadata().map_err(string)?;
        if (opened.dev(), opened.ino()) != (before.dev(), before.ino()) {
            return Err("shadow history changed while opening".into());
        }
        file.try_lock().map_err(string)?;
        Ok(file)
    } else {
        let file = options.create_new(true).open(path).map_err(string)?;
        file.try_lock().map_err(string)?;
        Ok(file)
    }
}
